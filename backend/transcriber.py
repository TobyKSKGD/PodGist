"""
语音转录模块 - 使用 DashScope 远程 ASR API

本版本移除了所有本地模型（Whisper / SenseVoice / PyTorch），
改用 DashScope 云端 ASR API 进行语音识别。

ASR 决策逻辑：
- 短音频（≤30分钟 且 文件≤60MB）：qwen3-asr-flash → MultiModalConversation.call
- 长音频（>30分钟 或 文件>60MB）：paraformer-v1 → Transcription.async_call
- qwen3-asr-flash-filetrans：仅当外部传入公网 URL 时启用（非默认）

模型命名：
- qwen3-asr-flash：短音频同步模型（MultiModalConversation.call）
- qwen3-asr-flash-filetrans：长音频异步模型（QwenTranscription.async_call，需公网 URL）
- paraformer-v1：长音频异步模型（Transcription.async_call）
"""

import os
import re
import time
import requests
from typing import Optional

# DashScope ASR 模型
# qwen3-asr-flash：短音频同步模型（MultiModalConversation.call）
# qwen3-asr-flash-filetrans：长音频异步模型（QwenTranscription.async_call，仅公网 URL）
# paraformer-v1：长音频异步模型（Transcription.async_call）
QwenFlashShortModel = "qwen3-asr-flash"          # 稳定名，用于 MultiModalConversation
QwenFlashFiletransModel = "qwen3-asr-flash-filetrans"  # 长音频，需公网 URL
ParaformerModel = "paraformer-v1"

# 短音频判定阈值
MAX_DURATION_SECONDS = 30 * 60   # 30 分钟
MAX_FILE_SIZE_BYTES = 60 * 1024 * 1024  # 60 MB（30分钟音频约 30MB）


