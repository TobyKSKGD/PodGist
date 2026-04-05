"""
依赖管理模块 - 管理 Python 包安装/卸载

支持 Windows/macOS/Linux，自动检测已安装的包。
"""

import subprocess
import sys
import os
from typing import Dict, List, Literal

# ================= 依赖包元数据 =================

Dependency = Literal[
    "whisper", "funasr", "modelscope",
    "chromadb", "sentence-transformers", "yt-dlp"
]

PACKAGES: Dict[str, Dict] = {
    "whisper": {
        "name": "Whisper",
        "description": "OpenAI 高精度语音转录模型",
        "size_mb": "~150MB（small 模型）",
        "required": True,
        "install_args": ["install", "-U", "openai-whisper"],
        "pip_name": "openai-whisper",
        "category": "core",
    },
    "funasr": {
        "name": "FunASR",
        "description": "阿里 SenseVoice 转录引擎，速度极快",
        "size_mb": "~50MB",
        "required": True,
        "install_args": ["install", "-U", "funasr"],
        "pip_name": "funasr",
        "category": "core",
    },
    "modelscope": {
        "name": "ModelScope",
        "description": "模型加载框架，FunASR 依赖此库",
        "size_mb": "~30MB",
        "required": True,
        "install_args": ["install", "-U", "modelscope"],
        "pip_name": "modelscope",
        "category": "core",
    },
    "chromadb": {
        "name": "ChromaDB",
        "description": "向量数据库，用于 RAG 语义搜索",
        "size_mb": "~30MB",
        "required": True,
        "install_args": ["install", "-U", "chromadb"],
        "pip_name": "chromadb",
        "category": "rag",
    },
    "sentence-transformers": {
        "name": "Sentence Transformers",
        "description": "文本 Embedding 模型，用于语义搜索",
        "size_mb": "~50MB",
        "required": True,
        "install_args": ["install", "-U", "sentence-transformers"],
        "pip_name": "sentence-transformers",
        "category": "rag",
    },
    "yt-dlp": {
        "name": "yt-dlp",
        "description": "音视频下载工具，支持多平台",
        "size_mb": "~5MB",
        "required": True,
        "install_args": ["install", "-U", "yt-dlp"],
        "pip_name": "yt-dlp",
        "category": "download",
    },
}

CORE_PACKAGES = list(PACKAGES.keys())


# ================= 工具函数 =================

def run_pip_command(args: List[str]) -> tuple:
    """运行 pip 命令并返回结果。"""
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
    """获取所有已安装的 pip 包及其版本。"""
    success, output = run_pip_command(["list", "--format=freeze"])
    if not success:
        return {}
    packages = {}
    for line in output.strip().split("\n"):
        if "==" in line:
            name, version = line.strip().split("==", 1)
            packages[name.lower()] = version
    return packages


def check_pip_package(pip_name: str) -> tuple:
    """检查某个 pip 包是否已安装。返回 (installed, version)。"""
    installed = get_installed_packages()
    pip_name_lower = pip_name.lower()
    for installed_name, version in installed.items():
        if installed_name == pip_name_lower:
            return True, version
        if pip_name_lower == "openai-whisper" and "whisper" in installed_name:
            return True, version
    return False, None


def get_torch_info() -> tuple:
    """
    检测已安装的 PyTorch 版本及类型。
    返回 (installed, version, is_gpu)
    - installed: bool
    - version: str or None
    - is_gpu: bool (True=GPU版, False=CPU版)
    """
    is_installed, version = check_pip_package("torch")
    if not is_installed:
        return False, None, False

    # 尝试导入 torch 检测 GPU 支持
    try:
        import torch
        is_gpu = torch.cuda.is_available()
        return True, version, is_gpu
    except ImportError:
        return True, version, False
    except Exception:
        return True, version, False


# ================= 核心 API =================

def get_all_packages_status() -> List[Dict]:
    """获取所有依赖包的状态。"""
    installed = get_installed_packages()
    torch_installed, torch_version, torch_is_gpu = get_torch_info()
    result = []

    # 核心依赖包
    for pkg_id, meta in PACKAGES.items():
        is_installed, version = check_pip_package(meta["pip_name"])
        result.append({
            "id": pkg_id,
            "name": meta["name"],
            "description": meta["description"],
            "size_mb": meta["size_mb"],
            "required": meta["required"],
            "installed": is_installed,
            "version": version,
            "category": meta["category"],
        })

    # PyTorch（CPU 版检测）
    result.append({
        "id": "torch",
        "name": "PyTorch (CPU)",
        "description": "深度学习框架，CPU 版本（非 GPU 用户使用）",
        "size_mb": "~200MB",
        "required": True,
        "installed": torch_installed and not torch_is_gpu,
        "version": torch_version if not torch_is_gpu else None,
        "is_gpu_torch": False,
        "category": "core",
    })

    # PyTorch GPU 版（独立条目）
    result.append({
        "id": "torch-gpu",
        "name": "PyTorch (CUDA 12.4)",
        "description": "深度学习框架，NVIDIA GPU 专用（需要 NVIDIA 显卡 + CUDA 驱动）",
        "size_mb": "~200MB + GPU 驱动",
        "required": False,
        "installed": torch_installed and torch_is_gpu,
        "version": torch_version if torch_is_gpu else None,
        "is_gpu_torch": True,
        "cuda_url": "https://pytorch.org/get-started/locally/",
        "category": "optional",
    })

    return result


