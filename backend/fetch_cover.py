"""
fetch_cover.py — 多策略封面抓取

支持来源优先级：
1. yt-dlp info dict 的 thumbnail 字段（通用方案）
2. 页面 og:image meta 标签（播客网页 fallback）
3. 通用页面 meta 图片

返回：(cover_url, cover_type) 或 (None, None)
cover_type: 'episode' | 'show' | 'video' | 'webpage'
"""

import requests
import re
import os
import sys

# 确保 backend 目录在 sys.path（兼容打包后的导入）
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


def _best_thumbnail(info: dict) -> str | None:
    """
    从 yt-dlp info dict 中提取最佳封面 URL。

    策略：
    - 优先用 thumbnails 数组里最高分辨率的项
    - 若 thumbnail 是已知 CDN 缩略图（imagev2.xmcdn.com 等），且 thumbnails[0] 是原图，优先用 thumbnails[0]
    - 回退到 thumbnail 字段
    """
    thumbnails = info.get('thumbnails') or []
    thumb_field = info.get('thumbnail') or ''

    # 已知的小图 CDN：喜马拉雅 imagev2 缩略图，优先用 thumbnails[0] 的原图
    if ('imagev2.xmcdn.com' in thumb_field or '!op_type=' in thumb_field) and thumbnails:
        first = thumbnails[0].get('url')
        if first and first.startswith('http') and '!op_type=' not in first:
            return first

    if thumbnails:
        # 找有 resolution 且最大的那个
        best = None
        best_res = 0
        for t in thumbnails:
            res = t.get('resolution') or ''
            if 'x' in str(res):
                try:
                    w = int(str(res).split('x')[0])
                    if w > best_res:
                        best_res = w
                        best = t.get('url')
                except:
                    pass
            elif res and not best:
                best = t.get('url')
        if best:
            return best

    # 回退字段
    for key in ('thumbnail', 'artwork_url', 'cover_url', 'image'):
        img = info.get(key)
        if img and isinstance(img, str) and img.startswith('http'):
            return img
    return None


def _fetch_via_ytdlp(url: str) -> tuple:
    """
    通过 yt-dlp extract_info 获取封面 URL。
    适用于：YouTube, Bilibili, Apple Podcasts, Netease, Ximalaya 等所有 yt-dlp 支持的平台。
    返回 (url, type)
    """
    try:
        import yt_dlp

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        img = _best_thumbnail(info)
        if img and isinstance(img, str) and img.startswith('http'):
            return (img, 'show')
        return (None, None)
    except Exception as e:
        print(f"[Cover] yt-dlp fetch failed: {e}")
        return (None, None)


def _fetch_via_og_image(url: str) -> tuple:
    """
    抓取页面 HTML，解析 og:image meta 标签。
    适用于：播客详情页、小宇宙单集页等。
    返回 (url, type)
    """
    try:
        headers = {
            'User-Agent': _UA,
            'Accept': 'text/html,application/xhtml+xml,*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        resp = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        if resp.status_code != 200:
            return (None, None)

        html = resp.text

        # 匹配 og:image
        match = re.search(
            r'<meta\s+(?:property|name)=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
            html, re.IGNORECASE
        )
        if not match:
            # 备选：twitter:image
            match = re.search(
                r'<meta\s+(?:property|name)=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']',
                html, re.IGNORECASE
            )
        if match:
            img_url = match.group(1).strip()
            if img_url.startswith('http'):
                return (img_url, 'webpage')
        return (None, None)
    except Exception as e:
        print(f"[Cover] og:image fetch failed: {e}")
        return (None, None)


def fetch_cover(url: str, source_type: str = 'podcast_url') -> tuple:
    """
    主入口：多级 fallback 抓取封面 URL。

    Args:
        url: 原始来源 URL
        source_type: 'podcast_url' | 'bilibili' | 'local_file'

    Returns:
        (cover_url, cover_type) — 抓取失败时 (None, None)
    """
    if source_type == 'local_file' or not url:
        return (None, None)

    # Bilibili 优先用 yt-dlp（B站封面在 info 里有）
    if 'bilibili.com' in url.lower():
        img, typ = _fetch_via_ytdlp(url)
        if img:
            return (img, 'video')

    # 通用播客 URL：优先 yt-dlp，再 og:image
    img, typ = _fetch_via_ytdlp(url)
    if img:
        return (img, typ)

    img, typ = _fetch_via_og_image(url)
    if img:
        return (img, typ)

    return (None, None)


def download_cover_image(cover_url: str, dest_path: str, referer: str = '') -> bool:
    """
    下载封面图片到本地路径。
    MIME 自动推断后缀（.jpg / .webp / .png）。

    Args:
        cover_url: 封面图片 URL
        dest_path: 目标路径（不含后缀）
        referer: 可选的 Referer URL（用于 B站等需要防盗链的平台）
    """
    try:
        headers = {
            'User-Agent': _UA,
        }
        if referer:
            headers['Referer'] = referer
        elif 'hdslb.com' in cover_url or 'bfs.cloud' in cover_url:
            # B站系域名，用通用 referer
            headers['Referer'] = 'https://www.bilibili.com/'
        elif 'imagev2.xmcdn.com' in cover_url:
            headers['Referer'] = 'https://www.ximalaya.com/'
        elif 'music.126.net' in cover_url:
            headers['Referer'] = 'https://music.163.com/'
        elif 'xyzcdn.net' in cover_url:
            headers['Referer'] = 'https://www.xiaoyuzhoufm.com/'
        elif 'mzstatic.com' in cover_url:
            headers['Referer'] = 'https://podcasts.apple.com/'

        resp = requests.get(cover_url, headers=headers, timeout=15, stream=True)
        if resp.status_code != 200:
            print(f"[Cover] Download HTTP {resp.status_code} for {cover_url}")
            return False

        content_type = resp.headers.get('Content-Type', '').lower()
        if 'jpeg' in content_type or 'jpg' in content_type:
            ext = '.jpg'
        elif 'webp' in content_type:
            ext = '.webp'
        elif 'png' in content_type:
            ext = '.png'
        else:
            # 尝试从 URL 推断
            if '.webp' in cover_url.lower():
                ext = '.webp'
            elif '.png' in cover_url.lower():
                ext = '.png'
            else:
                ext = '.jpg'

        final_path = os.path.splitext(dest_path)[0] + ext
        with open(final_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        size = os.path.getsize(final_path)
        if size < 2000:  # 小于 2KB 可能是错误占位图
            os.remove(final_path)
            print(f"[Cover] Rejected small file ({size} bytes): {final_path}")
            return False

        print(f"[Cover] Downloaded cover: {final_path} ({size} bytes)")
        return True
    except Exception as e:
        print(f"[Cover] Download failed: {e}")
        return False
