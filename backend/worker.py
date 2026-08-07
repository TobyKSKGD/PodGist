"""
后台 Worker 线程模块

负责从队列中拉取任务并执行完整的处理管线。
"""

import os
import sys
import time
import gc
import re
import shutil
import threading
import traceback
from datetime import datetime

# 确保可以导入后端模块
current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, current_dir)

# 导入项目模块
from backend import task_queue
from backend.transcriber import transcribe_with_dashscope_and_segments
from backend.llm_agent import get_podcast_summary_robust
from backend.timeline_agent import enrich_timeline_archive, enrich_timeline_node, generate_timeline_json, warmup_timeline_nodes
from backend.downloader import route_and_download, download_direct_audio
from backend.fetch_cover import fetch_cover, download_cover_image


# Worker 线程名称
WORKER_THREAD_NAME = "PodGist_Batch_Worker"
ENRICHMENT_WORKER_THREAD_NAME = "PodGist_Timeline_Enrichment_Worker"

# 工作目录（优先使用 PODGIST_DATA_DIR，否则回退到项目根目录）
_USER_DATA_DIR = os.environ.get('PODGIST_DATA_DIR')
if _USER_DATA_DIR:
    ARCHIVE_DIR = os.path.join(_USER_DATA_DIR, "archives")
    TEMP_DIR = os.path.join(_USER_DATA_DIR, "temp_audio")
else:
    ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archives")
    TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp_audio")
