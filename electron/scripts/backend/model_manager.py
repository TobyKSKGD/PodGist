"""
模型管理模块 - 检查状态、下载模型、断点续传

支持 Windows/macOS/Linux 多平台，自动检测模型缓存目录。
"""

import os
import requests
import hashlib
from typing import Dict, List, Optional
from urllib.parse import urlparse

# ================= 模型信息 =================

# Whisper 模型组 - 所有版本
WHISPER_MODELS = {
    "whisper-tiny": {
        "name": "Whisper tiny",
        "description": "最小模型，速度最快，精度较低",
        "size_mb": 75,
        "url": "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt",
        "cache_subdir": "whisper",
        "filename": "tiny.pt",
        "sha256": "65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9",
        "group": "whisper"
    },
    "whisper-base": {
        "name": "Whisper base",
        "description": "基础模型，速度快，精度一般",
        "size_mb": 142,
        "url": "https://openaipublic.azureedge.net/main/whisper/models/ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e/base.pt",
        "cache_subdir": "whisper",
        "filename": "base.pt",
        "sha256": "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e",
        "group": "whisper"
    },
    "whisper-small": {
        "name": "Whisper small",
        "description": "小模型，平衡选择（推荐）",
        "size_mb": 465,
        "url": "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt",
        "cache_subdir": "whisper",
        "filename": "small.pt",
        "sha256": "9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794",
        "group": "whisper"
    },
    "whisper-medium": {
        "name": "Whisper medium",
        "description": "中模型，精度较好，需更多显存",
        "size_mb": 1500,
        "url": "https://openaipublic.azureedge.net/main/whisper/models/345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1/medium.pt",
        "cache_subdir": "whisper",
        "filename": "medium.pt",
        "sha256": "345ae4da62f9b3d59415adc60127b97c714f32e89e936602e85993674d08dcb1",
        "group": "whisper"
    },
    "whisper-large-v3": {
        "name": "Whisper large-v3",
        "description": "最大模型，精度最高，需大量显存",
        "size_mb": 2880,
        "url": "https://openaipublic.azureedge.net/main/whisper/models/e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb/large-v3.pt",
        "cache_subdir": "whisper",
        "filename": "large-v3.pt",
        "sha256": "e5b1a55b89c1367dacf97e3e19bfd829a01529dbfdeefa8caeb59b3f1b81dadb",
        "group": "whisper"
    },
    "whisper-large-v3-turbo": {
        "name": "Whisper large-v3-turbo",
        "description": "large-v3 加速版，精度接近 large-v3，速度更快",
        "size_mb": 1550,
        "url": "https://openaipublic.azureedge.net/main/whisper/models/aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a/large-v3-turbo.pt",
        "cache_subdir": "whisper",
        "filename": "large-v3-turbo.pt",
        "sha256": "aff26ae408abcba5fbf8813c21e62b0941638c5f6eebfb145be0c9839262a19a",
        "group": "whisper"
    }
}

# 非 Whisper 模型
MODELS = {
    **WHISPER_MODELS,
    "sensevoice": {
        "name": "SenseVoice",
        "description": "极速语音转录（阿里开源）",
        "size_mb": 893,
        "url": "https://modelscope.cn/models/iic/SenseVoiceSmall/repository?file=SpeechSenseVoiceSmall/model.pt",
        "cache_subdir": "modelscope/hub/models/iic/SenseVoiceSmall",
        "filename": "model.pt",
        "sha256": None,  # ModelScope 不校验 SHA256
        "check_type": "file",
        "group": None
    },
    "all-MiniLM-L6-v2": {
        "name": "Sentence Transformer",
        "description": "文本向量化模型（用于 RAG 语义搜索）",
        "size_mb": 103,
        "url": "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/pytorch_model.bin",
        "cache_subdir": "huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2",
        "filename": None,  # HuggingFace 使用 blob 存储，不检查特定文件
        "sha256": None,
        "check_type": "directory",
        "group": None
    }
}

# ================= 路径工具 =================

def get_cache_dir() -> str:
    """获取模型缓存根目录"""
    # 优先使用环境变量指定的目录
    if os.environ.get('PODGIST_MODEL_DIR'):
        return os.environ['PODGIST_MODEL_DIR']

    # 回退到系统默认缓存目录
    home = os.path.expanduser("~")

    if os.name == 'nt':  # Windows
        return os.path.join(home, ".cache")
    elif os.uname().sysname == 'Darwin':  # macOS
        return os.path.join(home, ".cache")
    else:  # Linux
        return os.path.join(home, ".cache")

