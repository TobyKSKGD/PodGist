import os
import subprocess
import yt_dlp
import re
import requests
from urllib.parse import urlparse


class AudioDownloader:
    """
    在线音频/视频下载器，支持从 Bilibili 等平台提取音频。

    使用 yt-dlp 进行下载，配置为仅提取最高音质音频流，
    并自动转换为 MP3 格式。
    """

    def __init__(self, save_dir="temp_audio"):
        """
        初始化下载器。

        参数:
            save_dir (str): 音频保存目录
        """
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def sanitize_filename(self, filename):
        """
        清理文件名，移除无效字符。

        参数:
            filename (str): 原始文件名

        返回:
            str: 清理后的安全文件名
        """
        # 移除 Windows/macOS/Linux 文件名中的非法字符
        filename = re.sub(r'[\\/*?:"<>|]', "", filename)
        # 移除前后空格
        filename = filename.strip()
        # 限制文件名长度（保留足够空间给扩展名）
        if len(filename) > 200:
            filename = filename[:200]
        return filename

    def download_bilibili_audio(self, url, cookies_path=None):
        """
        从 Bilibili 下载视频并提取音频。

        参数:
            url (str): Bilibili 视频链接
            cookies_path (str, optional): cookies 文件路径，用于下载大会员内容

        返回:
            dict: 包含以下键的字典:
                - success (bool): 是否成功
                - file_path (str): 下载的音频文件路径（成功时）
                - title (str): 视频标题（成功时）
                - error (str): 错误信息（失败时）
        """
        # 先获取视频信息以获取标题
        ydl_opts_info = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }

        # 如果提供了 cookies，添加到配置中
        if cookies_path and os.path.exists(cookies_path):
            ydl_opts_info['cookiefile'] = cookies_path

        try:
            # 获取视频信息
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', 'unknown')
                video_title = self.sanitize_filename(video_title)
        except Exception as e:
            return {
                'success': False,
                'error': f"获取视频信息失败: {str(e)}"
            }

        # 下载音频的配置
        output_template = os.path.join(self.save_dir, f"{video_title}.%(ext)s")

        ydl_opts = {
            'format': 'bestaudio/best',
            # 音频提取选项
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [],
        }

        # 添加 cookies 支持（如果提供）
        if cookies_path and os.path.exists(cookies_path):
            ydl_opts['cookiefile'] = cookies_path

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # 查找下载的 MP3 文件
            mp3_path = os.path.join(self.save_dir, f"{video_title}.mp3")

            if os.path.exists(mp3_path):
                return {
                    'success': True,
                    'file_path': mp3_path,
                    'title': video_title
                }
            else:
                # 检查是否有其他格式的文件
                for ext in ['m4a', 'webm', 'aac', 'flac']:
                    alt_path = os.path.join(self.save_dir, f"{video_title}.{ext}")
                    if os.path.exists(alt_path):
                        # 尝试转换为 MP3
                        try:
                            mp3_path = alt_path.replace(f".{ext}", ".mp3")
                            subprocess.run([
                                'ffmpeg', '-i', alt_path,
                                '-codec:a', 'libmp3lame',
                                '-q:a', '2', mp3_path,
                                '-y'
                            ], capture_output=True, check=True)
                            os.remove(alt_path)
                            return {
                                'success': True,
                                'file_path': mp3_path,
                                'title': video_title
                            }
                        except Exception:
                            pass

                return {
                    'success': False,
                    'error': "音频文件下载失败或未找到"
                }

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "HTTP Error 403" in error_msg:
                return {
                    'success': False,
                    'error': "下载失败：该视频可能需要大会员权限或视频已被删除"
                }
            elif "HTTP Error 404" in error_msg:
                return {
                    'success': False,
                    'error': "下载失败：视频不存在或链接无效"
                }
            else:
                return {
                    'success': False,
                    'error': f"下载失败: {error_msg}"
                }
        except Exception as e:
            return {
                'success': False,
                'error': f"下载过程出错: {str(e)}"
            }


def download_audio_from_url(url, save_dir="temp_audio", cookies_path=None):
    """
    从在线 URL 下载音频文件的便捷函数。

    参数:
        url (str): 在线音频/视频 URL（如 Bilibili 链接）
        save_dir (str): 保存目录，默认为 'temp_audio'
        cookies_path (str, optional): cookies 文件路径

    返回:
        dict: 包含 success, file_path, title, error 键的字典
    """
    downloader = AudioDownloader(save_dir=save_dir)
    return downloader.bilibili_audio(url, cookies_path=cookies_path)


# 为保持向后兼容，保留原函数名
def download_and_convert(url, save_dir="temp_audio", cookies_path=None):
    """
    从 URL 下载并转换音频的向后兼容函数。

    参数:
        url (str): 视频 URL
        save_dir (str): 保存目录
        cookies_path (str, optional): cookies 路径

    返回:
        dict: 下载结果
    """
    downloader = AudioDownloader(save_dir=save_dir)
    return downloader.download_bilibili_audio(url, cookies_path=cookies_path)


# ================= 小宇宙播客抓取器 =================

def detect_platform(url):
    """
    根据 URL 识别播客平台。

    参数:
        url (str): 播客链接

    返回:
        str: 平台标识符，如 "xiaoyuzhou", "bilibili", "unknown"
    """
    url = url.lower()
    if "xiaoyuzhoufm.com" in url:
        return "xiaoyuzhou"
    elif "bilibili.com" in url:
        return "bilibili"
    else:
        return "unknown"


