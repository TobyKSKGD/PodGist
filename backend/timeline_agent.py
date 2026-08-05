"""
timeline_agent.py — 时间轴模式专用生成链路（Program-Slices-Span, Model-Writes-Content）

协议重构：程序切段，模型写内容。
- 程序先基于 transcript segments 自然边界切分连续 span
- 程序确定 span 的 start/end/time/seg_start_idx/seg_end_idx
- 模型只负责为每个 span 输出 title/summary/entities 等内容字段
- 不再让模型决定节点边界
- 程序负责 URL 解析（references），模型只提供候选实体
"""

import json
import re
import time
import os
import urllib.parse
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

from dashscope import Generation
from http import HTTPStatus

TIMELINE_MODEL = 'qwen-plus'


def _timeline_llm_concurrency() -> int:
    """读取可选并发配置；无效值回退到保守的默认值。"""
    try:
        return max(1, min(3, int(os.environ.get('PODGIST_TIMELINE_LLM_CONCURRENCY', '2'))))
    except (TypeError, ValueError):
        return 2


TIMELINE_LLM_CONCURRENCY = _timeline_llm_concurrency()

# ---------------------------------------------------------------------------
# LLM 调用
# ---------------------------------------------------------------------------

def _call_llm_json(api_key: str, messages: list, temperature: float = 0.3) -> dict:
    last_err = None
    for attempt in range(3):
        try:
            response = Generation.call(
                model=TIMELINE_MODEL,
                messages=messages,
                result_format="message",
                temperature=temperature,
                api_key=api_key,
                request_timeout=600,
            )
            if response.status_code == HTTPStatus.OK:
                content = response.output.choices[0].message.content
                return _extract_json(content)
            else:
                last_err = Exception(f"LLM error: status={response.code} msg={response.message}")
        except Exception as e:
            last_err = e
        if attempt < 2:
            time.sleep(3)
    raise last_err or Exception("LLM 调用失败")


def _extract_json(content: str) -> dict:
    content = content.strip()
    json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', content)
    if json_match:
        return json.loads(json_match.group(1))
    array_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', content)
    if array_match:
        return {"nodes": json.loads(array_match.group(1))}
    if content.startswith('{'):
        return json.loads(content)
    if content.startswith('['):
        return {"nodes": json.loads(content)}
    raise ValueError(f"无法从输出中提取 JSON: {content[:200]}")


def _format_time(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


# ---------------------------------------------------------------------------
# URL 解析服务（程序侧，非 LLM 直接生成）
# 来源层级：official > encyclopedia > media > community
# ---------------------------------------------------------------------------

# 来源层级定义（数值越高越可信）
SOURCE_TIERS = {
    "official": 4,
    "encyclopedia": 3,
    "media": 2,
    "community": 1,
}
SOURCE_LABELS = {
    "official": "官方",
    "encyclopedia": "百科",
    "media": "媒体",
    "community": "社区",
}

# 图片来源与资料来源分开处理：资料仍以可信度为主，图片则优先选取中国大陆
# 网络可访问性更好的页面。升级该版本会使用新的实体缓存键，避免继续复用旧的
# Wikipedia 图片 URL。
ENTITY_IMAGE_RESOLVER_VERSION = "mainland-v1"
DOMESTIC_IMAGE_PAGE_TIMEOUT_SECONDS = 3
FALLBACK_IMAGE_PAGE_TIMEOUT_SECONDS = 5
_MAINLAND_FRIENDLY_IMAGE_DOMAINS = (
    "baike.baidu.com", "baidu.com", "bdimg.com", "bcebos.com",
    "douban.com", "doubanio.com", "bilibili.com", "hdslb.com",
    "qq.com", "qpic.cn", "163.com", "music.126.net",
    "xiaoyuzhoufm.com", "xmcdn.com", "ximalaya.com",
)


def _entity_enrichment_cache_key(entity_name: str, entity_kind: str) -> str:
    """图片策略升级时用版本隔离缓存，旧实体会在下次富化时重新解析。"""
    return f"{ENTITY_IMAGE_RESOLVER_VERSION}:{entity_kind}:{entity_name.casefold()}"


def _is_mainland_friendly_url(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower().split(":", 1)[0]
    except ValueError:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in _MAINLAND_FRIENDLY_IMAGE_DOMAINS)


def _http_get(url: str, timeout: int = 5) -> Optional[str]:
    """轻量 GET，失败返回 None（统一使用 requests）"""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 PodGist/1.0"},
            timeout=timeout,
        )
        if resp.status_code == 200:
            return resp.text
        print(f"[HTTP GET] {url} → status={resp.status_code}")
    except requests.exceptions.Timeout:
        print(f"[HTTP GET] {url} → timeout ({timeout}s)")
    except requests.exceptions.RequestException as e:
        print(f"[HTTP GET] {url} → {type(e).__name__}: {e}")
    except Exception as e:
        print(f"[HTTP GET] {url} → {type(e).__name__}: {e}")
    return None


def _http_get_bytes(url: str, timeout: int = 8) -> Optional[bytes]:
    """下载图片等二进制资源，失败返回 None。返回原始字节，不做解码（统一使用 requests）。"""
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 PodGist/1.0",
                "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                "Referer": "https://www.google.com/",
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            print(f"[HTTP GET BYTES] {url} → status={resp.status_code}")
            return None
        # 验证 Content-Type 必须是图片
        content_type = resp.headers.get("Content-Type", "").lower()
        if not content_type.startswith("image/"):
            print(f"[HTTP GET BYTES] {url} → non-image Content-Type: {content_type}")
            return None
        # 过滤非图片 MIME（有些服务器错误地返回 text/html 或 application/octet-stream）
        # 同时禁用 SVG（XML 格式，浏览器兼容性问题多，当前阶段不稳定）
        forbidden = ("text/html", "application/octet-stream", "application/json", "image/svg+xml")
        if any(ct in content_type for ct in forbidden):
            print(f"[HTTP GET BYTES] {url} → forbidden Content-Type: {content_type}")
            return None
        data = resp.content
        # 最小文件大小过滤（太小可能是 favicon/占位图/错误页）
        if len(data) < 5000:
            print(f"[HTTP GET BYTES] {url} → too small: {len(data)} bytes")
            return None
        return data
    except requests.exceptions.Timeout:
        print(f"[HTTP GET BYTES] {url} → timeout ({timeout}s)")
    except requests.exceptions.RequestException as e:
        print(f"[HTTP GET BYTES] {url} → {type(e).__name__}: {e}")
    except Exception as e:
        print(f"[HTTP GET BYTES] {url} → {type(e).__name__}: {e}")
    return None


