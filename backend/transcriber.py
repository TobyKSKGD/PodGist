import whisper
import torch
import subprocess
import re

def get_available_devices():
    """
    检测并返回当前系统可用的计算设备。

    返回:
        dict: 可用设备字典，键为设备标识符（如 'cpu', 'cuda', 'mps'），
              值为设备描述字符串。
    """
    devices = {"cpu": "CPU (基础处理器)"}

    if torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(0)
        devices["cuda"] = f"GPU: {device_name}"

    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        try:
            # 通过系统命令获取 Apple Silicon 芯片型号
            chip_name = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).strip().decode("utf-8")
            devices["mps"] = f"Apple Silicon ({chip_name})"
        except Exception:
            # 若系统调用失败，使用默认描述
            devices["mps"] = "Apple M系芯片 (Mac 专属加速)"

    return devices

def get_whisper_model(model_name="small", device_key="cpu"):
    """
    加载指定规模的 Whisper 语音识别模型。

    参数:
        model_name (str): Whisper 模型规模，可选 'tiny', 'base', 'small', 'medium', 'large-v3'
        device_key (str): 计算设备标识符，如 'cpu', 'cuda', 'mps'

    返回:
        whisper.Whisper: 加载的 Whisper 模型实例
    """
    return whisper.load_model(model_name, device=device_key)

def transcribe_audio_to_timestamped_text(model, audio_file_path, device_key):
    """
    使用 Whisper 模型转录音频文件，并生成带时间戳的文本。

    参数:
        model: 已加载的 Whisper 模型实例
        audio_file_path (str): 音频文件路径
        device_key (str): 计算设备标识符，用于决定是否使用 FP16 精度

    返回:
        str: 带 [MM:SS] 格式时间戳的转录文本
    """
    # 仅在 CUDA 设备上使用 FP16 精度以提高性能
    use_fp16 = True if device_key == "cuda" else False

    transcribe_result = model.transcribe(
        audio_file_path,
        language="zh",
        initial_prompt="以下是一段精彩的音频内容，请输出简体中文。",
        fp16=use_fp16
    )

    full_text = ""
    for segment in transcribe_result["segments"]:
        minutes = int(segment["start"]) // 60
        seconds = int(segment["start"]) % 60
        full_text += f"[{minutes:02d}:{seconds:02d}] {segment['text']}\n"

    return full_text


# ================= SenseVoice 本地模型 =================

# SenseVoice 模型缓存
_sensevoice_model = None

def get_sensevoice_model(device_key="cuda"):
    """
    加载 SenseVoice 模型。

    参数:
        device_key (str): 计算设备标识符，如 'cuda', 'cpu'

    返回:
        SenseVoice 模型实例
    """
    global _sensevoice_model

    if _sensevoice_model is not None:
        return _sensevoice_model

    try:
        from modelscope.pipelines import pipeline
        from modelscope.utils.constant import Tasks

        # 使用 ModelScope 的 SenseVoice pipeline
        _sensevoice_model = pipeline(
            Tasks.auto_speech_recognition,
            model="iic/SenseVoiceSmall",
            device=device_key
        )
        return _sensevoice_model
    except ImportError:
        raise ImportError("请安装 ModelScope: pip install modelscope")


def clean_sensevoice_text(text):
    """
    清洗 SenseVoice 输出，移除情绪标签和特殊标记。

    参数:
        text (str): 原始 SenseVoice 输出

    返回:
        str: 清洗后的文本
    """
    # 移除 <|xxx|> 格式的标签（支持多标签连续的情况）
    text = re.sub(r'<\|[^|]*\|>', '', text)

    # 移除字典格式的残留（如 {'key': '...', 'text': '...'}）
    text = re.sub(r"\{[^}]+\}", '', text)

    # 移除多余的空格
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def transcribe_with_sensevoice(audio_file_path, device_key="cuda"):
    """
    使用 SenseVoice 模型转录音频文件（分片处理以获取时间戳）。

    参数:
        audio_file_path (str): 音频文件路径
        device_key (str): 计算设备标识符，如 'cuda', 'cpu', 'cuda:0'

    返回:
        str: 带 [MM:SS] 格式时间戳的转录文本
    """
    try:
        from modelscope.pipelines import pipeline
        from modelscope.utils.constant import Tasks
        from pydub import AudioSegment
    except ImportError as e:
        raise ImportError(f"缺少依赖: {e}，请安装: pip install modelscope pydub")

    # 转换设备参数格式
    if device_key == "cuda":
        device = "cuda:0"
    elif device_key == "mps":
        device = "cpu"
    else:
        device = "cpu"

    # 加载音频
    audio = AudioSegment.from_mp3(audio_file_path)
    duration_sec = len(audio) / 1000

    # 切片大小（秒）- 可调整
    chunk_size = 30
    num_chunks = int((duration_sec + chunk_size - 1) // chunk_size)

    # 创建 SenseVoice pipeline
    inference_pipeline = pipeline(
        Tasks.auto_speech_recognition,
        model="iic/SenseVoiceSmall",
        device=device
    )

    results = []

    # 分片处理
    for i in range(num_chunks):
        start_ms = i * chunk_size * 1000
        end_ms = min((i + 1) * chunk_size * 1000, len(audio))

        chunk = audio[start_ms:end_ms]

        # 保存到临时文件
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            chunk.export(tmp.name, format="wav")
            tmp_path = tmp.name

        try:
            # 转录
            result = inference_pipeline(tmp_path)

            # 提取文本
            text = ""
            if isinstance(result, dict):
                text = result.get("text", str(result))
            elif isinstance(result, list) and len(result) > 0:
                for item in result:
                    if isinstance(item, dict):
                        text += item.get("text", "")
                    elif isinstance(item, str):
                        text += item
            else:
                text = str(result)

            # 清洗文本
            text = clean_sensevoice_text(text)

            # 计算绝对时间戳
            timestamp = start_ms / 1000
            minutes = int(timestamp) // 60
            seconds = int(timestamp) % 60

            if text:
                results.append(f"[{minutes:02d}:{seconds:02d}] {text}")

        finally:
            # 删除临时文件
            os.remove(tmp_path)

    return "\n".join(results)
