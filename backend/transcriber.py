"""
语音转录模块 - 使用 DashScope 远程 ASR API

本版本移除了所有本地模型（Whisper / SenseVoice / PyTorch），
改用 DashScope 云端 ASR API 进行语音识别。

ASR 决策逻辑：
- 短音频（≤5分钟 且 文件≤10MB）：qwen3-asr-flash → MultiModalConversation.call
- 长音频：优先 Paraformer 云端直连可靠的公网音频 URL，失败后上传文件转写
- 上传大文件时仅为传输生成轻量副本，原始音频始终保留用于归档

模型命名：
- qwen3-asr-flash：短音频同步模型（MultiModalConversation.call）
- qwen3-asr-flash-filetrans：长音频异步模型（QwenTranscription.async_call，需公网 URL）
- paraformer-v1：长音频异步模型（Transcription.async_call）
"""

import os
import re
import time
import requests
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from backend import get_ffmpeg_path, get_ffprobe_path

# DashScope ASR 模型
# qwen3-asr-flash：短音频同步模型（MultiModalConversation.call）
# qwen3-asr-flash-filetrans：长音频异步模型（QwenTranscription.async_call，仅公网 URL）
# paraformer-v1：长音频异步模型（Transcription.async_call）
QwenFlashShortModel = "qwen3-asr-flash"          # 稳定名，用于 MultiModalConversation
QwenFlashFiletransModel = "qwen3-asr-flash-filetrans"  # 长音频，需公网 URL
ParaformerModel = "paraformer-v1"

# qwen3-asr-flash 当前限制为 5 分钟 / 10 MB。此前使用 30 分钟 / 60 MB 会让
# 不符合规格的音频先发起一次无效请求，再回退到文件转写，徒增等待时间。
MAX_DURATION_SECONDS = 5 * 60
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

# 大文件上传前的自适应传输副本。原始音频仍用于归档；这里只优化上传字节。
ASR_TRANSPORT_MIN_BYTES = 20 * 1024 * 1024
ASR_TRANSPORT_SAMPLE_RATE = 16000
ASR_TRANSPORT_BITRATE = "48k"
ASR_SUPPORTED_EXTENSIONS = {
    ".aac", ".amr", ".avi", ".flac", ".flv", ".m4a", ".mkv", ".mov",
    ".mp3", ".mp4", ".mpeg", ".ogg", ".opus", ".wav", ".webm", ".wma", ".wmv",
}

# 超长节目拆成带少量重叠的片段，并发提交两个 Paraformer 任务。重叠区保证不丢句，
# 最终按原始偏移量合并时间戳；一旦任意片段失败便回退为原先的单任务路径。
ASR_PARALLEL_MIN_DURATION_SECONDS = 60 * 60
ASR_PARALLEL_CHUNK_SECONDS = 30 * 60
ASR_PARALLEL_CHUNK_OVERLAP_SECONDS = 2
ASR_PARALLEL_MAX_WORKERS = 2


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
            get_ffprobe_path(),
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


def _notify_asr_stage(stage_callback: Optional[Callable[[str], None]], message: str) -> None:
    """发送不含敏感信息的转录进度；回调失败不影响主转录。"""
    print(f"[DashScope ASR] {message}")
    if stage_callback:
        try:
            stage_callback(message)
        except Exception as exc:
            print(f"[DashScope ASR] 进度回调失败: {type(exc).__name__}")


def _record_duration(metrics: Optional[dict], name: str, started_at: float) -> None:
    if metrics is not None:
        metrics[name] = round(time.perf_counter() - started_at, 3)