def _best_result(results: list) -> Optional[dict]:
    """从多个候选结果中选择最优的（按 sourceTier > confidence > 匹配度）"""
    if not results:
        return None
    results.sort(key=lambda r: (
        SOURCE_TIERS.get(r.get("sourceTier", "community"), 0),
        r.get("confidence", 0),
    ), reverse=True)
    return results[0]


def _normalize_title_match(query: str, title: str) -> float:
    """返回 0~1 的标题匹配度分数"""
    q = query.lower().replace('-', '').replace(' ', '').replace('_', '')
    t = title.lower().replace('-', '').replace(' ', '').replace('_', '')
    if q == t:
        return 1.0
    if q in t or t in q:
        return 0.85
    # 部分匹配
    q_chars = set(q)
    t_chars = set(t)
    overlap = len(q_chars & t_chars) / max(len(q_chars), 1)
    return overlap * 0.6 if overlap > 0.5 else 0


# ---- 百度百科 ----
def _resolve_baidu_baike(query: str) -> Optional[dict]:
    """百度百科搜索"""
    search_url = (
        "https://www.baidu.com/s?wd="
        f"{urllib.parse.quote(query + ' 百度百科')}"
        "&rn=1&ie=utf-8"
    )
    text = _http_get(search_url)
    if not text:
        return None
    try:
        # 从搜索结果中提取百度百科链接
        baike_match = re.search(r'href="(https?://baike\.baidu\.com/item[^"#]+)"', text)
        if not baike_match:
            baike_match = re.search(r'href="([^"]+baike\.baidu\.com[^"]+)"', text)
        if baike_match:
            url = baike_match.group(1).split('?')[0].split('#')[0]
            title_match = re.search(r'>([^<]*' + re.escape(query) + r'[^<]*百科[^<]*)<', text)
            title = title_match.group(1).strip() if title_match else query
            match_score = _normalize_title_match(query, title)
            return {
                "title": re.sub(r'[（）()【】\[\]]', '', title)[:60],
                "url": url[:200],
                "sourceTier": "encyclopedia",
                "confidence": 0.82 if match_score > 0.7 else 0.65,
                "note": "AI 生成，请自行判断",
            }
    except Exception:
        pass
    return None


# ---- 维基百科（中英文） ----
def _resolve_wikipedia(query: str, clean_query: str) -> Optional[dict]:
    """中英文 Wikipedia 搜索，返回最优结果"""

    def _search_wiki(lang: str, q: str) -> Optional[dict]:
        search_url = (
            f"https://{lang}.wikipedia.org/w/api.php"
            "?action=opensearch"
            f"&search={urllib.parse.quote(q)}"
            "&limit=1"
            "&namespace=0"
            "&format=json"
        )
        text = _http_get(search_url)
        if not text:
            return None
        try:
            data = json.loads(text)
            if not data or len(data) < 4:
                return None
            titles = data[1]
            urls = data[3]
            if not titles or not urls or not titles[0] or not urls[0]:
                return None
            title = titles[0]
            url = urls[0]
            match_score = _normalize_title_match(q, title)
            confidence = 0.85 if match_score > 0.75 else 0.65
            return {
                "title": title[:60],
                "url": url,
                "sourceTier": "encyclopedia",
                "confidence": confidence,
                "note": "AI 生成，请自行判断",
            }
        except Exception:
            return None

    results = []
    r1 = _search_wiki("en", clean_query)
    if r1:
        results.append(r1)
    r2 = _search_wiki("zh", clean_query)
    if r2:
        results.append(r2)
    return _best_result(results)


# ---- GitHub ----
def _resolve_github(query: str) -> Optional[dict]:
    """GitHub 仓库搜索"""
    search_url = (
        "https://api.github.com/search/repositories"
        f"?q={urllib.parse.quote(query)}"
        "&sort=stars"
        "&order=desc"
        "&per_page=3"
    )
    text = _http_get(search_url)
    if not text:
        return None
    try:
        data = json.loads(text)
        items = data.get("items", [])
        if not items:
            return None
        repo = items[0]
        return {
            "title": repo.get("full_name", query),
            "url": repo.get("html_url", ""),
            "sourceTier": "media",
            "confidence": 0.8,
            "note": "AI 生成，请自行判断",
        }
    except Exception:
        return None


# ---- 官方域名直接匹配 ----
# 按实体类型分配官方域名
_OFFICIAL_PATTERNS: list[tuple[str, str, str, str]] = [
    # (关键词, 显示名, 官网URL, 实体kind)
    ("youtube", "YouTube", "https://www.youtube.com", "company"),
    ("bilibili", "Bilibili", "https://www.bilibili.com", "company"),
    ("哔哩哔哩", "Bilibili", "https://www.bilibili.com", "company"),
    ("b站", "Bilibili", "https://www.bilibili.com", "company"),
    ("tencent", "Tencent", "https://www.tencent.com", "company"),
    ("bytedance", "ByteDance", "https://www.bytedance.com", "company"),
    ("alibaba", "Alibaba", "https://www.alibaba.com", "company"),
    ("baidu", "Baidu", "https://www.baidu.com", "company"),
    ("meta", "Meta", "https://www.meta.com", "company"),
    ("nvidia", "NVIDIA", "https://www.nvidia.com", "company"),
    ("openai", "OpenAI", "https://openai.com", "company"),
    ("microsoft", "Microsoft", "https://www.microsoft.com", "company"),
    ("google", "Google", "https://www.google.com", "company"),
    ("apple", "Apple", "https://www.apple.com", "company"),
    ("amazon", "Amazon", "https://www.amazon.com", "company"),
    ("spacex", "SpaceX", "https://www.spacex.com", "company"),
    ("tesla", "Tesla", "https://www.tesla.com", "company"),
    ("amd", "AMD", "https://www.amd.com", "company"),
    ("intel", "Intel", "https://www.intel.com", "company"),
    ("snapdragon", "Snapdragon", "https://www.qualcomm.com/snapdragon", "product"),
    ("apple podcasts", "Apple Podcasts", "https://podcasts.apple.com", "product"),
    ("小宇宙", "小宇宙", "https://www.xiaoyuzhoufm.com", "product"),
    ("喜马拉雅", "喜马拉雅", "https://www.ximalaya.com", "product"),
    ("网易云音乐", "网易云音乐", "https://music.163.com", "product"),
    ("网易云", "网易云音乐", "https://music.163.com", "product"),
    ("微信", "微信", "https://www.wechat.com", "product"),
    ("滴滴", "滴滴", "https://www.didiglobal.com", "company"),
    ("抖音", "抖音", "https://www.douyin.com", "product"),
    ("抖音", "抖音", "https://www.douyin.com", "company"),
    ("美团", "美团", "https://www.meituan.com", "company"),
    ("拼多多", "拼多多", "https://www.pinduoduo.com", "company"),
    ("京东", "京东", "https://www.jd.com", "company"),
    ("阿里巴巴", "阿里巴巴", "https://www.alibaba.com", "company"),
    ("腾讯音乐", "腾讯音乐", "https://www.tencent.com", "company"),
]


