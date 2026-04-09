import os
import platform as platform_sys
import shutil
import subprocess
import yt_dlp
import re
import requests
import threading
import sys
from urllib.parse import urlparse

# 延迟导入 get_ffmpeg_path，兼容开发环境和 electron 打包环境
def _get_ffmpeg_path_impl():
    resources_path = os.environ.get('PODGIST_RESOURCES_PATH')
    if resources_path:
        if platform_sys.system() == 'Windows':
            return os.path.join(resources_path, 'ffmpeg', 'ffmpeg.exe')
        return os.path.join(resources_path, 'ffmpeg', 'ffmpeg')
    return 'ffmpeg'

try:
    from backend import get_ffmpeg_path
except ImportError:
    _parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
    try:
        from backend import get_ffmpeg_path
    except ImportError:
        get_ffmpeg_path = _get_ffmpeg_path_impl


def _sanitize_title(title):
    title = re.sub(r'[\/*?:"<>|]', '', title)
    title = title.strip()
    if len(title) > 200:
        title = title[:200]
    return title


def _get_ffmpeg_dir():
    """获取 ffmpeg 目录路径，用于 yt-dlp 的 ffmpeg_location 参数。

    优先级（从高到低）：
    1. PODGIST_FFMPEG_DIR  — backendStarter.js 注入的运行时路径（userData/bin/）
    2. FFMPEG_BINARY / FFPROBE_BINARY — backendStarter.js 注入的明确路径
    3. shutil.which('ffmpeg') — 系统 PATH 中找
    4. get_ffmpeg_path() — 读取 PODGIST_RESOURCES_PATH 的打包资源路径

    返回目录字符串，或 None（届时 yt-dlp 用系统 PATH）。
    """
    print('[Downloader] _get_ffmpeg_dir() 诊断:')
    print(f'  PODGIST_FFMPEG_DIR   = {os.environ.get("PODGIST_FFMPEG_DIR", "(未设置)")}')
    print(f'  FFMPEG_BINARY        = {os.environ.get("FFMPEG_BINARY", "(未设置)")}')
    print(f'  FFPROBE_BINARY       = {os.environ.get("FFPROBE_BINARY", "(未设置)")}')
    which = shutil.which('ffmpeg')
    print(f'  shutil.which(ffmpeg)  = {which or "(未找到)"}')

    # 1. 最高优先级：PODGIST_FFMPEG_DIR
    podgist_dir = os.environ.get('PODGIST_FFMPEG_DIR')
    if podgist_dir:
        print(f'  -> 选用 PODGIST_FFMPEG_DIR: {podgist_dir}')
        _check_ffmpeg_in_dir(podgist_dir)
        return podgist_dir

    # 2. FFMPEG_BINARY / FFPROBE_BINARY
    ffmpeg_bin = os.environ.get('FFMPEG_BINARY')
    if ffmpeg_bin:
        ffmpeg_dir = os.path.dirname(ffmpeg_bin)
        print(f'  -> 选用 FFMPEG_BINARY 目录: {ffmpeg_dir}')
        _check_ffmpeg_in_dir(ffmpeg_dir)
        return ffmpeg_dir

    # 3. shutil.which
    if which:
        ffmpeg_dir = os.path.dirname(which)
        print(f'  -> 选用 shutil.which 目录: {ffmpeg_dir}')
        _check_ffmpeg_in_dir(ffmpeg_dir)
        return ffmpeg_dir

    # 4. 回退到打包资源路径
    ffmpeg_path = get_ffmpeg_path()
    ffmpeg_dir = os.path.dirname(ffmpeg_path)
    if ffmpeg_dir:
        print(f'  -> 选用 get_ffmpeg_path() 目录: {ffmpeg_dir}')
        _check_ffmpeg_in_dir(ffmpeg_dir)
        return ffmpeg_dir

    print('  -> 未能确定 ffmpeg 目录，返回 None（yt-dlp 使用系统 PATH）')
    return None


