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
from typing import Optional

from dashscope import Generation
from http import HTTPStatus

TIMELINE_MODEL = 'qwen-plus'

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


def _resolve_entity_reference(entity_name: str, entity_kind: str) -> Optional[dict]:
    """
    为单个实体解析参考链接（per-entity 版本）。
    返回带 sourceTier 的结果字典，或 None。

    来源优先级（按 kind 分）：
      company/product → 官方域名 → 百度百科 → Wikipedia
      tool/repo → GitHub → 官方域名 → Wikipedia
      game/film/media → Steam/豆瓣 → Wikipedia
      other → Wikipedia → 百度百科
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

    results: list[dict] = []
    kind = entity_kind.lower()
    is_tool = kind in {"tool", "repo", "product"}
    is_game_film = kind in {"game", "film", "media"}

    # 1. 官方域名（最高优先级）
    official = _try_official_url(clean)
    if official:
        results.append(official)

    # 2. 按类型分支
    if is_tool:
        # 工具/项目：官方域名（已查） → Wikipedia（GitHub 已暂时禁用）
        wiki = _resolve_wikipedia(clean, clean_for_search)
        if wiki:
            results.append(wiki)
    elif is_game_film:
        # 游戏/影视：Steam → 豆瓣 → Wikipedia
        steam = _resolve_game_store(clean)
        if steam:
            results.append(steam)
        douban = _resolve_douban(clean)
        if douban:
            results.append(douban)
        wiki = _resolve_wikipedia(clean, clean_for_search)
        if wiki:
            results.append(wiki)
        # 百度百科作为游戏/影视的补充
        baidu = _resolve_baidu_baike(clean)
        if baidu:
            results.append(baidu)
    else:
        # 公司/品牌/其他：百度百科 → Wikipedia（GitHub 已暂时禁用）
        baidu = _resolve_baidu_baike(clean)
        if baidu:
            results.append(baidu)
        wiki = _resolve_wikipedia(clean, clean_for_search)
        if wiki:
            results.append(wiki)

    # 选最优
    best = _best_result(results)
    if best and best.get("confidence", 0) >= 0.7:
        return best
    return None


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

注意：只基于提供的转录片段输出，不要自由发挥时间或事实。"""

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

def _extract_og_image(ref_url: str, entity_name: str, archive_path: str, entity_idx: int) -> Optional[dict]:
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
        text = _http_get(ref_url, timeout=8)
        if not text:
            return None

        og_match = re.search(
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            text, re.I
        )
        if not og_match:
            og_match = re.search(
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                text, re.I
            )
        if not og_match:
            return None

        img_url = og_match.group(1).strip()
        if not img_url or not img_url.startswith("http"):
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


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def generate_timeline_json(
    api_key: str,
    podcast_text: str,
    transcript_segments: list,
    title: str = "未命名节目",
    archive_path: Optional[str] = None,
) -> dict:
    """
    时间轴模式主入口（程序切段，模型写内容）。

    1. 程序侧按话题边界切分 segment spans（含实体首次出现检测）
    2. 对每个 span 调用模型输出 title/summary/entities/facts + reference_candidates
    3. 程序确定 start/end/time/seg_start_idx/seg_end_idx
    4. 程序侧解析 reference_candidates 生成 references（URL 查证）
    5. 合并 + 合法性校验 + 写盘
    """
    print(f"[Timeline] 程序切段模式开始 (segments={len(transcript_segments)})")

    audio_duration = 0
    if transcript_segments:
        audio_duration = transcript_segments[-1].get("seconds", 0)
        audio_duration = max(audio_duration, 60)

    spans = _slice_spans_by_topics(transcript_segments, audio_duration)
    print(f"[Timeline] 程序切出 {len(spans)} 个 spans")

    if not spans:
        return {"mode": "timeline", "version": 2, "title": title, "nodes": []}

    nodes = []
    for i, span in enumerate(spans):
        print(f"[Timeline] 生成 span {i + 1}/{len(spans)} ...")
        span_text = _get_span_text(
            transcript_segments,
            span["seg_start_idx"],
            span["seg_end_idx"]
        )
        content = _generate_content_for_span(
            api_key, span_text,
            span["start"], span["end"], span["time"],
            i, len(spans), audio_duration
        )

        entities = _normalize_entities(content.get("entities", []))
        # 为每个 entity 解析参考链接（per-entity 模式）
        for idx, ent in enumerate(entities):
            ref = _resolve_entity_reference(ent.get("name", ""), ent.get("type", "other"))
            if ref:
                ent["refUrl"] = ref.get("url", "")
                ent["refTitle"] = ref.get("title", "")
                ent["sourceTier"] = ref.get("sourceTier", "community")
            else:
                ent["refUrl"] = ""
                ent["refTitle"] = ""
                ent["sourceTier"] = ""

            # 提取 og:image（高可信来源才提取，不阻塞主流程）
            if ref and archive_path:
                try:
                    media = _extract_og_image(
                        ref.get("url", ""),
                        ent.get("name", ""),
                        archive_path,
                        idx,
                    )
                    ent["media"] = media if media else {}
                except Exception:
                    ent["media"] = {}
            else:
                ent["media"] = {}

        # 节点级引用（新闻/报告/文档等，非实体解释型）
        ref_candidates = _normalize_ref_candidates(content.get("reference_candidates", []))
        references = _resolve_node_references(ref_candidates) if ref_candidates else []

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
            "references": references,
            "media": [],
        }
        nodes.append(node)

    timeline_raw = {"mode": "timeline", "version": 2, "title": title, "nodes": nodes}
    normalized = _normalize_timeline(timeline_raw, audio_duration)

    print(f"[Timeline] 生成完成，共 {len(normalized.get('nodes', []))} 个节点")
    return normalized
