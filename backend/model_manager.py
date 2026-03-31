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

MODELS = {
    "whisper-large-v3": {
        "name": "Whisper large-v3",
        "description": "高精度语音转录模型",
        "size_mb": 2880,
        "url": "https://openaipublic.azureedge.net/main/whisper/models/81f6c10d7c7e6a8274c60fc4baa8dae83adfb42fb8d33f2fdb8fe64a24a0ec76/large-v3.pt",
        "cache_subdir": "whisper",
        "filename": "large-v3.pt",
        "sha256": "81f6c10d7c7e6a8274c60fc4baa8dae83adfb42fb8d33f2fdb8fe64a24a0ec76"
    },
    "sensevoice": {
        "name": "SenseVoice",
        "description": "极速语音转录（阿里开源）",
        "size_mb": 200,
        "url": "https://modelscope.cn/models/iic/SenseVoiceSmall/repository?file=SpeechSenseVoiceSmall/model.pt",
        "cache_subdir": "modelscope/iic/SenseVoiceSmall",
        "filename": "model.pt",
        "sha256": None  # ModelScope 不校验 SHA256
    },
    "all-MiniLM-L6-v2": {
        "name": "Sentence Transformer",
        "description": "文本向量化模型（用于 RAG 语义搜索）",
        "size_mb": 90,
        "url": "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/pytorch_model.bin",
        "cache_subdir": "huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/xxxx",
        "filename": "pytorch_model.bin",
        "sha256": None  # HuggingFace 不校验
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

    # Whisper 特殊处理
    if model_name == "whisper-large-v3":
        return os.path.join(cache_dir, model_info["cache_subdir"], model_info["filename"])

    # 其他模型
    return os.path.join(cache_dir, model_info["cache_subdir"], model_info["filename"])

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

    model_path = get_model_path(model_name)
    exists = os.path.exists(model_path)
    size_mb = 0

    if exists:
        size_mb = os.path.getsize(model_path) / (1024 * 1024)

    return {
        "name": model_name,
        "display_name": model_info["name"],
        "description": model_info["description"],
        "size_mb": model_info["size_mb"],
        "downloaded": exists,
        "local_size_mb": round(size_mb, 2) if exists else 0,
        "path": model_path,
        "download_url": model_info["url"]
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
    if model_name == "whisper-large-v3":
        return """1. 复制上方链接
2. 打开浏览器/迅雷/IDM 下载
3. 下载完成后，将文件保存到:
   Windows: %USERPROFILE%\\.cache\\whisper\\
   macOS: ~/.cache/whisper/
   Linux: ~/.cache/whisper/
4. 文件命名为: large-v3.pt
5. 刷新此页面"""
    elif model_name == "sensevoice":
        return """1. 复制上方链接
2. 打开 ModelScope App 或浏览器下载
3. 保存到以下目录:
   Windows: %USERPROFILE%\\.cache\\modelscope\\iic\\SenseVoiceSmall\\
   macOS: ~/.cache/modelscope/iic/SenseVoiceSmall/
4. 文件命名为: model.pt
5. 刷新此页面"""
    elif model_name == "all-MiniLM-L6-v2":
        return """1. 复制上方链接
2. 打开 HuggingFace 下载
3. 保存到以下目录:
   Windows: %USERPROFILE%\\.cache\\huggingface\\hub\\models--sentence-transformers--all-MiniLM-L6-v2\\
   macOS: ~/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/
4. 刷新此页面"""
    return ""