def _prepare_asr_transport_audio(audio_file_path: str, metrics: Optional[dict] = None) -> Optional[str]:
    """生成仅供上传的轻量语音副本；不改动用户保留的原始音频。"""
    try:
        source_size = os.path.getsize(audio_file_path)
    except OSError:
        return None
    needs_supported_format = os.path.splitext(audio_file_path)[1].lower() not in ASR_SUPPORTED_EXTENSIONS
    if source_size < ASR_TRANSPORT_MIN_BYTES and not needs_supported_format:
        return None

    base, _ = os.path.splitext(audio_file_path)
    transport_path = f"{base}.asr-16k.opus"
    started_at = time.perf_counter()
    print(
        f"[DashScope ASR] 优化上传音频: 原始={source_size / 1024 / 1024:.1f}MB，"
        f"目标={ASR_TRANSPORT_SAMPLE_RATE}Hz/mono/{ASR_TRANSPORT_BITRATE}"
    )
    try:
        result = subprocess.run(
            [
                get_ffmpeg_path(), "-i", audio_file_path, "-vn", "-ac", "1",
                "-ar", str(ASR_TRANSPORT_SAMPLE_RATE), "-c:a", "libopus",
                "-b:a", ASR_TRANSPORT_BITRATE, "-application", "audio", "-y", transport_path,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode != 0 or not os.path.isfile(transport_path):
            detail = (result.stderr or "")[-300:]
            print(f"[DashScope ASR] 轻量副本失败，继续使用原文件: {detail}")
            if os.path.isfile(transport_path):
                os.remove(transport_path)
            return None
        transport_size = os.path.getsize(transport_path)
        # 若压缩收益不足，上传原文件反而更快；删除副本并保持原始质量。
        if not needs_supported_format and transport_size >= source_size * 0.8:
            os.remove(transport_path)
            print("[DashScope ASR] 轻量副本压缩收益不足，继续使用原文件")
            return None
        _record_duration(metrics, "transport_prepare", started_at)
        if metrics is not None:
            metrics["transport_source_mb"] = round(source_size / 1024 / 1024, 2)
            metrics["transport_upload_mb"] = round(transport_size / 1024 / 1024, 2)
        print(f"[DashScope ASR] 使用轻量副本上传: {transport_size / 1024 / 1024:.1f}MB")
        return transport_path
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[DashScope ASR] 轻量副本异常，继续使用原文件: {type(exc).__name__}")
        if os.path.isfile(transport_path):
            try:
                os.remove(transport_path)
            except OSError:
                pass
        return None


def _split_asr_audio_chunks(audio_file_path: str, duration_seconds: float, metrics: Optional[dict] = None) -> list[dict]:
    """将超长音频编码成可并发上传的短语音片段，返回带原始偏移量的描述。"""
    if duration_seconds < ASR_PARALLEL_MIN_DURATION_SECONDS:
        return []

    base, _ = os.path.splitext(audio_file_path)
    started_at = time.perf_counter()
    chunks = []
    nominal_start = 0.0
    chunk_index = 0
    try:
        while nominal_start < duration_seconds:
            source_start = max(0.0, nominal_start - ASR_PARALLEL_CHUNK_OVERLAP_SECONDS)
            source_duration = min(
                ASR_PARALLEL_CHUNK_SECONDS + (nominal_start - source_start),
                duration_seconds - source_start,
            )
            chunk_path = f"{base}.asr-chunk-{chunk_index:02d}.opus"
            result = subprocess.run(
                [
                    get_ffmpeg_path(), "-ss", f"{source_start:.3f}", "-i", audio_file_path,
                    "-t", f"{source_duration:.3f}", "-vn", "-ac", "1",
                    "-ar", str(ASR_TRANSPORT_SAMPLE_RATE), "-c:a", "libopus",
                    "-b:a", ASR_TRANSPORT_BITRATE, "-application", "audio", "-y", chunk_path,
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != 0 or not os.path.isfile(chunk_path):
                detail = (result.stderr or "")[-300:]
                raise RuntimeError(f"切分片段 {chunk_index + 1} 失败: {detail}")
            chunks.append({
                "path": chunk_path,
                "source_start_seconds": source_start,
                "nominal_start_seconds": nominal_start,
            })
            nominal_start += ASR_PARALLEL_CHUNK_SECONDS
            chunk_index += 1

        if len(chunks) < 2:
            _cleanup_asr_chunks(chunks)
            return []
        _record_duration(metrics, "chunk_prepare", started_at)
        print(f"[DashScope ASR] 超长音频已切分为 {len(chunks)} 段，将以 {ASR_PARALLEL_MAX_WORKERS} 路并发转录")
        return chunks
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"[DashScope ASR] 并发切分不可用，回退单任务转录: {exc}")
        _cleanup_asr_chunks(chunks)
        return []


def _cleanup_asr_chunks(chunks: list[dict]) -> None:
    for chunk in chunks:
        chunk_path = chunk.get("path")
        if chunk_path and os.path.isfile(chunk_path):
            try:
                os.remove(chunk_path)
            except OSError:
                pass


def _merge_parallel_chunk_results(chunk_results: list[tuple[dict, dict]]) -> Optional[dict]:
    """按原音频时间轴合并片段结果，跳过重叠区的重复句子。"""
    merged_sentences = []
    previous_chunk_tail: list[str] = []
    for chunk, result in sorted(chunk_results, key=lambda item: item[0]["source_start_seconds"]):
        if not result.get("sentences"):
            return None
        source_offset_ms = int(chunk["source_start_seconds"] * 1000)
        nominal_start_ms = int(chunk["nominal_start_seconds"] * 1000)
        overlap_end_ms = nominal_start_ms + ASR_PARALLEL_CHUNK_OVERLAP_SECONDS * 1000
        current_chunk_tail: list[str] = []
        for sentence in result["sentences"]:
            text = clean_asr_text(sentence.get("text", ""))
            if not text:
                continue
            begin_time = int(sentence.get("begin_time", 0)) + source_offset_ms
            end_time = int(sentence.get("end_time", 0)) + source_offset_ms
            if nominal_start_ms and end_time <= nominal_start_ms:
                continue
            normalized_text = re.sub(r"\s+", "", text)
            # 只在相邻片段的 2 秒重叠区去重，正文里重复的表达必须原样保留。
            if (
                nominal_start_ms
                and begin_time < overlap_end_ms
                and normalized_text
                and normalized_text in previous_chunk_tail
            ):
                continue
            merged_sentences.append({"begin_time": begin_time, "end_time": end_time, "text": text})
            current_chunk_tail = (current_chunk_tail + [normalized_text])[-6:]
        if current_chunk_tail:
            previous_chunk_tail = current_chunk_tail

    if not merged_sentences:
        return None
    full_text = "\n".join(sentence["text"] for sentence in merged_sentences)
    return {"text": full_text, "sentences": merged_sentences}


def _transcribe_parallel_chunks(
    chunks: list[dict],
    api_key: str,
    metrics: Optional[dict] = None,
    stage_callback: Optional[Callable[[str], None]] = None,
) -> Optional[dict]:
    """并发上传并转录切片；任何一片失败即返回 None，调用方会安全回退。"""
    _notify_asr_stage(stage_callback, f"ASR：超长音频分段并发转录中（{len(chunks)} 段）...")
    started_at = time.perf_counter()

    def transcribe_chunk(chunk: dict) -> tuple[dict, dict]:
        audio_url = _upload_to_dashscope(chunk["path"], api_key)
        if not audio_url:
            raise RuntimeError("片段上传失败")
        result = _call_paraformer_transcription(audio_url, api_key)
        if "error" in result:
            raise RuntimeError(result["error"])
        return chunk, result

    try:
        results = []
        with ThreadPoolExecutor(max_workers=ASR_PARALLEL_MAX_WORKERS, thread_name_prefix="PodGist_ASR") as executor:
            futures = [executor.submit(transcribe_chunk, chunk) for chunk in chunks]
            for future in as_completed(futures):
                results.append(future.result())
        merged = _merge_parallel_chunk_results(results)
        if not merged:
            print("[DashScope ASR] 分段结果缺少句级时间戳，回退单任务转录")
            return None
        _record_duration(metrics, "parallel_cloud_asr", started_at)
        return merged
    except Exception as exc:
        print(f"[DashScope ASR] 并发转录失败，回退单任务转录: {type(exc).__name__}: {exc}")
        return None


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

def _fetch_transcription_from_url(transcription_url: str, metrics: Optional[dict] = None) -> dict:
    """
    从 transcription_url 获取转录结果。
    返回包含 text 和 sentences 的字典。
    """
    started_at = time.perf_counter()
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
    finally:
        _record_duration(metrics, "result_download", started_at)


def _call_paraformer_transcription(
    audio_url: str,
    api_key: str,
    model: str = ParaformerModel,
    metrics: Optional[dict] = None,
    stage_callback: Optional[Callable[[str], None]] = None,
    allow_model_fallback: bool = True,
) -> dict:
    """
    使用 Transcription API（function="conversation"）进行长音频语音识别。
    paraformer 系列使用此 API，无需公网 URL（通过 Files.upload 上传）。
    失败后自动降级：paraformer-v1 → paraformer-8k-v1 → paraformer-mtl-v1
    """
    from dashscope import Transcription

    print(f"[DashScope ASR] 调用 {model} (Transcription.async_call)，URL: {audio_url}")

    started_at = time.perf_counter()
    try:
        _notify_asr_stage(stage_callback, "ASR：云端识别中...")
        task = Transcription.async_call(
            model=model,
            file_urls=[audio_url],
            timestamp_alignment_enabled=True,
            api_key=api_key
        )

        if task.status_code != 200:
            err_msg = f"status={task.status_code} code={getattr(task, 'code', None)} message={getattr(task, 'message', None)}"
            print(f"[DashScope ASR] Transcription async_call 失败: {err_msg}")
            if allow_model_fallback and model == ParaformerModel:
                print(f"[DashScope ASR] {model} 失败，降级到 paraformer-8k-v1...")
                return _call_paraformer_transcription(
                    audio_url, api_key, model="paraformer-8k-v1", metrics=metrics,
                    stage_callback=stage_callback, allow_model_fallback=True,
                )
            elif allow_model_fallback and model == "paraformer-8k-v1":
                print(f"[DashScope ASR] paraformer-8k-v1 失败，降级到 paraformer-mtl-v1...")
                return _call_paraformer_transcription(
                    audio_url, api_key, model="paraformer-mtl-v1", metrics=metrics,
                    stage_callback=stage_callback, allow_model_fallback=True,
                )
            return {"error": err_msg}

        task_id = task.output.get('task_id') or task.output.task_id
        print(f"[DashScope ASR] {model} task_id: {task_id}")

        for attempt in range(60):
            result = Transcription.wait(task_id, api_key=api_key)
            status = result.output.get('task_status') or result.output.task_status

            if status == 'SUCCEEDED':
                transcription_url = result.output.get('transcription_url')
                if transcription_url:
                    return _fetch_transcription_from_url(transcription_url, metrics=metrics)
                results = result.output.get('results')
                if results:
                    transcription_url = results[0].get('transcription_url') if isinstance(results[0], dict) else getattr(results[0], 'transcription_url', None)
                    if transcription_url:
                        return _fetch_transcription_from_url(transcription_url, metrics=metrics)
                return {"text": "", "sentences": []}

            elif status == 'FAILED':
                error_msg = result.output.get('message') or str(result.output)
                print(f"[DashScope ASR] {model} 任务失败: {error_msg}")
                if allow_model_fallback and model == ParaformerModel:
                    print(f"[DashScope ASR] 降级到 paraformer-8k-v1...")
                    return _call_paraformer_transcription(
                        audio_url, api_key, model="paraformer-8k-v1", metrics=metrics,
                        stage_callback=stage_callback, allow_model_fallback=True,
                    )
                elif allow_model_fallback and model == "paraformer-8k-v1":
                    print(f"[DashScope ASR] 降级到 paraformer-mtl-v1...")
                    return _call_paraformer_transcription(
                        audio_url, api_key, model="paraformer-mtl-v1", metrics=metrics,
                        stage_callback=stage_callback, allow_model_fallback=True,
                    )
                return {"error": error_msg}

            if attempt and attempt % 5 == 0:
                _notify_asr_stage(stage_callback, f"ASR：云端仍在转录（已等待约 {attempt * 2} 秒）...")
            time.sleep(2)

        return {"error": "Timeout waiting for transcription"}

    except Exception as e:
        print(f"[DashScope ASR] {model} 异常: {type(e).__name__}: {e}")
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        _record_duration(metrics, "cloud_asr", started_at)


# ==================== 文件上传（仅 paraformer 需要）====================

def _upload_to_dashscope(
    audio_file_path: str,
    api_key: str,
    metrics: Optional[dict] = None,
    stage_callback: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """
    将本地音频文件上传到 DashScope，返回可访问的 URL（仅供 paraformer 使用）。
    qwen3-asr-flash 短音频不走此函数（直接 MultiModalConversation.call）。
    qwen3-asr-flash-filetrans 需要公网 URL，不走此上传。
    """
    from dashscope import Files

    started_at = time.perf_counter()
    try:
        _notify_asr_stage(stage_callback, "ASR：正在上传音频...")
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
    finally:
        _record_duration(metrics, "upload", started_at)


# ==================== 主入口：智能路由 ========================

def transcribe_with_dashscope(
    audio_file_path: str,
    api_key: str,
    public_audio_url: Optional[str] = None,
    metrics: Optional[dict] = None,
    stage_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """
    使用 DashScope ASR API 转录音频文件，返回带时间戳的文本。

    决策逻辑：
    1. 短音频（≤5分钟 且 ≤10MB）→ qwen3-asr-flash（MultiModalConversation.call）
    2. 长音频 → paraformer（Transcription.async_call）
       - 先上传文件到 DashScope 获取 URL
       - paraformer 失败后降级到 paraformer-8k-v1 → paraformer-mtl-v1
    3. 有可靠公网音频 URL 时，优先让 Paraformer 云端直连，失败后回退上传
    """
    text, _ = transcribe_with_dashscope_and_segments(
        audio_file_path,
        api_key,
        public_audio_url=public_audio_url,
        metrics=metrics,
        stage_callback=stage_callback,
    )
    return text


def transcribe_with_dashscope_and_segments(
    audio_file_path: str,
    api_key: str,
    public_audio_url: Optional[str] = None,
    metrics: Optional[dict] = None,
    stage_callback: Optional[Callable[[str], None]] = None,
) -> tuple[str, list]:
    """
    使用 DashScope ASR API 转录音频文件，返回 (带时间戳文本, 分段列表)。

    返回值：
    - text: 带时间戳的文本字符串
    - segments: 分段列表，每项包含 id, time, seconds, text

    决策逻辑同上。
    """
    if not api_key:
        raise ValueError("未配置 DashScope API Key，请在设置中添加 DASHSCOPE_API_KEY")

    total_started_at = time.perf_counter()
    transport_audio_path = None
    parallel_chunks: list[dict] = []
    try:
        # 步骤 1：判定音频类型
        if is_short_audio(audio_file_path):
            # ===== 短音频：qwen3-asr-flash =====
            _notify_asr_stage(stage_callback, "ASR：短音频快速转录中...")
            short_started_at = time.perf_counter()
            result = _call_qwen_flash_short(audio_file_path, api_key)
            _record_duration(metrics, "cloud_asr", short_started_at)

            if "error" not in result:
                return _build_timestamped_text(result), _build_segments_from_sentences(result.get("sentences", []))

            # qwen3-asr-flash 失败，尝试长音频路径（升级为 paraformer）
            print(f"[DashScope ASR] qwen3-asr-flash 失败，降级到 paraformer 长音频路径: {result.get('error')}")

        # ===== 长音频：paraformer =====
        print(f"[DashScope ASR] 长音频路径: paraformer (Transcription.async_call)")

        # 在线来源若提供可公开访问的直链，先让云端直接拉取；失败后严格回退到
        # 原有上传 + Paraformer 路径，因此不会因平台临时链接而降低成功率。
        if public_audio_url:
            _notify_asr_stage(stage_callback, "ASR：云端正直接获取在线音频...")
            direct_started_at = time.perf_counter()
            direct_result = _call_paraformer_transcription(
                public_audio_url,
                api_key,
                metrics=metrics,
                stage_callback=stage_callback,
                allow_model_fallback=False,
            )
            _record_duration(metrics, "public_url_asr", direct_started_at)
            if "error" not in direct_result and (direct_result.get("text") or direct_result.get("sentences")):
                print("[DashScope ASR] 云端直连音频转录成功")
                return _build_timestamped_text(direct_result), _build_segments_from_sentences(direct_result.get("sentences", []))
            print("[DashScope ASR] 云端直连不可用，自动回退为本地上传转录")

        _notify_asr_stage(stage_callback, "ASR：准备上传转录音频...")
        transport_audio_path = _prepare_asr_transport_audio(audio_file_path, metrics=metrics)
        upload_source = transport_audio_path or audio_file_path

        # 超过一小时的本地音频才分片并发。使用同一 Paraformer 模型、2 秒重叠和
        # 原始时间偏移合并；若任一环节异常，完整回退到下方的单文件路径。
        upload_duration = get_audio_duration(upload_source)
        parallel_chunks = _split_asr_audio_chunks(upload_source, upload_duration, metrics=metrics)
        if parallel_chunks:
            parallel_result = _transcribe_parallel_chunks(
                parallel_chunks,
                api_key,
                metrics=metrics,
                stage_callback=stage_callback,
            )
            if parallel_result:
                print("[DashScope ASR] 超长音频并发转录成功")
                return _build_timestamped_text(parallel_result), _build_segments_from_sentences(parallel_result["sentences"])

        audio_url = _upload_to_dashscope(upload_source, api_key, metrics=metrics, stage_callback=stage_callback)
        if not audio_url:
            raise RuntimeError("文件上传失败，无法获取访问 URL")

        result = _call_paraformer_transcription(
            audio_url,
            api_key,
            metrics=metrics,
            stage_callback=stage_callback,
        )

        if "error" in result:
            raise RuntimeError(f"ASR 转录失败: {result['error']}")

        return _build_timestamped_text(result), _build_segments_from_sentences(result.get("sentences", []))
    finally:
        _record_duration(metrics, "total", total_started_at)
        _cleanup_asr_chunks(parallel_chunks)
        if transport_audio_path and os.path.isfile(transport_audio_path):
            try:
                os.remove(transport_audio_path)
            except OSError:
                pass


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
