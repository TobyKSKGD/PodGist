"""
timeline_agent.py — 时间轴模式专用生成链路（Program-Slices-Span, Model-Writes-Content）

协议重构：程序切段，模型写内容。
- 程序先基于 transcript segments 自然边界切分连续 span
- 程序确定 span 的 start/end/time/seg_start_idx/seg_end_idx
- 模型只负责为每个 span 输出 title/summary/entities/facts 等内容字段
- 不再让模型决定节点边界
"""

import json
import re
import time
from typing import Optional

from dashscope import Generation
from http import HTTPStatus

TIMELINE_MODEL = 'qwen-plus'


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


def _slice_spans_by_topics(segments: list, audio_duration: float) -> list:
    """
    程序侧按话题自然边界切分 segment spans。

    策略：
    1. 扫描所有 segment 的文本
    2. 检测话题切换信号（新主题句、过渡承接句）
    3. 合并短于 MIN_SPAN_SECONDS 的相邻 span
    4. 拆分长于 MAX_SPAN_SECONDS 的超长 span
    5. 保证覆盖整期节目，不留大空洞

    返回: list[dict] 每个含 {seg_start_idx, seg_end_idx, start, end, time}
    """
    if not segments:
        return []

    MIN_SPAN_SECONDS = 60   # 最小 span 60 秒
    MAX_SPAN_SECONDS = 300   # 最大 span 5 分钟
    TOPIC_SWITCH_MARKERS = [
        "一、", "二、", "三、", "四、", "五、",
        "首先", "其次", "最后",
        "下面", "接下来", "另外", "还有",
        "刚才", "说到", "再补充",
        "欢迎来到", "这里是", "我是",
        "总之", "总的来说",
        "不过", "然而", "但是",
        "那么", "所以", "因此",
    ]
    spans = []
    cur_start = 0

    for i in range(len(segments)):
        seg = segments[i]
        text = seg.get("text", "")

        # 检测话题切换：同时检查当前 segment 和前一个 segment
        # 因为话题切换往往发生在前一个 segment 的结尾
        prev_text = segments[i - 1].get("text", "") if i > 0 else ""
        is_switch = False
        for marker in TOPIC_SWITCH_MARKERS:
            if (marker in text or marker in prev_text) and i > cur_start:
                is_switch = True
                break

        # 当前 span 时长
        span_end_seconds = segments[i].get("seconds", 0)
        span_duration = span_end_seconds - segments[cur_start].get("seconds", 0) if cur_start <= i else 0

        # 强制切分条件：超长 或 话题切换（且 span 已有足够内容）
        should_split = False
        if span_duration >= MAX_SPAN_SECONDS:
            should_split = True
        elif is_switch and span_duration >= MIN_SPAN_SECONDS:
            should_split = True

        if should_split:
            # 封口当前 span
            spans.append({
                "seg_start_idx": cur_start,
                "seg_end_idx": i - 1,
                "start": segments[cur_start].get("seconds", 0),
                "end": segments[i - 1].get("seconds", 0),
                "time": _format_time(segments[cur_start].get("seconds", 0)),
            })
            cur_start = i

    # 最后一个 span
    if cur_start < len(segments):
        spans.append({
            "seg_start_idx": cur_start,
            "seg_end_idx": len(segments) - 1,
            "start": segments[cur_start].get("seconds", 0),
            "end": segments[-1].get("seconds", 0),
            "time": _format_time(segments[cur_start].get("seconds", 0)),
        })

    # 只合并时长过短的 span（< MIN_SPAN_SECONDS），不按 gap 合并
    merged = []
    for span in spans:
        if not merged:
            merged.append(span)
            continue
        last = merged[-1]
        span_dur = span["start"] - last["end"]
        if span_dur < 0:
            # 重叠，合并
            last["seg_end_idx"] = span["seg_end_idx"]
            last["end"] = span["end"]
        elif last["end"] - last["start"] < MIN_SPAN_SECONDS:
            # 前一个 span 太短，合并
            last["seg_end_idx"] = span["seg_end_idx"]
            last["end"] = span["end"]
        else:
            merged.append(span)

    # 重新计算 time 字段
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


