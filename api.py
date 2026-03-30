from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import json
import re
import torch
from datetime import datetime
from backend.diagnostics import run_all_diagnostics
from backend.transcriber import transcribe_with_sensevoice, transcribe_audio_to_timestamped_text, get_whisper_model, get_available_devices
from backend.llm_agent import get_podcast_summary_robust, search_in_podcast
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
from sse_starlette.sse import EventSourceResponse
import asyncio

app = FastAPI(title="PodGist API", version="1.0.0")

# 获取 api.py 所在目录作为项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
    文件内容应为单行：sk-xxxxxx
    """
    try:
        if os.path.exists(ENV_FILE):
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                key = f.read().strip()
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
    max_timeline_items: int = Form(15)
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
            raise HTTPException(status_code=400, detail="请提供 DeepSeek API Key")

        # 2. 选择计算设备
        if device == "auto":
            if torch.cuda.is_available():
                device_key = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device_key = "mps"
            else:
                device_key = "cpu"
        else:
            device_key = device

        # 3. 转录（根据选择的引擎）
        if engine == "SenseVoice":
            # SenseVoice 转录
            podcast_text = transcribe_with_sensevoice(file_path, device_key)
        else:
            # Whisper 转录 - 使用前端指定的模型规模
            model = get_whisper_model(whisper_model, device_key)
            podcast_text = transcribe_audio_to_timestamped_text(model, file_path, device_key)

        # 4. 调用大模型生成摘要（使用前端指定的时间轴上限）
        summary = get_podcast_summary_robust(api_key, podcast_text, max_timeline_items=max_timeline_items)

        # 5. 提取第一行作为标题
        lines = summary.strip().split('\n')
        ai_title = lines[0] if lines else os.path.splitext(os.path.basename(file.filename))[0]

        # 6. 创建归档目录
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        archive_name = f"{os.path.splitext(file.filename)[0]}_{date_str}"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        os.makedirs(archive_path, exist_ok=True)

        # 7. 保存原始转录文本
        raw_path = os.path.join(archive_path, "raw.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(podcast_text)

        # 7.5 自动索引到向量库
        try:
            index_archive(archive_name, archive_name, podcast_text)
        except Exception as e:
            print(f"[RAG] 向量索引失败（不影响归档）: {e}")

        # 8. 保存摘要（确保有 H1 标题）
        summary_path = os.path.join(archive_path, "summary.md")
        lines = summary.strip().split('\n')
        if lines:
            first_line = lines[0].strip()
            # 如果第一行已经是标题格式，使用它；否则使用 ai_title
            if first_line.startswith('#'):
                ai_title = first_line.lstrip('#').strip()
                clean_summary = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
            else:
                ai_title = first_line if first_line else os.path.splitext(os.path.basename(file.filename))[0]
                clean_summary = summary

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"# {ai_title}\n\n{clean_summary}")

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
    max_timeline_items: int = Form(15)
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
        raise HTTPException(status_code=400, detail="请提供 DeepSeek API Key")

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
        # 3. 选择计算设备
        if device == "auto":
            if torch.cuda.is_available():
                device_key = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device_key = "mps"
            else:
                device_key = "cpu"
        else:
            device_key = device

        # 4. 转录（根据选择的引擎）
        if engine == "SenseVoice":
            podcast_text = transcribe_with_sensevoice(file_path, device_key)
        else:
            model = get_whisper_model(whisper_model, device_key)
            podcast_text = transcribe_audio_to_timestamped_text(model, file_path, device_key)

        # 5. 调用大模型生成摘要
        summary = get_podcast_summary_robust(api_key, podcast_text, max_timeline_items=max_timeline_items)

        # 6. 创建归档目录
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:50]
        archive_name = f"{safe_title}_{date_str}"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        os.makedirs(archive_path, exist_ok=True)

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
                clean_summary = summary
        else:
            ai_title = safe_title
            clean_summary = summary

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
                archives.append({
                    "id": item,  # 使用目录名作为 ID
                    "name": item  # 使用目录名作为显示名称
                })

        return {
            "status": "success",
            "archives": archives
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3.1 删除归档
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

        # 删除整个目录
        shutil.rmtree(archive_path)
        # 删除向量
        delete_archive_vectors(archive_name)
        return {"status": "success", "message": f"归档 '{archive_name}' 已删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 3.2 获取单个归档详情
@app.get("/api/archives/{archive_id}")
def get_archive_detail(archive_id: str):
    """
    获取指定归档的详细内容（摘要和原始转录）。
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

        return {
            "status": "success",
            "data": {
                "id": archive_id,
                "name": archive_id,
                "summary": summary,
                "rawText": raw_text,
                "createTime": create_time
            }
        }
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
    # 获取可用设备列表
    devices = get_available_devices()
    device_list = [{"key": k, "name": v} for k, v in devices.items()]
    return {
        "status": "success",
        "data": {
            "api_key": api_key,
            "engine": config.get("engine", "SenseVoice"),
            "whisper_model": config.get("whisper_model", "small"),
            "device": config.get("device", "auto"),
            "max_timeline_items": config.get("max_timeline_items", 15),
            "available_devices": device_list
        }
    }


# 7. 保存偏好设置
@app.post("/api/settings")
def save_settings(
    api_key: str = Form(""),
    engine: str = Form("SenseVoice"),
    whisper_model: str = Form("small"),
    device: str = Form("auto"),
    max_timeline_items: int = Form(15)
):
    try:
        # 保存 API Key 到 .env 文件
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write(api_key.strip())

        # 保存所有配置到 config.json
        config = load_config()
        config["engine"] = engine
        config["whisper_model"] = whisper_model
        config["device"] = device
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
    engine: str = Form("SenseVoice"),
    max_timeline_items: int = Form(15),
    name: str = Form("")
):
    """添加新任务到处理队列"""
    try:
        # 确保 Worker 正在运行
        if not is_worker_running():
            start_worker()

        # 转换引擎名称
        engine_key = "sensevoice" if engine == "SenseVoice" else "whisper"

        task_id = add_task(
            source=source,
            task_type=task_type,
            engine=engine_key,
            max_timeline_items=max_timeline_items,
            name=name if name else None
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
                clean_summary = raw_summary
        else:
            ai_title = title
            clean_summary = raw_summary

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
            raise HTTPException(status_code=400, detail="请先配置 DeepSeek API Key")

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
            raise HTTPException(status_code=400, detail="请先配置 DeepSeek API Key")

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
                top_k=5,
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
                    # 将 referenced_archives 内嵌到 data JSON 中，避免非标准 SSE 字段被忽略
                    yield {
                        "event": "done",
                        "data": full_content,
                        "extra_data": json.dumps(referenced_archives, ensure_ascii=False)
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
