"""跨平台子进程启动参数。"""

import os
import subprocess


def hidden_subprocess_kwargs() -> dict:
    """Windows 下禁止控制台子进程创建可见黑框，其他平台不添加参数。"""
    if os.name != "nt":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }
