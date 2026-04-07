import os
import platform as platform_sys
import subprocess
import yt_dlp
import re
import requests
import threading
import sys
from urllib.parse import urlparse

# 延迟导入 get_ffmpeg_path，兼容开发环境和 electron 打包环境
def _get_ffmpeg_path_impl():
    """自己实现 ffmpeg 路径查找，避免循环依赖。"""
    resources_path = os.environ.get('PODGIST_RESOURCES_PATH')
    if resources_path:
        if platform_sys.system() == 'Windows':
            return os.path.join(resources_path, 'ffmpeg', 'ffmpeg.exe')
        return os.path.join(resources_path, 'ffmpeg', 'ffmpeg')
    return 'ffmpeg'

try:
    from backend import get_ffmpeg_path
except ImportError:
    # electron 打包后，backend 在 app.asar.unpacked/backend/，
    # 尝试把 backend 的 parent 目录加入 path 后再导入
    _parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    try:
        from backend import get_ffmpeg_path
    except ImportError:
        # 最后 fallback：使用本地实现
        get_ffmpeg_path = _get_ffmpeg_path_impl


# ================= 统一 yt-dlp 下载 helpers =================

def _sanitize_title(title):
    """清理标题，移除 Windows/macOS/Linux 文件名非法字符。"""
    title = re.sub(r'[\\/*?:"<>|]', "", title)
    title = title.strip()
    if len(title) > 200:
        title = title[:200]
    return title


def _get_ffmpeg_dir():
    """获取 ffmpeg 所在目录，用于传给 yt-dlp ffmpeg_location。"""
    ffmpeg_path = get_ffmpeg_path()
    return os.path.dirname(ffmpeg_path)