def _check_ffmpeg_in_dir(ffmpeg_dir):
    """诊断：检查 ffmpeg_dir 中 ffmpeg 和 ffprobe 是否存在、是否可执行。"""
    if not ffmpeg_dir or not os.path.isdir(ffmpeg_dir):
        print(f'  [WARN] ffmpeg_dir 不存在或非目录: {ffmpeg_dir}')
        return
    for name in ['ffmpeg', 'ffprobe']:
        fpath = os.path.join(ffmpeg_dir, name)
        exists = os.path.exists(fpath)
        executable = os.access(fpath, os.X_OK) if exists else False
        print(f'  {name}: exists={exists}, executable={executable}, path={fpath}')


def extract_info_with_ytdlp(url, cookies_path=None):
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
        return {'success': False, 'info': None, 'error': '获取信息失败: ' + str(e)}
    except Exception as e:
        return {'success': False, 'info': None, 'error': '获取信息出错: ' + str(e)}


def download_audio_with_ytdlp(url, save_dir, title=None, prefer_m4a=False,
                               cookies_path=None, timeout=300):
    os.makedirs(save_dir, exist_ok=True)

    print('[Downloader] === 下载任务环境诊断 ===')
    print(f'  PATH = {os.environ.get("PATH", "(未设置)")[:200]}')
    print(f'  PODGIST_FFMPEG_DIR = {os.environ.get("PODGIST_FFMPEG_DIR", "(未设置)")}')
    print(f'  FFMPEG_BINARY      = {os.environ.get("FFMPEG_BINARY", "(未设置)")}')
    print(f'  FFPROBE_BINARY    = {os.environ.get("FFPROBE_BINARY", "(未设置)")}')

    ffmpeg_dir = _get_ffmpeg_dir()

    # 获取音频信息（先 extract 再 download，用 process_info 获取实际 filepath）
    info_result = extract_info_with_ytdlp(url, cookies_path=cookies_path)
    if not info_result['success']:
        return {'success': False, 'file_path': None, 'title': None, 'error': info_result['error'], 'platform': None}

    if title is None:
        raw_title = info_result['info'].get('title', 'audio')
        title = _sanitize_title(raw_title)
    else:
        title = _sanitize_title(title)

    print('[Downloader] 开始下载: ' + title)

    # yt-dlp 输出模板用 sanitized title（yt-dlp 会再次 sanitize，与我们独立计算的结果可能有差异）
    output_template = os.path.join(save_dir, title + '.%(ext)s')

    postprocessors = []
    if prefer_m4a:
        postprocessors.append({'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a', 'preferredquality': '192'})
    else:
        postprocessors.append({'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'})

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'quiet': False,
        'no_warnings': False,
        'socket_timeout': 30,
        'retries': 3,
        'postprocessors': postprocessors,
    }
    if ffmpeg_dir:
        ydl_opts['ffmpeg_location'] = ffmpeg_dir
    if cookies_path and os.path.exists(cookies_path):
        ydl_opts['cookiefile'] = cookies_path

    print(f'[Downloader] yt-dlp ffmpeg_location = {ydl_opts.get("ffmpeg_location", "(未设置)")}')

    # 记录下载前目录中的文件（用于下载后通过 mtime 找到新文件）
    before_files = {}
    for f in os.listdir(save_dir):
        fp = os.path.join(save_dir, f)
        if os.path.isfile(fp):
            before_files[f] = os.path.getmtime(fp)

    download_error = [None]

    def _do_download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # extract_info(download=True) 会下载并执行 postprocessors，完成后返回 info dict
                ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            download_error[0] = e
        except Exception as e:
            download_error[0] = e

    download_thread = threading.Thread(target=_do_download)
    download_thread.daemon = True
    download_thread.start()
    download_thread.join(timeout=timeout)

    if download_thread.is_alive():
        return {'success': False, 'file_path': None, 'title': title, 'error': '下载超时（' + str(timeout) + '秒），可能网络问题或内容无法访问', 'platform': None}

    if download_error[0]:
        error_msg = str(download_error[0])
        if 'HTTP Error 403' in error_msg or '403' in error_msg:
            return {'success': False, 'file_path': None, 'title': title, 'error': '下载失败：该内容可能需要 VIP 权限或已被删除', 'platform': None}
        elif 'HTTP Error 404' in error_msg or '404' in error_msg:
            return {'success': False, 'file_path': None, 'title': title, 'error': '下载失败：内容不存在或链接无效', 'platform': None}
        else:
            return {'success': False, 'file_path': None, 'title': title, 'error': '下载失败: ' + error_msg, 'platform': None}

    # 通过 mtime 找到新创建/更新的文件（yt-dlp 内部 sanitize 过的文件名可能与我们计算的不同）
    newest_file = None
    newest_mtime = 0
    for f in os.listdir(save_dir):
        fp = os.path.join(save_dir, f)
        if os.path.isfile(fp) and f not in before_files:
            mtime = os.path.getmtime(fp)
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest_file = fp
        elif os.path.isfile(fp) and f in before_files:
            mtime = os.path.getmtime(fp)
            if mtime > before_files[f] + 1:  # 允许 1 秒误差
                if mtime > newest_mtime:
                    newest_mtime = mtime
                    newest_file = fp

    if newest_file is None or not os.path.exists(newest_file) or os.path.getsize(newest_file) == 0:
        return {'success': False, 'file_path': None, 'title': title, 'error': '音频文件下载失败或未找到', 'platform': None}

    file_path = newest_file
    print('[Downloader] 下载完成: ' + file_path)

    # 如果需要转码（prefer_m4a=False 但得到的是 m4a）
    _, ext = os.path.splitext(file_path)
    if not prefer_m4a and ext.lower() != '.mp3':
        mp3_path = os.path.join(save_dir, title + '.mp3')
        try:
            result2 = subprocess.run([get_ffmpeg_path(), '-i', file_path, '-codec:a', 'libmp3lame', '-q:a', '2', mp3_path, '-y'], capture_output=True, text=True, timeout=60)
            if result2.returncode == 0:
                os.remove(file_path)
                file_path = mp3_path
                print('[Downloader] 转码完成: ' + title)
            else:
                print('[Downloader] FFmpeg 转码失败: ' + result2.stderr[:200])
                return {'success': False, 'file_path': None, 'title': title, 'error': '音频格式转换失败', 'platform': None}
        except subprocess.TimeoutExpired:
            return {'success': False, 'file_path': None, 'title': title, 'error': '音频格式转换超时', 'platform': None}
        except Exception as e:
            print('[Downloader] 转码出错: ' + str(e))
            return {'success': False, 'file_path': None, 'title': title, 'error': '音频格式转换出错: ' + str(e), 'platform': None}

    return {'success': True, 'file_path': file_path, 'title': title, 'error': None, 'platform': None}


