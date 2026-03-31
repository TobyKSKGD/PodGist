#!/usr/bin/env python3
"""
PodGist Electron 专用后端入口脚本

用于 Electron 桌面应用中启动 FastAPI 后端服务。
接收命令行参数，配置路径后启动 uvicorn。
"""

import sys
import os
import argparse

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
        '--port',
        type=int,
        default=8000,
        help='服务端口'
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

    # 启动 FastAPI 服务
    import uvicorn

    print(f"[start_electron] 启动后端服务 on port {args.port}...")

    uvicorn.run(
        "api:app",
        host="127.0.0.1",
        port=args.port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    main()
