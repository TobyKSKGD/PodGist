import os
import platform

def get_ffmpeg_path():
    """获取 FFmpeg 可执行文件路径

    在 Electron 打包环境下，从 resources/ffmpeg/ 目录返回正确的 FFmpeg 路径。
    在开发环境下，返回 'ffmpeg'（从 PATH 查找）。
    """
    resources_path = os.environ.get('PODGIST_RESOURCES_PATH')
    if resources_path:
        if platform.system() == 'Windows':
            return os.path.join(resources_path, 'ffmpeg', 'ffmpeg.exe')
        else:
            return os.path.join(resources_path, 'ffmpeg', 'ffmpeg')
    return 'ffmpeg'  # Fallback to PATH


def get_ffprobe_path():
    """获取 FFprobe 可执行文件路径

    在 Electron 打包环境下，从 resources/ffmpeg/ 目录返回正确的 FFprobe 路径。
    在开发环境下，返回 'ffprobe'（从 PATH 查找）。
    """
    resources_path = os.environ.get('PODGIST_RESOURCES_PATH')
    if resources_path:
        if platform.system() == 'Windows':
            return os.path.join(resources_path, 'ffmpeg', 'ffprobe.exe')
        else:
            return os.path.join(resources_path, 'ffmpeg', 'ffprobe')
    return 'ffprobe'  # Fallback to PATH


def setup_pydub_paths():
    """配置 pydub 的 ffmpeg/ffprobe 路径（在 import pydub 之前调用）"""
    ffmpeg_path = get_ffmpeg_path()
    ffprobe_path = get_ffprobe_path()
    os.environ['FFMPEG_BINARY'] = ffmpeg_path
    os.environ['FFPROBE_BINARY'] = ffprobe_path

# 自动设置 pydub 路径（ Electron 打包环境）
setup_pydub_paths()