def download_xiaoyuzhou_audio(url, save_dir="temp_audio"):
    """
    从小宇宙播客单集链接下载音频。

    参数:
        url (str): 小宇宙分享链接（如 https://xiaoyuzhoufm.com/episode/xxx）
        save_dir (str): 保存目录

    返回:
        dict: 包含以下键的字典:
            - success (bool): 是否成功
            - file_path (str): 下载的音频文件路径（成功时）
            - title (str): 播客标题（成功时）
            - error (str): 错误信息（失败时）
    """
    os.makedirs(save_dir, exist_ok=True)

    # 检查 URL 格式
    if detect_platform(url) != "xiaoyuzhou":
        return {
            'success': False,
            'error': "非有效的小宇宙分享链接，请检查链接是否正确"
        }

    # 伪装浏览器 User-Agent
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }

    try:
        # 请求网页
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {
                'success': False,
                'error': f"请求失败，状态码: {response.status_code}"
            }

        html_content = response.text

        # 提取音频直链 - 查找 <meta property="og:audio" content="...">
        audio_url = None
        title = "未知标题"

        import re

        # 匹配 og:audio
        audio_match = re.search(r'<meta\s+(?:property|name)="og:audio"\s+content="([^"]+)"', html_content)
        if audio_match:
            audio_url = audio_match.group(1)
        else:
            # 备选：查找 data-src 属性
            audio_match = re.search(r'data-src="([^"]+\.mp3)"', html_content)
            if audio_match:
                audio_url = audio_match.group(1)

        # 提取标题 - 查找 <meta property="og:title" content="...">
        title_match = re.search(r'<meta\s+(?:property|name)="og:title"\s+content="([^"]+)"', html_content)
        if title_match:
            title = title_match.group(1)
        else:
            # 备选：查找 <title>
            title_match = re.search(r'<title>([^<]+)</title>', html_content)
            if title_match:
                title = title_match.group(1)

        if not audio_url:
            return {
                'success': False,
                'error': "页面结构已变更，无法解析音频链接，请等待开发者更新"
            }

        # 清理标题
        title = re.sub(r'[\\/*?:"<>|]', "", title).strip()
        if len(title) > 200:
            title = title[:200]

        # 下载音频文件
        print(f"正在下载音频: {title}")
        print(f"音频链接: {audio_url}")

        # 流式下载
        audio_response = requests.get(audio_url, headers=headers, timeout=60, stream=True)
        if audio_response.status_code != 200:
            return {
                'success': False,
                'error': f"音频下载失败，状态码: {audio_response.status_code}"
            }

        # 根据 Content-Type 确定文件扩展名
        content_type = audio_response.headers.get('Content-Type', '').lower()
        if 'mpeg' in content_type or 'mp3' in content_type:
            ext = '.mp3'
        elif 'm4a' in content_type or 'mp4' in content_type:
            ext = '.m4a'
        elif 'audio/aac' in content_type:
            ext = '.aac'
        else:
            # 默认先保存为 .m4a，后续可以转换
            ext = '.m4a'

        # 保存文件
        file_path = os.path.join(save_dir, f"{title}{ext}")
        temp_path = file_path  # 初始保存路径

        with open(file_path, 'wb') as f:
            for chunk in audio_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        # 如果是 m4a/aac 格式，转换为 mp3
        if ext in ['.m4a', '.aac'] and os.path.exists(file_path):
            try:
                import subprocess
                mp3_path = file_path.replace(ext, '.mp3')
                subprocess.run([
                    'ffmpeg', '-i', file_path,
                    '-codec:a', 'libmp3lame',
                    '-q:a', '2', mp3_path,
                    '-y'
                ], capture_output=True, check=True)
                os.remove(file_path)  # 删除原文件
                file_path = mp3_path  # 使用转换后的文件
            except Exception as e:
                print(f"格式转换失败，保持原格式: {e}")

        # 验证文件
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return {
                'success': True,
                'file_path': file_path,
                'title': title
            }
        else:
            return {
                'success': False,
                'error': "音频文件保存失败"
            }

    except requests.exceptions.Timeout:
        return {
            'success': False,
            'error': "网络连接超时，请检查网络或稍后再试"
        }
    except requests.exceptions.ConnectionError:
        return {
            'success': False,
            'error': "网络连接失败，请检查网络"
        }
    except Exception as e:
        return {
            'success': False,
            'error': f"下载过程出错: {str(e)}"
        }


def route_and_download(url, save_dir="temp_dir", cookies_path=None):
    """
    根据 URL 类型智能路由并下载音频。

    参数:
        url (str): 在线链接
        save_dir (str): 保存目录
        cookies_path (str, optional): cookies 文件路径

    返回:
        dict: 下载结果
    """
    platform = detect_platform(url)

    if platform == "xiaoyuzhou":
        return download_xiaoyuzhou_audio(url, save_dir)
    elif platform == "bilibili":
        downloader = AudioDownloader(save_dir=save_dir)
        return downloader.download_bilibili_audio(url, cookies_path)
    else:
        return {
            'success': False,
            'error': f"不支持的平台，当前仅支持小宇宙和 Bilibili"
        }