def get_dashscope_api_key() -> str:
    """从环境变量或 .env 文件获取 DashScope API Key"""
    env_api_key = os.environ.get('DASHSCOPE_API_KEY', None)
    if env_api_key:
        return env_api_key

    data_dir = os.environ.get('PODGIST_DATA_DIR')
    if data_dir:
        env_path = os.path.join(data_dir, '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('DASHSCOPE_API_KEY='):
                        return line.split('=', 1)[1].strip().strip('"\'')

    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('DASHSCOPE_API_KEY='):
                    return line.split('=', 1)[1].strip().strip('"\'')

    return ""


def get_audio_duration(file_path: str) -> float:
    """
    使用 ffprobe 获取音频时长（秒）。
    ffprobe 比 mutagen 更准确，且项目已有 ffmpeg 依赖。
    失败时返回 0（表示未知时长，走长音频路径）。
    """
    import subprocess
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception as e:
        print(f"[DashScope ASR] ffprobe 获取时长失败: {e}")
    return 0  # 失败时默认返回 0，走长音频路径


def is_short_audio(file_path: str) -> bool:
    """
    判断是否为短音频（≤5分钟 且 ≤10MB）。
    同时满足两个条件才走 qwen3-asr-flash 短音频路径。
    """
    # 检查文件大小
    try:
        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            print(f"[DashScope ASR] 文件大小 {file_size} bytes > {MAX_FILE_SIZE_BYTES}，判定为长音频")
            return False
    except Exception as e:
        print(f"[DashScope ASR] 获取文件大小失败: {e}")

    # 检查时长
    duration = get_audio_duration(file_path)
    if duration <= 0:
        # 无法获取时长，保守起见按长音频处理
        print(f"[DashScope ASR] 无法获取音频时长，判定为长音频")
        return False
    if duration > MAX_DURATION_SECONDS:
        print(f"[DashScope ASR] 音频时长 {duration:.0f}s > {MAX_DURATION_SECONDS}s，判定为长音频")
        return False

    print(f"[DashScope ASR] 音频时长 {duration:.0f}s，文件大小正常，判定为短音频")
    return True


def clean_asr_text(text: str) -> str:
    """清洗 ASR 输出，移除特殊标记"""
    text = re.sub(r'<\|[^|]*\|>', '', text)
    text = re.sub(r'\{[^}]+\}', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ==================== qwen3-asr-flash 短音频（MultiModalConversation）====================

def _call_qwen_flash_short(audio_file_path: str, api_key: str) -> dict:
    """
    使用 qwen3-asr-flash 短音频模型，通过 MultiModalConversation.call 接口。
    适用：≤5分钟 且 ≤10MB 的音频。

    qwen3-asr-flash 是同步调用，不需要轮询，直接返回结果。
    模型名使用稳定名 'qwen3-asr-flash'，而非 snapshot 名。
    """
    from dashscope import MultiModalConversation

    if not os.path.exists(audio_file_path):
        return {"error": f"音频文件不存在: {audio_file_path}"}

    # MultiModalConversation 格式：audio 参数传本地文件路径
    messages = [
        {
            'role': 'user',
            'content': [
                {'audio': audio_file_path},
                {'text': '请转录这段音频的完整内容，逐字输出。'}
            ]
        }
    ]

    print(f"[DashScope ASR] 调用 qwen3-asr-flash (MultiModalConversation)，文件: {audio_file_path}")

    try:
        response = MultiModalConversation.call(
            model=QwenFlashShortModel,
            messages=messages,
            api_key=api_key
        )

        print(f"[DashScope ASR] MultiModalConversation 响应: status_code={response.status_code}")

        if response.status_code != 200:
            err_msg = f"status={response.status_code} code={getattr(response, 'code', None)} message={getattr(response, 'message', None)}"
            print(f"[DashScope ASR] qwen3-asr-flash 调用失败: {err_msg}")
            return {"error": err_msg}

        # 解析输出
        # response.output.choices[0].message.content 是列表，通常为 [{text: "..."}]
        content = response.output.choices[0].message.content
        if isinstance(content, list) and len(content) > 0:
            text = content[0].get('text', '') if isinstance(content[0], dict) else str(content[0])
        elif isinstance(content, str):
            text = content
        else:
            text = ''

        text = clean_asr_text(text)
        print(f"[DashScope ASR] qwen3-asr-flash 转录成功，文本长度: {len(text)}")

        # qwen3-asr-flash 短音频通常无逐句时间戳，返回纯文本
        # 时间戳在后续统一添加 [00:00]
        if text:
            return {"text": text, "sentences": [{"begin_time": 0, "end_time": 0, "text": text}]}
        return {"text": "", "sentences": []}

    except Exception as e:
        print(f"[DashScope ASR] qwen3-asr-flash 异常: {type(e).__name__}: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


# ==================== qwen3-asr-flash-filetrans 长音频（QwenTranscription）====================

def _call_qwen_flash_filetrans(audio_url: str, api_key: str) -> dict:
    """
    使用 qwen3-asr-flash-filetrans 长音频异步模型，通过 QwenTranscription.async_call 接口。
    仅当有公网可访问 URL 时启用。

    qwen3-asr-flash-filetrans 要求音频 URL 必须公网可访问。
    如果没有公网 URL，应跳过此函数直接走 paraformer。
    """
    from dashscope.audio.qwen_asr import QwenTranscription

    print(f"[DashScope ASR] 调用 qwen3-asr-flash-filetrans (QwenTranscription)，URL: {audio_url}")

    try:
        task = QwenTranscription.async_call(
            model=QwenFlashFiletransModel,
            file_url=audio_url,
            api_key=api_key
        )

        if task.status_code != 200:
            err_msg = f"status={task.status_code} code={getattr(task, 'code', None)} message={getattr(task, 'message', None)}"
            print(f"[DashScope ASR] QwenTranscription async_call 失败: {err_msg}")
            return {"error": err_msg}

        task_id = task.output.get('task_id') or task.output.task_id
        print(f"[DashScope ASR] qwen3-asr-flash-filetrans task_id: {task_id}")

        for _ in range(60):
            result = QwenTranscription.wait(task_id, api_key=api_key)
            status = result.output.get('task_status') or result.output.task_status

            if status == 'SUCCEEDED':
                transcription_url = result.output.get('transcription_url')
                if transcription_url:
                    return _fetch_transcription_from_url(transcription_url)
                text = result.output.get('text')
                if text:
                    return {"text": text, "sentences": []}
                return {"text": "", "sentences": []}

            elif status == 'FAILED':
                error_msg = result.output.get('message') or str(result.output)
                print(f"[DashScope ASR] qwen3-asr-flash-filetrans FAILED: {error_msg}")
                return {"error": error_msg}

            time.sleep(2)

        return {"error": "Timeout waiting for qwen3-asr-flash-filetrans"}

    except Exception as e:
        print(f"[DashScope ASR] qwen3-asr-flash-filetrans 异常: {type(e).__name__}: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


# ==================== paraformer 长音频（Transcription.async_call）====================

def _fetch_transcription_from_url(transcription_url: str) -> dict:
    """
    从 transcription_url 获取转录结果。
    返回包含 text 和 sentences 的字典。
    """
    try:
        resp = requests.get(transcription_url, timeout=30)
        if resp.status_code != 200:
            print(f"[DashScope ASR] Failed to fetch transcription: {resp.status_code}")
            return {"text": "", "sentences": []}

        data = resp.json()

        transcripts = data.get("transcripts", [])
        if not transcripts:
            return {"text": "", "sentences": []}

        transcript = transcripts[0]
        full_text = transcript.get("text", "")

        sentences_data = transcript.get("sentences", [])
        sentences = []

        if sentences_data:
            for sent in sentences_data:
                sentences.append({
                    "begin_time": sent.get("begin_time", 0),
                    "end_time": sent.get("end_time", 0),
                    "text": sent.get("text", "")
                })
        else:
            # 没有句子级别时间戳，按固定间隔分段
            duration_ms = data.get("properties", {}).get("original_duration_in_milliseconds", 0)
            if full_text and duration_ms > 0:
                chunk_duration = 30000
                current_pos = 0
                text_len = len(full_text)
                chunk_size = text_len // (duration_ms // chunk_duration + 1)

                while current_pos < text_len:
                    end_pos = min(current_pos + chunk_size, text_len)
                    cut_pos = end_pos
                    for p in range(min(end_pos, text_len - 1), current_pos, -1):
                        if full_text[p] in '。！？，、':
                            cut_pos = p + 1
                            break

                    chunk_text = full_text[current_pos:cut_pos].strip()
                    if chunk_text:
                        sentences.append({
                            "begin_time": (current_pos * duration_ms) // text_len,
                            "end_time": (cut_pos * duration_ms) // text_len,
                            "text": chunk_text
                        })
                    current_pos = cut_pos

        return {"text": full_text, "sentences": sentences}

    except Exception as e:
        print(f"[DashScope ASR] Error fetching transcription: {e}")
        return {"text": "", "sentences": []}


def _call_paraformer_transcription(audio_url: str, api_key: str, model: str = ParaformerModel) -> dict:
    """
    使用 Transcription API（function="conversation"）进行长音频语音识别。
    paraformer 系列使用此 API，无需公网 URL（通过 Files.upload 上传）。
    失败后自动降级：paraformer-v1 → paraformer-8k-v1 → paraformer-mtl-v1
    """
    from dashscope import Transcription

    print(f"[DashScope ASR] 调用 {model} (Transcription.async_call)，URL: {audio_url}")

    try:
        task = Transcription.async_call(
            model=model,
            file_urls=[audio_url],
            timestamp_alignment_enabled=True,
            api_key=api_key
        )

        if task.status_code != 200:
            err_msg = f"status={task.status_code} code={getattr(task, 'code', None)} message={getattr(task, 'message', None)}"
            print(f"[DashScope ASR] Transcription async_call 失败: {err_msg}")
            if model == ParaformerModel:
                print(f"[DashScope ASR] {model} 失败，降级到 paraformer-8k-v1...")
                return _call_paraformer_transcription(audio_url, api_key, model="paraformer-8k-v1")
            elif model == "paraformer-8k-v1":
                print(f"[DashScope ASR] paraformer-8k-v1 失败，降级到 paraformer-mtl-v1...")
                return _call_paraformer_transcription(audio_url, api_key, model="paraformer-mtl-v1")
            return {"error": err_msg}

        task_id = task.output.get('task_id') or task.output.task_id
        print(f"[DashScope ASR] {model} task_id: {task_id}")

        for _ in range(60):
            result = Transcription.wait(task_id, api_key=api_key)
            status = result.output.get('task_status') or result.output.task_status

            if status == 'SUCCEEDED':
                transcription_url = result.output.get('transcription_url')
                if transcription_url:
                    return _fetch_transcription_from_url(transcription_url)
                results = result.output.get('results')
                if results:
                    transcription_url = results[0].get('transcription_url') if isinstance(results[0], dict) else getattr(results[0], 'transcription_url', None)
                    if transcription_url:
                        return _fetch_transcription_from_url(transcription_url)
                return {"text": "", "sentences": []}

            elif status == 'FAILED':
                error_msg = result.output.get('message') or str(result.output)
                print(f"[DashScope ASR] {model} 任务失败: {error_msg}")
                if model == ParaformerModel:
                    print(f"[DashScope ASR] 降级到 paraformer-8k-v1...")
                    return _call_paraformer_transcription(audio_url, api_key, model="paraformer-8k-v1")
                elif model == "paraformer-8k-v1":
                    print(f"[DashScope ASR] 降级到 paraformer-mtl-v1...")
                    return _call_paraformer_transcription(audio_url, api_key, model="paraformer-mtl-v1")
                return {"error": error_msg}

            time.sleep(2)

        return {"error": "Timeout waiting for transcription"}

    except Exception as e:
        print(f"[DashScope ASR] {model} 异常: {type(e).__name__}: {e}")
        return {"error": f"{type(e).__name__}: {e}"}


# ==================== 文件上传（仅 paraformer 需要）====================

def _upload_to_dashscope(audio_file_path: str, api_key: str) -> Optional[str]:
    """
    将本地音频文件上传到 DashScope，返回可访问的 URL（仅供 paraformer 使用）。
    qwen3-asr-flash 短音频不走此函数（直接 MultiModalConversation.call）。
    qwen3-asr-flash-filetrans 需要公网 URL，不走此上传。
    """
    from dashscope import Files

    try:
        upload_response = Files.upload(
            file_path=audio_file_path,
            purpose='inference',
            api_key=api_key
        )

        if upload_response.status_code != 200:
            print(f"[DashScope ASR] Upload failed: {upload_response.output}")
            return None

        file_id = upload_response.output['uploaded_files'][0]['file_id']
        file_info = Files.get(file_id, api_key=api_key)
        if file_info.status_code != 200:
            print(f"[DashScope ASR] Get file info failed: {file_info.output}")
            return None

        url = file_info.output['url']
        print(f"[DashScope ASR] 文件上传成功，URL: {url}")
        return url

    except Exception as e:
        print(f"[DashScope ASR] Upload error: {e}")
        return None


# ==================== 主入口：智能路由 ========================

def transcribe_with_dashscope(audio_file_path: str, api_key: str) -> str:
    """
    使用 DashScope ASR API 转录音频文件，返回带时间戳的文本。

    决策逻辑：
    1. 短音频（≤30分钟 且 ≤60MB）→ qwen3-asr-flash（MultiModalConversation.call）
    2. 长音频 → paraformer（Transcription.async_call）
       - 先上传文件到 DashScope 获取 URL
       - paraformer 失败后降级到 paraformer-8k-v1 → paraformer-mtl-v1
    3. qwen3-asr-flash-filetrans：仅当 external_public_url 参数传入公网 URL 时启用
    """
    text, _ = transcribe_with_dashscope_and_segments(audio_file_path, api_key)
    return text


def transcribe_with_dashscope_and_segments(audio_file_path: str, api_key: str) -> tuple[str, list]:
    """
    使用 DashScope ASR API 转录音频文件，返回 (带时间戳文本, 分段列表)。

    返回值：
    - text: 带时间戳的文本字符串
    - segments: 分段列表，每项包含 id, time, seconds, text

    决策逻辑同上。
    """
    if not api_key:
        raise ValueError("未配置 DashScope API Key，请在设置中添加 DASHSCOPE_API_KEY")

    # 步骤 1：判定音频类型
    if is_short_audio(audio_file_path):
        # ===== 短音频：qwen3-asr-flash =====
        print(f"[DashScope ASR] 短音频路径: qwen3-asr-flash (MultiModalConversation)")
        result = _call_qwen_flash_short(audio_file_path, api_key)

        if "error" not in result:
            return _build_timestamped_text(result), _build_segments_from_sentences(result.get("sentences", []))

        # qwen3-asr-flash 失败，尝试长音频路径（升级为 paraformer）
        print(f"[DashScope ASR] qwen3-asr-flash 失败，降级到 paraformer 长音频路径: {result.get('error')}")

    # ===== 长音频：paraformer =====
    print(f"[DashScope ASR] 长音频路径: paraformer (Transcription.async_call)")

    print(f"[DashScope ASR] 上传音频文件...")
    audio_url = _upload_to_dashscope(audio_file_path, api_key)
    if not audio_url:
        raise RuntimeError("文件上传失败，无法获取访问 URL")

    result = _call_paraformer_transcription(audio_url, api_key)

    if "error" in result:
        raise RuntimeError(f"ASR 转录失败: {result['error']}")

    return _build_timestamped_text(result), _build_segments_from_sentences(result.get("sentences", []))


def _build_timestamped_text(result: dict) -> str:
    """将转录结果转换为带时间戳的文本"""
    lines = []
    for sent in result.get("sentences", []):
        begin_time = int(sent.get('begin_time', 0))
        text = clean_asr_text(sent.get('text', ''))

        if text:
            minutes = begin_time // 1000 // 60
            seconds = (begin_time // 1000) % 60
            lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")

    if not lines:
        text = clean_asr_text(result.get('text', ''))
        if text:
            lines.append(f"[00:00] {text}")
        else:
            return ""

    return '\n'.join(lines)


def _build_segments_from_sentences(sentences: list) -> list:
    """
    将 sentences 数组转换为前端 TimelineItem 格式的分段列表。

    参数:
        sentences: ASR 返回的 sentences 数组，每项含 begin_time(ms), end_time(ms), text

    返回:
        分段列表，每项格式：{id, time, seconds, text}
    """
    segments = []
    for i, sent in enumerate(sentences):
        begin_time = int(sent.get('begin_time', 0))
        text = clean_asr_text(sent.get('text', ''))
        if not text:
            continue
        total_seconds = begin_time // 1000
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        segments.append({
            "id": f"seg_{i}",
            "time": f"{minutes:02d}:{seconds:02d}",
            "seconds": total_seconds,
            "text": text
        })
    return segments


# ==================== 兼容层（供 api.py / worker.py 统一调用）====================

def get_available_devices():
    """返回可用设备（远程 API 模式下始终返回云端）"""
    return {"cloud": "云端 ASR (DashScope)"}


def transcribe_with_sensevoice(audio_file_path: str, device_key: str = "cpu") -> str:
    """
    兼容层：将 SenseVoice 接口重定向到 DashScope ASR。
    """
    api_key = get_dashscope_api_key()
    return transcribe_with_dashscope(audio_file_path, api_key)


def transcribe_audio_to_timestamped_text(model, audio_file_path: str, device_key: str) -> str:
    """兼容层：Whisper 接口重定向到 DashScope ASR。"""
    api_key = get_dashscope_api_key()
    return transcribe_with_dashscope(audio_file_path, api_key)


def get_whisper_model(model_name: str = "small", device_key: str = "cpu"):
    """兼容层：返回 None，Whisper 模型不再需要。"""
    return None
