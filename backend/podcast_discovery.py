"""播客内容发现：统一外部目录结果，并优先返回中国大陆可处理的音频来源。"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import requests


APPLE_SEARCH_URL = "https://itunes.apple.com/search"
PODCAST_INDEX_URL = "https://api.podcastindex.org/api/1.0"
REQUEST_HEADERS = {
    "User-Agent": "PodGist/0.2.7 (+https://github.com/TobyKSKGD/PodGist)",
    "Accept": "application/json",
}


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


def _episode_key(show: str, title: str, published_at: str, audio_url: str) -> str:
    raw = "|".join((show.casefold().strip(), title.casefold().strip(), published_at[:10], audio_url))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


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