def _normalize_timeline(timeline: dict, audio_duration: float) -> dict:
    """合法性校验 + 过滤越界节点"""
    nodes = timeline.get("nodes", [])
    if not nodes:
        return timeline

    # 过滤 start >= audio_duration
    filtered = [n for n in nodes if (n.get("start", 0) or 0) < audio_duration]

    # clamp end
    for n in filtered:
        end = n.get("end")
        if end is None or end <= 0 or end > audio_duration:
            n["end"] = audio_duration
        if n["end"] <= n["start"]:
            n["end"] = min(n["start"] + 60, audio_duration)

    # 排序
    filtered.sort(key=lambda n: n.get("start", 0) or 0)

    # 合并重叠 > 80%
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
        "version": 1,
        "title": timeline.get("title", ""),
        "nodes": [{**n, "id": f"node_{i + 1:03d}"} for i, n in enumerate(merged)],
    }


# node_type 归一化映射表（支持中英文、模糊匹配）
_NODE_TYPE_ALIASES = {
    # company_news 变体
    "company_news": "company_news", "company": "company_news", "公司动态": "company_news",
    "企业动态": "company_news", "企业": "company_news",
    # product 变体
    "product": "product", "产品": "product", "产品发布": "product",
    "新品": "product",
    # person 变体
    "person": "person", "人物": "person", "人物动态": "person", "人物专访": "person",
    # topic_change 变体
    "topic_change": "topic_change", "话题切换": "topic_change", "过渡": "topic_change",
    "承上启下": "topic_change",
    # background 变体
    "background": "background", "背景": "background", "背景知识": "background",
    "行业背景": "background",
    # fun_moment / quote 变体
    "fun_moment": "fun_moment", "趣味": "fun_moment", "金句": "fun_moment",
    "quote": "fun_moment", "quote_or_joke_explainer": "fun_moment",
    # 数字类
    "1": "other", "2": "other",
}


def _normalize_node_type(raw: str) -> str:
    """将模型输出的各种 node_type 格式归一化为标准值"""
    if not raw:
        return "other"
    raw = raw.strip().lower()
    return _NODE_TYPE_ALIASES.get(raw, "other")


def _normalize_entities(raw: list) -> list:
    """
    规范化 entities 字段：
    - 字符串项 -> {name: str, type: "other", description: ""}
    - 对象项 -> 确保有 name/type/description，无则补空字符串
    - 跳过无效项（无 name 或 name 为空）
    """
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
    """
    规范化 facts 字段：
    - 字符串项 -> {label: "事实", value: str}
    - 对象项 -> 确保有 label/value，无则补空字符串
    - 跳过无效项
    """
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


def generate_timeline_json(
    api_key: str,
    podcast_text: str,
    transcript_segments: list,
    title: str = "未命名节目"
) -> dict:
    """
    时间轴模式主入口（程序切段，模型写内容）。

    1. 程序侧按话题边界切分 segment spans
    2. 对每个 span 调用模型输出 title/summary/entities/facts
    3. 程序确定 start/end/time/seg_start_idx/seg_end_idx
    4. 合并 + 合法性校验 + 写盘
    """
    print(f"[Timeline] 程序切段模式开始 (segments={len(transcript_segments)})")

    audio_duration = 0
    if transcript_segments:
        audio_duration = transcript_segments[-1].get("seconds", 0)
        audio_duration = max(audio_duration, 60)

    # Step 1: 程序切分 spans
    spans = _slice_spans_by_topics(transcript_segments, audio_duration)
    print(f"[Timeline] 程序切出 {len(spans)} 个 spans")

    if not spans:
        return {"mode": "timeline", "version": 1, "title": title, "nodes": []}

    # Step 2: 对每个 span 调用模型写内容
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
            "entities": _normalize_entities(content.get("entities", [])),
            "facts": _normalize_facts(content.get("facts", [])),
            "quote_or_joke_explainer": content.get("quote_or_joke_explainer", ""),
        }
        nodes.append(node)

    # Step 3: 合并 + 校验
    timeline_raw = {"mode": "timeline", "version": 1, "title": title, "nodes": nodes}
    normalized = _normalize_timeline(timeline_raw, audio_duration)

    print(f"[Timeline] 生成完成，共 {len(normalized.get('nodes', []))} 个节点")
    return normalized