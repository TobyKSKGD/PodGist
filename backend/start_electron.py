#!/usr/bin/env python3
"""
PodGist Electron 专用后端入口脚本

用于 Electron 桌面应用中启动 FastAPI 后端服务。
接收命令行参数，配置路径后启动 uvicorn。
"""

import sys
import os
import argparse
import platform
import multiprocessing

# 将项目根目录添加到 Python 路径
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)  # backend/ 的父目录就是项目根目录
sys.path.insert(0, project_root)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='PodGist API Server (Electron Mode)')
    parser.add_argument(
        '--data-dir',
        type=str,
        default=None,
        help='用户数据目录（archives, temp_audio, config, .env）'
    )
    parser.add_argument(
        '--model-dir',
        type=str,
        default=None,
        help='AI 模型目录路径'
    )
    parser.add_argument(
        '--resources-path',
        type=str,
        default=None,
        help='Electron 资源目录路径（用于定位 FFmpeg 等资源）'
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # 设置环境变量供其他模块使用
    if args.data_dir:
        os.environ['PODGIST_DATA_DIR'] = args.data_dir
        print(f"[start_electron] 用户数据目录: {args.data_dir}")

    if args.model_dir:
        os.environ['PODGIST_MODEL_DIR'] = args.model_dir
        print(f"[start_electron] 模型目录: {args.model_dir}")

    if args.resources_path:
        os.environ['PODGIST_RESOURCES_PATH'] = args.resources_path
        print(f"[start_electron] 资源目录: {args.resources_path}")

        # 将 python_venv 的 bin 目录加入到 PATH（yt-dlp 等系统命令需要）
        venv_bin = os.path.join(args.resources_path, 'python_venv', 'bin')
        if platform.system() == 'Windows':
            venv_bin = os.path.join(args.resources_path, 'python_venv', 'Scripts')
        if os.path.isdir(venv_bin):
            os.environ['PATH'] = venv_bin + os.pathsep + os.environ.get('PATH', '')
            print(f"[start_electron] 已将 venv bin 加入 PATH: {venv_bin}")

    # 初始化 pydub 的 ffmpeg/ffprobe 路径
    from backend import setup_pydub_paths
    setup_pydub_paths()

    # 启动 FastAPI 服务
    import uvicorn

    print(f"[start_electron] 启动后端服务 on port 8000...")

    uvicorn.run(
        "api:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    # Windows 专用：防止 PyTorch/Uvicorn 多进程无限递归启动
    # 必须在所有业务逻辑之前调用，且放在 if __name__ == '__main__' 内
    multiprocessing.freeze_support()
    main()
