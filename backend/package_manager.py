"""
依赖管理模块（远程 ASR 版）

本版本移除了所有本地模型包管理（torch/whisper/funasr/modelscope），
改为纯远程 API 模式，依赖仅剩 dashscope SDK 等轻量级包。
"""

import subprocess
import sys
import os
from typing import Dict, List, Literal
from backend.subprocess_utils import hidden_subprocess_kwargs

# ================= 依赖包元数据（仅剩基础依赖）=================

PACKAGES: Dict[str, Dict] = {
    "dashscope": {
        "name": "DashScope SDK",
        "description": "阿里云 DashScope API Python SDK",
        "required": True,
        "install_args": ["install", "-U", "dashscope"],
        "pip_name": "dashscope",
        "category": "core",
    },
}


# ================= 工具函数 =================

def run_pip_command(args: List[str]) -> tuple:
    """运行 pip 命令并返回结果。"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip"] + args,
            capture_output=True,
            text=True,
            timeout=300,
            **hidden_subprocess_kwargs(),
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
    return False, None


# ================= 核心 API =================

def get_all_packages_status() -> List[Dict]:
    """获取所有依赖包的状态。"""
    result = []

    for pkg_id, meta in PACKAGES.items():
        is_installed, version = check_pip_package(meta["pip_name"])
        result.append({
            "id": pkg_id,
            "name": meta["name"],
            "description": meta["description"],
            "size_mb": "~10MB",
            "required": meta["required"],
            "installed": is_installed,
            "version": version,
            "category": meta["category"],
        })

    return result


def install_package(pkg_id: str) -> tuple:
    """安装指定的包。"""
    if pkg_id not in PACKAGES:
        return False, f"未知包: {pkg_id}"

    meta = PACKAGES[pkg_id]
    is_installed, version = check_pip_package(meta["pip_name"])
    if is_installed:
        return True, f"{meta['name']} 已安装 (版本 {version})"

    success, output = run_pip_command(meta["install_args"])
    if success:
        return True, f"{meta['name']} 安装成功"
    return False, f"安装失败: {output[:200]}"


def install_core_packages() -> tuple:
    """一键安装所有核心依赖。"""
    results = []
    all_success = True

    for pkg_id in PACKAGES:
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
    if pkg_id not in PACKAGES:
        return False, f"未知包: {pkg_id}"

    meta = PACKAGES[pkg_id]
    is_installed, _ = check_pip_package(meta["pip_name"])
    if not is_installed:
        return True, f"{meta['name']} 未安装"

    success, output = run_pip_command(["uninstall", meta["pip_name"], "-y"])
    if success:
        return True, f"{meta['name']} 卸载成功"
    return False, f"卸载失败: {output[:200]}"