def extract_info_with_ytdlp(url, cookies_path=None):
    """
    使用 yt_dlp.YoutubeDL API 提取视频/音频信息。

    参数:
        url (str): 目标 URL
        cookies_path (str, optional): cookies 文件路径

    返回:
        dict: {"success": bool, "info": dict, "error": str}
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {'success': True, 'info': info, 'error': None}
    except yt_dlp.utils.DownloadError as e:
        return {'success': False, 'info': None, 'error': f"获取信息失败: {str(e)}"}
    except Exception as e:
        return {'success': False, 'info': None, 'error': f"获取信息出错: {str(e)}'}


def download_audio_with_ytdlp(url, save_dir, title=None, prefer_m4a=False,
                               cookies_path=None, timeout=300):
    """
    使用 yt_dlp.YoutubeDL API 下载并转换音频。

    参数:
        url (str): 目标 URL
        save_dir (str): 保存目录
        title (str, optional): 指定标题（会自动 sanitize）
        prefer_m4a (bool): True=保留 m4a，False=转换为 mp3
        cookies_path (str, optional): cookies 文件路径
        timeout (int): 下载超时（秒），默认 5 分钟

    返回:
        dict: {"success": bool, "file_path": str, "title": str, "error": str, "platform": str}
    """
    os.makedirs(save_dir, exist_ok=True)
    ffmpeg_dir = _get_ffmpeg_dir()

    # 如果没指定标题，先提取
    if title is None:
        info_result = extract_info_with_ytdlp(url, cookies_path=cookies_path)
        if not info_result['success']:
            return {
                'success': False,
                'file_path': None,
                'title': None,
                'error': info_result['error'],
                'platform': None
            }
        raw_title = info_result['info'].get('title', 'audio')
        title = _sanitize_title(raw_title)
    else:
        title = _sanitize_title(title)

    print(f"[Downloader] 开始下载: {title}")

    output_template = os.path.join(save_dir, f"{title}.%(ext)s")

    postprocessors = []
    if prefer_m4a:
        postprocessors.append({
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'm4a',
            'preferredquality': '192',
        })
    else:
        postprocessors.append({
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        })

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'quiet': False,
        'no_warnings': False,
        'socket_timeout': 30,
        'retries': 3,
        'postprocessors': postprocessors,
        'ffmpeg_location': ffmpeg_dir,
    }
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path

    download_error = [None]

    def _do_download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            download_error[0] = e

    download_thread = threading.Thread(target=_do_download)
    download_thread.daemon = True
    download_thread.start()
    download_thread.join(timeout=timeout)

    if download_thread.is_alive():
        return {
            'success': False,
            'file_path': None,
            'title': title,
            'error': f"下载超时（{timeout}秒），可能网络问题或内容无法访问",
            'platform': None
        }

    if download_error[0]:
        error_msg = str(download_error[0])
        if "HTTP Error 403" in error_msg or "403" in error_msg:
            return {
                'success': False, 'file_path': None, 'title': title,
                'error': "下载失败：该内容可能需要 VIP 权限或已被删除", 'platform': None
            }
        elif "HTTP Error 404" in error_msg or "404" in error_msg:
            return {
                'success': False, 'file_path': None, 'title': title,
                'error': "下载失败：内容不存在或链接无效", 'platform': None
            }
        else:
            return {
                'success': False, 'file_path': None, 'title': title,
                'error': f"下载失败: {error_msg}", 'platform': None
            }

    # 查找下载的文件
    exts = ['.m4a', '.mp3', '.webm', '.aac', '.flac'] if prefer_m4a else ['.mp3', '.m4a', '.webm', '.aac', '.flac']
    for ext in exts:
        file_path = os.path.join(save_dir, f"{title}.{ext}")
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            # 如果是 m4a/aac 等非 mp3 格式，且 prefer_m4a=False，尝试转 mp3
            if not prefer_m4a and ext != '.mp3':
                mp3_path = os.path.join(save_dir, f"{title}.mp3")
                try:
                    result = subprocess.run([
                        get_ffmpeg_path(), '-i', file_path,
                        '-codec:a', 'libmp3lame', '-q:a', '2', mp3_path, '-y'
                    ], capture_output=True, text=True, timeout=60)
                    if result.returncode == 0:
                        os.remove(file_path)
                        file_path = mp3_path
                        print(f"[Downloader] 转码完成: {title}")
                    else:
                        print(f"[Downloader] FFmpeg 转码失败: {result.stderr[:200]}")
                        # 回退：保留原格式
                except subprocess.TimeoutExpired:
                    return {
                        'success': False, 'file_path': None, 'title': title,
                        'error': "音频格式转换超时", 'platform': None
                    }
                except Exception as e:
                    print(f"[Downloader] 转码出错: {e}")

            return {
                'success': True,
                'file_path': file_path,
                'title': title,
                'error': None,
                'platform': None
            }

    return {
        'success': False,
        'file_path': None,
        'title': title,
        'error': "音频文件下载失败或未找到",
        'platform': None
    }


# ================= AudioDownloader =================

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
        return _sanitize_title(filename)

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
                - platform (str): "bilibili"
        """
        result = download_audio_with_ytdlp(
            url=url,
            save_dir=self.save_dir,
            prefer_m4a=False,
            cookies_path=cookies_path,
            timeout=300
        )
        result['platform'] = 'bilibili'
        return result


