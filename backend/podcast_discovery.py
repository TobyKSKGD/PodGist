"""播客内容发现：统一外部目录结果，并优先返回中国大陆可处理的音频来源。"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import requests
import xml.etree.ElementTree as ET


APPLE_SEARCH_URL = "https://itunes.apple.com/search"
APPLE_LOOKUP_URL = "https://itunes.apple.com/lookup"
PODCAST_INDEX_URL = "https://api.podcastindex.org/api/1.0"
REQUEST_HEADERS = {
    "User-Agent": "PodGist/0.3.1 (+https://github.com/TobyKSKGD/PodGist)",
    "Accept": "application/json",
}
RSS_REQUEST_HEADERS = {
    "User-Agent": "AppleCoreMedia/1.0.0.20A362 (iPhone; U; CPU OS 16_0 like Mac OS X; zh_cn)",
    "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
}


def _get_rss(feed_url: str, timeout: int = 15) -> requests.Response:
    """兼容会按客户端标识限制访问的中文播客托管服务。"""
    response = requests.get(feed_url, headers=RSS_REQUEST_HEADERS, timeout=timeout)
    if response.status_code in (401, 403, 406):
        response = requests.get(feed_url, timeout=timeout)
    response.raise_for_status()
    return response


def _provider_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "xiaoyuzhoufm.com" in host or "xyzcdn.net" in host or "xyzfm.space" in host:
        return "xiaoyuzhou"
    if "ximalaya.com" in host or "xima.tv" in host:
        return "ximalaya"
    if "music.163.com" in host or "163cn.tv" in host:
        return "netease"
    if "bilibili.com" in host or "b23.tv" in host:
        return "bilibili"
    return "rss"


def is_safe_public_url(url: str) -> bool:
    """拒绝本机、内网和非 HTTP(S) 地址，避免内容发现入口被用于访问本地服务。"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        hostname = parsed.hostname.casefold()
        if hostname in ("localhost", "localhost.localdomain") or hostname.endswith(".local"):
            return False
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return True
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )
    except ValueError:
        return False


def _source(provider: str, url: str, role: str, recommended: bool = False) -> dict[str, Any]:
    labels = {
        "apple": "Apple Podcasts",
        "podcastindex": "Podcast Index",
        "rss": "公开 RSS",
        "xiaoyuzhou": "小宇宙",
        "ximalaya": "喜马拉雅",
        "netease": "网易云音乐",
        "bilibili": "Bilibili",
    }
    return {
        "provider": provider,
        "label": labels.get(provider, provider),
        "url": url,
        "role": role,
        "recommended": recommended,
    }