def get_model_path(model_name: str) -> str:
    """获取模型的完整路径"""
    cache_dir = get_cache_dir()
    model_info = MODELS.get(model_name)

    if not model_info:
        raise ValueError(f"未知模型: {model_name}")

    filename = model_info.get("filename")
    if not filename:
        # 对于没有特定文件名的模型（如 HuggingFace），返回目录路径
        return os.path.join(cache_dir, model_info["cache_subdir"])

    return os.path.join(cache_dir, model_info["cache_subdir"], filename)

def get_model_dir(model_name: str) -> str:
    """获取模型的目录路径"""
    cache_dir = get_cache_dir()
    model_info = MODELS.get(model_name)
    return os.path.join(cache_dir, model_info["cache_subdir"])

def ensure_model_dir(model_name: str) -> str:
    """确保模型目录存在，返回目录路径"""
    model_dir = get_model_dir(model_name)
    os.makedirs(model_dir, exist_ok=True)
    return model_dir

# ================= 状态检查 =================

def check_model_status(model_name: str) -> Dict:
    """检查单个模型的状态"""
    model_info = MODELS.get(model_name)
    if not model_info:
        return {"error": f"未知模型: {model_name}"}

    check_type = model_info.get("check_type", "file")
    model_dir = get_model_dir(model_name)
    exists = False
    size_mb = 0
    display_path = model_dir

    if check_type == "directory":
        # 对于 HuggingFace 等目录式存储，检查目录是否存在
        exists = os.path.isdir(model_dir)
        if exists:
            # 计算目录总大小
            for dirpath, dirnames, filenames in os.walk(model_dir):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.exists(fp):
                        size_mb += os.path.getsize(fp) / (1024 * 1024)
    else:
        # 对于文件式存储，检查具体文件
        model_path = get_model_path(model_name)
        exists = os.path.exists(model_path)
        display_path = model_path
        if exists:
            size_mb = os.path.getsize(model_path) / (1024 * 1024)

    return {
        "name": model_name,
        "display_name": model_info["name"],
        "description": model_info["description"],
        "size_mb": model_info["size_mb"],
        "downloaded": exists,
        "local_size_mb": round(size_mb, 2) if exists else 0,
        "path": display_path,
        "download_url": model_info["url"],
        "group": model_info.get("group")
    }

def get_all_models_status() -> List[Dict]:
    """获取所有模型的状态"""
    return [check_model_status(name) for name in MODELS.keys()]

# ================= 下载工具 =================

def verify_file_sha256(file_path: str, expected_sha256: str) -> bool:
    """验证文件 SHA256"""
    if not expected_sha256:
        return True  # 不校验

    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256_hash.update(chunk)

    actual_sha256 = sha256_hash.hexdigest()
    return actual_sha256 == expected_sha256

def download_with_resume(url: str, dest_path: str, expected_sha256: Optional[str] = None,
                         chunk_size: int = 8192) -> Dict:
    """
    下载文件，支持断点续传

    返回:
        {"success": True, "message": "下载完成"}
        {"success": False, "error": "错误信息", "can_resume": True, "downloaded_mb": xxx}
    """
    # 确保目录存在
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    # 检查已下载的大小
    existing_size = 0
    if os.path.exists(dest_path):
        existing_size = os.path.getsize(dest_path)

    # 获取文件总大小
    try:
        response = requests.head(url, allow_redirects=True, timeout=30)
        total_size = int(response.headers.get('content-length', 0))
    except Exception as e:
        return {"success": False, "error": f"无法获取文件大小: {str(e)}", "can_resume": False}

    # 如果文件已存在且完整，验证
    if existing_size == total_size and total_size > 0:
        if expected_sha256 and not verify_file_sha256(dest_path, expected_sha256):
            # 校验失败，删除并重新下载
            os.remove(dest_path)
            existing_size = 0
        else:
            return {"success": True, "message": "文件已完整存在", "already_downloaded": True}

    # 断点续传下载
    headers = {}
    if existing_size > 0:
        headers["Range"] = f"bytes={existing_size}-"
        print(f"[ModelManager] 断点续传，从 {existing_size} 字节开始")

    try:
        response = requests.get(url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()

        # 处理 Range 请求的响应
        if response.status_code == 206:
            # 断点续传成功
            content_range = response.headers.get('content-range', '')
            print(f"[ModelManager] 206 响应: {content_range}")
        elif existing_size > 0:
            # 服务器不支持断点续传，从头开始
            print(f"[ModelManager] 服务器不支持断点续传，重新下载")
            os.remove(dest_path)
            existing_size = 0
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0)) + existing_size

        with open(dest_path, "ab" if existing_size > 0 else "wb") as f:
            downloaded = existing_size
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    # 发送进度（通过 yield 实现）
                    yield {
                        "type": "progress",
                        "downloaded_mb": round(downloaded / (1024 * 1024), 2),
                        "total_mb": round(total_size / (1024 * 1024), 2),
                        "percent": round(downloaded / total_size * 100, 1) if total_size > 0 else 0
                    }

        # 下载完成，校验
        if expected_sha256 and not verify_file_sha256(dest_path, expected_sha256):
            os.remove(dest_path)
            yield {"type": "error", "error": "SHA256 校验失败，文件已损坏"}
            return

        yield {"type": "success", "message": "下载完成"}

    except requests.exceptions.Timeout:
        yield {"type": "error", "error": "下载超时，请重试或使用手动下载"}
    except requests.exceptions.RequestException as e:
        yield {"type": "error", "error": f"下载失败: {str(e)}"}
    except IOError as e:
        yield {"type": "error", "error": f"文件写入失败: {str(e)}"}

