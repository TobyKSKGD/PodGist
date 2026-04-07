#!/usr/bin/env python3
"""
PodGist 后端语法检查脚本。

检查 backend/ 目录下所有 .py 文件以及项目根目录 api.py 的语法。
使用 py_compile + compileall 进行编译时检查。

用法:
    python scripts/check_backend.py

Exit codes:
    0 - 所有文件语法检查通过
    1 - 存在语法错误
"""

import sys
import os
import py_compile
import compileall
import traceback

# 项目根目录（scripts/ 的父目录）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
API_FILE = os.path.join(PROJECT_ROOT, "api.py")

# electron/scripts/backend/ 目录（Mac/Windows 共享源码）
ELECTRON_BACKEND_DIR = os.path.join(PROJECT_ROOT, "electron", "scripts", "backend")


def check_file(file_path: str) -> bool:
    """
    对单个 .py 文件执行 py_compile 检查。

    参数:
        file_path: .py 文件路径

    返回:
        True = 检查通过，False = 存在语法错误
    """
    try:
        py_compile.compile(file_path, doraise=True, quiet=2)
        return True
    except py_compile.PyCompileError as e:
        print(f"Syntax error in: {file_path}", file=sys.stderr)
        print(f"  {e.msg}", file=sys.stderr)
        if e.lineno is not None:
            print(f"  Line {e.lineno}", file=sys.stderr)
        if e.text:
            print(f"  {e.text.rstrip()}", file=sys.stderr)
        return False


def collect_py_files(directory: str) -> list:
    """递归收集目录下所有 .py 文件。"""
    py_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".py"):
                py_files.append(os.path.join(root, file))
    return sorted(py_files)


def main() -> int:
    """主入口。返回 0=成功，1=失败。"""
    print("=== PodGist Backend Syntax Check ===")

    has_error = False

    # 1. 检查项目根目录 api.py
    if os.path.exists(API_FILE):
        print(f"Checking: {API_FILE}")
        if not check_file(API_FILE):
            has_error = True
    else:
        print(f"[WARN] api.py not found at {API_FILE}")

    # 2. 检查 backend/ 目录
    if os.path.exists(BACKEND_DIR):
        print(f"\nChecking backend/ directory: {BACKEND_DIR}")
        backend_files = collect_py_files(BACKEND_DIR)
        for f in backend_files:
            rel = os.path.relpath(f, PROJECT_ROOT)
            print(f"  Checking: {rel}")
            if not check_file(f):
                has_error = True
    else:
        print(f"[WARN] backend/ directory not found at {BACKEND_DIR}")

    # 3. 检查 electron/scripts/backend/ 目录
    if os.path.exists(ELECTRON_BACKEND_DIR):
        print(f"\nChecking electron/scripts/backend/ directory: {ELECTRON_BACKEND_DIR}")
        electron_files = collect_py_files(ELECTRON_BACKEND_DIR)
        for f in electron_files:
            rel = os.path.relpath(f, PROJECT_ROOT)
            print(f"  Checking: {rel}")
            if not check_file(f):
                has_error = True
    else:
        print(f"[WARN] electron/scripts/backend/ not found at {ELECTRON_BACKEND_DIR}")

    # 4. 使用 compileall 做二次验证（更严格的深度检查）
    print("\nRunning compileall validation...")
    if os.path.exists(BACKEND_DIR):
        # compileall 在 quiet=1 时只打印总结，quiet=2 完全静默
        ok = compileall.compile_dir(
            BACKEND_DIR,
            force=True,
            quiet=1,
            workers=1,
        )
        if not ok:
            print("[WARN] compileall reported failures in backend/", file=sys.stderr)
            # compileall 返回值：True=成功，False=失败（注意和 exit code 语义不同）

    if has_error:
        print("\n=== FAILED: Backend syntax check did not pass ===", file=sys.stderr)
        return 1
    else:
        print("\n=== Backend syntax check passed ===")
        return 0


if __name__ == "__main__":
    sys.exit(main())
