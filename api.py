from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import json
import re
import argparse
import stat
import platform
from datetime import datetime
from backend.diagnostics import run_all_diagnostics
from backend.transcriber import transcribe_with_sensevoice, transcribe_with_dashscope_and_segments, get_available_devices
from backend.llm_agent import get_podcast_summary_robust, search_in_podcast
from backend.timeline_agent import generate_timeline_json
from backend.downloader import route_and_download, detect_platform, AudioDownloader
from backend.task_queue import add_task, get_task, get_all_tasks, get_queue_stats, update_task_status, delete_task, clear_completed
from backend.worker import start_worker, is_worker_running, pause_worker, resume_worker, is_paused, stop_worker, retry_failed_tasks
from backend.rag_db import (
    create_tag, get_all_tags, delete_tag, set_archive_tags, get_archive_tags,
    create_chat_session, get_chat_sessions, get_chat_session, update_chat_session_title, delete_chat_session,
    add_chat_message, get_chat_messages, add_chat_reference, get_archive_references,
    index_archive, delete_archive_vectors, get_archives_by_tag, init_db as init_rag_db
)
from backend.rag_retriever import generate_chat_response
from backend.fetch_cover import fetch_cover, download_cover_image
from sse_starlette.sse import EventSourceResponse
import asyncio

# ================= 命令行参数解析 =================
# 注意：使用 parse_known_args() 而不是 parse_args()
# 这样当 uvicorn 传递参数时，只会处理我们定义的参数，忽略其他的
_parser = argparse.ArgumentParser(description='PodGist API Server')
_parser.add_argument('--data-dir', type=str, default=None,
                     help='用户数据目录（archives, temp_audio, config, .env）')
_parser.add_argument('--model-dir', type=str, default=None,
                     help='AI 模型目录路径')
_cli_args, _unknown = _parser.parse_known_args()

# 设置环境变量供其他模块使用
if _cli_args.data_dir:
    os.environ['PODGIST_DATA_DIR'] = _cli_args.data_dir
if _cli_args.model_dir:
    os.environ['PODGIST_MODEL_DIR'] = _cli_args.model_dir

app = FastAPI(title="PodGist API", version="0.1.1")

@app.on_event("startup")
async def startup_index():
    """启动时自动索引所有已有归档到向量库（后台运行，避免阻塞启动）"""
    # 必须用 create_task 包装 to_thread，否则 FastAPI 无法正确调度这个后台任务
    asyncio.create_task(asyncio.to_thread(index_all_archives))

# 获取 api.py 所在目录作为项目根目录（默认）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# 用户数据目录（Electron 模式或开发模式）
if _cli_args.data_dir:
    BASE_DIR = _cli_args.data_dir
else:
    BASE_DIR = _SCRIPT_DIR

ENV_FILE = os.path.join(BASE_DIR, ".env")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# ================= 安全配置：跨域 (CORS) =================
# 极其关键：允许未来的 React 前端与这个后端通信
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def load_api_key():
    """
    从 .env 文件加载 API Key。
    支持两种格式：DASHSCOPE_API_KEY=sk-xxxxxx（带前缀）或 sk-xxxxxx（裸 key）
    """
    try:
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
                # 去掉前缀以兼容旧格式
                if key.startswith("DASHSCOPE_API_KEY="):
                    key = key[len("DASHSCOPE_API_KEY="):]
                return key if key else ""
        return ""
    except Exception:
        return ""

def load_config():
    """
    加载配置文件，返回字典。
    如果文件不存在，返回默认配置。
    """
    default_config = {
        "engine": "SenseVoice",
        "whisper_model": "small",
        "device": "auto",
        "max_timeline_items": 15
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 确保包含所有默认键
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                return config
        return default_config
    except Exception:
        return default_config

def save_config(config):
    """
    保存配置到文件。
    """
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception:
        return False

TEMP_DIR = os.path.join(BASE_DIR, "temp_audio")
ARCHIVE_DIR = os.path.join(BASE_DIR, "archives")
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)


