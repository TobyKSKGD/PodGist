import whisper
import torch
import subprocess

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
        initial_prompt="以下是一段精彩的中文播客内容，请输出简体中文。",
        fp16=use_fp16
    )

    full_text = ""
    for segment in transcribe_result["segments"]:
        minutes = int(segment["start"]) // 60
        seconds = int(segment["start"]) % 60
        full_text += f"[{minutes:02d}:{seconds:02d}] {segment['text']}\n"

    return full_text