def download_model(model_name: str, progress_callback=None) -> Dict:
    """
    下载指定模型

    Args:
        model_name: 模型名称
        progress_callback: 进度回调函数，接收进度字典

    Returns:
        最终结果字典
    """
    model_info = MODELS.get(model_name)
    if not model_info:
        return {"success": False, "error": f"未知模型: {model_name}"}

    dest_path = get_model_path(model_name)

    # 如果已存在且完整
    if os.path.exists(dest_path):
        size = os.path.getsize(dest_path)
        if model_info["size_mb"] * 1024 * 1024 * 0.9 < size < model_info["size_mb"] * 1024 * 1024 * 1.5:
            return {"success": True, "message": "模型已存在", "already_downloaded": True}

    # 执行下载
    result = None
    for event in download_with_resume(
        url=model_info["url"],
        dest_path=dest_path,
        expected_sha256=model_info.get("sha256")
    ):
        if event["type"] == "progress":
            if progress_callback:
                progress_callback(event)
        elif event["type"] == "error":
            result = {"success": False, "error": event["error"]}
        elif event["type"] == "success":
            result = {"success": True, "message": event["message"], "path": dest_path}

    return result or {"success": False, "error": "未知错误"}

# ================= 获取手动下载链接 =================

def get_manual_download_info(model_name: str) -> Dict:
    """获取手动下载信息"""
    model_info = MODELS.get(model_name)
    if not model_info:
        return {"error": f"未知模型: {model_name}"}

    return {
        "name": model_name,
        "display_name": model_info["name"],
        "url": model_info["url"],
        "filename": model_info["filename"],
        "size_mb": model_info["size_mb"],
        "instructions": _get_download_instructions(model_name)
    }

def _get_download_instructions(model_name: str) -> str:
    """获取下载说明"""
    model_info = MODELS.get(model_name)
    if not model_info:
        return ""

    # Whisper 系列统一处理
    if model_info.get("group") == "whisper":
        filename = model_info["filename"]
        return f"""1. 复制上方链接
2. 打开浏览器/迅雷/IDM 下载
3. 下载完成后，将文件保存到:
   Windows: %USERPROFILE%\.cache\whisper\
   macOS: ~/.cache/whisper/
   Linux: ~/.cache/whisper/
4. 文件命名为: {filename}
5. 刷新此页面"""

    if model_name == "sensevoice":
        return """1. 复制上方链接
2. 打开 ModelScope App 或浏览器下载
3. 保存到以下目录:
   Windows: %USERPROFILE%\.cache\modelscope\hub\models\iic\SenseVoiceSmall\
   macOS: ~/.cache/modelscope/hub/models/iic/SenseVoiceSmall/
4. 文件命名为: model.pt
5. 刷新此页面"""

    if model_name == "all-MiniLM-L6-v2":
        return """1. 复制上方链接
2. 打开 HuggingFace 下载
3. 保存到以下目录:
   Windows: %USERPROFILE%\.cache\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2\
   macOS: ~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/
4. 刷新此页面"""

    return ""

