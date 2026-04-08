"""
语音转录模块 - 使用 DashScope 远程 ASR API

本版本移除了所有本地模型（Whisper / SenseVoice / PyTorch），
改用 DashScope 云端 ASR API（qwen3-asr-flash + paraformer）进行语音识别。

两个 API 入口：
- qwen3-asr-flash 系列 → dashscope.audio.qwen_asr.QwenTranscription（function="transcription"）
- paraformer 系列 → dashscope.Transcription（function="conversation"）
"""

import os
import re
import time
import requests
from typing import Optional

# DashScope ASR API 配置
# qwen3-asr-flash-2026-02-10 需要使用 QwenTranscription API（function="transcription"）
# paraformer 系列需要使用 Transcription API（function="conversation"）
DASHSCOPE_ASR_MODEL = "qwen3-asr-flash-2026-02-10"
PARAFORMER_ASR_MODEL = "paraformer-v1"


def get_dashscope_api_key() -> str:
    """从环境变量或 .env 文件获取 DashScope API Key"""
    # 优先从环境变量读取（Electron 打包时由 backendStarter 注入）
    # 注意：即使是空字符串也要继续尝试 .env 文件
    env_api_key = os.environ.get('DASHSCOPE_API_KEY', None)
    if env_api_key:
        return env_api_key

    # 回退到 .env 文件（Electron 打包环境）
    data_dir = os.environ.get('PODGIST_DATA_DIR')
    if data_dir:
        env_path = os.path.join(data_dir, '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('DASHSCOPE_API_KEY='):
                        return line.split('=', 1)[1].strip().strip('"\'')

    # 最后回退到项目根目录（开发环境）
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('DASHSCOPE_API_KEY='):
                    return line.split('=', 1)[1].strip().strip('"\'')

    return ""


def clean_asr_text(text: str) -> str:
    """清洗 ASR 输出，移除特殊标记"""
    text = re.sub(r'<\|[^|]*\|>', '', text)
    text = re.sub(r'\{[^}]+\}', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _upload_to_dashscope(audio_file_path: str, api_key: str) -> Optional[str]:
    """
    将本地音频文件上传到 DashScope，返回可访问的 URL。
    """
    from dashscope import Files

    try:
        upload_response = Files.upload(
            file_path=audio_file_path,
            purpose='audio',
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

        return file_info.output['url']

    except Exception as e:
        print(f"[DashScope ASR] Upload error: {e}")
        return None


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

        # 解析 transcripts 结构
        transcripts = data.get("transcripts", [])
        if not transcripts:
            return {"text": "", "sentences": []}

        transcript = transcripts[0]  # 取第一个 channel
        full_text = transcript.get("text", "")

        # 提取句子级别时间戳（如果有的话）
        sentences_data = transcript.get("sentences", [])
        sentences = []

        if sentences_data:
            # sentences 格式: [{"begin_time": ..., "end_time": ..., "text": "..."}]
            for sent in sentences_data:
                sentences.append({
                    "begin_time": sent.get("begin_time", 0),
                    "end_time": sent.get("end_time", 0),
                    "text": sent.get("text", "")
                })
        else:
            # 没有句子级别时间戳，按固定间隔分段
            # 尝试从 text 和 duration 估算
            duration_ms = data.get("properties", {}).get("original_duration_in_milliseconds", 0)
            if full_text and duration_ms > 0:
                # 粗略分段：每 30 秒一个时间戳
                chunk_duration = 30000
                current_pos = 0
                text_len = len(full_text)
                chunk_size = text_len // (duration_ms // chunk_duration + 1)

                while current_pos < text_len:
                    end_pos = min(current_pos + chunk_size, text_len)
                    # 找最后一个句号或逗号切分
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


def _call_qwen_transcription(audio_url: str, api_key: str, model: str) -> dict:
    """
    使用 QwenTranscription API（function="transcription"）进行语音识别。
    qwen3-asr-flash 系列必须使用此 API。
    """
    from dashscope.audio.qwen_asr import QwenTranscription

    task = QwenTranscription.async_call(
        model=model,
        file_url=audio_url,
        api_key=api_key
    )

    if task.status_code != 200:
        # 打印详细信息帮助诊断
        print(f"[DashScope ASR] QwenTranscription async_call failed: status={task.status_code} code={getattr(task, 'code', None)} message={getattr(task, 'message', None)} output={getattr(task, 'output', None)}")
        return {"error": f"status={task.status_code} code={getattr(task, 'code', None)} message={getattr(task, 'message', None)}"}

    task_id = task.output.get('task_id') or task.output.task_id

    for _ in range(60):
        result = QwenTranscription.wait(task_id, api_key=api_key)
        status = result.output.get('task_status') or result.output.task_status

        if status == 'SUCCEEDED':
            # QwenTranscription 返回的 output 中，transcription_url 在 kwargs 里
            transcription_url = result.output.get('transcription_url')
            if transcription_url:
                return _fetch_transcription_from_url(transcription_url)
            # 也可能直接返回 text（某些模型）
            text = result.output.get('text')
            if text:
                return {"text": text, "sentences": []}
            return {"text": "", "sentences": []}

        elif status == 'FAILED':
            error_msg = result.output.get('message') or str(result.output)
            return {"error": error_msg}

        time.sleep(2)

    return {"error": "Timeout waiting for transcription"}


def _call_paraformer_transcription(audio_url: str, api_key: str, model: str = PARAFORMER_ASR_MODEL) -> dict:
    """
    使用 Transcription API（function="conversation"）进行语音识别。
    paraformer 系列使用此 API。
    """
    from dashscope import Transcription

    task = Transcription.async_call(
        model=model,
        file_urls=[audio_url],
        timestamp_alignment_enabled=True,
        api_key=api_key
    )

    if task.status_code != 200:
        print(f"[DashScope ASR] Transcription async_call failed: status={task.status_code} code={getattr(task, 'code', None)} message={getattr(task, 'message', None)}")
        if model == PARAFORMER_ASR_MODEL:
            print(f"[DashScope ASR] {model} failed, trying paraformer-8k-v1...")
            return _call_paraformer_transcription(audio_url, api_key, model="paraformer-8k-v1")
        return {"error": f"status={task.status_code} code={getattr(task, 'code', None)} message={getattr(task, 'message', None)}"}

    task_id = task.output.get('task_id') or task.output.task_id

    for _ in range(60):
        result = Transcription.wait(task_id, api_key=api_key)
        status = result.output.get('task_status') or result.output.task_status

        if status == 'SUCCEEDED':
            # 从 transcription_url 获取实际转录内容
            transcription_url = result.output.get('transcription_url')
            if transcription_url:
                return _fetch_transcription_from_url(transcription_url)
            # 备选：从 results 结构获取
            results = result.output.get('results')
            if results:
                transcription_url = results[0].get('transcription_url') if isinstance(results[0], dict) else getattr(results[0], 'transcription_url', None)
                if transcription_url:
                    return _fetch_transcription_from_url(transcription_url)
            return {"text": "", "sentences": []}

        elif status == 'FAILED':
            error_msg = result.output.get('message') or str(result.output)
            print(f"[DashScope ASR] Paraformer task failed: {error_msg}")
            if model == PARAFORMER_ASR_MODEL:
                print(f"[DashScope ASR] Retrying with paraformer-8k-v1...")
                return _call_paraformer_transcription(audio_url, api_key, model="paraformer-8k-v1")
            elif model == "paraformer-8k-v1":
                print(f"[DashScope ASR] paraformer-8k-v1 also failed, trying paraformer-mtl-v1...")
                return _call_paraformer_transcription(audio_url, api_key, model="paraformer-mtl-v1")
            return {"error": error_msg}

        time.sleep(2)

    return {"error": "Timeout waiting for transcription"}


def _call_dashscope_asr(audio_url: str, api_key: str, model: str = DASHSCOPE_ASR_MODEL) -> dict:
    """
    调用 DashScope ASR API。
    qwen3-asr-flash → QwenTranscription API
    paraformer → Transcription API

    优先使用 qwen3-asr-flash，失败后自动降级到 paraformer。
    """
    # qwen3-asr-flash 必须用 QwenTranscription
    if 'qwen' in model.lower() and 'paraformer' not in model.lower():
        result = _call_qwen_transcription(audio_url, api_key, model)
        if "error" not in result:
            return result
        # qwen3-asr-flash 失败，降级到 paraformer
        print(f"[DashScope ASR] qwen3-asr-flash 失败，降级到 paraformer...")
        return _call_paraformer_transcription(audio_url, api_key, PARAFORMER_ASR_MODEL)
    # paraformer 用 Transcription API
    return _call_paraformer_transcription(audio_url, api_key, model)


def transcribe_with_dashscope(audio_file_path: str, api_key: str) -> str:
    """
    使用 DashScope ASR API 转录音频文件，返回带时间戳的文本。
    """
    if not api_key:
        raise ValueError("未配置 DashScope API Key，请在设置中添加 DASHSCOPE_API_KEY")

    print(f"[DashScope ASR] Uploading {audio_file_path}...")
    audio_url = _upload_to_dashscope(audio_file_path, api_key)
    if not audio_url:
        raise RuntimeError("文件上传失败，无法获取访问 URL")

    print(f"[DashScope ASR] File uploaded, calling ASR...")
    result = _call_dashscope_asr(audio_url, api_key)

    if "error" in result:
        raise RuntimeError(f"ASR 转录失败: {result['error']}")

    # 生成带时间戳的文本
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


# ================= 兼容层（供 api.py 统一调用）=================

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
