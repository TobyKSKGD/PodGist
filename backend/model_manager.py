"""
模型管理模块（远程 ASR 版）

本版本移除了所有本地模型下载管理，
改为提供 DashScope ASR 的 API 配置信息。

本地模型相关代码已移至 transcriber_local_backup.py。
"""

import os
from typing import Dict, List, Optional

# ================= 远程 ASR 模型信息 =================

ASR_MODEL_INFO = {
    "id": "qwen3-asr-flash",
    "name": "Qwen3-ASR-Flash",
    "description": "阿里云 DashScope 语音识别 API，云端运行，无需本地配置",
    "version": "2026-02-10",
    "features": ["时间轴对齐", "中文优化", "长音频分片"],
    "api_type": "cloud"
}


def get_all_models_status() -> List[Dict]:
    """
    返回所有模型的状态（远程 ASR 版）。
    仅返回 DashScope ASR 信息，不再列出本地 Whisper/SenseVoice 模型。
    """
    return [
        {
            "id": ASR_MODEL_INFO["id"],
            "name": ASR_MODEL_INFO["name"],
            "description": ASR_MODEL_INFO["description"],
            "status": "ready",
            "size_mb": "云端运行",
            "is_local": False,
            "features": ASR_MODEL_INFO["features"],
        }
    ]


def get_manual_download_info(model_name: str) -> Optional[Dict]:
    """
    返回模型的手动下载信息（远程 ASR 版）。
    远程 API 无需手动下载，返回提示信息。
    """
    return {
        "model_name": model_name,
        "message": "使用 DashScope ASR API，无需下载模型",
        "api_key_needed": True,
        "setup_url": "https://dashscope.console.aliyun.com/apiKey"
    }


def get_model_path(model_name: str) -> Optional[str]:
    """
    返回模型的本地路径（远程 ASR 版）。
    始终返回 None，因为使用云端 API。
    """
    return None


def download_model(model_name: str, progress_callback=None) -> Dict:
    """
    下载模型（远程 ASR 版）。
    实际上不需要下载，返回成功信息。
    """
    return {
        "success": True,
        "model_name": model_name,
        "message": "DashScope ASR 使用云端服务，无需下载模型"
    }
