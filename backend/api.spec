# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for PodGist backend (云端 ASR 版)
# 用于在 Windows Runner 上构建 Windows 后端可执行目录
#
# 构建命令: pyinstaller --noconsole --onedir backend/api.spec
# 产物目录: backend/dist/api/

import os
import sys

# SPECPATH 指向 spec 文件所在目录（backend/）
# project_root 是 SPECPATH 的上一级（项目根目录）
project_root = os.path.dirname(os.path.abspath(SPECPATH))

block_cipher = None

a = Analysis(
    [os.path.join(project_root, 'backend', 'start_electron.py')],
    pathex=[project_root],
    binaries=[],
    datas=[
        # 打入 Python 源码目录（backend/ 下所有 .py 文件）
        (os.path.join(project_root, 'backend'), 'backend'),
        (os.path.join(project_root, 'api.py'), '.'),
    ],
    hiddenimports=[
        # === FastAPI / Uvicorn 核心 ===
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.config',
        'fastapi',
        'fastapi.responses',
        'fastapi.middleware.cors',
        'starlette',
        'starlette.responses',
        'starlette.middleware',
        'starlette.middleware.cors',
        # === Pydantic ===
        'pydantic',
        'pydantic.deprecated',
        'pydantic.deprecated.base',
        'pydantic.v1',
        'pydantic_settings',
        # === SSE ===
        'sse_starlette',
        'sse_starlette.sse',
        # === 核心依赖 ===
        'dashscope',
        'httpx',
        'requests',
        'python_dotenv',
        'python_multipart',
        'jinja2',
        'itsdangerous',
        'sniffio',
        'pydub',
        # === RAG / 向量数据库 ===
        'chromadb',
        'chromadb.api',
        'chromadb.config',
        'chromadb.client',
        'chromadb.collection',
        'chromadb.rust_bindings',
        'grpcio',
        'opentelemetry',
        'opentelemetry.api',
        'opentelemetry.sdk',
        'opentelemetry.exporter.otlp.proto.grpc',
        # === 下载器 ===
        'yt_dlp',
        'yt_dlp.utils',
        'yt_dlp.compat',
        # === 其他工具 ===
        'tokenizers',
        'numpy',
        'json',
        'sqlite3',
        'hashlib',
        'datetime',
        'uuid',
        'struct',
        'asyncio',
    ],
    win_no_prefer_redirects=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='api-engine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='api',
)

import shutil
import os
# 将 dist/api 复制到项目根目录的 dist/api（供 electron-builder 使用）
src = os.path.join(project_root, 'backend', 'dist', 'api')
dst = os.path.join(project_root, 'dist', 'api')
if os.path.exists(src):
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copytree(src, dst)
    print(f"Copied {src} -> {dst}")