def _clean_text(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def recover_episode_metadata(feed_url: str, audio_url: str = "", title: str = "") -> dict[str, Any]:
    """从原 RSS 重新找回单集简介和封面；用于归档完整性修复。"""
    if not is_safe_public_url(feed_url):
        return {}
    response = _get_rss(feed_url, timeout=12)
    if len(response.content) > 12 * 1024 * 1024:
        raise ValueError("RSS 文件过大")
    root = ET.fromstring(response.content)
    channel = root.find("channel")
    if channel is None:
        channel = root.find("./{*}channel")
    if channel is None:
        return {}

    def node_text(node: ET.Element, paths: tuple[str, ...]) -> str:
        for path in paths:
            child = node.find(path)
            if child is not None and child.text:
                value = _clean_text(child.text)
                if value:
                    return value
        return ""

    channel_cover = ""
    image = channel.find("image/url")
    if image is not None and image.text:
        channel_cover = image.text.strip()
    for child in channel:
        if child.tag.endswith("image") and child.attrib.get("href"):
            channel_cover = child.attrib["href"].strip()

    normalized_audio = audio_url.split("?", 1)[0]
    matched = None
    for item in channel.findall("item") + channel.findall("{*}item"):
        enclosure = item.find("enclosure")
        if enclosure is None:
            enclosure = item.find("{*}enclosure")
        enclosure_url = (enclosure.attrib.get("url", "") if enclosure is not None else "").strip()
        item_title = node_text(item, ("title", "{*}title"))
        if (normalized_audio and enclosure_url.split("?", 1)[0] == normalized_audio) or (
            title and item_title.casefold() == title.casefold()
        ):
            matched = item
            break
    if matched is None:
        return {}

    description = node_text(matched, ("{http://purl.org/rss/1.0/modules/content/}encoded", "{*}summary", "description", "{*}description"))
    cover_url = channel_cover
    for child in matched:
        if child.tag.endswith("image") and child.attrib.get("href"):
            cover_url = child.attrib["href"].strip()
    return {"description": description, "cover_url": cover_url}


def _episode_key(show: str, title: str, published_at: str, audio_url: str) -> str:
    raw = "|".join((show.casefold().strip(), title.casefold().strip(), published_at[:10], audio_url))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def search_podcast_shows(query: str, limit: int = 12) -> list[dict[str, Any]]:
    """按节目系列搜索；单集历史随后直接从节目 RSS 读取。"""
    response = requests.get(
        APPLE_SEARCH_URL,
        params={"term": query, "media": "podcast", "entity": "podcast", "country": "CN", "lang": "zh_cn", "limit": min(max(limit, 1), 30)},
        headers=REQUEST_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    shows = []
    for item in response.json().get("results", []):
        feed_url = str(item.get("feedUrl") or "").strip()
        title = _clean_text(item.get("collectionName"))
        if not feed_url or not title or not is_safe_public_url(feed_url):
            continue
        shows.append({
            "id": str(item.get("collectionId") or hashlib.sha1(feed_url.encode()).hexdigest()),
            "title": title,
            "author": _clean_text(item.get("artistName")),
            "description": "",
            "feed_url": feed_url,
            "page_url": str(item.get("collectionViewUrl") or ""),
            "cover_url": str(item.get("artworkUrl600") or item.get("artworkUrl100") or ""),
            "episode_count": int(item.get("trackCount") or 0),
            "provider": "apple",
        })
    return shows


def fetch_apple_show(collection_id: str, feed_url: str = "", page_url: str = "") -> dict[str, Any]:
    """RSS 不可用时，从 Apple 目录读取其当前收录的节目和单集。"""
    if not collection_id.isdigit():
        raise ValueError("无效的 Apple 节目 ID")
    response = requests.get(
        APPLE_LOOKUP_URL,
        params={"id": collection_id, "entity": "podcastEpisode", "limit": 200, "country": "CN", "lang": "zh_cn"},
        headers=REQUEST_HEADERS,
        timeout=12,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    show_item = next((item for item in results if item.get("kind") == "podcast"), {})
    show_title = _clean_text(show_item.get("collectionName") or show_item.get("trackName"))
    show_cover = str(show_item.get("artworkUrl600") or show_item.get("artworkUrl100") or "")
    actual_feed = str(show_item.get("feedUrl") or feed_url)
    actual_page = str(show_item.get("collectionViewUrl") or page_url)
    episodes = []
    for item in results:
        if item.get("wrapperType") != "podcastEpisode":
            continue
        audio_url = str(item.get("episodeUrl") or "").strip()
        title = _clean_text(item.get("trackName"))
        if not audio_url or not title or not is_safe_public_url(audio_url):
            continue
        published_at = str(item.get("releaseDate") or "")
        provider = _provider_for_url(audio_url)
        episode_cover = str(item.get("artworkUrl600") or item.get("artworkUrl160") or item.get("artworkUrl100") or show_cover)
        episodes.append({
            "id": _episode_key(show_title, title, published_at, audio_url), "title": title,
            "show_title": show_title, "description": _clean_text(item.get("description") or item.get("shortDescription")),
            "published_at": published_at, "duration_seconds": int((item.get("trackTimeMillis") or 0) / 1000),
            "cover_url": episode_cover, "cover_candidates": [url for url in (episode_cover, show_cover) if url],
            "audio_url": audio_url, "page_url": str(item.get("trackViewUrl") or actual_page),
            "feed_url": actual_feed, "recommended_provider": provider,
            "sources": [_source(provider, audio_url, "audio", True), _source("apple", actual_page, "catalog")],
        })
    episodes.sort(key=lambda episode: episode.get("published_at", ""), reverse=True)
    if not show_title or not episodes:
        raise ValueError("Apple 目录没有可用单集")
    return {
        "id": collection_id, "title": show_title, "author": _clean_text(show_item.get("artistName")),
        "description": "", "feed_url": actual_feed, "page_url": actual_page, "cover_url": show_cover,
        "episode_count": len(episodes), "provider": "apple", "episodes": episodes,
    }


def _parse_duration(value: str) -> int:
    value = (value or "").strip()
    if value.isdigit():
        return int(value)
    try:
        parts = [int(part) for part in value.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    except ValueError:
        pass
    return 0


def fetch_podcast_show(feed_url: str, page_url: str = "") -> dict[str, Any]:
    """读取节目 RSS 中当前仍公开的全部单集和节目元数据。"""
    if not is_safe_public_url(feed_url):
        raise ValueError("无效的 RSS 地址")
    response = _get_rss(feed_url, timeout=15)
    if len(response.content) > 20 * 1024 * 1024:
        raise ValueError("RSS 文件过大")
    root = ET.fromstring(response.content)
    channel = root.find("channel")
    if channel is None:
        channel = root.find("./{*}channel")
    if channel is None:
        raise ValueError("无法识别 RSS 节目结构")

    def text_at(node: ET.Element, *paths: str) -> str:
        for path in paths:
            child = node.find(path)
            if child is not None and child.text:
                value = _clean_text(child.text)
                if value:
                    return value
        return ""

    title = text_at(channel, "title", "{*}title")
    author = text_at(channel, "{*}author", "{*}creator", "author")
    description = text_at(channel, "{http://purl.org/rss/1.0/modules/content/}encoded", "{*}summary", "description", "{*}description")
    cover_url = ""
    image_node = channel.find("image/url")
    if image_node is not None and image_node.text:
        cover_url = image_node.text.strip()
    for child in channel:
        if child.tag.endswith("image") and child.attrib.get("href"):
            cover_url = child.attrib["href"].strip()

    episodes = []
    seen_items: set[str] = set()
    for item in channel.findall("item") + channel.findall("{*}item"):
        enclosure = item.find("enclosure")
        if enclosure is None:
            enclosure = item.find("{*}enclosure")
        audio_url = (enclosure.attrib.get("url", "") if enclosure is not None else "").strip()
        episode_title = text_at(item, "title", "{*}title")
        if not audio_url or not episode_title or audio_url in seen_items or not is_safe_public_url(audio_url):
            continue
        seen_items.add(audio_url)
        published_raw = text_at(item, "pubDate", "{*}date")
        try:
            published_at = parsedate_to_datetime(published_raw).isoformat() if published_raw else ""
        except (TypeError, ValueError, OverflowError):
            published_at = published_raw
        episode_cover_candidates = []
        for child in item:
            local_name = child.tag.rsplit("}", 1)[-1].casefold()
            if local_name == "image" and child.attrib.get("href"):
                episode_cover_candidates.append(child.attrib["href"].strip())
            elif local_name == "thumbnail" and child.attrib.get("url"):
                episode_cover_candidates.append(child.attrib["url"].strip())
            elif local_name == "content" and child.attrib.get("url"):
                media_type = str(child.attrib.get("type") or "").casefold()
                medium = str(child.attrib.get("medium") or "").casefold()
                if media_type.startswith("image/") or medium == "image":
                    episode_cover_candidates.append(child.attrib["url"].strip())
        episode_cover_candidates = [url for url in episode_cover_candidates if is_safe_public_url(url)]
        episode_cover = episode_cover_candidates[0] if episode_cover_candidates else cover_url
        link = text_at(item, "link", "{*}link") or page_url
        provider = _provider_for_url(audio_url)
        episodes.append({
            "id": _episode_key(title, episode_title, published_at, audio_url),
            "title": episode_title,
            "show_title": title,
            "description": text_at(item, "{http://purl.org/rss/1.0/modules/content/}encoded", "{*}summary", "description", "{*}description"),
            "published_at": published_at,
            "duration_seconds": _parse_duration(text_at(item, "{*}duration", "duration")),
            "cover_url": episode_cover,
            "cover_candidates": list(dict.fromkeys([*episode_cover_candidates, cover_url])) if cover_url else episode_cover_candidates,
            "audio_url": audio_url,
            "page_url": link,
            "feed_url": feed_url,
            "recommended_provider": provider,
            "sources": [_source(provider, audio_url, "audio", True), _source("rss", feed_url, "feed")],
        })
    episodes.sort(key=lambda episode: episode.get("published_at", ""), reverse=True)
    return {
        "id": hashlib.sha1(feed_url.encode()).hexdigest(), "title": title, "author": author,
        "description": description, "feed_url": feed_url, "page_url": page_url,
        "cover_url": cover_url, "episode_count": len(episodes), "provider": "rss", "episodes": episodes,
    }


def _apple_search(query: str, limit: int) -> list[dict[str, Any]]:
    response = requests.get(
        APPLE_SEARCH_URL,
        params={
            "term": query,
            "media": "podcast",
            "entity": "podcastEpisode",
            "country": "CN",
            "lang": "zh_cn",
            "limit": min(max(limit, 1), 50),
        },
        headers=REQUEST_HEADERS,
        timeout=10,
    )
    response.raise_for_status()
    episodes = []
    for item in response.json().get("results", []):
        audio_url = str(item.get("episodeUrl") or "").strip()
        title = _clean_text(item.get("trackName"))
        show = _clean_text(item.get("collectionName"))
        if not audio_url or not title:
            continue
        audio_provider = _provider_for_url(audio_url)
        page_url = str(item.get("trackViewUrl") or item.get("collectionViewUrl") or "")
        feed_url = str(item.get("feedUrl") or "")
        sources = [_source(audio_provider, audio_url, "audio", True)]
        if feed_url:
            sources.append(_source("rss", feed_url, "feed"))
        if page_url:
            sources.append(_source("apple", page_url, "catalog"))
        published_at = str(item.get("releaseDate") or "")
        episodes.append({
            "id": _episode_key(show, title, published_at, audio_url),
            "title": title,
            "show_title": show,
            "description": _clean_text(item.get("description") or item.get("shortDescription")),
            "published_at": published_at,
            "duration_seconds": int((item.get("trackTimeMillis") or 0) / 1000),
            "cover_url": item.get("artworkUrl600") or item.get("artworkUrl100") or "",
            "audio_url": audio_url,
            "page_url": page_url,
            "feed_url": feed_url,
            "recommended_provider": audio_provider,
            "sources": sources,
        })
    return episodes


def _podcast_index_headers() -> dict[str, str] | None:
    api_key = os.environ.get("PODCASTINDEX_API_KEY", "").strip()
    api_secret = os.environ.get("PODCASTINDEX_API_SECRET", "").strip()
    if not api_key or not api_secret:
        return None
    auth_date = str(int(datetime.now().timestamp()))
    signature = hashlib.sha1((api_key + api_secret + auth_date).encode("utf-8")).hexdigest()
    return {
        **REQUEST_HEADERS,
        "X-Auth-Date": auth_date,
        "X-Auth-Key": api_key,
        "Authorization": signature,
    }


def _podcast_index_search(query: str, limit: int) -> list[dict[str, Any]]:
    headers = _podcast_index_headers()
    if headers is None:
        return []
    response = requests.get(
        f"{PODCAST_INDEX_URL}/search/byterm",
        params={"q": query, "max": min(max(limit, 1), 20)},
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    # Podcast Index 的关键词接口主要返回节目。开发版先将其作为来源补充；
    # 单集音频仍以 Apple/RSS 目录结果为可入队对象。
    return []


def search_podcast_episodes(query: str, limit: int = 24) -> dict[str, Any]:
    query = query.strip()
    if not query:
        return {"episodes": [], "providers": []}

    providers = [
        {"id": "apple", "label": "Apple Podcasts 中国区", "status": "available"},
        {
            "id": "podcastindex",
            "label": "Podcast Index",
            "status": "available" if _podcast_index_headers() else "not_configured",
        },
        {"id": "rss", "label": "公开 RSS / 音频源", "status": "available"},
    ]
    episodes: list[dict[str, Any]] = []
    errors: list[str] = []
    searches = (("apple", _apple_search), ("podcastindex", _podcast_index_search))
    with ThreadPoolExecutor(max_workers=len(searches)) as executor:
        futures = {name: executor.submit(searcher, query, limit) for name, searcher in searches}
        for name, future in futures.items():
            try:
                episodes.extend(future.result())
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                for provider in providers:
                    if provider["id"] == name:
                        provider["status"] = "unavailable"

    merged: dict[str, dict[str, Any]] = {}
    for episode in episodes:
        merge_key = "|".join((
            episode["show_title"].casefold(),
            re.sub(r"\W+", "", episode["title"].casefold()),
            episode["published_at"][:10],
        ))
        if merge_key not in merged:
            merged[merge_key] = episode
            continue
        known = {(source["provider"], source["url"]) for source in merged[merge_key]["sources"]}
        merged[merge_key]["sources"].extend(
            source for source in episode["sources"]
            if (source["provider"], source["url"]) not in known
        )

    return {
        "episodes": list(merged.values())[:limit],
        "providers": providers,
        "errors": errors,
    }