class AudioDownloader:
    def __init__(self, save_dir='temp_audio'):
        self.save_dir = save_dir
        os.makedirs(save_dir, exist_ok=True)

    def sanitize_filename(self, filename):
        return _sanitize_title(filename)

    def download_bilibili_audio(self, url, cookies_path=None):
        result = download_audio_with_ytdlp(url=url, save_dir=self.save_dir, prefer_m4a=False, cookies_path=cookies_path, timeout=300)
        result['platform'] = 'bilibili'
        return result


def download_audio_from_url(url, save_dir='temp_audio', cookies_path=None):
    downloader = AudioDownloader(save_dir=save_dir)
    return downloader.download_bilibili_audio(url, cookies_path=cookies_path)


def download_and_convert(url, save_dir='temp_audio', cookies_path=None):
    downloader = AudioDownloader(save_dir=save_dir)
    return downloader.download_bilibili_audio(url, cookies_path=cookies_path)


def detect_platform(url):
    url = url.lower()
    if 'xiaoyuzhoufm.com' in url:
        return 'xiaoyuzhou'
    elif 'bilibili.com' in url:
        return 'bilibili'
    elif '163cn.tv' in url or 'music.163.com' in url:
        return 'netease'
    elif 'xima.tv' in url or 'ximalaya.com' in url:
        return 'ximalaya'
    elif 'podcasts.apple.com' in url:
        return 'applepodcasts'
    else:
        return 'unknown'


def parse_netease_url(raw_text):
    short_match = re.search(r'(https?://163cn\.tv/[a-zA-Z0-9]+)', raw_text)
    if short_match:
        short_url = short_match.group(1)
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            response = requests.get(short_url, headers=headers, timeout=10)
            real_url = response.url
            id_match = re.search(r'[?&]id=(\d+)', real_url)
            if id_match:
                podcast_id = id_match.group(1)
                return 'https://music.163.com/program?id=' + podcast_id
        except Exception as e:
            print('短链解包失败: ' + str(e))
            return None

    long_match = re.search(r'https?://music\.163\.com/(?:#/)?(?:program|dj)\?id=(\d+)', raw_text)
    if long_match:
        podcast_id = long_match.group(1)
        return 'https://music.163.com/program?id=' + podcast_id
    return None


