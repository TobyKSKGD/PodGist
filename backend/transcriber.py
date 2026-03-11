import whisper
import torch
import subprocess

def get_available_devices():
    """
    动态嗅探当前机器的底层算力硬件，并精确识别 Mac 芯片型号
    """
    devices = {"cpu": "CPU (基础处理器)"}
    
    if torch.cuda.is_available():
        device_name = torch.cuda.get_device_name(0)
        devices["cuda"] = f"GPU: {device_name}"
        
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        try:
            # 调用 macOS 底层系统命令，获取具体的芯片字符串 (例如 "Apple M1")
            chip_name = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).strip().decode("utf-8")
            devices["mps"] = f"Apple Silicon ({chip_name})"
        except Exception:
            # 如果系统调用失败，做个保底
            devices["mps"] = "Apple M系芯片 (Mac 专属加速)"
            
    return devices

def get_whisper_model(model_name="small", device_key="cpu"):
    return whisper.load_model(model_name, device=device_key)

def transcribe_audio_to_timestamped_text(model, audio_file_path, device_key):
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