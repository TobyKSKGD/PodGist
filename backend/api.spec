# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for PodGist backend (Windows / onedir)

import os
import sys


# SPECPATH 指向 spec 文件所在目录（backend/）
# 取其上一级作为项目根目录
project_root = os.path.dirname(os.path.abspath(SPECPATH))


block_cipher = None


# -----------------------------
# 显式收集 Windows 运行时 DLL
# 重点是 VC runtime，避免 python311.dll 依赖缺失
# -----------------------------
candidate_dirs = []

for p in {
    os.path.dirname(sys.executable),
    getattr(sys, "base_prefix", ""),
    os.path.join(os.path.dirname(sys.executable), "DLLs"),
    os.path.join(getattr(sys, "base_prefix", ""), "DLLs"),
}:
    if p and os.path.isdir(p):
        candidate_dirs.append(p)

system_root = os.environ.get("SystemRoot")
if system_root:
    system32 = os.path.join(system_root, "System32")
    if os.path.isdir(system32):
        candidate_dirs.append(system32)

extra_runtime_binaries = []
for dll_name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
    found = False
    for base in candidate_dirs:
        dll_path = os.path.join(base, dll_name)
        if os.path.exists(dll_path):
            extra_runtime_binaries.append((dll_path, "."))
            found = True
            break
    if not found:
        print(f"WARNING: runtime DLL not found during spec evaluation: {dll_name}")

print("Collected runtime DLLs:", [os.path.basename(x[0]) for x in extra_runtime_binaries])


a = Analysis(
    [os.path.join(project_root, "backend", "start_electron.py")],
    pathex=[project_root],
    binaries=extra_runtime_binaries,
    workpath='build/',
    datas=[
        (os.path.join(project_root, "backend"), "backend"),
        (os.path.join(project_root, "api.py"), "."),
    ],
    hiddenimports=[
        # === FastAPI / Uvicorn ===
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.config",
        "fastapi",
        "fastapi.responses",
        "fastapi.middleware.cors",
        "starlette",
        "starlette.responses",
        "starlette.middleware",
        "starlette.middleware.cors",

        # === Pydantic ===
        "pydantic",
        "pydantic.v1",
        "pydantic_core",
        "pydantic_settings",
        "annotated_types",

        # === SSE ===
        "sse_starlette",
        "sse_starlette.sse",

        # === 核心依赖 ===
        "dashscope",
        "httpx",
        "requests",
        "dotenv",
        "multipart",
        "jinja2",
        "itsdangerous",
        "sniffio",
        "pydub",

        # === RAG / 向量数据库 ===
        "chromadb",
        "chromadb.api",
        "chromadb.config",
        "chromadb.client",
        "chromadb.collection",
        "chromadb.rust_bindings",
        "grpc",
        "grpc._cython.cygrpc",
        "opentelemetry",
        "opentelemetry.api",
        "opentelemetry.sdk",
        "opentelemetry.exporter.otlp.proto.grpc",

        # === 下载器 ===
        "yt_dlp",
        "yt_dlp.utils",
        "yt_dlp.compat",

        # === 其他工具 ===
        "tokenizers",
        "numpy",
        "json",
        "sqlite3",
        "hashlib",
        "datetime",
        "uuid",
        "struct",
        "asyncio",
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
    name="api-engine",
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
    name="api",
)