def _try_official_url(entity_name: str) -> Optional[dict]:
    """尝试通过已知官方域名构建 URL"""
    key = entity_name.lower()
    for kw, title, url, _ in _OFFICIAL_PATTERNS:
        if kw in key or key in kw:
            return {
                "title": title,
                "url": url,
                "sourceTier": "official",
                "confidence": 0.88,
                "note": "AI 生成，请自行判断",
            }
    return None


# ---- Steam / TapTap ----
def _resolve_game_store(query: str) -> Optional[dict]:
    """Steam 商店搜索（游戏）"""
    search_url = (
        f"https://store.steampowered.com/search/?term={urllib.parse.quote(query)}&format=json"
    )
    text = _http_get(search_url)
    if not text:
        return None
    try:
        # Steam search 结果含 HTML，简单提取第一个结果链接和标题
        match = re.search(
            r'href="(https://store\.steampowered\.com/app/\d+[^"]*)"[^>]*>.*?<img[^>]*title="([^"]+)"',
            text, re.DOTALL
        )
        if not match:
            match = re.search(r'href="(https://store\.steampowered\.com/app/\d+[^"]*)"', text)
        if match:
            url = match.group(1).split('?')[0]
            title = match.group(2).strip() if match.lastindex and match.group(2) else query
            return {
                "title": title[:60],
                "url": url,
                "sourceTier": "official",
                "confidence": 0.82,
                "note": "AI 生成，请自行判断",
            }
    except Exception:
        pass
    return None


# ---- 豆瓣 ----
def _resolve_douban(query: str) -> Optional[dict]:
    """豆瓣搜索（影视/作品）"""
    search_url = (
        f"https://www.douban.com/search?cat=1002&q={urllib.parse.quote(query)}"
    )
    text = _http_get(search_url)
    if not text:
        return None
    try:
        match = re.search(
            r'href="(https://www\.douban\.com/subject/\d+[^"]*)"[^>]*>.*?title="([^"]+)"',
            text, re.DOTALL
        )
        if match:
            url = match.group(1).split('?')[0]
            title = match.group(2).strip()[:60]
            match_score = _normalize_title_match(query, title)
            return {
                "title": title,
                "url": url,
                "sourceTier": "media",
                "confidence": 0.78 if match_score > 0.6 else 0.65,
                "note": "AI 生成，请自行判断",
            }
    except Exception:
        pass
    return None


def _resolve_douban_book(query: str) -> Optional[dict]:
    """豆瓣读书检索，补足影视搜索无法覆盖的书籍与非虚构作品。"""
    search_url = (
        "https://book.douban.com/subject_search?search_text="
        f"{urllib.parse.quote(query)}"
    )
    text = _http_get(search_url)
    if not text:
        return None
    try:
        match = re.search(r'https?://book\.douban\.com/subject/(\d+)/', text)
        if not match:
            return None
        url = f"https://book.douban.com/subject/{match.group(1)}/"
        return {
            "title": query[:60],
            "url": url,
            "sourceTier": "media",
            "confidence": 0.78,
            "note": "AI 生成，请自行判断",
        }
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        print(f"[Reference] 豆瓣读书解析失败: {type(exc).__name__}: {exc}")
        return None


def _resolve_entity_reference(entity_name: str, entity_kind: str) -> Optional[dict]:
    """
    为单个实体解析参考链接（per-entity 版本）。
    返回带 sourceTier 的结果字典，或 None。

    来源优先级（按 kind 分）：
      company/product/other → 官方域名 → 高匹配度百度百科 → Wikipedia
      tool/repo → 官方域名 → Wikipedia
      game/film/media → Steam/豆瓣 → Wikipedia → 百度百科

    对可确认的国内百科结果快速返回，避免即使已经命中仍串行请求中英文
    Wikipedia。这既缩短后台富化，也让后续图片优先落在大陆可达的页面上。
    """
    # 去噪声词
    clean = re.sub(r'[\[\]【】()（)《》<>""'']', '', entity_name).strip()
    if not clean or len(clean) < 2:
        return None

    # 预处理：去掉数字前缀
    clean_for_search = re.sub(
        r'^(?:\d+\s*[.。]?\s*|第[一二三四五六七八九十百千\d]+[节章节个条次号]?\s*)',
        '', clean
    )

    kind = entity_kind.lower()
    is_tool = kind in {"tool", "repo"}
    is_game_film = kind in {"game", "film", "media"}

    # 1. 官方域名（最高优先级）
    official = _try_official_url(clean)
    if official:
        return official

    # 2. 按类型分支
    if is_tool:
        # 工具/项目：官方域名（已查） → Wikipedia（GitHub 已暂时禁用）
        wiki = _resolve_wikipedia(clean, clean_for_search)
        return wiki if wiki and wiki.get("confidence", 0) >= 0.7 else None
    elif is_game_film:
        # 游戏/影视：Steam → 豆瓣 → Wikipedia。Steam/豆瓣命中后无需继续探测。
        steam = _resolve_game_store(clean)
        if steam and steam.get("confidence", 0) >= 0.7:
            return steam
        douban = _resolve_douban(clean)
        if douban and douban.get("confidence", 0) >= 0.7:
            return douban
        douban_book = _resolve_douban_book(clean)
        if douban_book and douban_book.get("confidence", 0) >= 0.7:
            return douban_book
        wiki = _resolve_wikipedia(clean, clean_for_search)
        if wiki and wiki.get("confidence", 0) >= 0.7:
            return wiki
        # 百度百科作为游戏/影视的补充
        baidu = _resolve_baidu_baike(clean)
        return baidu if baidu and baidu.get("confidence", 0) >= 0.7 else None
    else:
        # 公司/品牌/产品/其他：高匹配度百度百科优先，Wiki 只作为回退。
        baidu = _resolve_baidu_baike(clean)
        if baidu and baidu.get("confidence", 0) >= 0.8:
            return baidu
        wiki = _resolve_wikipedia(clean, clean_for_search)
        if wiki and wiki.get("confidence", 0) >= 0.7:
            return wiki
        return baidu if baidu and baidu.get("confidence", 0) >= 0.7 else None