def save_archive_metadata(archive_path: str, title: str, mode: str, source_type: str, source_url: str, audio_saved: bool, audio_filename: str | None, cover_saved: bool = False, cover_filename: str | None = None, cover_source_url: str | None = None, cover_type: str | None = None):
    """
    将归档元数据写入 archive_path/metadata.json。

    参数:
        archive_path: 归档目录的绝对路径
        title: 归档标题
        mode: 'summary' 或 'timeline'
        source_type: 'local_file' / 'podcast_url' / 'bilibili' / 'other'
        source_url: 原始来源 URL（本地文件为本地路径）
        audio_saved: 是否保存了音频副本
        audio_filename: 归档中音频文件名（如 source.mp3），无则为 None
        cover_saved: 是否保存了封面副本
        cover_filename: 归档中封面文件名（如 cover.jpg），无则为 None
        cover_source_url: 原始封面来源 URL
        cover_type: 封面类型 'episode' | 'show' | 'video' | 'webpage'
    """
    import json
    metadata = {
        "id": os.path.basename(archive_path),
        "title": title,
        "mode": mode,
        "source_type": source_type,
        "source_url": source_url,
        "audio_saved": audio_saved,
        "audio_filename": audio_filename,
        "can_redownload": source_url.startswith("http") or source_url.startswith("www"),
        "created_at": datetime.now().isoformat(),
        "cover_saved": cover_saved,
        "cover_filename": cover_filename,
        "cover_source_url": cover_source_url,
        "cover_type": cover_type,
    }
    metadata_path = os.path.join(archive_path, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

# 1. 健康检查接口
@app.get("/")
def read_root():
    return {"status": "ok", "message": "PodGist V2 后端引擎已成功启动"}

# 2. 接收本地音频上传的接口 (真实逻辑)
@app.post("/api/transcribe/local")
async def transcribe_local(
    file: UploadFile = File(...),
    api_key: str = Form(""),
    engine: str = Form("SenseVoice"),
    whisper_model: str = Form("small"),
    device: str = Form("auto"),
    max_timeline_items: int = Form(15),
    mode: str = Form("summary")
):
    if not file.filename.endswith((".mp3", ".wav", ".m4a")):
        raise HTTPException(status_code=400, detail="不支持的音频格式，请上传 mp3/wav/m4a")

    file_path = os.path.join(TEMP_DIR, file.filename)
    try:
        # 将前端传来的文件保存到本地临时目录
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # 1. 获取 API Key（优先使用前端传的，否则从 .env 读取）
        if not api_key:
            api_key = load_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="请提供 DashScope API Key")

        # 2. 转录（使用 DashScope 云端 ASR）
        podcast_text, transcript_segments = transcribe_with_dashscope_and_segments(file_path, api_key)

        # 3. 根据 mode 生成内容
        safe_basename = os.path.splitext(os.path.basename(file.filename))[0]
        if mode == "timeline":
            timeline_data = generate_timeline_json(api_key, podcast_text, transcript_segments, title=safe_basename)
            ai_title = timeline_data.get("title", safe_basename)
        else:
            summary = get_podcast_summary_robust(api_key, podcast_text)
            lines = summary.strip().split('\n')
            ai_title = lines[0] if lines else safe_basename

        # 4. 创建归档目录
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        archive_name = f"{safe_basename}_{date_str}"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        os.makedirs(archive_path, exist_ok=True)

        # 4.5 保存音频副本
        audio_filename = None
        audio_saved = False
        if os.path.exists(file_path):
            _, ext = os.path.splitext(file.filename)
            audio_filename = f"source{ext}"
            audio_dest = os.path.join(archive_path, audio_filename)
            shutil.copy2(file_path, audio_dest)
            audio_saved = True

        # 4.6 保存 metadata.json
        save_archive_metadata(
            archive_path=archive_path,
            title=ai_title,
            mode=mode,
            source_type="local_file",
            source_url=file_path,
            audio_saved=audio_saved,
            audio_filename=audio_filename,
        )

        # 5. 保存原始转录文本
        raw_path = os.path.join(archive_path, "raw.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(podcast_text)

        # 6. 保存 segments.json
        segments_path = os.path.join(archive_path, "segments.json")
        with open(segments_path, "w", encoding="utf-8") as f:
            json.dump(transcript_segments, f, ensure_ascii=False, indent=2)

        # 7. 保存内容（mode 路由）
        if mode == "timeline":
            timeline_path = os.path.join(archive_path, "timeline.json")
            with open(timeline_path, "w", encoding="utf-8") as f:
                json.dump(timeline_data, f, ensure_ascii=False, indent=2)
            summary_path = os.path.join(archive_path, "summary.md")
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(f"# {ai_title}\n\n[时间轴模式] 共 {len(timeline_data.get('nodes', []))} 个节点\n")
        else:
            summary_path = os.path.join(archive_path, "summary.md")
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(f"# {ai_title}\n\n{chr(10).join(lines[1:]).strip() if lines else ''}")

        # 7.5 自动索引到向量库
        try:
            index_archive(archive_name, archive_name, podcast_text)
        except Exception as e:
            print(f"[RAG] 向量索引失败（不影响归档）: {e}")

        # 9. 清理临时音频文件
        os.remove(file_path)

        return {
            "status": "success",
            "filename": file.filename,
            "archive_name": archive_name,
            "message": f"音频转录与摘要生成完成！归档目录: {archive_name}"
        }
    except Exception as e:
        # 清理临时文件（如果存在）
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        file.file.close()

# 2.1 接收 URL 并下载音频后转录的接口
@app.post("/api/transcribe/url")
async def transcribe_url(
    url: str = Form(...),
    type: str = Form("podcast"),  # 'podcast' 或 'bilibili'
    api_key: str = Form(""),
    engine: str = Form("SenseVoice"),
    whisper_model: str = Form("small"),
    device: str = Form("auto"),
    max_timeline_items: int = Form(15),
    mode: str = Form("summary")
):
    """
    从在线 URL（播客/Bilibili）下载音频并进行转录摘要。
    """
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="请输入有效的 URL 链接")

    # 1. 获取 API Key
    if not api_key:
        api_key = load_api_key()
    if not api_key:
        raise HTTPException(status_code=400, detail="请提供 DashScope API Key")

    # 2. 根据类型选择下载方式
    if type == "bilibili":
        # Bilibili 使用 AudioDownloader 类
        if "bilibili.com" not in url.lower():
            raise HTTPException(status_code=400, detail="请输入有效的 Bilibili 视频链接")

        print(f"[DEBUG] 开始下载 Bilibili 视频: {url}")
        downloader = AudioDownloader(save_dir=TEMP_DIR)
        download_result = downloader.download_bilibili_audio(url)
        print(f"[DEBUG] 下载结果: {download_result}")
    else:
        # 播客使用 route_and_download
        platform = detect_platform(url)
        if platform == "unknown":
            raise HTTPException(status_code=400, detail="不支持的播客平台，当前支持小宇宙、网易云音乐、喜马拉雅、Apple Podcasts")

        download_result = route_and_download(url, save_dir=TEMP_DIR)

    # 检查下载结果
    if not download_result.get('success'):
        error_msg = download_result.get('error', '下载失败')
        # 返回更友好的错误信息
        if "403" in error_msg:
            error_msg = "该内容可能需要会员权限或已被删除"
        elif "404" in error_msg:
            error_msg = "内容不存在或链接无效"
        raise HTTPException(status_code=400, detail=error_msg)

    file_path = download_result['file_path']
    title = download_result.get('title', 'unknown')

    try:
        # 3. 转录（使用 DashScope 云端 ASR）
        podcast_text = transcribe_with_sensevoice(file_path)

        # 5. 调用大模型生成摘要
        summary = get_podcast_summary_robust(api_key, podcast_text, max_timeline_items=max_timeline_items)

        # 6. 创建归档目录
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:50]
        archive_name = f"{safe_title}_{date_str}"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        os.makedirs(archive_path, exist_ok=True)

        # 6.5 确定 source_type 并尝试抓取封面
        source_type = "bilibili" if type == "bilibili" else "podcast_url"

        # 6.6 抓取封面（不阻塞主流程）
        cover_saved = False
        cover_filename = None
        cover_source_url = None
        cover_type = None
        try:
            cover_url, cover_type = fetch_cover(url, source_type)
            if cover_url:
                tmp_cover = os.path.join(archive_path, "cover.tmp")
                if download_cover_image(cover_url, tmp_cover):
                    # 重命名获取实际后缀
                    actual_ext = os.path.splitext(tmp_cover)[1]
                    cover_filename = "cover" + actual_ext
                    cover_dest = os.path.join(archive_path, cover_filename)
                    os.rename(tmp_cover, cover_dest)
                    cover_saved = True
                    cover_source_url = cover_url
                    print(f"[Cover] 封面已保存: {cover_filename}")
                elif os.path.exists(tmp_cover):
                    os.remove(tmp_cover)
        except Exception as e:
            print(f"[Cover] 封面抓取失败（不阻塞主流程）: {e}")

        # 6.7 保存音频副本
        audio_filename = None
        audio_saved = False
        if os.path.exists(file_path):
            _, ext = os.path.splitext(file_path)
            audio_filename = f"source{ext}"
            audio_dest = os.path.join(archive_path, audio_filename)
            shutil.copy2(file_path, audio_dest)
            audio_saved = True

        # 6.8 保存 metadata.json
        save_archive_metadata(
            archive_path=archive_path,
            title=safe_title,
            mode=mode,
            source_type=source_type,
            source_url=url,
            audio_saved=audio_saved,
            audio_filename=audio_filename,
            cover_saved=cover_saved,
            cover_filename=cover_filename,
            cover_source_url=cover_source_url,
            cover_type=cover_type,
        )

        # 7. 保存原始转录文本
        raw_path = os.path.join(archive_path, "raw.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(podcast_text)

        # 7.5 自动索引到向量库
        try:
            index_archive(archive_name, archive_name, podcast_text)
        except Exception as e:
            print(f"[RAG] 向量索引失败（不影响归档）: {e}")

        # 8. 保存摘要
        summary_path = os.path.join(archive_path, "summary.md")
        lines = summary.strip().split('\n')
        if lines:
            first_line = lines[0].strip()
            if first_line.startswith('#'):
                ai_title = first_line.lstrip('#').strip()
                clean_summary = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
            else:
                ai_title = first_line if first_line else safe_title
                clean_summary = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        else:
            ai_title = safe_title
            clean_summary = ""

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"# {ai_title}\n\n{clean_summary}")

        # 9. 清理临时音频文件
        if os.path.exists(file_path):
            os.remove(file_path)

        return {
            "status": "success",
            "filename": title,
            "archive_name": archive_name,
            "platform": type,
            "message": f"{type} 音频转录与摘要生成完成！"
        }

    except Exception as e:
        # 清理临时文件
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        raise HTTPException(status_code=500, detail=str(e))

