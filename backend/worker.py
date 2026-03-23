"""
后台 Worker 线程模块

负责从队列中拉取任务并执行完整的处理管线。
"""

import os
import sys
import time
import gc
import threading
import traceback
from datetime import datetime

# 确保可以导入后端模块
current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, current_dir)

# 导入项目模块
from backend import task_queue
from backend.transcriber import transcribe_with_sensevoice, transcribe_audio_to_timestamped_text, get_whisper_model
from backend.llm_agent import get_podcast_summary_robust
from backend.downloader import route_and_download


# Worker 线程名称
WORKER_THREAD_NAME = "PodGist_Batch_Worker"

# 工作目录
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archives")
TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp_audio")
os.makedirs(ARCHIVE_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)


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

    返回:
        str: API Key
    """
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            return f.read().strip()
    return None


def get_task_type(source):
    """
    根据来源判断任务类型。

    参数:
        source (str): 任务来源

    返回:
        str: 任务类型 (local / bilibili / xiaoyuzhou / netease)
    """
    # 转为小写方便比较
    s = source.lower()

    # 网易云检测 - 必须在其他检测之前
    if "163cn.tv" in s or "music.163.com" in s:
        return "netease"

    # 小宇宙检测
    if "xiaoyuzhoufm.com" in s:
        return "xiaoyuzhou"

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

    print(f"[Worker] 开始处理任务: {source}")

    # 初始化音频文件路径（用于后续清理）
    audio_file_path = None

    try:
        # 步骤 1: 获取音频文件
        task_type = get_task_type(source)
        task_queue.update_progress_status(task_id, "📥 正在获取音频...")

        if task_type == "local":
            # 本地文件
            audio_file_path = source
            title = os.path.splitext(os.path.basename(source))[0]
        elif task_type in ("xiaoyuzhou", "bilibili", "netease"):
            # 下载在线音频
            result = route_and_download(source, TEMP_DIR)
            if not result["success"]:
                return False, None, f"下载失败: {result.get('error', '未知错误')}"
            audio_file_path = result["file_path"]
            title = result["title"]
        else:
            return False, None, f"不支持的任务类型: {task_type}"

        # 更新任务名称（从下载结果获取真实标题）
        task_queue.update_task_name(task_id, title)
        task_queue.update_progress_status(task_id, "✅ 音频获取成功")

        # 步骤 2: 转录
        print(f"[Worker] 转录中: {title}")
        engine_name = "SenseVoice" if engine == "sensevoice" else "Whisper"
        task_queue.update_progress_status(task_id, f"🎙️ 正在调用 {engine_name} 转录...")

        if engine == "sensevoice":
            # 选择设备
            import torch
            if torch.cuda.is_available():
                device_key = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device_key = "mps"
            else:
                device_key = "cpu"

            podcast_text = transcribe_with_sensevoice(audio_file_path, device_key)
        else:
            # Whisper
            import whisper
            import torch
            if torch.cuda.is_available():
                device_key = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device_key = "mps"
            else:
                device_key = "cpu"

            model = get_whisper_model("small", device_key)
            podcast_text = transcribe_audio_to_timestamped_text(model, audio_file_path, device_key)

        task_queue.update_progress_status(task_id, f"✅ {engine_name} 转录完成")

        # 步骤 3: 清理音频文件
        if os.path.exists(audio_file_path) and task_type != "local":
            try:
                os.remove(audio_file_path)
            except:
                pass

        # 步骤 4: 调用大模型生成摘要
        print(f"[Worker] 生成摘要中: {title}")
        task_queue.update_progress_status(task_id, "🧠 正在调用 DeepSeek 提炼高光...")

        raw_summary = get_podcast_summary_robust(api_key, podcast_text, max_timeline_items)

        # 提取第一行作为标题
        lines = raw_summary.strip().split('\n')
        ai_title = lines[0] if lines else title

        task_queue.update_progress_status(task_id, "✅ DeepSeek 提炼完成")

        # 步骤 5: 归档
        print(f"[Worker] 归档中: {title}")
        task_queue.update_progress_status(task_id, "💾 正在归档...")

        date_str = datetime.now().strftime("%Y%m%d_%H%M")
        archive_name = f"{date_str}_{title}"

        # 创建归档目录
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        os.makedirs(archive_path, exist_ok=True)

        # 保存 raw.txt
        raw_path = os.path.join(archive_path, "raw.txt")
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(podcast_text)

        # 保存 summary.md（确保有 H1 标题）
        summary_path = os.path.join(archive_path, "summary.md")

        # 提取标题和内容
        lines = raw_summary.strip().split('\n')
        if lines:
            first_line = lines[0].strip()
            # 如果第一行已经是标题格式，使用它；否则使用 title
            if first_line.startswith('#'):
                ai_title = first_line.lstrip('#').strip()
                clean_summary = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
            else:
                ai_title = first_line if first_line else title
                clean_summary = raw_summary

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"# 🎙️ {ai_title}\n\n{clean_summary}")

        task_queue.update_progress_status(task_id, "✅ 归档完成")

        print(f"[Worker] 任务完成: {title}")

        # 清理临时音频文件
        cleanup_temp_audio_file(audio_file_path)

        return True, archive_path, None

    except Exception as e:
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        print(f"[Worker] 任务失败: {error_msg}")

        # 清理临时音频文件（即使失败也清理）
        cleanup_temp_audio_file(audio_file_path)

        return False, None, error_msg


def should_stop():
    """
    检查是否应该停止批处理。

    返回:
        bool: 是否应该停止
    """
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

            # 处理任务
            success, result_path, error_msg = process_single_task(task, api_key)

            # 更新任务状态
            if success:
                task_queue.mark_completed(task_id, result_path)
                print(f"[Worker] 任务 {task_id[:8]} 完成")
            else:
                task_queue.mark_failed(task_id, error_msg)
                print(f"[Worker] 任务 {task_id[:8]} 失败: {error_msg[:100]}")

            # 显存清理
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except:
                pass

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


def start_worker():
    """
    启动 Worker 线程（如果尚未运行）。
    """
    # 检查是否已在运行
    if is_worker_running():
        print("[Worker] 线程已在运行中")
        return False

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
