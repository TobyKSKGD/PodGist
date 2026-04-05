"""
语音转录模块 - 使用 DashScope 远程 ASR API

本版本移除了所有本地模型（Whisper / SenseVoice / PyTorch），
改用 DashScope Qwen3-ASR-Flash 云端 API 进行语音识别。
"""

import os
import re
import time
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

    参数:
        audio_file_path: 本地音频文件路径
        api_key: DashScope API Key

    返回:
        str: DashScope 上的文件 URL，失败返回 None
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

        # 获取文件的访问 URL
        file_info = Files.get(file_id)
        if file_info.status_code != 200:
            print(f"[DashScope ASR] Get file info failed: {file_info.output}")
            return None

        return file_info.output['url']

    except Exception as e:
        print(f"[DashScope ASR] Upload error: {e}")
        return None


def _call_dashscope_asr(audio_url: str, api_key: str, model: str = DASHSCOPE_ASR_MODEL) -> dict:
    """
    调用 DashScope ASR API 进行语音识别。

    参数:
        audio_url: 音频文件的公开访问 URL
        api_key: DashScope API Key
        model: ASR 模型名称

    返回:
        dict: 包含 'text'（完整文本）和 'sentences'（分段时间戳）的字典
    """
    from dashscope import Transcription

    os.environ['DASHSCOPE_API_KEY'] = api_key

    # 先尝试 qwen3-asr-flash
    task = Transcription.async_call(
        model=model,
        file_urls=[audio_url],
        timestamp_alignment_enabled=True
    )

    if task.status_code != 200:
        # 如果 qwen3-asr-flash 失败，尝试 paraformer-v1
        if model == DASHSCOPE_ASR_MODEL:
            print(f"[DashScope ASR] {model} failed, trying {FALLBACK_ASR_MODEL}...")
            return _call_dashscope_asr(audio_url, api_key, model=FALLBACK_ASR_MODEL)
        return {"error": f"Task creation failed: {task.output}"}

    task_id = task.output['task_id']

    # 轮询等待结果
    for _ in range(60):  # 最多等2分钟
        result = Transcription.wait(task_id)
        status = result.output.task_status

        if status == 'SUCCEEDED':
            # 解析结果
            transcription_text = ""
            sentences = []

            for r in result.output.results:
                transcription_text += r.get('transcription', '')
                sentences.extend(r.get('sentences', []))

            return {
                "text": transcription_text,
                "sentences": sentences
            }
        elif status == 'FAILED':
            error_msg = result.output.message
            print(f"[DashScope ASR] Task failed: {error_msg}")

            # 如果 qwen3-asr-flash 失败，尝试 paraformer-v1
            if model == DASHSCOPE_ASR_MODEL:
                print(f"[DashScope ASR] Retrying with {FALLBACK_ASR_MODEL}...")
                return _call_dashscope_asr(audio_url, api_key, model=FALLBACK_ASR_MODEL)

            return {"error": error_msg}

        time.sleep(2)

    return {"error": "Timeout waiting for transcription"}


def transcribe_with_dashscope(audio_file_path: str, api_key: str) -> str:
    """
    使用 DashScope ASR API 转录音频文件，返回带时间戳的文本。

    参数:
        audio_file_path: 音频文件路径
        api_key: DashScope API Key

    返回:
        str: 带 [MM:SS] 格式时间戳的转录文本
    """
    if not api_key:
        raise ValueError("未配置 DashScope API Key，请在设置中添加 DASHSCOPE_API_KEY")

    # 1. 上传文件到 DashScope
    print(f"[DashScope ASR] Uploading {audio_file_path}...")
    audio_url = _upload_to_dashscope(audio_file_path, api_key)
    if not audio_url:
        raise RuntimeError("文件上传失败，无法获取访问 URL")

    print(f"[DashScope ASR] File uploaded, calling ASR...")
    result = _call_dashscope_asr(audio_url, api_key)

    if "error" in result:
        raise RuntimeError(f"ASR 转录失败: {result['error']}")

    # 2. 解析结果，生成带时间戳的文本
    lines = []
    for sent in result.get("sentences", []):
        begin_time = int(sent.get('begin_time', 0))  # 毫秒
        text = clean_asr_text(sent.get('text', ''))

        if text:
            minutes = begin_time // 1000 // 60
            seconds = (begin_time // 1000) % 60
            lines.append(f"[{minutes:02d}:{seconds:02d}] {text}")

    if not lines:
        # 没有时间戳句子，尝试用完整文本
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
    device_key 参数被忽略（始终使用云端 API）。
    """
    api_key = get_dashscope_api_key()
    return transcribe_with_dashscope(audio_file_path, api_key)


def transcribe_audio_to_timestamped_text(model, audio_file_path: str, device_key: str) -> str:
    """
    兼容层：将 Whisper 接口重定向到 DashScope ASR。
    model 和 device_key 参数被忽略。
    """
    api_key = get_dashscope_api_key()
    return transcribe_with_dashscope(audio_file_path, api_key)


def get_whisper_model(model_name: str = "small", device_key: str = "cpu"):
    """兼容层：返回 None，Whisper 模型不再需要。"""
    return None
