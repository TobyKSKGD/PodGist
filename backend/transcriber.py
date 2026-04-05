"""
语音转录模块 - 使用 DashScope 远程 ASR API

本版本移除了所有本地模型（Whisper / SenseVoice / PyTorch），
改用 DashScope Qwen3-ASR-Flash 云端 API 进行语音识别。
"""

import os
import re
import time
import requests
from typing import Optional

# DashScope ASR API 配置
DASHSCOPE_ASR_MODEL = "qwen3-asr-flash-2026-02-10"
FALLBACK_ASR_MODEL = "paraformer-v1"


def get_dashscope_api_key() -> str:
    """从环境变量或 .env 文件获取 DashScope API Key"""
    api_key = os.environ.get('DASHSCOPE_API_KEY', '')
    if not api_key:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('DASHSCOPE_API_KEY='):
                        api_key = line.split('=', 1)[1].strip().strip('"\'')
                        break
    return api_key


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

    os.environ['DASHSCOPE_API_KEY'] = api_key

    try:
        upload_response = Files.upload(
            file_path=audio_file_path,
            purpose='audio'
        )

        if upload_response.status_code != 200:
            print(f"[DashScope ASR] Upload failed: {upload_response.output}")
            return None

        file_id = upload_response.output['uploaded_files'][0]['file_id']
        file_info = Files.get(file_id)
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


def _call_dashscope_asr(audio_url: str, api_key: str, model: str = DASHSCOPE_ASR_MODEL) -> dict:
    """
    调用 DashScope ASR API 进行语音识别。
    """
    from dashscope import Transcription

    os.environ['DASHSCOPE_API_KEY'] = api_key

    task = Transcription.async_call(
        model=model,
        file_urls=[audio_url],
        timestamp_alignment_enabled=True
    )

    if task.status_code != 200:
        if model == DASHSCOPE_ASR_MODEL:
            print(f"[DashScope ASR] {model} failed, trying {FALLBACK_ASR_MODEL}...")
            return _call_dashscope_asr(audio_url, api_key, model=FALLBACK_ASR_MODEL)
        return {"error": f"Task creation failed: {task.output}"}

    task_id = task.output['task_id']

    for _ in range(60):
        result = Transcription.wait(task_id)
        status = result.output.task_status

        if status == 'SUCCEEDED':
            # 从 transcription_url 获取实际转录内容
            transcription_url = result.output.results[0].get('transcription_url')
            if transcription_url:
                return _fetch_transcription_from_url(transcription_url)
            return {"text": "", "sentences": []}

        elif status == 'FAILED':
            error_msg = result.output.message
            print(f"[DashScope ASR] Task failed: {error_msg}")
            if model == DASHSCOPE_ASR_MODEL:
                print(f"[DashScope ASR] Retrying with {FALLBACK_ASR_MODEL}...")
                return _call_dashscope_asr(audio_url, api_key, model=FALLBACK_ASR_MODEL)
            return {"error": error_msg}

        time.sleep(2)

    return {"error": "Timeout waiting for transcription"}


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