def _resolve_node_references(ref_candidates: list) -> list:
    """
    节点级引用（新闻/报告/文档/文章等，非实体解释型）。
    这类引用不映射到具体实体，放入 node.references[]。
    只保留 sourceTier >= encyclopedia 的结果。
    """
    refs = []
    seen_urls = set()
    for ent in ref_candidates[:6]:
        name = ent.get("name", "")
        kind = ent.get("kind", "webpage")
        ref = _resolve_entity_reference(name, kind)
        # 只保留 encyclopedia（维基/百科）及以上层级的节点级引用
        tier = SOURCE_TIERS.get(ref.get("sourceTier", "community"), 0) if ref else 0
        if ref and ref["url"] not in seen_urls and tier >= SOURCE_TIERS["encyclopedia"]:
            seen_urls.add(ref["url"])
            refs.append(ref)
            if len(refs) >= 3:
                break
    return refs


# ---------------------------------------------------------------------------
# Span 切分（程序侧）
# ---------------------------------------------------------------------------

def _slice_spans_by_topics(segments: list, audio_duration: float) -> list:
    """
    程序侧按话题自然边界切分 segment spans。

    策略：
    1. 扫描所有 segment 的文本，检测话题切换信号
    2. 额外检测"新实体/产品首次出现"作为切分信号
    3. 合并短于 MIN_SPAN_SECONDS 的相邻 span
    4. 拆分超长 span
    5. 保证覆盖整期节目，不留大空洞
    """

    if not segments:
        return []

    MIN_SPAN_SECONDS = 60
    MAX_SPAN_SECONDS = 300
    TOPIC_SWITCH_MARKERS = [
        "一、", "二、", "三、", "四、", "五、",
        "首先", "其次", "最后",
        "下面", "接下来", "另外", "还有",
        "刚才", "说到", "再补充",
        "欢迎来到", "这里是", "我是",
        "总之", "总的来说",
        "不过", "然而", "但是",
        "那么", "所以", "因此",
        "接下来", "然后", "我们先说",
        "进入", "来看看", "来聊聊",
    ]
    # 已知产品/公司名触发词（首次出现时常标志新话题）
    ENTITY_MARKERS = [
        "发布", "推出", "上线", "推出", "宣布",
        "推出", "发布", "推出",
        "收购", "获得", "完成",
        "万", "亿美元", "亿元",
    ]

    spans = []
    cur_start = 0
    # 追踪本 span 内已出现过的产品/公司名（避免重复切分）
    seen_entities_in_span: set[str] = set()

    for i in range(len(segments)):
        seg = segments[i]
        text = seg.get("text", "")

        # 检测话题切换
        prev_text = segments[i - 1].get("text", "") if i > 0 else ""
        is_switch = False
        for marker in TOPIC_SWITCH_MARKERS:
            if (marker in text or marker in prev_text) and i > cur_start:
                is_switch = True
                break

        # 检测新实体首次出现（带金额/产品词时更可能是新话题）
        has_new_entity = False
        for marker in ENTITY_MARKERS:
            if marker in text and len(text) < 200:
                # 提取附近的名词短语作为实体名
                for m in re.finditer(rf'{marker}\s*([\u4e00-\u9fa5a-zA-Z0-9（）\(\)《》]+)', text):
                    entity_mention = m.group(1).strip()
                    if entity_mention and entity_mention not in seen_entities_in_span:
                        # 跳过常见动词/副词
                        skip_words = {"一个", "这个", "那个", "我们", "他们", "一些", "很多", "什么", "怎么"}
                        if entity_mention not in skip_words and len(entity_mention) >= 2:
                            has_new_entity = True
                            seen_entities_in_span.add(entity_mention)
                            break
            if has_new_entity:
                break

        # 当前 span 时长
        span_end_seconds = segments[i].get("seconds", 0)
        span_duration = span_end_seconds - segments[cur_start].get("seconds", 0) if cur_start <= i else 0

        should_split = False
        if span_duration >= MAX_SPAN_SECONDS:
            should_split = True
        elif is_switch and span_duration >= MIN_SPAN_SECONDS:
            should_split = True
        elif has_new_entity and span_duration >= MIN_SPAN_SECONDS:
            should_split = True

        if should_split:
            spans.append({
                "seg_start_idx": cur_start,
                "seg_end_idx": i - 1,
                "start": segments[cur_start].get("seconds", 0),
                "end": segments[i - 1].get("seconds", 0),
                "time": _format_time(segments[cur_start].get("seconds", 0)),
            })
            cur_start = i
            seen_entities_in_span.clear()

    # 最后一个 span
    if cur_start < len(segments):
        spans.append({
            "seg_start_idx": cur_start,
            "seg_end_idx": len(segments) - 1,
            "start": segments[cur_start].get("seconds", 0),
            "end": segments[-1].get("seconds", 0),
            "time": _format_time(segments[cur_start].get("seconds", 0)),
        })

    # 合并时长过短的 span
    merged = []
    for span in spans:
        if not merged:
            merged.append(span)
            continue
        last = merged[-1]
        span_dur = span["start"] - last["end"]
        if span_dur < 0:
            last["seg_end_idx"] = span["seg_end_idx"]
            last["end"] = span["end"]
        elif last["end"] - last["start"] < MIN_SPAN_SECONDS:
            last["seg_end_idx"] = span["seg_end_idx"]
            last["end"] = span["end"]
        else:
            merged.append(span)

    for span in merged:
        span["time"] = _format_time(span["start"])

    return merged


