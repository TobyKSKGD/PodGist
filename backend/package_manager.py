"""
依赖管理模块 - 管理 Python 包安装/卸载

支持 Windows/macOS/Linux，自动检测已安装的包。
"""

import subprocess
import sys
import re
import os
from typing import Dict, List, Optional, Literal

# ================= 依赖包元数据 =================

Dependency = Literal[
    "torch", "whisper", "funasr", "modelscope",
    "chromadb", "sentence-transformers", "yt-dlp"
]

PACKAGES: Dict[Dependency, Dict] = {
    "torch": {
        "name": "PyTorch",
        "description": "深度学习框架，支持 CPU/GPU 加速",
        "size_mb": "~200MB（CPU）",
        "required": True,
        "is_cuda_separate": True,
        "cuda_note": "GPU 用户请在官网下载 CUDA 版本：https://pytorch.org/get-started/locally/",
        "install_cmd": ["pip", "install", "torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cpu"],
        "pip_name": "torch",
        "category": "core",
    },
    "whisper": {
        "name": "Whisper",
        "description": "OpenAI 高精度语音转录模型",
        "size_mb": "~150MB（small 模型）",
        "required": True,
        "is_cuda_separate": False,
        "install_cmd": ["pip", "install", "-U", "openai-whisper"],
        "pip_name": "openai-whisper",
        "category": "core",
    },
    "funasr": {
        "name": "FunASR",
        "description": "阿里 SenseVoice 转录引擎，速度极快",
        "size_mb": "~50MB",
        "required": True,
        "is_cuda_separate": False,
        "install_cmd": ["pip", "install", "-U", "funasr"],
        "pip_name": "funasr",
        "category": "core",
    },
    "modelscope": {
        "name": "ModelScope",
        "description": "模型加载框架，FunASR 依赖此库",
        "size_mb": "~30MB",
        "required": True,
        "is_cuda_separate": False,
        "install_cmd": ["pip", "install", "-U", "modelscope"],
        "pip_name": "modelscope",
        "category": "core",
    },
    "chromadb": {
        "name": "ChromaDB",
        "description": "向量数据库，用于 RAG 语义搜索",
        "size_mb": "~30MB",
        "required": True,
        "is_cuda_separate": False,
        "install_cmd": ["pip", "install", "-U", "chromadb"],
        "pip_name": "chromadb",
        "category": "rag",
    },
    "sentence-transformers": {
        "name": "Sentence Transformers",
        "description": "文本 Embedding 模型，用于语义搜索",
        "size_mb": "~50MB",
        "required": True,
        "is_cuda_separate": False,
        "install_cmd": ["pip", "install", "-U", "sentence-transformers"],
        "pip_name": "sentence-transformers",
        "category": "rag",
    },
    "yt-dlp": {
        "name": "yt-dlp",
        "description": "音视频下载工具，支持多平台",
        "size_mb": "~5MB",
        "required": True,
        "is_cuda_separate": False,
        "install_cmd": ["pip", "install", "-U", "yt-dlp"],
        "pip_name": "yt-dlp",
        "category": "download",
    },
}

# 核心必须包（不含 torch GPU 版）
CORE_PACKAGES = ["whisper", "funasr", "modelscope", "chromadb", "sentence-transformers", "yt-dlp"]


# ================= 工具函数 =================

def run_pip_command(args: List[str]) -> tuple:
    """
    运行 pip 命令并返回结果。

    返回:
        (success: bool, output: str)
    """
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip"] + args,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "命令执行超时"
    except Exception as e:
        return False, str(e)


def get_installed_packages() -> Dict[str, str]:
    """
    获取所有已安装的 pip 包及其版本。

    返回:
        {"包名": "版本"} 字典
    """
    success, output = run_pip_command(["list", "--format=freeze"])
    if not success:
        return {}

    packages = {}
    for line in output.strip().split("\n"):
        if "==" in line:
            name, version = line.strip().split("==", 1)
            packages[name.lower()] = version
    return packages


def check_package_installed(pip_name: str) -> tuple:
    """
    检查某个 pip 包是否已安装。

    返回:
        (installed: bool, version: str or None)
    """
    installed = get_installed_packages()
    # 匹配包名（部分包有不同命名）
    pip_name_lower = pip_name.lower()

    # 特殊映射
    name_mapping = {
        "openai-whisper": "openai-whisper",
        "torch": "torch",
        "funasr": "funasr",
        "modelscope": "modelscope",
        "chromadb": "chromadb",
        "sentence-transformers": "sentence-transformers",
        "yt-dlp": "yt-dlp",
    }

    for installed_name, version in installed.items():
        if installed_name == pip_name_lower:
            return True, version
        # 检查变体
        if pip_name_lower == "openai-whisper" and "whisper" in installed_name:
            return True, version

    return False, None


# ================= 核心 API =================

def get_all_packages_status() -> List[Dict]:
    """
    获取所有依赖包的状态。

    返回:
        List[Dict]: 每个包的状态信息
    """
    installed = get_installed_packages()
    result = []

    for pkg_id, meta in PACKAGES.items():
        pip_name = meta["pip_name"]
        is_installed, version = check_package_installed(pip_name)

        result.append({
            "id": pkg_id,
            "name": meta["name"],
            "description": meta["description"],
            "size_mb": meta["size_mb"],
            "required": meta["required"],
            "is_cuda_separate": meta.get("is_cuda_separate", False),
            "cuda_note": meta.get("cuda_note", ""),
            "installed": is_installed,
            "version": version,
            "category": meta["category"],
        })

    return result


def install_package(pkg_id: Dependency) -> tuple:
    """
    安装指定的包。

    返回:
        (success: bool, message: str)
    """
    if pkg_id not in PACKAGES:
        return False, f"未知包: {pkg_id}"

    meta = PACKAGES[pkg_id]
    pip_name = meta["pip_name"]

    # 先检查是否已安装
    is_installed, version = check_package_installed(pip_name)
    if is_installed:
        return True, f"{meta['name']} 已安装 (版本 {version})"

    success, output = run_pip_command(["install", pip_name])
    if success:
        return True, f"{meta['name']} 安装成功"
    else:
        return False, f"安装失败: {output[:200]}"


def install_core_packages() -> tuple:
    """
    一键安装所有核心依赖（不含 torch GPU 版）。

    返回:
        (success: bool, results: List[dict])
    """
    results = []
    all_success = True

    for pkg_id in CORE_PACKAGES:
        success, msg = install_package(pkg_id)
        results.append({
            "id": pkg_id,
            "name": PACKAGES[pkg_id]["name"],
            "success": success,
            "message": msg,
        })
        if not success:
            all_success = False

    return all_success, results


def uninstall_package(pkg_id: Dependency) -> tuple:
    """
    卸载指定的包。

    返回:
        (success: bool, message: str)
    """
    if pkg_id not in PACKAGES:
        return False, f"未知包: {pkg_id}"

    meta = PACKAGES[pkg_id]
    pip_name = meta["pip_name"]

    # 检查是否安装
    is_installed, _ = check_package_installed(pip_name)
    if not is_installed:
        return True, f"{meta['name']} 未安装"

    success, output = run_pip_command(["uninstall", pip_name, "-y"])
    if success:
        return True, f"{meta['name']} 卸载成功"
    else:
        return False, f"卸载失败: {output[:200]}"