# 3. 获取历史归档列表的接口 (真实数据)
@app.get("/api/archives")
def get_archives():
    try:
        archives = []
        if os.path.exists(ARCHIVE_DIR):
            # 获取所有归档目录，按修改时间倒序排列（最新的在前）
            items = []
            for item in os.listdir(ARCHIVE_DIR):
                item_path = os.path.join(ARCHIVE_DIR, item)
                if os.path.isdir(item_path):
                    # 获取目录修改时间
                    mtime = os.path.getmtime(item_path)
                    items.append((mtime, item))

            # 按修改时间倒序排序
            items.sort(key=lambda x: x[0], reverse=True)

            # 转换为前端需要的格式
            for mtime, item in items:
                item_path = os.path.join(ARCHIVE_DIR, item)
                # 提取标题：优先读 summary.md 第一行非标题行，否则用目录名
                display_name = item
                summary_path = os.path.join(item_path, "summary.md")
                if os.path.exists(summary_path):
                    try:
                        with open(summary_path, "r", encoding="utf-8") as f:
                            first_line = f.readline().strip()
                            if first_line and not first_line.startswith('#') and not first_line.startswith('>'):
                                display_name = first_line
                    except Exception:
                        pass
                # 检查音频
                has_audio = any(f.startswith('source.') for f in os.listdir(item_path)) if os.path.exists(item_path) else False
                # 检查 segments
                has_segments = os.path.exists(os.path.join(item_path, "segments.json"))
                # 读取 metadata.json 获取模式
                metadata_path = os.path.join(item_path, "metadata.json")
                mode = "summary"
                can_migrate = False
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                            mode = meta.get("mode", "summary")
                            can_migrate = (
                                meta.get("can_redownload", False) or
                                (meta.get("audio_saved", False) and meta.get("audio_filename"))
                            )
                    except Exception:
                        pass
                # 检查是否有 timeline.json
                has_timeline = os.path.exists(os.path.join(item_path, "timeline.json"))

                # 读取封面信息（容错：metadata 可能有误，以磁盘实际文件为准）
                cover_url = None
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                            cf = meta.get("cover_filename")
                            if cf and os.path.exists(os.path.join(item_path, cf)):
                                cover_url = f"/api/archives/{item}/cover"
                    except Exception:
                        pass
                # metadata 读取失败或 cover_saved 不准确时，扫描磁盘上是否有 cover.* 文件
                if not cover_url:
                    for fname in os.listdir(item_path):
                        if fname.startswith("cover.") and not fname.startswith("cover.tmp"):
                            cover_url = f"/api/archives/{item}/cover"
                            break

                archives.append({
                    "id": item,
                    "name": display_name,
                    "createTime": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                    "hasAudio": has_audio,
                    "hasSegments": has_segments,
                    "mode": mode,
                    "hasTimeline": has_timeline,
                    "canMigrate": can_migrate,
                    "coverUrl": cover_url,
                })

        return {
            "status": "success",
            "archives": archives
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3.2 迁移归档为 timeline 模式
@app.post("/api/archives/{archive_id}/migrate")
def migrate_archive_to_timeline(archive_id: str):
    """
    将 summary 模式归档迁移为 timeline 模式。
    在已有 segments.json + raw.txt 的基础上重新生成 timeline.json。
    新建一条 timeline 归档，保留原 summary 归档。
    """
    try:
        archive_path = os.path.join(ARCHIVE_DIR, archive_id)

        if not os.path.abspath(archive_path).startswith(os.path.abspath(ARCHIVE_DIR)):
            raise HTTPException(status_code=400, detail="无效的归档名")
        if not os.path.exists(archive_path) or not os.path.isdir(archive_path):
            raise HTTPException(status_code=404, detail="归档不存在")

        # 读取转录文本和分段
        raw_path = os.path.join(archive_path, "raw.txt")
        segments_path = os.path.join(archive_path, "segments.json")
        if not os.path.exists(raw_path):
            raise HTTPException(status_code=400, detail="归档缺少 raw.txt，无法迁移")
        with open(raw_path, "r", encoding="utf-8") as f:
            podcast_text = f.read()
        transcript_segments = []
        if os.path.exists(segments_path):
            with open(segments_path, "r", encoding="utf-8") as f:
                transcript_segments = json.load(f)

        # 获取 API Key
        api_key = load_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="请先配置 DashScope API Key")

        # 生成 timeline
        timeline_data = generate_timeline_json(api_key, podcast_text, transcript_segments, title=archive_id)

        # 读取原 metadata
        metadata_path = os.path.join(archive_path, "metadata.json")
        original_meta = {}
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                original_meta = json.load(f)

        # 新建 timeline 归档（在原名后加 _tl 后缀）
        tl_archive_name = f"{archive_id}_tl"
        tl_archive_path = os.path.join(ARCHIVE_DIR, tl_archive_name)
        os.makedirs(tl_archive_path, exist_ok=True)

        # 复制原音频（如果存在）
        audio_filename = original_meta.get("audio_filename")
        if audio_filename:
            src_audio = os.path.join(archive_path, audio_filename)
            if os.path.exists(src_audio):
                shutil.copy2(src_audio, os.path.join(tl_archive_path, audio_filename))

        # 复制 raw.txt 和 segments.json
        if os.path.exists(raw_path):
            shutil.copy2(raw_path, os.path.join(tl_archive_path, "raw.txt"))
        if os.path.exists(segments_path):
            shutil.copy2(segments_path, os.path.join(tl_archive_path, "segments.json"))

        # 写 timeline.json
        with open(os.path.join(tl_archive_path, "timeline.json"), "w", encoding="utf-8") as f:
            json.dump(timeline_data, f, ensure_ascii=False, indent=2)

        # 写 summary.md（轻量）
        node_count = len(timeline_data.get("nodes", []))
        with open(os.path.join(tl_archive_path, "summary.md"), "w", encoding="utf-8") as f:
            f.write(f"# {timeline_data.get('title', archive_id)}\n\n[时间轴模式] 共 {node_count} 个节点\n")

        # 写 metadata.json
        tl_meta = {
            "id": tl_archive_name,
            "title": timeline_data.get("title", archive_id),
            "mode": "timeline",
            "source_type": original_meta.get("source_type", "other"),
            "source_url": original_meta.get("source_url", ""),
            "audio_saved": original_meta.get("audio_saved", False),
            "audio_filename": original_meta.get("audio_filename"),
            "can_redownload": original_meta.get("can_redownload", False),
            "created_at": datetime.now().isoformat(),
        }
        with open(os.path.join(tl_archive_path, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(tl_meta, f, ensure_ascii=False, indent=2)

        # 向量索引
        try:
            index_archive(tl_archive_name, tl_archive_name, podcast_text)
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"已生成时间轴模式归档",
            "timeline_archive_id": tl_archive_name
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3.3 删除归档
def _robust_rmtree(path):
    """
    跨平台 robust 删除目录，处理 Windows 锁定文件和只读属性。
    """
    if platform.system() == 'Windows':
        def _onerror(func, file_path, exc_info):
            # Windows 上如果文件被锁定或只读，先修改权限再重试
            os.chmod(file_path, stat.S_IWRITE)
            func(file_path)
        shutil.rmtree(path, onerror=_onerror)
    else:
        shutil.rmtree(path)


@app.delete("/api/archives/{archive_name}")
def delete_archive(archive_name: str):
    """
    删除指定的归档目录。
    """
    try:
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)

        # 安全检查：确保路径在归档目录内
        if not os.path.abspath(archive_path).startswith(os.path.abspath(ARCHIVE_DIR)):
            raise HTTPException(status_code=400, detail="无效的归档名")

        if not os.path.exists(archive_path) or not os.path.isdir(archive_path):
            raise HTTPException(status_code=404, detail="归档不存在")

        # 删除整个目录（使用 robust 版本，处理 Windows 锁定文件）
        _robust_rmtree(archive_path)
        # 删除向量
        delete_archive_vectors(archive_name)
        return {"status": "success", "message": f"归档 '{archive_name}' 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3.2 获取单个归档详情
def _find_audio_in_archive(archive_path: str) -> str | None:
    """
    在归档目录中查找音频文件。
    支持常见格式：source.mp3, source.m4a, source.wav 等。
    返回相对于 archive 目录的路径，或 None。
    """
    import os
    if not os.path.exists(archive_path):
        return None
    for fname in os.listdir(archive_path):
        if fname.startswith('source.'):
            return fname
    return None


def _generate_chapters_from_highlights(highlights: list, target_count: int = 6) -> list:
    """
    基于 highlights 的时间均匀分段生成章节。

    策略：
    1. 将音频总时长按 target_count 切分为 chunk_size，按时间均匀分段
    2. 每段取首条 highlight 提取章节标题
    3. 章节不足 3 条 highlight 则向前合并，避免过薄章节
    4. 标题提取：移除中文编号前缀，优先取冒号后内容，再取第一停顿符前内容
    无需 LLM，纯规则驱动，稳定可解释。
    """
    if not highlights or len(highlights) < 3:
        return []

    total_seconds = highlights[-1]["seconds"]
    if total_seconds <= 0:
        return []

    chunk_size = total_seconds / target_count

    chapters = []
    current_chapter = {
        "items": [highlights[0]],
        "start_seconds": highlights[0]["seconds"]
    }

    for i, hl in enumerate(highlights[1:], start=1):
        elapsed = hl["seconds"] - current_chapter["start_seconds"]
        is_last = (i == len(highlights) - 1)

        if elapsed >= chunk_size or is_last:
            current_chapter["items"].append(hl)
            first = current_chapter["items"][0]
            last = current_chapter["items"][-1]

            raw_title = first.get("title", first.get("description", ""))
            chapter_title = _extract_chapter_title(raw_title)

            chapters.append({
                "id": f"ch_{len(chapters)}",
                "time": first["time"],
                "seconds": first["seconds"],
                "title": chapter_title,
                "description": f"{first['time']} - {last['time']}",
                "items": current_chapter["items"]
            })

            current_chapter = {"items": [hl], "start_seconds": hl["seconds"]}
        else:
            current_chapter["items"].append(hl)

    # 后处理：章节不足 3 条 highlight 则向前合并
    merged = []
    for ch in chapters:
        if len(ch["items"]) < 3 and merged:
            prev = merged[-1]
            # 合并到前一章：更新 items 和 description
            prev["items"].extend(ch["items"])
            last_item = ch["items"][-1]
            prev["description"] = f"{prev['time']} - {last_item['time']}"
            # 如果前章标题是开场白引子，替换为当前章标题
            if _is_opening_title(prev["title"]):
                prev["title"] = ch["title"]
                prev["time"] = ch["time"]
                prev["seconds"] = ch["seconds"]
        else:
            merged.append(ch)

    return merged[:8]


def _is_opening_title(title: str) -> bool:
    """判断章节标题是否属于'开场/引子'类低信息量标题，触发替换。"""
    import re
    opening_patterns = [
        r'^.{0,10}[开场开场白序幕引子导入]$',  # 以"开场"等结尾的短标题
        r'^[男女].{0,8}[说问道称提提道云云云]',  # 以"他说"/"我问道"等开头的对话引入
        r'^.{0,8}[啊呢嘛呀哈哦嘿嗯]$',  # 以语气词结尾
        r'^[上下左右前后前后]半段',  # 明显不完整的切分标题
    ]
    for p in opening_patterns:
        if re.search(p, title):
            return True
    # 超过5个字符且不含专有名词/公司名的中文标题，也可能是引子
    if len(title) <= 6 and not re.search(r'[公司集团机构]', title):
        return True
    return False


def _extract_chapter_title(text: str) -> str:
    """
    从 highlight 原始文本提取短章节标题。
    规则：移除中文编号前缀，取冒号后半部分，取第一个停顿符前的内容，不超过 26 字符。
    """
    import re
    # 移除开头的话题标记（一、二、三、1.2.3.等）
    text = re.sub(r'^[一二三四五六七八九\d]+[、.、\s—\-:：]+', '', text)

    # 如果有冒号/：取其后半部分（章节标题通常在冒号后）
    if '：' in text:
        parts = text.split('：', 1)
        if len(parts[1].strip()) >= 4:
            text = parts[1].strip()
    elif ':' in text:
        parts = text.split(':', 1)
        if len(parts[1].strip()) >= 4:
            text = parts[1].strip()

    # 取第一个常见停顿符前的部分
    for sep in ['，', '、', '。', '？', '?']:
        if sep in text:
            text = text.split(sep)[0]
            break
    text = text.strip()
    if len(text) > 26:
        text = text[:26]
    return text or "章节"


def _generate_terms_from_summary_and_segments(summary: str, transcript_segments: list) -> list:
    """
    从 summary.md 的核心关键词区块提取术语，并在 transcriptSegments 中
    匹配首次出现时间，生成带解释的 terms 数组。

    策略：
    1. 解析 summary 中的 '> 核心关键词：' 行，逗号分隔提取 term 候选
    2. 在 transcriptSegments 中模糊匹配每个 term 的首次出现
    3. 取该 segment 的 seconds 作为 time，并截取前后各一整句作为 explanation
    无需 LLM，纯规则驱动。
    """
    import re

    # 1. 提取核心关键词行
    kw_match = re.search(r'核心关键词[：:]\s*(.+)', summary)
    if not kw_match:
        return []

    keywords_raw = kw_match.group(1).strip()
    # 过滤掉 > 注释符和空条目
    keyword_terms = [
        t.strip().rstrip('。.,;:，、')
        for t in keywords_raw.split('，')
        if t.strip() and not t.strip().startswith('>')
    ]

    if not keyword_terms:
        return []

    # 2. 构建 segment 文本用于匹配（按时间顺序）
    segments_text = [(seg.get("seconds", 0), seg.get("time", ""), seg.get("text", "")) for seg in transcript_segments]

    terms = []
    seen_terms = set()  # 避免重复

    for term in keyword_terms:
        if len(term) < 2 or term in seen_terms:
            continue

        # 3. 在 segments 中找包含该 term 的最佳 segment（模糊匹配）
        # 策略：优先 exact match，其次最长的 contentful 子串匹配
        skip_prefixes = {'本', '期', '今', '昨', '各', '该', '这', '那', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '百', '千', '万', '第', '的', '了', '在', '是', '和', '与', '或', '但', '而', '以', '及', '等', '将', '已', '正在', 'The ', 'A ', 'An '}
        best_seg = None
        best_score = 0
        for sec, time_str, text in segments_text:
            score = 0
            if term in text:
                score = 100  # exact match
            else:
                # 找所有 3+ char contentful 子串在 text 中的出现次数
                for i in range(len(term)):
                    sub = term[i:i+4]
                    if len(sub) >= 3 and sub not in skip_prefixes:
                        cnt = text.count(sub)
                        if cnt > 0:
                            score = max(score, len(sub) * cnt)  # 越长 + 越多 = 越好
                    elif len(sub) == 2:
                        cnt = text.count(sub)
                        if cnt > 0:
                            score = max(score, 2 * cnt)
                # 带 × 拆分的 part 匹配
                if '×' in term or '·' in term:
                    for part in term.split('×') if '×' in term else term.split('·'):
                        part = part.strip()
                        if len(part) >= 2 and part in text:
                            score = max(score, len(part) * 2)
            if score > best_score:
                best_score = score
                best_seg = (sec, time_str, text)
                if score >= 100:
                    break

        if best_seg is None:
            # fallback：在 highlights 行中查找
            for line in summary.split('\n'):
                m = re.match(r'^- \[(\d+):(\d{2})(?:\.\d+)?\] (.+)$', line.strip())
                if m and term in m.group(3):
                    sec = int(m.group(1)) * 60 + int(m.group(2))
                    best_seg = (sec, f"{int(m.group(1)):02d}:{int(m.group(2)):02d}", m.group(3))
                    break

        if best_seg:
            sec, time_str, seg_text = best_seg
            # 4. 生成 explanation：从 segment 文本中提取包含 term 的那一小句
            explanation = _make_term_explanation(term, seg_text)
            terms.append({
                "id": f"term_{len(terms)}",
                "term": term,
                "time": time_str,
                "seconds": sec,
                "explanation": explanation
            })
            seen_terms.add(term)

        if len(terms) >= 12:  # 最多 12 个 term
            break

    return terms


def _make_term_explanation(term: str, segment_text: str) -> str:
    """从包含 term 的 segment 中提取一句简洁解释。"""
    import re
    # 找到 term 在文本中的位置，取其前后各 10 个字符的范围
    idx = segment_text.find(term)
    if idx == -1:
        # fuzzy fallback：截取 segment 前 40 字符
        return segment_text[:40].strip(' ，、。')

    # 以常见句子分隔符切分，取包含 term 的那句
    for sep in ['。', '？', '！', '；']:
        sentences = segment_text.split(sep)
        for sent in sentences:
            if term in sent:
                return (sent + sep).strip()
    # fallback
    start = max(0, idx - 10)
    end = min(len(segment_text), idx + len(term) + 20)
    return segment_text[start:end].strip(' ，、')


def _parse_timeline_from_summary(summary: str) -> dict:
    """
    从 summary markdown 中解析时间轴数据（highlights + chapters）。

    格式示例：
    ### 细致高光时间轴
    - [00:19] 开场寒暄，介绍播客背景
    - [05:32] 讨论的话题引入
    """
    highlights = []
    terms = []

    # 从 summary 中提取高光时间轴（- [MM:SS] 格式）
    for line in summary.split('\n'):
        match = re.match(r'^- \[(\d+):(\d{2})(?:\.\d+)?\] (.+)$', line.strip())
        if match:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            total_seconds = minutes * 60 + seconds
            text = match.group(3).strip()
            highlights.append({
                "id": f"hl_{len(highlights)}",
                "time": f"{minutes:02d}:{seconds:02d}",
                "seconds": total_seconds,
                "title": text[:80] if len(text) > 80 else text,
                "description": text
            })

    # 从 highlights 聚类生成章节
    chapters = _generate_chapters_from_highlights(highlights, target_count=6)

    # terms 由 get_archive_detail 调用 _generate_terms_from_summary_and_segments 单独生成
    return {
        "chapters": chapters,
        "highlights": highlights,
        "terms": terms
    }


@app.get("/api/archives/{archive_id}")
def get_archive_detail(archive_id: str):
    """
    获取指定归档的详细内容（摘要、原始转录、时间轴）。
    """
    try:
        archive_path = os.path.join(ARCHIVE_DIR, archive_id)

        # 安全检查：确保路径在归档目录内
        if not os.path.abspath(archive_path).startswith(os.path.abspath(ARCHIVE_DIR)):
            raise HTTPException(status_code=400, detail="无效的归档ID")

        if not os.path.exists(archive_path) or not os.path.isdir(archive_path):
            raise HTTPException(status_code=404, detail="归档不存在")

        # 读取摘要文件
        summary_path = os.path.join(archive_path, "summary.md")
        summary = ""
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                summary = f.read()

        # 读取原始转录文件
        raw_path = os.path.join(archive_path, "raw.txt")
        raw_text = ""
        if os.path.exists(raw_path):
            with open(raw_path, "r", encoding="utf-8") as f:
                raw_text = f.read()

        # 获取创建时间
        create_time = datetime.fromtimestamp(
            os.path.getctime(archive_path)
        ).strftime("%Y-%m-%d %H:%M")

        # 解析时间轴
        timeline = _parse_timeline_from_summary(summary)

        # 读取转录分段
        transcript_segments = []
        segments_path = os.path.join(archive_path, "segments.json")
        if os.path.exists(segments_path):
            import json
            with open(segments_path, "r", encoding="utf-8") as f:
                transcript_segments = json.load(f)

        # 生成 terms（基于 summary 关键词 + transcriptSegments 首次出现时间）
        # 映射为 TimelineItem 结构：term→title, explanation→description
        raw_terms = _generate_terms_from_summary_and_segments(summary, transcript_segments)
        timeline["terms"] = [
            {
                "id": t["id"],
                "title": t["term"],
                "time": t["time"],
                "seconds": t["seconds"],
                "description": t["explanation"]
            }
            for t in raw_terms
        ]

        # 查找归档中的音频文件
        audio_filename = _find_audio_in_archive(archive_path)
        audio_url = f"/api/archives/{archive_id}/audio" if audio_filename else None

        # 提取标题（summary 第一行）
        title = archive_id
        if summary:
            first_line = summary.split('\n')[0].strip()
            if first_line and not first_line.startswith('#') and not first_line.startswith('>'):
                title = first_line

        # 读取 metadata.json（timeline 模式才有）
        metadata = None
        metadata_path = os.path.join(archive_path, "metadata.json")
        if os.path.exists(metadata_path):
            import json
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

        # 读取 timeline.json（timeline 模式才有）
        timeline_data = None
        tl_path = os.path.join(archive_path, "timeline.json")
        if os.path.exists(tl_path):
            import json
            with open(tl_path, "r", encoding="utf-8") as f:
                timeline_data = json.load(f)

        # 解析封面 URL（容错：metadata 可能有误，以磁盘实际文件为准）
        cover_url = None
        if os.path.exists(metadata_path):
            try:
                import json as _json
                with open(metadata_path, "r", encoding="utf-8") as f:
                    meta = _json.load(f)
                cf = meta.get("cover_filename")
                if cf and os.path.exists(os.path.join(archive_path, cf)):
                    cover_url = f"/api/archives/{archive_id}/cover"
            except Exception:
                pass
        if not cover_url:
            for fname in os.listdir(archive_path):
                if fname.startswith("cover.") and not fname.startswith("cover.tmp"):
                    cover_url = f"/api/archives/{archive_id}/cover"
                    break

        return {
            "status": "success",
            "data": {
                "id": archive_id,
                "name": title,
                "summary": summary,
                "rawText": raw_text,
                "createTime": create_time,
                "audioUrl": audio_url,
                "audioFilename": audio_filename,
                "coverUrl": cover_url,
                "timeline": timeline,
                "transcriptSegments": transcript_segments,
                "mode": metadata.get("mode", "summary") if metadata else "summary",
                "metadata": metadata,
                "timelineData": timeline_data,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/archives/{archive_id}/audio")
def stream_archive_audio(archive_id: str, request: Request):
    """
    流式返回归档目录中的音频文件（source.*），支持 HTTP Range 请求。
    用于前端 <audio> 标签的 src。
    """
    try:
        archive_path = os.path.join(ARCHIVE_DIR, archive_id)

        # 安全检查
        if not os.path.abspath(archive_path).startswith(os.path.abspath(ARCHIVE_DIR)):
            raise HTTPException(status_code=400, detail="无效的归档ID")

        if not os.path.exists(archive_path) or not os.path.isdir(archive_path):
            raise HTTPException(status_code=404, detail="归档不存在")

        # 查找音频文件
        audio_filename = _find_audio_in_archive(archive_path)
        if not audio_filename:
            raise HTTPException(status_code=404, detail="归档中未找到音频文件")

        audio_path = os.path.join(archive_path, audio_filename)

        import mimetypes
        mime_type, _ = mimetypes.guess_type(audio_path)
        # 规范化 MIME 类型
        if mime_type == "audio/mp4a-latm":
            mime_type = "audio/mp4"
        mime_type = mime_type or "application/octet-stream"

        file_size = os.path.getsize(audio_path)

        # 处理 Range 请求
        range_header = request.headers.get("range")
        if range_header:
            # 解析 Range 头，格式: "bytes=start-end"
            try:
                range_match = range_header.strip().replace('bytes=', '')
                if '-' in range_match:
                    parts = range_match.split('-')
                    start = int(parts[0]) if parts[0] else 0
                    end = int(parts[1]) if parts[1] else file_size - 1
                else:
                    start = int(range_match)
                    end = file_size - 1
                start = max(0, start)
                end = min(end, file_size - 1)
                if start > end or start >= file_size:
                    return Response(
                        content=b"",
                        status_code=416,
                        headers={
                            "Content-Range": f"bytes */{file_size}",
                            "Accept-Ranges": "bytes",
                        }
                    )
                content_length = end - start + 1

                def iter_range():
                    with open(audio_path, "rb") as f:
                        f.seek(start)
                        remaining = content_length
                        while remaining > 0:
                            chunk_size = min(65536, remaining)
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk

                return StreamingResponse(
                    iter_range(),
                    status_code=206,
                    media_type=mime_type,
                    headers={
                        "Content-Length": str(content_length),
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                        "Accept-Ranges": "bytes",
                        "Content-Disposition": f'inline; filename="{audio_filename}"',
                    }
                )
            except Exception as e:
                print(f"[Audio] Range 解析失败: {e}")

        # 无 Range 或解析失败：返回完整文件
        def iterfile():
            with open(audio_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            iterfile(),
            media_type=mime_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'inline; filename="{audio_filename}"',
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/archives/{archive_id}/cover")
def serve_archive_cover(archive_id: str):
    """
    返回归档目录中的封面图片文件。
    """
    try:
        archive_path = os.path.join(ARCHIVE_DIR, archive_id)

        # 安全检查
        if not os.path.abspath(archive_path).startswith(os.path.abspath(ARCHIVE_DIR)):
            raise HTTPException(status_code=400, detail="无效的归档ID")

        if not os.path.exists(archive_path) or not os.path.isdir(archive_path):
            raise HTTPException(status_code=404, detail="归档不存在")

        # 读取 metadata 找到封面文件名（容错：以磁盘实际文件为准）
        metadata_path = os.path.join(archive_path, "metadata.json")
        cover_filename = None
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    cf = meta.get("cover_filename")
                    if cf and os.path.exists(os.path.join(archive_path, cf)):
                        cover_filename = cf
            except Exception:
                pass

        # metadata 读取失败或 cover_saved 不准确时，扫描磁盘上是否有 cover.* 文件
        if not cover_filename:
            for fname in os.listdir(archive_path):
                if fname.startswith("cover.") and not fname.startswith("cover.tmp"):
                    cover_filename = fname
                    break

        if not cover_filename:
            raise HTTPException(status_code=404, detail="归档无封面")

        cover_path = os.path.join(archive_path, cover_filename)
        if not os.path.exists(cover_path):
            raise HTTPException(status_code=404, detail="封面文件不存在")

        import mimetypes
        mime_type, _ = mimetypes.guess_type(cover_path)
        mime_type = mime_type or "image/jpeg"
        file_size = os.path.getsize(cover_path)

        def iterfile():
            with open(cover_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            iterfile(),
            media_type=mime_type,
            headers={
                "Content-Length": str(file_size),
                "Cache-Control": "public, max-age=86400",
                "Content-Disposition": f'inline; filename="{cover_filename}"',
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 4. 系统诊断接口
@app.get("/api/diagnostics")
def run_diagnostics():
    try:
        api_key = load_api_key()
        results = run_all_diagnostics(api_key=api_key)
        # 转换结果为前端易用的格式
        formatted_results = []
        for name, success, message in results:
            formatted_results.append({
                "name": name,
                "success": success,
                "message": message
            })
        return {"status": "success", "data": formatted_results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================= 模型管理 API（云端模式，无需本地模型）=================

@app.get("/api/models/status")
def get_models_status():
    """本地模型已停用，统一使用 DashScope 云端 ASR"""
    return {"status": "success", "data": []}

@app.get("/api/models/manual-download/{model_name}")
def get_manual_download(model_name: str):
    raise HTTPException(status_code=404, detail="本地模型已停用，使用 DashScope 云端 ASR")

@app.delete("/api/models/{model_name}")
def delete_model(model_name: str):
    raise HTTPException(status_code=404, detail="本地模型已停用，使用 DashScope 云端 ASR")


# 5. 获取可用硬件设备列表
@app.get("/api/devices")
def get_devices():
    """
    获取系统可用的计算设备列表。
    """
    try:
        devices = get_available_devices()
        # 转换为前端需要的格式
        device_list = []
        for key, name in devices.items():
            device_list.append({
                "key": key,
                "name": name
            })
        return {
            "status": "success",
            "data": device_list
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 6. 获取偏好设置
@app.get("/api/settings")
def get_settings():
    api_key = load_api_key()
    config = load_config()
    return {
        "status": "success",
        "data": {
            "dashscope_api_key": api_key,
            "max_timeline_items": config.get("max_timeline_items", 15)
        }
    }


# 7. 保存偏好设置
@app.post("/api/settings")
def save_settings(
    dashscope_api_key: str = Form(""),
    max_timeline_items: int = Form(15)
):
    try:
        # 保存 API Key 到 .env 文件（使用 DASHSCOPE_API_KEY=xxx 格式）
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write(f"DASHSCOPE_API_KEY={dashscope_api_key.strip()}")

        # 同步更新当前进程环境变量，使 worker 线程立即可见
        os.environ['DASHSCOPE_API_KEY'] = dashscope_api_key.strip()

        # 保存配置到 config.json
        config = load_config()
        config["max_timeline_items"] = max_timeline_items
        save_config(config)

        return {"status": "success", "message": "设置已保存"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================= 任务队列 API =================

# 8. 获取队列统计
@app.get("/api/tasks/stats")
def get_tasks_stats():
    """获取任务队列统计信息"""
    try:
        stats = get_queue_stats()
        worker_running = is_worker_running()
        paused = is_paused()
        return {
            "status": "success",
            "data": {
                "pending": stats.get("PENDING", 0),
                "processing": stats.get("PROCESSING", 0),
                "completed": stats.get("COMPLETED", 0),
                "failed": stats.get("FAILED", 0),
                "worker_running": worker_running,
                "paused": paused
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 9. 获取所有任务
@app.get("/api/tasks")
def list_tasks(status: str = None):
    """获取任务列表"""
    try:
        if status:
            tasks = get_all_tasks(status=status)
        else:
            tasks = get_all_tasks()
        return {
            "status": "success",
            "tasks": tasks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 10. 获取单个任务
@app.get("/api/tasks/{task_id}")
def get_single_task(task_id: str):
    """获取指定任务详情"""
    try:
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {
            "status": "success",
            "task": task
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 11. 添加新任务到队列
@app.post("/api/tasks")
async def create_task(
    source: str = Form(...),
    task_type: str = Form(...),
    max_timeline_items: int = Form(15),
    name: str = Form(""),
    mode: str = Form("summary")
):
    """添加新任务到处理队列"""
    try:
        # 确保 Worker 正在运行
        if not is_worker_running():
            start_worker()

        task_id = add_task(
            source=source,
            task_type=task_type,
            max_timeline_items=max_timeline_items,
            name=name if name else None,
            mode=mode
        )
        return {
            "status": "success",
            "task_id": task_id,
            "message": "任务已添加到队列"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 12. 删除任务
@app.delete("/api/tasks/{task_id}")
def remove_task(task_id: str):
    """删除指定任务"""
    try:
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        delete_task(task_id)
        return {"status": "success", "message": "任务已删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 13. 清空已完成任务
@app.post("/api/tasks/clear-completed")
def clear_finished_tasks():
    """清空所有已完成的任务"""
    try:
        count = clear_completed()
        return {"status": "success", "message": f"已清空 {count} 个已完成任务"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 14. 重试失败任务
@app.post("/api/tasks/retry-failed")
def retry_tasks():
    """重试所有失败的任务"""
    try:
        api_key = load_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="请先配置 API Key")

        success_count = retry_failed_tasks(api_key)
        return {"status": "success", "message": f"成功重试 {success_count} 个任务"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 15. 暂停/恢复 Worker
@app.post("/api/tasks/pause")
def pause_queue():
    """暂停任务队列处理"""
    try:
        pause_worker()
        return {"status": "success", "message": "队列已暂停"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tasks/resume")
def resume_queue():
    """恢复任务队列处理"""
    try:
        resume_worker()
        return {"status": "success", "message": "队列已恢复"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 16. 重试 LLM 摘要（仅生成摘要，跳过下载和转录）
@app.post("/api/tasks/{task_id}/retry-llm")
def retry_task_llm(task_id: str):
    """
    对于 LLM 失败的任务，使用已保存的转录文本重新生成摘要。
    仅跳过下载和转录步骤，直接调用 LLM 并归档。
    """
    try:
        # 获取 API Key
        api_key = load_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="请先配置 API Key")

        # 获取任务信息
        task = get_task(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        if task["status"] != "FAILED":
            raise HTTPException(status_code=400, detail="只能重试失败的任务")

        # 检查恢复文件是否存在
        recovery_path = os.path.join(TEMP_DIR, f".llm_recovery_{task_id}.txt")
        if not os.path.exists(recovery_path):
            raise HTTPException(status_code=404, detail="未找到转录恢复文件，请重新处理此任务")

        # 读取转录文本
        with open(recovery_path, "r", encoding="utf-8") as f:
            podcast_text = f.read()

        if not podcast_text:
            raise HTTPException(status_code=400, detail="转录文本为空")

        # 获取任务参数
        max_timeline_items = task.get("max_timeline_items", 15)
        title = task.get("name", "未知任务")

        # 调用 LLM 生成摘要
        print(f"[Retry-LLM] 正在为任务 {task_id} 生成摘要...")
        raw_summary = get_podcast_summary_robust(api_key, podcast_text, max_timeline_items)

        # 提取第一行作为标题
        lines = raw_summary.strip().split('\n')
        ai_title = lines[0] if lines else title

        # 归档
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:50]
        archive_name = f"{safe_title}_{date_str}"

        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        os.makedirs(archive_path, exist_ok=True)

        # 保存 raw.txt
        raw_path = os.path.join(archive_path, "raw.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(podcast_text)

        # 自动索引到向量库
        try:
            index_archive(archive_name, archive_name, podcast_text)
        except Exception as e:
            print(f"[RAG] 向量索引失败（不影响归档）: {e}")

        # 保存 summary.md
        summary_path = os.path.join(archive_path, "summary.md")
        lines = raw_summary.strip().split('\n')
        if lines:
            first_line = lines[0].strip()
            if first_line.startswith('#'):
                ai_title = first_line.lstrip('#').strip()
                clean_summary = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
            else:
                ai_title = first_line if first_line else title
                clean_summary = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        else:
            ai_title = title
            clean_summary = ""

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"# {ai_title}\n\n{clean_summary}")

        # 更新任务状态为已完成
        update_task_status(task_id, "COMPLETED", result_path=archive_path)

        # 清理恢复文件
        try:
            os.remove(recovery_path)
        except:
            pass

        print(f"[Retry-LLM] 任务 {task_id} 摘要重试成功，归档到: {archive_path}")

        return {
            "status": "success",
            "message": f"摘要生成成功，已归档到: {archive_name}",
            "archive_id": archive_name
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 17. AI 模糊定位器（单归档版）
@app.post("/api/search")
async def search_podcast(request: dict):
    """在归档的转录文本中搜索相关内容"""
    try:
        archive_id = request.get('archive_id')
        query = request.get('query')
        api_key = request.get('api_key', '')

        if not archive_id or not query:
            raise HTTPException(status_code=400, detail="缺少 archive_id 或 query 参数")

        # 获取 API Key
        if not api_key:
            api_key = load_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="请先配置 DashScope API Key")

        # 获取归档的转录文本
        archive_path = os.path.join(ARCHIVE_DIR, archive_id)
        if not os.path.exists(archive_path):
            raise HTTPException(status_code=404, detail="归档不存在")

        raw_path = os.path.join(archive_path, "raw.txt")
        if not os.path.exists(raw_path):
            raise HTTPException(status_code=404, detail="转录文本不存在")

        with open(raw_path, "r", encoding="utf-8") as f:
            podcast_text = f.read()

        # 调用搜索
        result = search_in_podcast(api_key, query, podcast_text)

        return {"status": "success", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================= RAG 知识库 API =================

# 18. 标签管理
@app.get("/api/chat/tags")
def list_tags():
    """获取所有标签"""
    try:
        return {"status": "success", "data": get_all_tags()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/tags")
def create_tag_api(request: dict):
    """创建标签"""
    try:
        name = request.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="标签名不能为空")
        tag_id = create_tag(name)
        return {"status": "success", "tag_id": tag_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/chat/tags/{tag_id}")
def delete_tag_api(tag_id: str):
    """删除标签"""
    try:
        delete_tag(tag_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 19. 归档标签关联
@app.get("/api/chat/archives/{archive_id}/tags")
def get_archive_tags_api(archive_id: str):
    """获取归档的标签"""
    try:
        return {"status": "success", "data": get_archive_tags(archive_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/archives/{archive_id}/tags")
def set_archive_tags_api(archive_id: str, request: dict):
    """设置归档的标签"""
    try:
        tag_ids = request.get("tag_ids", [])
        set_archive_tags(archive_id, tag_ids)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 20. 会话管理
@app.get("/api/chat/sessions")
def list_chat_sessions():
    """获取所有会话列表"""
    try:
        return {"status": "success", "data": get_chat_sessions()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/sessions")
def create_chat_session_api(request: dict = None):
    """创建新会话"""
    try:
        title = (request.get("title", "新对话") if request else "新对话").strip()
        if not title:
            title = "新对话"
        session_id = create_chat_session(title)
        return {"status": "success", "session_id": session_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/chat/sessions/{session_id}")
def get_chat_session_api(session_id: str):
    """获取会话详情（含消息）"""
    try:
        session = get_chat_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = get_chat_messages(session_id)
        return {"status": "success", "data": {**session, "messages": messages}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/chat/sessions/{session_id}/title")
def update_chat_session_title_api(session_id: str, request: dict):
    """更新会话标题"""
    try:
        title = request.get("title", "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="标题不能为空")
        update_chat_session_title(session_id, title)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/chat/sessions/{session_id}")
def delete_chat_session_api(session_id: str):
    """删除会话"""
    try:
        delete_chat_session(session_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 21. SSE 流式对话
@app.post("/api/chat/sessions/{session_id}/stream")
async def chat_stream(session_id: str, request: dict):
    """
    SSE 流式对话接口。

    前端发送：{"query": "...", "archive_ids": [], "tag_ids": []}
    返回：Server-Sent Events 流
    """
    try:
        session = get_chat_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在")

        query = request.get("query", "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="问题不能为空")

        archive_ids = request.get("archive_ids") or None
        tag_ids = request.get("tag_ids") or None

        api_key = load_api_key()
        if not api_key:
            raise HTTPException(status_code=400, detail="请先配置 DashScope API Key")

        # 保存用户消息
        add_chat_message(session_id, "user", query)

        # 异步生成器，用于 SSE
        async def event_generator():
            referenced_archives = []
            full_content = ""

            for event in generate_chat_response(
                api_key=api_key,
                query=query,
                archive_ids=archive_ids,
                tag_ids=tag_ids,
                top_k=20,
                stream=True
            ):
                if event["type"] == "token":
                    referenced_archives = event["referenced_archives"]
                    full_content += event["content"]
                    yield {
                        "event": "token",
                        "data": event["content"]
                    }
                elif event["type"] == "done":
                    referenced_archives = event["referenced_archives"]
                    full_content = event["content"]
                    # JSON 放前面（JSON 不以 \n 开头，保证 split 只匹配分隔符）
                    yield {
                        "event": "done",
                        "data": f"{json.dumps(referenced_archives, ensure_ascii=False)}\n{full_content}"
                    }

            # 保存助手消息
            if full_content:
                add_chat_message(session_id, "assistant", full_content)

                # 记录引用（去重，按 archive_id）
                seen_ids = set()
                for ref in referenced_archives:
                    aid = ref["archive_id"]
                    if aid not in seen_ids:
                        seen_ids.add(aid)
                        add_chat_reference(session_id, aid, cited_timestamp=ref.get("timestamp", ""))

                # 更新会话标题（如果还是默认标题，用第一个用户问题截取）
                if session.get("title", "新对话") == "新对话":
                    short_title = query[:30] + ("..." if len(query) > 30 else "")
                    update_chat_session_title(session_id, short_title)

            yield {"event": "end", "data": ""}

        return EventSourceResponse(event_generator())

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 22. 归档索引（手动触发）
@app.post("/api/chat/archives/{archive_id}/index")
def index_archive_api(archive_id: str):
    """手动将归档索引到向量库"""
    try:
        archive_path = os.path.join(ARCHIVE_DIR, archive_id)
        if not os.path.exists(archive_path):
            raise HTTPException(status_code=404, detail="归档不存在")

        raw_path = os.path.join(archive_path, "raw.txt")
        if not os.path.exists(raw_path):
            raise HTTPException(status_code=404, detail="转录文本不存在")

        with open(raw_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        index_archive(archive_id, archive_id, raw_text)
        return {"status": "success", "message": f"归档 '{archive_id}' 已索引"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 23. 批量索引所有未索引的归档
@app.post("/api/chat/index-all")
def index_all_archives():
    """将所有已有 raw.txt 的归档批量索引"""
    try:
        if not os.path.exists(ARCHIVE_DIR):
            return {"status": "success", "indexed": 0, "skipped": 0}

        indexed = 0
        skipped = 0
        for archive_name in os.listdir(ARCHIVE_DIR):
            archive_path = os.path.join(ARCHIVE_DIR, archive_name)
            if not os.path.isdir(archive_path):
                continue
            raw_path = os.path.join(archive_path, "raw.txt")
            if not os.path.exists(raw_path):
                skipped += 1
                continue
            try:
                with open(raw_path, "r", encoding="utf-8") as f:
                    raw_text = f.read()
                index_archive(archive_name, archive_name, raw_text)
                indexed += 1
            except Exception:
                skipped += 1

        return {"status": "success", "indexed": indexed, "skipped": skipped}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 24. 归档的反向引用（Backlinks）
@app.get("/api/chat/archives/{archive_id}/references")
def get_archive_backlinks(archive_id: str):
    """获取哪些对话引用过此归档"""
    try:
        refs = get_archive_references(archive_id)
        return {"status": "success", "data": refs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================= 启动时初始化 RAG 数据库 =================
init_rag_db()
