# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for PodGist backend
# 用于在 Windows Runner 上构建 Windows 后端可执行目录
#
# 构建命令: pyinstaller --noconsole --onedir backend/api.spec
# 产物目录: backend/dist/start_electron/

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
        # === FastAPI 核心 ===
        'fastapi',
        'fastapi.responses',
        'fastapi.middleware.cors',
        'starlette',
        'starlette.responses',
        'starlette.middleware',
        'starlette.middleware.cors',
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
        # === Pydantic ===
        'pydantic',
        'pydantic.deprecated',
        'pydantic.deprecated.base',
        'pydantic.deprecated.class_validators',
        'pydantic.v1',
        'pydantic_settings',
        # === 核心依赖 ===
        'openai',
        'httpx',
        'requests',
        'python_dotenv',
        'python_multipart',
        'jinja2',
        'itsdangerous',
        'sniffio',
        # === AI / 语音 ===
        'whisper',
        'torch',
        'torchaudio',
        'modelscope',
        'modelscope.pipelines',
        'modelscope.pipelines.builder',
        'modelscope.utils',
        'modelscope.utils.constant',
        'modelscope.utils.download',
        'funaudio',
        'funasr',
        'funasr-pipeline',
        'funasr.utils',
        'funasr.utils.download',
        'funasr.bin',
        'pydub',
        # === RAG / 向量 ===
        'chromadb',
        'chromadb.api',
        'chromadb.config',
        'chromadb.client',
        'chromadb.collection',
        'sentence_transformers',
        'sentence_transformers.cross_encoder',
        # === 下载器 ===
        'yt_dlp',
        'yt_dlp.utils',
        'yt_dlp.compat',
        # === 数据库 ===
        'sqlite3',
        'json',
        'hashlib',
        'datetime',
        'uuid',
        # === 其他 ===
        'numpy',
        'nvidia',
        'nvidia.cudnn',
        'nvidia.cuda_runtime',
        'nvidia.cuda_runtime.driver',
        'nvidia.cuda_runtime.events',
        'nvidia.cufft',
        'nvidia.curand',
        'nvidia.cublas',
        'nvidia.cusolver',
        'nvidia.cusparse',
        'nvidia.nccl',
        'triton',
        'safetensors',
        'tokenizers',
        'sse_starlette',
        'sse_starlette.sse',
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
    exclude=['matplotlib', 'tkinter', 'PyQt5'],  # 排除不需要的巨大模块
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