def download_audio_from_url(url, save_dir="temp_audio", cookies_path=None):
    """
    从在线 URL 下载音频文件的便捷函数。

    参数:
        url (str): 在线音频/视频 URL（如 Bilibili 链接）
        save_dir (str): 保存目录，默认为 'temp_audio'
        cookies_path (str, optional): cookies 文件路径

    返回:
        dict: 包含 success, file_path, title, error, platform 键的字典
    """
    downloader = AudioDownloader(save_dir=save_dir)
    return downloader.download_bilibili_audio(url, cookies_path=cookies_path)


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
        url (str): 播客链接（可能包含分享文案）

    返回:
        str: 平台标识符，如 "xiaoyuzhou", "bilibili", "netease", "ximalaya", "applepodcasts", "unknown"
    """
    url = url.lower()
    if "xiaoyuzhoufm.com" in url:
        return "xiaoyuzhou"
    elif "bilibili.com" in url:
        return "bilibili"
    elif "163cn.tv" in url or "music.163.com" in url:
        return "netease"
    elif "xima.tv" in url or "ximalaya.com" in url:
        return "ximalaya"
    elif "podcasts.apple.com" in url:
        return "applepodcasts"
    else:
        return "unknown"


def parse_netease_url(raw_text):
    """
    智能嗅探并净化网易云播客链接（终极版：支持动态解包短链）

    参数:
        raw_text (str): 用户分享的原始文本（可能包含分享文案）

    返回:
        str or None: 净化后的标准播客 URL，失败返回 None
    """
    # 场景 1: 嗅探并解包手机端短链 (如 https://163cn.tv/3Kc5VwN)
    short_match = re.search(r'(https?://163cn\.tv/[a-zA-Z0-9]+)', raw_text)
    if short_match:
        short_url = short_match.group(1)
        try:
            # 伪装浏览器请求，防止被网易云基础风控拦截
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            # 发起请求，requests 默认会跟随重定向 (allow_redirects=True)
            response = requests.get(short_url, headers=headers, timeout=10)

            # response.url 就是重定向后极其冗长的真实 URL
            real_url = response.url

            # 从冗长的 URL 中精准提取 id
            # 兼容形如 ?app_version=xxx&id=12345 或 ?id=12345 的情况
            id_match = re.search(r'[?&]id=(\d+)', real_url)
            if id_match:
                podcast_id = id_match.group(1)
                # 重新组装成 yt-dlp 绝对能认出来的纯净格式！
                return f"https://music.163.com/program?id={podcast_id}"

        except Exception as e:
            print(f"短链解包失败: {e}")
            return None  # 如果网络炸了，优雅退出

    # 场景 2: 嗅探 PC/网页端长链 (直接正则切除盲肠参数)
    long_match = re.search(r'https?://music\.163\.com/(?:#/)?(?:program|dj)\?id=(\d+)', raw_text)
    if long_match:
        podcast_id = long_match.group(1)
        return f"https://music.163.com/program?id={podcast_id}"

    # 如果什么都没匹配到，返回 None
    return None


def parse_ximalaya_url(raw_text):
    """
    智能嗅探并净化喜马拉雅播客链接（支持动态解包短链）

    参数:
        raw_text (str): 用户分享的原始文本（可能包含分享文案）

    返回:
        str or None: 净化后的标准播客 URL，失败返回 None
    """
    # 场景 1: 短链 xima.tv/xxx
    short_match = re.search(r'(https?://xima\.tv/[a-zA-Z0-9_]+)', raw_text)
    if short_match:
        short_url = short_match.group(1)
        # 移除可能的追踪参数如 ?_sonic=0
        short_url = re.sub(r'\?_sonic=\d+', '', short_url)
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(short_url, headers=headers, timeout=10, allow_redirects=True)
            real_url = response.url

            # 从重定向 URL 中提取音频 ID
            # 格式: https://m.ximalaya.com/gatekeeper/podcast-share/sound/964832711
            sound_match = re.search(r'/sound/(\d+)', real_url)
            if sound_match:
                sound_id = sound_match.group(1)
                return f"https://m.ximalaya.com/sound/{sound_id}"

        except Exception as e:
            print(f"喜马拉雅短链解包失败: {e}")
            return None

    # 场景 2: 长链 m.ximalaya.com/sound/xxx
    long_match = re.search(r'https?://(?:[a-z]+\.)?ximalaya\.com/sound/(\d+)', raw_text)
    if long_match:
        sound_id = long_match.group(1)
        return f"https://m.ximalaya.com/sound/{sound_id}"

    # 场景 3: 带参数的分享链接
    share_match = re.search(r'https?://m\.ximalaya\.com/gatekeeper/podcast-share/sound/(\d+)', raw_text)
    if share_match:
        sound_id = share_match.group(1)
        return f"https://m.ximalaya.com/sound/{sound_id}"

    return None


def fetch_netease_title(podcast_url):
    """
    获取网易云播客标题。

    参数:
        podcast_url (str): 净化后的播客 URL

    返回:
        str: 播客标题，失败返回 None
    """
    result = extract_info_with_ytdlp(podcast_url)
    if result['success']:
        return result['info'].get('title', None)
    print(f"获取标题失败: {result['error']}")
    return None


def fetch_ximalaya_title(podcast_url):
    """
    获取喜马拉雅播客标题。

    参数:
        podcast_url (str): 净化后的播客 URL

    返回:
        str: 播客标题，失败返回 None
    """
    result = extract_info_with_ytdlp(podcast_url)
    if result['success']:
        return result['info'].get('title', None)
    print(f"获取喜马拉雅标题失败: {result['error']}")
    return None


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
            - platform (str): "xiaoyuzhou"
    """
    os.makedirs(save_dir, exist_ok=True)

    # 检查 URL 格式
    if detect_platform(url) != "xiaoyuzhou":
        return {
            'success': False,
            'file_path': None,
            'title': None,
            'error': "非有效的小宇宙分享链接，请检查链接是否正确",
            'platform': "xiaoyuzhou"
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
                'success': False, 'file_path': None, 'title': None,
                'error': f"请求失败，状态码: {response.status_code}", 'platform': "xiaoyuzhou"
            }

        html_content = response.text

        # 提取音频直链 - 查找 <meta property="og:audio" content="...">
        audio_url = None
        title = "未知标题"

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
                'success': False, 'file_path': None, 'title': None,
                'error': "页面结构已变更，无法解析音频链接，请等待开发者更新",
                'platform': "xiaoyuzhou"
            }

        # 清理标题
        title = _sanitize_title(title)

        # 下载音频文件
        print(f"[Downloader] 正在下载音频: {title}")

        # 流式下载
        audio_response = requests.get(audio_url, headers=headers, timeout=60, stream=True)
        if audio_response.status_code != 200:
            return {
                'success': False, 'file_path': None, 'title': title,
                'error': f"音频下载失败，状态码: {audio_response.status_code}",
                'platform': "xiaoyuzhou"
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
            ext = '.m4a'

        # 保存文件
        file_path = os.path.join(save_dir, f"{title}{ext}")

        with open(file_path, 'wb') as f:
            for chunk in audio_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        print(f"[Downloader] 下载完成: {title}，转码中...")

        # 如果是 m4a/aac 格式，转换为 mp3
        if ext in ['.m4a', '.aac'] and os.path.exists(file_path):
            try:
                mp3_path = os.path.join(save_dir, f"{title}.mp3")
                result = subprocess.run([
                    get_ffmpeg_path(), '-i', file_path,
                    '-codec:a', 'libmp3lame', '-q:a', '2', mp3_path, '-y'
                ], capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    os.remove(file_path)
                    file_path = mp3_path
                    print(f"[Downloader] 转码完成: {title}")
                else:
                    print(f"[Downloader] FFmpeg 转码失败: {result.stderr[:200]}")
                    # 回退：保留原格式
            except Exception as e:
                print(f"[Downloader] 格式转换失败，保持原格式: {e}")

        # 验证文件
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return {
                'success': True,
                'file_path': file_path,
                'title': title,
                'error': None,
                'platform': "xiaoyuzhou"
            }
        else:
            return {
                'success': False, 'file_path': None, 'title': title,
                'error': "音频文件保存失败",
                'platform': "xiaoyuzhou"
            }

    except requests.exceptions.Timeout:
        return {
            'success': False, 'file_path': None, 'title': None,
            'error': "网络连接超时，请检查网络或稍后再试",
            'platform': "xiaoyuzhou"
        }
    except requests.exceptions.ConnectionError:
        return {
            'success': False, 'file_path': None, 'title': None,
            'error': "网络连接失败，请检查网络",
            'platform': "xiaoyuzhou"
        }
    except Exception as e:
        return {
            'success': False, 'file_path': None, 'title': None,
            'error': f"下载过程出错: {str(e)}",
            'platform': "xiaoyuzhou"
        }


def download_netease_audio(raw_text, save_dir="temp_audio"):
    """
    从网易云播客链接下载音频。

    参数:
        raw_text (str): 用户分享的原始文本（可能包含分享文案）
        save_dir (str): 保存目录

    返回:
        dict: 包含以下键的字典:
            - success (bool): 是否成功
            - file_path (str): 下载的音频文件路径（成功时）
            - title (str): 播客标题（成功时）
            - error (str): 错误信息（失败时）
            - platform (str): "netease"
    """
    os.makedirs(save_dir, exist_ok=True)

    # 先解析并净化 URL
    podcast_url = parse_netease_url(raw_text)
    if not podcast_url:
        return {
            'success': False, 'file_path': None, 'title': None,
            'error': "无法解析网易云播客链接，请检查链接是否正确",
            'platform': "netease"
        }

    print(f"[Downloader] 净化后的播客链接: {podcast_url}")

    # 使用统一 helper 下载
    result = download_audio_with_ytdlp(
        url=podcast_url,
        save_dir=save_dir,
        prefer_m4a=False,
        timeout=300
    )
    result['platform'] = 'netease'
    return result


def download_ximalaya_audio(raw_text, save_dir="temp_audio"):
    """
    从喜马拉雅播客链接下载音频。

    参数:
        raw_text (str): 用户分享的原始文本（可能包含分享文案）
        save_dir (str): 保存目录

    返回:
        dict: 包含以下键的字典:
            - success (bool): 是否成功
            - file_path (str): 下载的音频文件路径（成功时）
            - title (str): 播客标题（成功时）
            - error (str): 错误信息（失败时）
            - platform (str): "ximalaya"
    """
    os.makedirs(save_dir, exist_ok=True)

    # 先解析并净化 URL
    podcast_url = parse_ximalaya_url(raw_text)
    if not podcast_url:
        return {
            'success': False, 'file_path': None, 'title': None,
            'error': "无法解析喜马拉雅播客链接，请检查链接是否正确",
            'platform': "ximalaya"
        }

    print(f"[Downloader] 净化后的喜马拉雅链接: {podcast_url}")

    # 使用统一 helper 下载
    result = download_audio_with_ytdlp(
        url=podcast_url,
        save_dir=save_dir,
        prefer_m4a=False,
        timeout=300
    )
    result['platform'] = 'ximalaya'
    return result


def download_applepodcasts_audio(url, save_dir="temp_audio"):
    """
    从苹果播客链接下载音频。

    参数:
        url (str): 苹果播客分享链接
        save_dir (str): 保存目录

    返回:
        dict: {"success": bool, "file_path": str, "title": str, "error": str, "platform": "applepodcasts"}
    """
    os.makedirs(save_dir, exist_ok=True)

    # 使用统一 helper 提取信息（不再依赖 subprocess yt-dlp）
    info_result = extract_info_with_ytdlp(url)
    if not info_result['success']:
        return {
            'success': False, 'file_path': None, 'title': None,
            'error': info_result['error'],
            'platform': "applepodcasts"
        }

    title = _sanitize_title(info_result['info'].get('title', 'apple_podcast'))
    print(f"[Downloader] 开始下载 Apple Podcasts: {title}")

    # 使用统一 helper 下载（保留 m4a 容器，不转 mp3）
    result = download_audio_with_ytdlp(
        url=url,
        save_dir=save_dir,
        title=title,
        prefer_m4a=True,   # Apple Podcasts 保留 m4a
        timeout=300
    )
    result['platform'] = 'applepodcasts'
    return result


def route_and_download(url, save_dir="temp_audio", cookies_path=None):
    """
    根据 URL 类型智能路由并下载音频。

    参数:
        url (str): 在线链接（可能包含分享文案）
        save_dir (str): 保存目录
        cookies_path (str, optional): cookies 文件路径

    返回:
        dict: 下载结果（统一格式含 platform 字段）
    """
    platform = detect_platform(url)

    if platform == "xiaoyuzhou":
        return download_xiaoyuzhou_audio(url, save_dir)
    elif platform == "bilibili":
        downloader = AudioDownloader(save_dir=save_dir)
        return downloader.download_bilibili_audio(url, cookies_path)
    elif platform == "netease":
        return download_netease_audio(url, save_dir)
    elif platform == "ximalaya":
        return download_ximalaya_audio(url, save_dir)
    elif platform == "applepodcasts":
        return download_applepodcasts_audio(url, save_dir)
    else:
        return {
            'success': False,
            'file_path': None,
            'title': None,
            'error': f"不支持的平台，当前仅支持小宇宙、网易云、喜马拉雅、苹果播客和 Bilibili",
            'platform': platform
        }