def install_package(pkg_id: str) -> tuple:
    """安装指定的包。"""
    if pkg_id == "torch-gpu":
        return _install_torch_gpu()

    if pkg_id not in PACKAGES and pkg_id not in ("torch", "torch-gpu"):
        return False, f"未知包: {pkg_id}"

    # torch (CPU) 走默认安装
    if pkg_id == "torch":
        is_installed, _, _ = get_torch_info()
        if is_installed:
            return True, "PyTorch 已安装"
        success, output = run_pip_command([
            "install", "torch", "torchvision", "torchaudio",
            "--index-url", "https://download.pytorch.org/whl/cpu"
        ])
        if success:
            return True, "PyTorch (CPU) 安装成功"
        return False, f"安装失败: {output[:200]}"

    meta = PACKAGES[pkg_id]
    is_installed, version = check_pip_package(meta["pip_name"])
    if is_installed:
        return True, f"{meta['name']} 已安装 (版本 {version})"

    success, output = run_pip_command(meta["install_args"])
    if success:
        return True, f"{meta['name']} 安装成功"
    return False, f"安装失败: {output[:200]}"


def _install_torch_gpu() -> tuple:
    """安装 PyTorch GPU 版本（自动卸载 CPU 版本）。"""
    torch_installed, torch_version, torch_is_gpu = get_torch_info()

    # 如果已经是 GPU 版本
    if torch_is_gpu:
        return True, f"PyTorch (CUDA) 已安装 (版本 {torch_version})"

    msgs = []

    # 卸载 CPU 版本
    if torch_installed:
        success, output = run_pip_command(["uninstall", "torch", "torchvision", "torchaudio", "-y"])
        if success:
            msgs.append("已卸载 CPU 版 PyTorch")
        else:
            msgs.append(f"卸载 CPU 版时出现警告: {output[:100]}")

    # 安装 GPU 版本（CUDA 12.4）
    success, output = run_pip_command([
        "install", "torch", "torchvision", "torchaudio",
        "--index-url", "https://download.pytorch.org/whl/cu124"
    ])

    if success:
        # 验证是否为 GPU 版本
        _, _, is_gpu = get_torch_info()
        if is_gpu:
            return True, "PyTorch (CUDA 12.4) 安装成功，GPU 加速已启用"
        return True, "PyTorch 安装完成（请重启应用后确认 GPU 加速）"
    return False, f"GPU 版本安装失败: {output[:200]}"


def install_core_packages() -> tuple:
    """一键安装所有核心依赖（不含 torch GPU 版）。"""
    results = []
    all_success = True

    # 先安装 torch CPU 版
    success, msg = install_package("torch")
    results.append({"id": "torch", "name": "PyTorch (CPU)", "success": success, "message": msg})
    if not success:
        all_success = False

    # 再安装其他核心包
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


def uninstall_package(pkg_id: str) -> tuple:
    """卸载指定的包。"""
    if pkg_id == "torch-gpu":
        # GPU 版就是 torch 本身
        return uninstall_package("torch")

    if pkg_id not in PACKAGES and pkg_id != "torch":
        return False, f"未知包: {pkg_id}"

    if pkg_id == "torch":
        is_installed, _, _ = get_torch_info()
        if not is_installed:
            return True, "PyTorch 未安装"
        success, output = run_pip_command(["uninstall", "torch", "torchvision", "torchaudio", "-y"])
        if success:
            return True, "PyTorch 已卸载"
        return False, f"卸载失败: {output[:200]}"

    meta = PACKAGES[pkg_id]
    is_installed, _ = check_pip_package(meta["pip_name"])
    if not is_installed:
        return True, f"{meta['name']} 未安装"

    success, output = run_pip_command(["uninstall", meta["pip_name"], "-y"])
    if success:
        return True, f"{meta['name']} 卸载成功"
    return False, f"卸载失败: {output[:200]}"