def parse_ximalaya_url(raw_text):
    short_match = re.search(r'(https?://xima\.tv/[a-zA-Z0-9_]+)', raw_text)
    if short_match:
        short_url = short_match.group(1)
        short_url = re.sub(r'\?_sonic=\d+', '', short_url)
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
            response = requests.get(short_url, headers=headers, timeout=10, allow_redirects=True)
            real_url = response.url
            sound_match = re.search(r'/sound/(\d+)', real_url)
            if sound_match:
                sound_id = sound_match.group(1)
                return 'https://m.ximalaya.com/sound/' + sound_id
        except Exception as e:
            print('喜马拉雅短链解包失败: ' + str(e))
            return None

    long_match = re.search(r'https?://(?:[a-z]+\.)?ximalaya\.com/sound/(\d+)', raw_text)
    if long_match:
        sound_id = long_match.group(1)
        return 'https://m.ximalaya.com/sound/' + sound_id

    share_match = re.search(r'https?://m\.ximalaya\.com/gatekeeper/podcast-share/sound/(\d+)', raw_text)
    if share_match:
        sound_id = share_match.group(1)
        return 'https://m.ximalaya.com/sound/' + sound_id
    return None


def fetch_netease_title(podcast_url):
    result = extract_info_with_ytdlp(podcast_url)
    if result['success']:
        return result['info'].get('title', None)
    print('获取标题失败: ' + str(result['error']))
    return None


def fetch_ximalaya_title(podcast_url):
    result = extract_info_with_ytdlp(podcast_url)
    if result['success']:
        return result['info'].get('title', None)
    print('获取喜马拉雅标题失败: ' + str(result['error']))
    return None