def _get_span_text(segments: list, seg_start: int, seg_end: int) -> str:
    """提取 span 内的完整文本用于模型输入"""
    lines = []
    for i in range(seg_start, min(seg_end + 1, len(segments))):
        seg = segments[i]
        lines.append(f"[{seg.get('time', '00:00')}] {seg.get('text', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 模型调用（写内容）
# ---------------------------------------------------------------------------

def _generate_content_for_span(
    api_key: str,
    span_text: str,
    span_start: int,
    span_end: int,
    span_time: str,
    span_index: int,
    total_spans: int,
    audio_duration: float
) -> dict:
    """调用模型为单个 span 输出内容字段（不含时间边界）"""
    system_prompt = """你是一个播客内容分析专家，擅长从播客转录片段中提取结构化摘要。

输出格式：纯 JSON 对象，不要 markdown 包裹，不要任何解释文字。
字段说明：
- title: 节点标题（10字以内，概括这段在讲什么）
- node_type: 节点内容类型，从以下选项中选择最准确的一个：
  company_news（公司财报/战略/合作动态）、
  product（产品发布/评测）、
  person（人物动态/专访）、
  topic_change（话题切换/承上启下）、
  background（背景知识/行业概况）、
  fun_moment（趣味片段/金句/梗）、
  other（不属于以上类型的杂项）
- summary: 这段主要说了什么（1-3句话）
- why_it_matters: 为什么这个节点重要（1句话）
- entities: 提到的公司/人/产品/地点列表，每项须包含 name/type/description：
  - name: 实体名称
  - type: company|product|person|location|concept|media|other
  - description: 在本期语境下的简要解释（1句话）
- facts: 具体事实列表，每项须包含 label/value：
  - label: 事实标签（如"市值"、"发布时间"、"同比增长"等）
  - value: 具体事实内容
- quote_or_joke_explainer: 梗/双关/上下文解释（无则空字符串）
- reference_candidates: 本段中提到的值得查证的实体列表，每项需含 name/kind/keywords：
  - name: 实体准确名称
  - kind: 该实体类型，取值 tool|company|product|game|film|article|person|location|webpage
  - keywords: 用于搜索该实体官网/维基的关键词（英文，适合 API 搜索）
  注意：只列出你确定在转录中明确提到的实体，不要捏造。最多 4 项。
- skip_node: 是否应从时间轴中省略该片段。仅节目名称、主持人/嘉宾自我介绍、录制地点、欢迎语、例行开场、口播或赞助信息时必须为 true。

注意：节目名称、节目/播客品牌、主持人姓名、录制地点和例行开场信息的语音识别极不可靠，
除非它们是本段被深入讨论的主题，否则绝不能作为节点标题、摘要重点、实体、事实或参考候选输出。
若 skip_node 为 true，请返回空 entities、facts、reference_candidates，且不要把这些开场信息改写成内容节点。
只基于提供的转录片段输出，不要自由发挥时间或事实。"""

    user_prompt = f"""【转录片段 {span_index + 1}/{total_spans}】
时间范围：{span_time} ~ {_format_time(span_end)}（共 {span_end - span_start:.0f} 秒）

转录内容：
{span_text}

请生成这段的内容摘要（纯 JSON，不要 markdown 包裹，不要解释）："""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = _call_llm_json(api_key, messages, temperature=0.3)
        if isinstance(result, dict):
            return result
        return {}
    except Exception as e:
        print(f"  [Timeline] span {span_index} 生成失败: {e}")
        return {}


# ---------------------------------------------------------------------------
# 规范化工具
# ---------------------------------------------------------------------------

def _normalize_timeline(timeline: dict, audio_duration: float) -> dict:
    """合法性校验 + 过滤越界节点"""
    nodes = timeline.get("nodes", [])
    if not nodes:
        return timeline

    filtered = [n for n in nodes if (n.get("start", 0) or 0) < audio_duration]

    for n in filtered:
        end = n.get("end")
        if end is None or end <= 0 or end > audio_duration:
            n["end"] = audio_duration
        if n["end"] <= n["start"]:
            n["end"] = min(n["start"] + 60, audio_duration)

    filtered.sort(key=lambda n: n.get("start", 0) or 0)

    merged = []
    for n in filtered:
        if not merged:
            merged.append(n)
            continue
        last = merged[-1]
        last_end = last.get("end", 0) or 0
        last_start = last.get("start", 0) or 0
        n_start = n.get("start", 0) or 0
        n_end = n.get("end", 0) or 0

        overlap = last_end - n_start
        last_dur = last_end - last_start
        if overlap > 0 and last_dur > 0 and overlap / last_dur > 0.8:
            if n.get("summary"):
                last["summary"] = (last.get("summary", "") + " " + n.get("summary", "")).strip()
            if n.get("entities"):
                existing = {e["name"] for e in last.get("entities", [])}
                for e in n["entities"]:
                    if e["name"] not in existing:
                        last.setdefault("entities", []).append(e)
            last["end"] = max(last_end, n_end)
        else:
            merged.append(n)

    return {
        "mode": "timeline",
        "version": 2,
        "title": timeline.get("title", ""),
        "nodes": [{**n, "id": f"node_{i + 1:03d}"} for i, n in enumerate(merged)],
    }


_NODE_TYPE_ALIASES = {
    "company_news": "company_news", "company": "company_news", "公司动态": "company_news",
    "企业动态": "company_news", "企业": "company_news",
    "product": "product", "产品": "product", "产品发布": "product", "新品": "product",
    "person": "person", "人物": "person", "人物动态": "person", "人物专访": "person",
    "topic_change": "topic_change", "话题切换": "topic_change", "过渡": "topic_change",
    "承上启下": "topic_change",
    "background": "background", "背景": "background", "背景知识": "background",
    "行业背景": "background",
    "fun_moment": "fun_moment", "趣味": "fun_moment", "金句": "fun_moment",
    "quote": "fun_moment", "quote_or_joke_explainer": "fun_moment",
    "1": "other", "2": "other",
}


def _normalize_node_type(raw: str) -> str:
    if not raw:
        return "other"
    raw = raw.strip().lower()
    return _NODE_TYPE_ALIASES.get(raw, "other")


def _normalize_entities(raw: list) -> list:
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            if name:
                result.append({"name": name, "type": "other", "description": ""})
        elif isinstance(item, dict):
            name = item.get("name", "")
            if not name or not isinstance(name, str) or not name.strip():
                continue
            result.append({
                "name": name.strip(),
                "type": item.get("type", "other") or "other",
                "description": item.get("description", "") or "",
            })
    return result


def _normalize_facts(raw: list) -> list:
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if isinstance(item, str):
            value = item.strip()
            if value:
                result.append({"label": "事实", "value": value})
        elif isinstance(item, dict):
            label = item.get("label", "")
            value = item.get("value", "")
            if not isinstance(label, str):
                label = ""
            if not isinstance(value, str):
                value = ""
            if label.strip() or value.strip():
                result.append({"label": label.strip() or "事实", "value": value.strip()})
    return result


def _normalize_ref_candidates(raw: list) -> list:
    """规范化 reference_candidates 字段"""
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if isinstance(item, dict):
            name = item.get("name", "")
            if not name or not isinstance(name, str) or not name.strip():
                continue
            result.append({
                "name": name.strip(),
                "kind": item.get("kind", "webpage") or "webpage",
                "keywords": item.get("keywords", name) or name,
            })
        elif isinstance(item, str):
            name = item.strip()
            if name:
                result.append({"name": name, "kind": "webpage", "keywords": name})
    return result


# ---------------------------------------------------------------------------
# Entity 媒体缩略图提取
# ---------------------------------------------------------------------------

def _append_image_page_candidate(candidates: list[dict], candidate: Optional[dict]) -> None:
    """按 URL 去重地加入候选图片页面。"""
    if not candidate or not candidate.get("url"):
        return
    url = candidate["url"]
    if any(item["url"] == url for item in candidates):
        return
    candidates.append(candidate)


def _resolve_entity_image(entity_name: str, entity_kind: str, reference: Optional[dict]) -> dict:
    """解析实体图片，优先大陆可达页面，资料引用与图片来源可以不同。"""
    candidates: list[dict] = []
    kind = entity_kind.lower()
    reference_url = reference.get("url", "") if reference else ""
    reference_host = urllib.parse.urlparse(reference_url).netloc.lower()

    # 已选参考页如果来自国内，优先使用，通常只需一次页面请求即可得到图片。
    if reference and _is_mainland_friendly_url(reference_url):
        _append_image_page_candidate(candidates, reference)

    # 影视和游戏优先豆瓣（其中包含稳定的图书检索页）。它只负责图片候选，
    # 不会覆盖已经确定的资料引用。
    if kind in {"game", "film", "media"} and "douban.com" not in reference_host:
        _append_image_page_candidate(candidates, _resolve_douban(entity_name))
        _append_image_page_candidate(candidates, _resolve_douban_book(entity_name))

    # 已确定的参考页永远是最终回退，保证国内候选没有图片时功能不退化。
    _append_image_page_candidate(candidates, reference)

    started_at = time.monotonic()
    for candidate in candidates:
        page_url = candidate.get("url", "")
        timeout = (
            DOMESTIC_IMAGE_PAGE_TIMEOUT_SECONDS
            if _is_mainland_friendly_url(page_url)
            else FALLBACK_IMAGE_PAGE_TIMEOUT_SECONDS
        )
        image_url = _extract_og_image_url(page_url, timeout=timeout)
        if image_url:
            elapsed = time.monotonic() - started_at
            region = "mainland" if _is_mainland_friendly_url(page_url) else "fallback"
            print(
                f"[Image Resolver] {entity_name} → {region} source "
                f"({elapsed:.1f}s, page={urllib.parse.urlparse(page_url).netloc})"
            )
            return {
                "remote_image_url": image_url,
                "image_source_url": page_url,
                "image_source_region": region,
            }

    # 国内页面没有开放 og:image 时，维持原先的 Wiki 图片回退能力。将搜索放在
    # 上述候选实际失败之后，避免已命中大陆图片仍等待中英文 Wiki 请求。
    if "wikipedia.org" not in reference_host:
        wiki = _resolve_wikipedia(entity_name, entity_name)
        if wiki:
            page_url = wiki.get("url", "")
            image_url = _extract_og_image_url(page_url, timeout=FALLBACK_IMAGE_PAGE_TIMEOUT_SECONDS)
            if image_url:
                elapsed = time.monotonic() - started_at
                print(
                    f"[Image Resolver] {entity_name} → fallback source "
                    f"({elapsed:.1f}s, page={urllib.parse.urlparse(page_url).netloc})"
                )
                return {
                    "remote_image_url": image_url,
                    "image_source_url": page_url,
                    "image_source_region": "fallback",
                }

    elapsed = time.monotonic() - started_at
    print(f"[Image Resolver] {entity_name} → no image ({elapsed:.1f}s, candidates={len(candidates)})")
    return {"remote_image_url": "", "image_source_url": "", "image_source_region": ""}


def _resolve_entity_enrichment(entity_name: str, entity_kind: str) -> dict:
    """一次性得到资料引用和适合展示的图片 URL。"""
    ref = _resolve_entity_reference(entity_name, entity_kind)
    image = _resolve_entity_image(entity_name, entity_kind, ref)
    return {
        "ref_url": ref.get("url", "") if ref else "",
        "ref_title": ref.get("title", "") if ref else "",
        "source_tier": ref.get("sourceTier", "") if ref else "",
        **image,
    }


def _extract_og_image(
    ref_url: str,
    entity_name: str,
    archive_path: str,
    entity_idx: int,
    remote_image_url: str = "",
) -> Optional[dict]:
    """
    从 ref_url 页面提取 og:image，下载到 archive_path/media/ 目录。
    返回本地文件名（相对于 archive）或 None。

    修复：使用 _http_get_bytes() 下载原始字节，Content-Type 校验 + Pillow 验证，
    确保只保存真实图片不过滤横幅/ICO/favicon 类图片。
    """
    if not ref_url or not ref_url.startswith("http"):
        return None
    try:
        import os as _os
        media_dir = _os.path.join(archive_path, "media")
        _os.makedirs(media_dir, exist_ok=True)

        # 清理实体名作为文件名
        safe = re.sub(r'[^\w\-]', '_', entity_name)[:30]

        # 1. 获取页面 HTML，提取 og:image URL
        img_url = remote_image_url or _extract_og_image_url(ref_url)
        if not img_url:
            return None

        # 2. 推断扩展名（从 URL 猜测，真实类型由 Pillow 检测）
        ext_match = re.search(r'\.(jpg|jpeg|png|webp|svg|gif)', img_url, re.I)
        ext = ext_match.group(1).lower() if ext_match else "jpg"
        if ext == "jpeg":
            ext = "jpg"

        # 3. 二进制下载（含 Content-Type 校验）
        img_data = _http_get_bytes(img_url, timeout=10)
        if not img_data:
            return None

        # 4. Pillow 图像验证（确保不是 HTML/JSON/损坏数据）
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(img_data))
            img.verify()  # 验证图像完整性
            # 重新打开（verify 后需要重新创建对象才能操作）
            img = Image.open(io.BytesIO(img_data))
            actual_format = img.format.lower() if img.format else ext
            # SVG 被 Pillow 识别为 SVG，不稳定，彻底禁用
            if actual_format == "svg":
                return None
        except Exception:
            return None

        # 5. 质量过滤
        width, height = img.size
        # 过滤太小的图（可能是 favicon/banner 占位图）
        if width < 120 or height < 80:
            return None
        # 过滤极端宽高比（超宽横幅或超窄竖条）
        ratio = max(width, height) / max(min(width, height), 1)
        if ratio > 8:
            return None

        # 6. 统一转为 JPEG 或保留原格式（SVG/PDF 等非 raster 转 JPEG）
        local_name = f"entity_{entity_idx:03d}_{safe}.{ext}"
        local_path = _os.path.join(media_dir, local_name)

        try:
            if actual_format in ("svg", "webp", "gif"):
                # 转为 JPEG
                rgb_img = img.convert("RGB")
                rgb_img.save(local_path, "JPEG", quality=85, optimize=True)
            elif actual_format in ("jpeg", "jpg", "png"):
                # 直接保存，PNG 保持透明通道
                if actual_format == "png":
                    img.save(local_path, "PNG", optimize=True)
                else:
                    img.save(local_path, "JPEG", quality=85, optimize=True)
            else:
                # 其他格式统一转 JPEG
                rgb_img = img.convert("RGB")
                rgb_img.save(local_path, "JPEG", quality=85, optimize=True)
        except Exception:
            # 写入失败时清理
            if _os.path.exists(local_path):
                _os.remove(local_path)
            return None

        # 7. 二次验证：写入后检查文件大小
        file_size = _os.path.getsize(local_path)
        if file_size < 3000:
            _os.remove(local_path)
            return None

        return {
            "filename": local_name,
            "source_url": img_url,
        }
    except Exception:
        return None