os.makedirs(ARCHIVE_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# Worker 停止标志
_worker_stop_flag = False
_task_cancel_events: dict[str, threading.Event] = {}
_task_cancel_lock = threading.Lock()


class TaskCancelled(Exception):
    """用户主动取消任务；与处理失败分开记录。"""
    is_task_cancellation = True


def request_task_cancellation(task_id: str) -> bool:
    """向当前 Worker 发出即时信号，并把请求写入数据库用于重启恢复。"""
    with _task_cancel_lock:
        _task_cancel_events.setdefault(task_id, threading.Event()).set()
    return task_queue.request_task_cancellation(task_id)


def _clear_task_cancel_event(task_id: str) -> None:
    with _task_cancel_lock:
        _task_cancel_events.pop(task_id, None)


def _is_task_cancelled(task_id: str) -> bool:
    with _task_cancel_lock:
        event = _task_cancel_events.get(task_id)
        if event and event.is_set():
            return True
    return task_queue.is_task_cancellation_requested(task_id)


def _raise_if_task_cancelled(task_id: str) -> None:
    if _is_task_cancelled(task_id):
        raise TaskCancelled(f"任务 {task_id} 已取消")


def _remove_task_partial_files(task_id: str, archive_path: str | None = None) -> None:
    """只清理该任务明确拥有的暂存目录，绝不扫描或删除其他任务文件。"""
    staging_root = os.path.abspath(os.path.join(TEMP_DIR, "incomplete_archives"))
    targets = [(os.path.abspath(os.path.join(staging_root, task_id)), staging_root)]
    if archive_path:
        targets.append((os.path.abspath(archive_path), os.path.abspath(ARCHIVE_DIR)))
    for target, allowed_root in targets:
        if target == allowed_root or os.path.commonpath([target, allowed_root]) != allowed_root:
            continue
        if os.path.isdir(target):
            shutil.rmtree(target, ignore_errors=True)


def is_worker_running():
    """
    检查 Worker 线程是否已经在运行。

    返回:
        bool: 是否在运行
    """
    for t in threading.enumerate():
        if t.name == WORKER_THREAD_NAME and t.is_alive():
            return True
    return False


def is_enrichment_worker_running():
    """检查后台实体资料富化线程是否正在运行。"""
    return any(t.name == ENRICHMENT_WORKER_THREAD_NAME and t.is_alive() for t in threading.enumerate())


def stop_worker():
    """
    请求停止 Worker 线程（通过创建标志文件）。
    """
    stop_file = os.path.join(TEMP_DIR, ".worker_stop_flag")
    with open(stop_file, "w") as f:
        f.write("1")


def pause_worker():
    """
    暂停 Worker 线程（通过创建暂停标志文件）。
    """
    pause_file = os.path.join(TEMP_DIR, ".worker_pause_flag")
    with open(pause_file, "w") as f:
        f.write("1")


def resume_worker():
    """
    恢复 Worker 线程（删除暂停标志文件）。
    """
    pause_file = os.path.join(TEMP_DIR, ".worker_pause_flag")
    if os.path.exists(pause_file):
        os.remove(pause_file)


def is_paused():
    """
    检查 Worker 是否处于暂停状态。

    返回:
        bool: 是否暂停
    """
    pause_file = os.path.join(TEMP_DIR, ".worker_pause_flag")
    return os.path.exists(pause_file)


def cleanup_temp_audio_file(audio_file_path):
    """
    清理临时音频文件（仅清理下载的文件，不清理本地文件）。

    参数:
        audio_file_path (str): 音频文件路径
    """
    if not audio_file_path:
        return

    # 检查文件是否存在
    if not os.path.exists(audio_file_path):
        return

    # 检查文件是否在 TEMP_DIR 中（只清理 temp_audio 目录下的文件）
    if not audio_file_path.startswith(TEMP_DIR):
        return

    try:
        os.remove(audio_file_path)
        print(f"[Worker] 已清理临时文件: {audio_file_path}")
    except Exception as e:
        print(f"[Worker] 清理临时文件失败: {e}")



def get_api_key():
    """
    从 .env 文件读取 API Key。

    优先从 PODGIST_DATA_DIR 读取（Electron 打包环境），
    其次回退到项目根目录（开发环境）。

    返回:
        str: 干净的 API Key（不含 DASHSCOPE_API_KEY= 前缀）
    """
    # 优先使用 PODGIST_DATA_DIR（打包环境）
    data_dir = os.environ.get('PODGIST_DATA_DIR')
    if data_dir:
        env_path = os.path.join(data_dir, ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DASHSCOPE_API_KEY="):
                        return line.split("=", 1)[1].strip().strip("'\"")
    # 回退到项目根目录（开发环境）
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DASHSCOPE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    return None


def get_task_type(source):
    """
    根据来源判断任务类型。

    参数:
        source (str): 任务来源

    返回:
        str: 任务类型 (local / bilibili / xiaoyuzhou / netease / ximalaya)
    """
    print(f"[get_task_type] source={source}")
    # 转为小写方便比较
    s = source.lower()
    print(f"[get_task_type] s={s}")

    # 网易云检测 - 必须在其他检测之前
    if "163cn.tv" in s or "music.163.com" in s:
        return "netease"

    # 小宇宙检测
    if "xiaoyuzhoufm.com" in s:
        return "xiaoyuzhou"

    # 喜马拉雅检测
    if "xima.tv" in s or "ximalaya.com" in s:
        print(f"[get_task_type] matched ximalaya!")
        return "ximalaya"

    # 苹果播客检测
    if "podcasts.apple.com" in s:
        return "applepodcasts"

    # B站检测
    if "bilibili.com" in s:
        return "bilibili"

    # 本地文件检测
    if os.path.exists(source):
        return "local"

    return "unknown"


def process_single_task(task, api_key):
    """
    处理单个任务。

    参数:
        task (dict): 任务信息
        api_key (str): API Key

    返回:
        tuple: (success, result_path, error_msg)
    """
    task_id = task["id"]
    source = task["source"]
    engine = task.get("engine", "sensevoice")
    max_timeline_items = task.get("max_timeline_items", 15)
    mode = task.get("mode", "summary")

    # 确定 source_type
    source_type_map = {
        "local": "local_file",
        "bilibili": "bilibili",
        "xiaoyuzhou": "podcast_url",
        "netease": "podcast_url",
        "ximalaya": "podcast_url",
        "applepodcasts": "podcast_url",
        "rss": "podcast_url",
    }
    source_type = source_type_map.get(task.get("type", ""), "other")

    print(f"[Worker] 开始处理任务: {source}")

    # 初始化音频文件路径（用于后续清理）
    audio_file_path = None
    public_audio_url = None
    archive_path = None
    final_archive_path = None
    archive_published = False

    try:
        _raise_if_task_cancelled(task_id)
        # 步骤 1: 获取音频文件
        task_type = "rss" if task.get("type") == "rss" else get_task_type(source)
        print(f"[Worker] source={source}, task_type={task_type}, type={type(task_type)}")
        task_queue.update_progress_status(task_id, "正在获取音频...")

        # 强制处理 ximalaya
        if task_type == 'ximalaya':
            print("[Worker] 进入 ximalaya 下载分支")
            result = route_and_download(source, TEMP_DIR)
            if not result["success"]:
                return False, None, f"下载失败: {result.get('error', '未知错误')}"
            audio_file_path = result["file_path"]
            title = result["title"]
            public_audio_url = result.get("asr_public_url")
            task_queue.update_task_name(task_id, title)
            task_queue.update_progress_status(task_id, "音频获取成功")
            # 继续转录...
        elif task_type == "local":
            # 本地文件
            audio_file_path = source
            title = os.path.splitext(os.path.basename(source))[0]
        elif task_type == 'rss':
            result = download_direct_audio(
                source,
                TEMP_DIR,
                title=task.get("name"),
                cancellation_callback=lambda: _raise_if_task_cancelled(task_id),
            )
            if not result["success"]:
                return False, None, f"下载失败: {result.get('error', '未知错误')}"
            audio_file_path = result["file_path"]
            title = result["title"]
            public_audio_url = result.get("asr_public_url")
        elif task_type in ('xiaoyuzhou', 'bilibili', 'netease', 'ximalaya', 'applepodcasts'):
            # 下载在线音频
            result = route_and_download(source, TEMP_DIR)
            if not result["success"]:
                return False, None, f"下载失败: {result.get('error', '未知错误')}"
            audio_file_path = result["file_path"]
            title = result["title"]
            public_audio_url = result.get("asr_public_url")
        else:
            return False, None, f"不支持的任务类型: {task_type}"

        _raise_if_task_cancelled(task_id)

        # 更新任务名称（从下载结果获取真实标题）
        task_queue.update_task_name(task_id, title)
        task_queue.update_progress_status(task_id, "音频获取成功")

        # 步骤 2: 转录（使用 DashScope 云端 ASR）
        print(f"[Worker] 转录中: {title}")
        task_queue.update_progress_status(task_id, "正在调用 DashScope ASR 转录...")

        asr_metrics = {}
        podcast_text, transcript_segments = transcribe_with_dashscope_and_segments(
            audio_file_path,
            api_key,
            public_audio_url=public_audio_url,
            metrics=asr_metrics,
            stage_callback=lambda status: (
                _raise_if_task_cancelled(task_id),
                task_queue.update_progress_status(task_id, status),
            )[-1],
        )
        _raise_if_task_cancelled(task_id)
        if asr_metrics:
            timing_text = ", ".join(
                f"{name}={seconds:.1f}{'MB' if name.endswith('_mb') else 's'}" for name, seconds in asr_metrics.items()
                if isinstance(seconds, (int, float))
            )
            print(f"[Worker] ASR 阶段耗时: {timing_text}")

        task_queue.update_progress_status(task_id, "DashScope ASR 转录完成")

        # 步骤 3: 预建归档目录并保存音频副本（在清理音频文件之前）
        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        safe_title = re.sub(r'[\\/*?:"<>|]', "", title).strip()[:50]
        archive_name = f"{safe_title}_{date_str}"
        final_archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        suffix = 2
        while os.path.exists(final_archive_path):
            final_archive_path = os.path.join(ARCHIVE_DIR, f"{archive_name}_{suffix}")
            suffix += 1
        archive_name = os.path.basename(final_archive_path)
        archive_path = os.path.join(TEMP_DIR, "incomplete_archives", task_id)
        if os.path.isdir(archive_path):
            shutil.rmtree(archive_path, ignore_errors=True)
        os.makedirs(archive_path, exist_ok=True)

        # 保存音频副本（保留原始扩展名）
        audio_filename = None
        audio_saved = False
        if os.path.exists(audio_file_path):
            _, ext = os.path.splitext(audio_file_path)
            audio_filename = f"source{ext}"
            audio_dest = os.path.join(archive_path, audio_filename)
            shutil.copy2(audio_file_path, audio_dest)
            audio_saved = True
            print(f"[Worker] 音频已保存到归档: {audio_dest}")

        # 封面抓取（不阻塞主流程）。内容获取任务优先使用目录已经提供的封面，
        # 其他任务继续从原始页面发现封面。
        cover_saved = False
        cover_filename = None
        cover_source_url = None
        cover_type = None
        if source_type != "local_file" and source.startswith("http"):
            try:
                cover_url = (task.get("cover_url") or "").strip()
                source_page_url = (task.get("source_page_url") or "").strip()
                if cover_url:
                    cover_type = "episode"
                else:
                    cover_url, cover_type = fetch_cover(source_page_url or source, source_type)
                if cover_url:
                    cover_base = os.path.join(archive_path, "cover")
                    if download_cover_image(cover_url, cover_base, referer=source_page_url):
                        cover_files = [
                            filename for filename in os.listdir(archive_path)
                            if filename.startswith("cover.") and filename != "cover.tmp"
                        ]
                        cover_filename = cover_files[0] if cover_files else None
                        if not cover_filename:
                            raise RuntimeError("封面下载成功但未找到输出文件")
                        cover_saved = True
                        cover_source_url = cover_url
                        print(f"[Worker] 封面已保存: {cover_filename}")
            except Exception as e:
                print(f"[Worker] 封面抓取失败（不阻塞）: {e}")

        # 保存 metadata.json
        import json
        from datetime import datetime as dt
        metadata = {
            "id": archive_name,
            "title": safe_title,
            "mode": mode,
            "source_type": source_type,
            "source_url": task.get("source_page_url") or source,
            "audio_source_url": source,
            "feed_url": task.get("feed_url") or None,
            "show_title": task.get("show_title") or None,
            "discovery_provider": task.get("discovery_provider") or None,
            "description": task.get("description") or "",
            "published_at": task.get("published_at") or None,
            "duration_seconds": task.get("duration_seconds") or None,
            "audio_saved": audio_saved,
            "audio_filename": audio_filename,
            "can_redownload": source.startswith("http") or source.startswith("www"),
            "created_at": dt.now().isoformat(),
            "cover_saved": cover_saved,
            "cover_filename": cover_filename,
            "cover_source_url": cover_source_url,
            "cover_type": cover_type,
        }
        with open(os.path.join(archive_path, "metadata.json"), "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        _raise_if_task_cancelled(task_id)

        # 步骤 4: 清理音频文件（下载的临时文件此时被删除，归档已有副本）
        if os.path.exists(audio_file_path) and task_type != "local":
            try:
                os.remove(audio_file_path)
            except:
                pass

        # 步骤 5: 根据 mode 调用大模型
        print(f"[Worker] 生成内容中 (mode={mode}): {title}")
        if mode == "timeline":
            task_queue.update_progress_status(task_id, "正在生成时间轴节点...")
            timeline_data = generate_timeline_json(
                api_key,
                podcast_text,
                transcript_segments,
                title=safe_title,
                source_description=task.get("description") or "",
                cancellation_callback=lambda: _raise_if_task_cancelled(task_id),
                progress_callback=lambda done, total: task_queue.update_progress_status(
                    task_id, f"正在生成时间轴节点（{done}/{total}）..."
                ),
            )
            ai_title = timeline_data.get("title", safe_title)
        else:
            task_queue.update_progress_status(task_id, "正在调用通义千问提炼高光...")
            raw_summary = get_podcast_summary_robust(api_key, podcast_text)
            lines = raw_summary.strip().split('\n')
            ai_title = lines[0] if lines else title

        _raise_if_task_cancelled(task_id)

        task_queue.update_progress_status(task_id, "内容生成完成")

        # 步骤 6: 保存归档文件
        print(f"[Worker] 保存归档文件中: {title}")
        task_queue.update_progress_status(task_id, "正在保存归档...")

        # 保存 raw.txt
        raw_path = os.path.join(archive_path, "raw.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(podcast_text)

        # 保存 segments.json（转录分段）
        import json as _json
        segments_path = os.path.join(archive_path, "segments.json")
        with open(segments_path, "w", encoding="utf-8") as f:
            _json.dump(transcript_segments, f, ensure_ascii=False, indent=2)

        if mode == "timeline":
            # 保存 timeline.json
            timeline_path = os.path.join(archive_path, "timeline.json")
            with open(timeline_path, "w", encoding="utf-8") as f:
                _json.dump(timeline_data, f, ensure_ascii=False, indent=2)
            # 同时生成轻量 summary.md（供列表页展示标题用）
            summary_path = os.path.join(archive_path, "summary.md")
            node_count = len(timeline_data.get("nodes", []))
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(f"# {ai_title}\n\n[时间轴模式] 共 {node_count} 个节点\n")
            _raise_if_task_cancelled(task_id)
            os.replace(archive_path, final_archive_path)
            archive_path = final_archive_path
            archive_published = True
            # 首屏最多为两张远程图片等待十秒；其余资料由独立、可恢复的后台任务补齐。
            node_ids = [node.get("id", "") for node in timeline_data.get("nodes", []) if node.get("id")]
            warmed_node_ids = []
            try:
                warmed_node_ids = warmup_timeline_nodes(
                    archive_name,
                    archive_path,
                    node_ids[:2],
                    cache_entity_images=_should_cache_entity_images(),
                )
            except Exception as exc:
                # 首屏资料失败不能拖累时间轴主任务；节点任务会在后台继续重试。
                print(f"[Enrichment] 首屏保障跳过 ({archive_name}): {exc}")
            task_queue.create_node_enrichment_jobs(archive_name, node_ids)
            for node_id in warmed_node_ids:
                task_queue.complete_node_enrichment_job(archive_name, node_id)
        else:
            # 保存 summary.md
            summary_path = os.path.join(archive_path, "summary.md")
            with open(summary_path, "w", encoding="utf-8") as f:
                f.write(raw_summary)
            _raise_if_task_cancelled(task_id)
            os.replace(archive_path, final_archive_path)
            archive_path = final_archive_path
            archive_published = True

        _raise_if_task_cancelled(task_id)
        task_queue.update_progress_status(task_id, "归档完成")

        print(f"[Worker] 任务完成: {title}")

        # 清理临时音频文件
        cleanup_temp_audio_file(audio_file_path)

        return True, archive_path, None

    except TaskCancelled:
        print(f"[Worker] 任务已取消，开始清理: {task_id}")
        cleanup_temp_audio_file(audio_file_path)
        _remove_task_partial_files(task_id, archive_path if not archive_published else None)
        if archive_published and final_archive_path:
            resolved_final = os.path.abspath(final_archive_path)
            resolved_root = os.path.abspath(ARCHIVE_DIR)
            if os.path.commonpath([resolved_final, resolved_root]) == resolved_root and os.path.isdir(resolved_final):
                shutil.rmtree(resolved_final, ignore_errors=True)
            task_queue.delete_enrichment_jobs(os.path.basename(resolved_final))
        return False, None, "[已取消]"

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"[Worker] 任务失败: {error_msg}")

        # 如果是 LLM 失败且已有转录文本，保存到恢复文件
        if 'podcast_text' in dir() and podcast_text:
            import json
            recovery_path = os.path.join(TEMP_DIR, f".llm_recovery_{task_id}.txt")
            segments_rec_path = os.path.join(TEMP_DIR, f".llm_recovery_{task_id}_segments.json")
            try:
                with open(recovery_path, "w", encoding="utf-8") as f:
                    f.write(podcast_text)
                with open(segments_rec_path, "w", encoding="utf-8") as f:
                    json.dump(transcript_segments, f, ensure_ascii=False, indent=2)
                print(f"[Worker] 已保存转录文本到恢复文件: {recovery_path}")
                # 更新任务 error_msg 标记有恢复文件
                error_msg = f"[可重试] {error_msg}\n恢复文件: {recovery_path}"
            except Exception as save_err:
                print(f"[Worker] 保存恢复文件失败: {save_err}")

        # 清理临时音频文件（即使失败也清理）
        cleanup_temp_audio_file(audio_file_path)
        if archive_path and not archive_published:
            _remove_task_partial_files(task_id, archive_path)

        return False, None, error_msg


def should_stop():
    """
    检查是否应该停止批处理。

    返回:
        bool: 是否应该停止
    """
    global _worker_stop_flag
    if _worker_stop_flag:
        return True
    stop_file = os.path.join(TEMP_DIR, ".worker_stop_flag")
    return os.path.exists(stop_file)


def worker_loop():
    """
    Worker 主循环。
    """
    api_key = get_api_key()
    if not api_key:
        print("[Worker] 错误: 未找到 API Key")
        return

    # 检查停止标志文件是否存在，如果存在则删除（之前的停止请求）
    stop_file = os.path.join(TEMP_DIR, ".worker_stop_flag")
    if os.path.exists(stop_file):
        os.remove(stop_file)

    # 已持久化的取消请求不能在进程重启后被恢复成待处理任务。
    for cancelled_task in task_queue.get_cancellation_requested_tasks():
        cancelled_id = cancelled_task["id"]
        _remove_task_partial_files(cancelled_id)
        task_queue.delete_task(cancelled_id)

    # 恢复之前卡在 PROCESSING 状态的任务到 PENDING
    reset_count = task_queue.reset_processing_to_pending()
    if reset_count > 0:
        print(f"[Worker] 已恢复 {reset_count} 个任务到等待状态")

    print("[Worker] 启动成功，开始监听任务队列...")

    while True:
        try:
            # 检查是否需要停止
            if should_stop():
                print("[Worker] 收到停止信号，退出")
                # 清理停止标志
                if os.path.exists(stop_file):
                    os.remove(stop_file)
                break

            # 检查是否暂停
            if is_paused():
                print("[Worker] 已暂停，等待恢复...")
                time.sleep(2)
                continue

            # 检查是否有正在处理的任务
            processing_task = task_queue.get_processing_task()
            if processing_task:
                # 有任务正在处理，等待
                time.sleep(2)
                continue

            # 获取下一个等待中的任务
            pending_tasks = task_queue.get_pending_tasks()
            if not pending_tasks:
                # 没有任务，休眠后检查是否需要停止或暂停
                time.sleep(5)
                if should_stop() or is_paused():
                    continue
                    break
                continue

            # 取第一个任务
            task = pending_tasks[0]
            task_id = task["id"]

            # 消除“Worker 刚取出任务、用户同时点击取消”的竞态窗口。
            if _is_task_cancelled(task_id):
                _remove_task_partial_files(task_id)
                task_queue.delete_task(task_id)
                _clear_task_cancel_event(task_id)
                continue

            # 清理 temp_audio 中的旧临时文件（只清理音频文件，不清理标志文件）
            try:
                for f in os.listdir(TEMP_DIR):
                    filepath = os.path.join(TEMP_DIR, f)
                    # 只清理音频文件和临时文件，保留标志文件
                    if os.path.isfile(filepath) and not f.startswith('.'):
                        ext = os.path.splitext(f)[1].lower()
                        if ext in ['.mp3', '.m4a', '.wav', '.flac', '.aac', '.webm', '.txt', '.json']:
                            os.remove(filepath)
                            print(f"[Worker] 清理旧临时文件: {f}")
            except Exception as e:
                print(f"[Worker] 清理临时文件失败: {e}")

            # 标记为处理中
            task_queue.mark_processing(task_id)
            print(f"[Worker] 开始处理任务 {task_id[:8]}...")

            # 处理任务；只有清理结束后，取消中的任务才从队列消失。
            try:
                success, result_path, error_msg = process_single_task(task, api_key)
                if error_msg == "[已取消]" or _is_task_cancelled(task_id):
                    _remove_task_partial_files(task_id, result_path if success else None)
                    if result_path:
                        task_queue.delete_enrichment_jobs(os.path.basename(result_path))
                    task_queue.delete_task(task_id)
                    print(f"[Worker] 任务 {task_id[:8]} 已取消并清理")
                elif success:
                    task_queue.mark_completed(task_id, result_path)
                    print(f"[Worker] 任务 {task_id[:8]} 完成")
                else:
                    task_queue.mark_failed(task_id, error_msg)
                    print(f"[Worker] 任务 {task_id[:8]} 失败: {error_msg[:100]}")
            finally:
                _clear_task_cancel_event(task_id)

            # 显存清理（DashScope 模式无需 GPU 显存管理）
            gc.collect()

        except KeyboardInterrupt:
            print("[Worker] 收到中断信号，退出")
            break
        except Exception as e:
            print(f"[Worker] 循环异常: {e}")
            time.sleep(5)


def retry_failed_tasks(api_key):
    """
    重试所有失败的任务。

    参数:
        api_key (str): API Key

    返回:
        int: 重试成功的数量
    """
    failed_tasks = task_queue.get_failed_tasks()
    success_count = 0

    for task in failed_tasks:
        task_id = task["id"]
        # 重置为 PENDING
        task_queue.update_task_status(task_id, "PENDING")

        # 标记为处理中
        task_queue.mark_processing(task_id)

        # 处理
        success, result_path, error_msg = process_single_task(task, api_key)

        # 更新状态
        if success:
            task_queue.mark_completed(task_id, result_path)
            success_count += 1
        else:
            task_queue.mark_failed(task_id, error_msg)

        # 清理显存
        gc.collect()

    return success_count


def _should_cache_entity_images():
    """读取当前设置；默认仅保存远程图片链接，不写入归档媒体目录。"""
    config_path = os.path.join(_USER_DATA_DIR or current_dir, "config.json")
    try:
        import json
        with open(config_path, "r", encoding="utf-8") as f:
            return bool(json.load(f).get("cache_entity_images", False))
    except (OSError, ValueError, TypeError):
        return False


def enrichment_worker_loop():
    """低优先级、持久化的时间轴资料富化循环。"""
    reset_count = task_queue.reset_processing_enrichment_jobs()
    reset_count += task_queue.reset_processing_node_enrichment_jobs()
    if reset_count:
        print(f"[Enrichment] 已恢复 {reset_count} 个未完成富化任务")

    while not should_stop():
        if is_paused():
            time.sleep(2)
            continue

        node_job = task_queue.claim_next_node_enrichment_job()
        if node_job:
            archive_id = node_job["archive_id"]
            node_id = node_job["node_id"]
            archive_path = os.path.join(ARCHIVE_DIR, archive_id)
            if not os.path.abspath(archive_path).startswith(os.path.abspath(ARCHIVE_DIR)):
                task_queue.fail_node_enrichment_job(archive_id, node_id, "无效归档路径")
                continue
            try:
                print(f"[Enrichment] 开始节点富化: {archive_id}/{node_id}")
                enrich_timeline_node(
                    archive_id,
                    archive_path,
                    node_id,
                    cache_entity_images=_should_cache_entity_images(),
                )
                task_queue.complete_node_enrichment_job(archive_id, node_id)
            except Exception as exc:
                task_queue.fail_node_enrichment_job(archive_id, node_id, str(exc))
                print(f"[Enrichment] 节点失败 ({archive_id}/{node_id}): {exc}")
            continue

        # 兼容已在新版发布前创建的整期富化任务。
        job = task_queue.claim_next_enrichment_job()
        if not job:
            time.sleep(3)
            continue

        archive_id = job["archive_id"]
        archive_path = os.path.join(ARCHIVE_DIR, archive_id)
        if not os.path.abspath(archive_path).startswith(os.path.abspath(ARCHIVE_DIR)):
            task_queue.fail_enrichment_job(archive_id, "无效归档路径")
            continue

        try:
            print(f"[Enrichment] 开始补充归档资料: {archive_id}")
            enrich_timeline_archive(
                archive_id,
                archive_path,
                cache_entity_images=_should_cache_entity_images(),
            )
            task_queue.complete_enrichment_job(archive_id)
            print(f"[Enrichment] 完成: {archive_id}")
        except Exception as exc:
            task_queue.fail_enrichment_job(archive_id, str(exc))
            print(f"[Enrichment] 失败 ({archive_id}): {exc}")


def start_enrichment_worker():
    """启动独立富化线程，不与主转录/时间轴队列竞争。"""
    if is_enrichment_worker_running():
        return False
    thread = threading.Thread(
        target=enrichment_worker_loop,
        name=ENRICHMENT_WORKER_THREAD_NAME,
        daemon=True,
    )
    thread.start()
    print(f"[Enrichment] 已启动线程: {ENRICHMENT_WORKER_THREAD_NAME}")
    return True


def start_worker(force_restart=False):
    """
    启动 Worker 线程（如果尚未运行）。

    参数:
        force_restart (bool): 是否强制重启
    """
    global _worker_stop_flag

    # 检查是否已在运行
    if is_worker_running():
        if not force_restart:
            print("[Worker] 线程已在运行中")
            return False
        # 强制停止旧线程
        print("[Worker] 强制停止旧线程...")
        _worker_stop_flag = True
        import time
        time.sleep(0.5)  # 等待线程结束

    # 重置停止标志
    _worker_stop_flag = False

    # 清理内存
    gc.collect()

    # 启动线程
    worker_thread = threading.Thread(
        target=worker_loop,
        name=WORKER_THREAD_NAME,
        daemon=True
    )
    worker_thread.start()

    print(f"[Worker] 已启动新线程: {WORKER_THREAD_NAME}")
    return True