def download_xiaoyuzhou_audio(url, save_dir='temp_audio'):
    os.makedirs(save_dir, exist_ok=True)
    if detect_platform(url) != 'xiaoyuzhou':
        return {'success': False, 'file_path': None, 'title': None, 'error': '非有效的小宇宙分享链接，请检查链接是否正确', 'platform': 'xiaoyuzhou'}

    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8', 'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return {'success': False, 'file_path': None, 'title': None, 'error': '请求失败，状态码: ' + str(response.status_code), 'platform': 'xiaoyuzhou'}

        html_content = response.text
        audio_url = None
        title = '未知标题'

        audio_match = re.search(r'<meta\s+(?:property|name)="og:audio"\s+content="([^"]+)"', html_content)
        if audio_match:
            audio_url = audio_match.group(1)
        else:
            audio_match = re.search(r'data-src="([^"]+\.mp3)"', html_content)
            if audio_match:
                audio_url = audio_match.group(1)

        title_match = re.search(r'<meta\s+(?:property|name)="og:title"\s+content="([^"]+)"', html_content)
        if title_match:
            title = title_match.group(1)
        else:
            title_match = re.search(r'<title>([^<]+)</title>', html_content)
            if title_match:
                title = title_match.group(1)

        if not audio_url:
            return {'success': False, 'file_path': None, 'title': None, 'error': '页面结构已变更，无法解析音频链接，请等待开发者更新', 'platform': 'xiaoyuzhou'}

        title = _sanitize_title(title)
        print('[Downloader] 正在下载音频: ' + title)

        audio_response = requests.get(audio_url, headers=headers, timeout=60, stream=True)
        if audio_response.status_code != 200:
            return {'success': False, 'file_path': None, 'title': title, 'error': '音频下载失败，状态码: ' + str(audio_response.status_code), 'platform': 'xiaoyuzhou'}

        content_type = audio_response.headers.get('Content-Type', '').lower()
        if 'mpeg' in content_type or 'mp3' in content_type:
            ext = '.mp3'
        elif 'm4a' in content_type or 'mp4' in content_type:
            ext = '.m4a'
        elif 'audio/aac' in content_type:
            ext = '.aac'
        else:
            ext = '.m4a'

        file_path = os.path.join(save_dir, title + ext)
        with open(file_path, 'wb') as f:
            for chunk in audio_response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        print('[Downloader] 下载完成: ' + title + '，转码中...')

        if ext in ['.m4a', '.aac'] and os.path.exists(file_path):
            try:
                mp3_path = os.path.join(save_dir, title + '.mp3')
                result = subprocess.run([get_ffmpeg_path(), '-i', file_path, '-codec:a', 'libmp3lame', '-q:a', '2', mp3_path, '-y'], capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    os.remove(file_path)
                    file_path = mp3_path
                    print('[Downloader] 转码完成: ' + title)
                else:
                    print('[Downloader] FFmpeg 转码失败: ' + result.stderr[:200])
            except Exception as e:
                print('[Downloader] 格式转换失败，保持原格式: ' + str(e))

        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            return {'success': True, 'file_path': file_path, 'title': title, 'error': None, 'platform': 'xiaoyuzhou'}
        else:
            return {'success': False, 'file_path': None, 'title': title, 'error': '音频文件保存失败', 'platform': 'xiaoyuzhou'}

    except requests.exceptions.Timeout:
        return {'success': False, 'file_path': None, 'title': None, 'error': '网络连接超时，请检查网络或稍后再试', 'platform': 'xiaoyuzhou'}
    except requests.exceptions.ConnectionError:
        return {'success': False, 'file_path': None, 'title': None, 'error': '网络连接失败，请检查网络', 'platform': 'xiaoyuzhou'}
    except Exception as e:
        return {'success': False, 'file_path': None, 'title': None, 'error': '下载过程出错: ' + str(e), 'platform': 'xiaoyuzhou'}


def download_netease_audio(raw_text, save_dir='temp_audio'):
    os.makedirs(save_dir, exist_ok=True)
    podcast_url = parse_netease_url(raw_text)
    if not podcast_url:
        return {'success': False, 'file_path': None, 'title': None, 'error': '无法解析网易云播客链接，请检查链接是否正确', 'platform': 'netease'}
    print('[Downloader] 净化后的播客链接: ' + podcast_url)
    result = download_audio_with_ytdlp(url=podcast_url, save_dir=save_dir, prefer_m4a=False, timeout=300)
    result['platform'] = 'netease'
    return result


def download_ximalaya_audio(raw_text, save_dir='temp_audio'):
    os.makedirs(save_dir, exist_ok=True)
    podcast_url = parse_ximalaya_url(raw_text)
    if not podcast_url:
        return {'success': False, 'file_path': None, 'title': None, 'error': '无法解析喜马拉雅播客链接，请检查链接是否正确', 'platform': 'ximalaya'}
    print('[Downloader] 净化后的喜马拉雅链接: ' + podcast_url)
    result = download_audio_with_ytdlp(url=podcast_url, save_dir=save_dir, prefer_m4a=False, timeout=300)
    result['platform'] = 'ximalaya'
    return result


def download_applepodcasts_audio(url, save_dir='temp_audio'):
    os.makedirs(save_dir, exist_ok=True)
    info_result = extract_info_with_ytdlp(url)
    if not info_result['success']:
        return {'success': False, 'file_path': None, 'title': None, 'error': info_result['error'], 'platform': 'applepodcasts'}
    title = _sanitize_title(info_result['info'].get('title', 'apple_podcast'))
    print('[Downloader] 开始下载 Apple Podcasts: ' + title)
    result = download_audio_with_ytdlp(url=url, save_dir=save_dir, title=title, prefer_m4a=True, timeout=300)
    result['platform'] = 'applepodcasts'
    return result


def route_and_download(url, save_dir='temp_audio', cookies_path=None):
    platform = detect_platform(url)
    if platform == 'xiaoyuzhou':
        return download_xiaoyuzhou_audio(url, save_dir)
    elif platform == 'bilibili':
        downloader = AudioDownloader(save_dir=save_dir)
        return downloader.download_bilibili_audio(url, cookies_path)
    elif platform == 'netease':
        return download_netease_audio(url, save_dir)
    elif platform == 'ximalaya':
        return download_ximalaya_audio(url, save_dir)
    elif platform == 'applepodcasts':
        return download_applepodcasts_audio(url, save_dir)
    else:
        return {'success': False, 'file_path': None, 'title': None, 'error': '不支持的平台，当前仅支持小宇宙、网易云、喜马拉雅、苹果播客和 Bilibili', 'platform': platform}