def _extract_og_image_url(ref_url: str, timeout: int = 8) -> Optional[str]:
    """仅提取远程 og:image 链接，不下载图片字节。"""
    if not ref_url or not ref_url.startswith("http"):
        return None
    text = _http_get(ref_url, timeout=timeout)
    if not text:
        return None
    og_match = re.search(
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        text, re.I,
    )
    if not og_match:
        og_match = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            text, re.I,
        )
    if not og_match:
        return None
    image_url = og_match.group(1).strip().replace("&amp;", "&")
    if image_url.startswith("//"):
        image_url = f"https:{image_url}"
    return image_url if image_url.startswith("http") else None


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def generate_timeline_json(
    api_key: str,
    podcast_text: str,
    transcript_segments: list,
    title: str = "未命名节目",
    archive_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """
    时间轴模式主入口（程序切段，模型写内容）。

    1. 程序侧按话题边界切分 segment spans（含实体首次出现检测）
    2. 对每个 span 调用模型输出 title/summary/entities/facts + reference_candidates
    3. 程序确定 start/end/time/seg_start_idx/seg_end_idx
    4. 将外部资料候选保留给后台富化任务处理
    5. 合并 + 合法性校验 + 写盘
    """
    print(f"[Timeline] 程序切段模式开始 (segments={len(transcript_segments)})")
    generation_started_at = time.perf_counter()

    audio_duration = 0
    if transcript_segments:
        audio_duration = transcript_segments[-1].get("seconds", 0)
        audio_duration = max(audio_duration, 60)

    spans = _slice_spans_by_topics(transcript_segments, audio_duration)
    print(f"[Timeline] 程序切出 {len(spans)} 个 spans")

    if not spans:
        return {"mode": "timeline", "version": 2, "title": title, "nodes": []}

    # 保持每个 span 的模型、提示词和输出字段不变，只以受控并发缩短墙钟时间。
    contents: list[dict] = [{} for _ in spans]
    completed = 0
    with ThreadPoolExecutor(max_workers=TIMELINE_LLM_CONCURRENCY, thread_name_prefix="PodGist_Timeline") as executor:
        futures = {}
        for i, span in enumerate(spans):
            print(f"[Timeline] 提交 span {i + 1}/{len(spans)} ...")
            span_text = _get_span_text(transcript_segments, span["seg_start_idx"], span["seg_end_idx"])
            future = executor.submit(
                _generate_content_for_span,
                api_key, span_text, span["start"], span["end"], span["time"], i, len(spans), audio_duration,
            )
            futures[future] = i

        for future in as_completed(futures):
            index = futures[future]
            try:
                contents[index] = future.result()
            except Exception as exc:
                print(f"[Timeline] span {index + 1} 未生成: {exc}")
            completed += 1
            if progress_callback:
                progress_callback(completed, len(spans))

    nodes = []
    for i, span in enumerate(spans):
        content = contents[i]
        # 仅有片头元数据的 span 不构成可检索、可回听的内容节点。
        if content.get("skip_node") is True:
            continue
        entities = _normalize_entities(content.get("entities", []))
        # 外部参考资料和图片属于可失败的增强信息，交由持久化后台任务处理。
        for ent in entities:
            ent["media"] = {}

        node = {
            "id": f"node_{i + 1:03d}",
            "seg_start_idx": span["seg_start_idx"],
            "seg_end_idx": span["seg_end_idx"],
            "start": span["start"],
            "end": span["end"],
            "time": span["time"],
            "title": content.get("title", f"话题 {i + 1}"),
            "node_type": _normalize_node_type(content.get("node_type", "")),
            "summary": content.get("summary", ""),
            "why_it_matters": content.get("why_it_matters", ""),
            "entities": entities,
            "facts": _normalize_facts(content.get("facts", [])),
            "quote_or_joke_explainer": content.get("quote_or_joke_explainer", ""),
            "references": [],
            "reference_candidates": _normalize_ref_candidates(content.get("reference_candidates", [])),
            "media": [],
        }
        nodes.append(node)

    timeline_raw = {"mode": "timeline", "version": 2, "title": title, "nodes": nodes}
    normalized = _normalize_timeline(timeline_raw, audio_duration)

    elapsed = time.perf_counter() - generation_started_at
    print(
        f"[Timeline] 核心生成完成，共 {len(normalized.get('nodes', []))} 个节点，"
        f"耗时 {elapsed:.1f}s（并发={TIMELINE_LLM_CONCURRENCY}）"
    )
    return normalized


def enrich_timeline_archive(archive_id: str, archive_path: str, cache_entity_images: bool = False) -> None:
    """在核心时间轴完成后补充实体链接和图片，不影响主任务可用性。"""
    from backend import task_queue

    timeline_path = os.path.join(archive_path, "timeline.json")
    if not os.path.isfile(timeline_path):
        raise FileNotFoundError("未找到 timeline.json")
    with open(timeline_path, "r", encoding="utf-8") as f:
        timeline = json.load(f)

    def persist_timeline() -> None:
        """原子写盘，让已完成的实体资料无需等待整期富化结束即可展示。"""
        temp_path = f"{timeline_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(timeline, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, timeline_path)

    resolved: dict[str, dict] = {}
    entity_index = 0
    changed = False
    for node in timeline.get("nodes", []):
        for entity in node.get("entities", []):
            name = (entity.get("name") or "").strip()
            entity_type = (entity.get("type") or "other").strip().lower()
            if not name:
                continue
            entity_key = _entity_enrichment_cache_key(name, entity_type)
            if entity_key not in resolved:
                cached = task_queue.get_entity_enrichment_cache(entity_key)
                if cached:
                    resolved[entity_key] = cached
                else:
                    result = _resolve_entity_enrichment(name, entity_type)
                    task_queue.upsert_entity_enrichment_cache(
                        entity_key, result["ref_url"], result["ref_title"], result["source_tier"], result["remote_image_url"],
                        result["image_source_url"], result["image_source_region"],
                    )
                    resolved[entity_key] = result

            result = resolved[entity_key]
            entity["refUrl"] = result.get("ref_url", "") or ""
            entity["refTitle"] = result.get("ref_title", "") or ""
            entity["sourceTier"] = result.get("source_tier", "") or ""
            remote_url = result.get("remote_image_url", "") or ""
            media = {
                "remote_url": remote_url,
                "source_url": entity["refUrl"],
                "image_source_url": result.get("image_source_url", "") or "",
                "image_source_region": result.get("image_source_region", "") or "",
            } if remote_url else {}

            if cache_entity_images and entity["refUrl"]:
                local_media = _extract_og_image(
                    entity["refUrl"], name, archive_path, entity_index, remote_image_url=remote_url,
                )
                if local_media:
                    media = {**local_media, "remote_url": remote_url}
            entity["media"] = media
            entity["enrichmentVersion"] = ENTITY_IMAGE_RESOLVER_VERSION
            entity_index += 1
            changed = True
            persist_timeline()

        candidates = _normalize_ref_candidates(node.get("reference_candidates", []))
        if candidates:
            node["references"] = _resolve_node_references(candidates)
            changed = True
        node.pop("reference_candidates", None)
        if changed:
            persist_timeline()

    if changed:
        print(f"[Enrichment] 已写入归档资料: {archive_id}")


def enrich_timeline_node(
    archive_id: str,
    archive_path: str,
    node_id: str,
    cache_entity_images: bool = False,
    max_new_remote_images: Optional[int] = None,
    deadline_at: Optional[float] = None,
) -> tuple[bool, int]:
    """只富化一个节点，供优先级队列在播放/跳转时快速响应。"""
    from backend import task_queue

    timeline_path = os.path.join(archive_path, "timeline.json")
    if not os.path.isfile(timeline_path):
        raise FileNotFoundError("未找到 timeline.json")
    with open(timeline_path, "r", encoding="utf-8") as f:
        timeline = json.load(f)

    node = next((item for item in timeline.get("nodes", []) if item.get("id") == node_id), None)
    if not node:
        raise ValueError(f"未找到时间轴节点: {node_id}")

    # 节点内的图片序号加上节点序号，避免本地缓存文件名跨节点冲突。
    node_match = re.search(r"(\d+)$", node_id)
    node_index = int(node_match.group(1)) if node_match else 0
    completed = True
    new_remote_images = 0
    for entity_index, entity in enumerate(node.get("entities", [])):
        name = (entity.get("name") or "").strip()
        entity_type = (entity.get("type") or "other").strip().lower()
        if not name:
            continue

        # 已按当前图片策略处理过（即使没有找到资料）则不重复访问外部网页。
        if entity.get("enrichmentVersion") == ENTITY_IMAGE_RESOLVER_VERSION and "refUrl" in entity:
            continue
        if deadline_at is not None and time.monotonic() >= deadline_at:
            completed = False
            break
        if max_new_remote_images is not None and new_remote_images >= max_new_remote_images:
            completed = False
            break

        entity_key = _entity_enrichment_cache_key(name, entity_type)
        cached = task_queue.get_entity_enrichment_cache(entity_key)
        if cached:
            result = cached
        else:
            result = _resolve_entity_enrichment(name, entity_type)
            task_queue.upsert_entity_enrichment_cache(
                entity_key, result["ref_url"], result["ref_title"], result["source_tier"], result["remote_image_url"],
                result["image_source_url"], result["image_source_region"],
            )

        entity["refUrl"] = result.get("ref_url", "") or ""
        entity["refTitle"] = result.get("ref_title", "") or ""
        entity["sourceTier"] = result.get("source_tier", "") or ""
        remote_url = result.get("remote_image_url", "") or ""
        media = {
            "remote_url": remote_url,
            "source_url": entity["refUrl"],
            "image_source_url": result.get("image_source_url", "") or "",
            "image_source_region": result.get("image_source_region", "") or "",
        } if remote_url else {}
        if remote_url:
            new_remote_images += 1
        if cache_entity_images and entity["refUrl"]:
            local_media = _extract_og_image(
                entity["refUrl"], name, archive_path, node_index * 100 + entity_index, remote_image_url=remote_url,
            )
            if local_media:
                media = {**local_media, "remote_url": remote_url}
        entity["media"] = media
        entity["enrichmentVersion"] = ENTITY_IMAGE_RESOLVER_VERSION

    if completed:
        candidates = _normalize_ref_candidates(node.get("reference_candidates", []))
        if candidates:
            node["references"] = _resolve_node_references(candidates)
        node.pop("reference_candidates", None)

    temp_path = f"{timeline_path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(timeline, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, timeline_path)
    state = "完成" if completed else "部分完成"
    print(f"[Enrichment] 节点{state}: {archive_id}/{node_id}（新增图片={new_remote_images}）")
    return completed, new_remote_images


def warmup_timeline_nodes(
    archive_id: str,
    archive_path: str,
    node_ids: list[str],
    cache_entity_images: bool = False,
    max_remote_images: int = 2,
    time_budget_seconds: float = 10.0,
) -> list[str]:
    """主任务结束前保障首屏：最多等待固定时间并优先得到若干图片。"""
    deadline_at = time.monotonic() + time_budget_seconds
    completed_node_ids = []
    collected_images = 0
    for node_id in node_ids:
        if collected_images >= max_remote_images or time.monotonic() >= deadline_at:
            break
        completed, added_images = enrich_timeline_node(
            archive_id,
            archive_path,
            node_id,
            cache_entity_images=cache_entity_images,
            max_new_remote_images=max_remote_images - collected_images,
            deadline_at=deadline_at,
        )
        collected_images += added_images
        if completed:
            completed_node_ids.append(node_id)
    print(
        f"[Enrichment] 首屏保障完成：节点={len(completed_node_ids)}，"
        f"图片={collected_images}/{max_remote_images}，预算={time_budget_seconds:.0f}s"
    )
    return completed_node_ids
