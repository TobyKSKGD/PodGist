"""
timeline_agent.py — 时间轴模式专用生成链路

生成结构化的 timeline.json，包含丰富的富节点列表。
与 summary 模式（llm_agent.py）完全分离。
"""

import json
import re
import time
from typing import Optional

from dashscope import Generation
from http import HTTPStatus

# 模型梯队
TIMELINE_MODEL = 'qwen-plus'  # timeline 生成用较强模型，保证质量


def _call_llm_json(api_key: str, messages: list, temperature: float = 0.3) -> dict:
    """
    调用 LLM 并期望返回 JSON 结构。
    失败时抛出异常。
    """
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
                # 尝试提取 JSON
                return _extract_json(content)
            else:
                err_msg = f"status={response.code} msg={response.message}"
                last_err = Exception(f"LLM error: {err_msg}")
        except Exception as e:
            last_err = e

        if attempt < 2:
            time.sleep(3)

    raise last_err or Exception("LLM 调用失败")


def _extract_json(content: str) -> dict:
    """
    从 LLM 输出中提取 JSON。
    支持：
    - Markdown ```json ... ``` 包裹的 { ... } 对象
    - Markdown ```json ... ``` 包裹的 [ ... ] 数组（转为 {"nodes": [...]}）
    - 纯粹的 { ... } 对象
    - 纯粹的 [ ... ] 数组（转为 {"nodes": [...]}）
    """
    content = content.strip()

    # 1. Markdown ```json ... ``` 包裹的对象（用贪婪匹配处理多行嵌套）
    json_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', content)
    if json_match:
        return json.loads(json_match.group(1))

    # 2. Markdown ```json ... ``` 包裹的数组（LLM 有时返回数组）
    array_match = re.search(r'```(?:json)?\s*(\[[\s\S]*?\])\s*```', content)
    if array_match:
        return {"nodes": json.loads(array_match.group(1))}

    # 3. 纯 JSON 对象
    if content.startswith('{'):
        return json.loads(content)

    # 4. 纯 JSON 数组
    if content.startswith('['):
        return {"nodes": json.loads(content)}

    raise ValueError(f"无法从输出中提取 JSON: {content[:200]}")


def _split_transcript_by_segments(transcript_text: str, segments: list, max_chars_per_chunk: int = 8000) -> list:
    """
    按 transcript segments 的自然边界切分文本。

    策略：
    1. 按时间顺序遍历 segments
    2. 每凑满 ~max_chars 字符形成一块
    3. 保证节点边界完整（不切断节点）

    参数:
        transcript_text: 带时间戳的原始转录文本
        segments: 转录分段列表（每项含 seconds, text）
        max_chars_per_chunk: 每块最大字符数

    返回:
        list[dict]: 每块含 {"text": str, "start_seconds": int, "end_seconds": int}
    """
    if not segments:
        # fallback：按字符数均分
        lines = transcript_text.split('\n')
        chunks = []
        current = []
        current_len = 0
        for line in lines:
            if current_len + len(line) > max_chars_per_chunk and current:
                chunks.append('\n'.join(current))
                current = [line]
                current_len = len(line)
            else:
                current.append(line)
                current_len += len(line)
        if current:
            chunks.append('\n'.join(current))
        return [{"text": c, "start_seconds": 0, "end_seconds": 0} for c in chunks] if chunks else []

    chunks = []
    current_lines = []
    current_len = 0
    chunk_start = 0

    for seg in segments:
        seg_text = f"[{seg.get('time', '00:00')}] {seg.get('text', '')}"
        seg_len = len(seg_text)

        if current_len + seg_len > max_chars_per_chunk and current_lines:
            # 当前块封口
            chunks.append({
                "text": '\n'.join(current_lines),
                "start_seconds": chunks[-1]["end_seconds"] if chunks else 0,
                "end_seconds": seg.get('seconds', 0),
            })
            current_lines = [seg_text]
            current_len = seg_len
        else:
            current_lines.append(seg_text)
            current_len += seg_len

    if current_lines:
        chunks.append({
            "text": '\n'.join(current_lines),
            "start_seconds": chunks[-1]["end_seconds"] if chunks else 0,
            "end_seconds": segments[-1].get('seconds', 0) if segments else 0,
        })

    return chunks


def _format_time(seconds: float) -> str:
    """将秒数转换为 M:SS 格式"""
    s = int(seconds)
    m = s // 60
    sec = s % 60
    return f"{m}:{sec:02d}"


def _find_segment_index(segments: list, seconds: float) -> int:
    """找到 seconds 对应的 segment 下标（二分查找）"""
    lo, hi = 0, len(segments) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if segments[mid].get("seconds", 0) < seconds:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _fill_coverage_gaps(nodes: list, audio_duration: float, segments: list) -> list:
    """
    检查节点间的覆盖缺口，对过大的时间间隔（> 180s ≈ 3 分钟）补充粗粒度节点。
    只在空白过大的区间插入填充节点，不改变已有的高质量节点。
    """
    if not nodes or audio_duration <= 0:
        return nodes

    result = list(nodes)
    i = 0
    while i < len(result) - 1:
        cur_end = result[i].get("end", 0) or 0
        next_start = result[i + 1].get("start", 0) or 0
        gap = next_start - cur_end
        if gap > 180:
            # 找到 cur_end 附近的 segment
            seg_idx = 0
            for idx, seg in enumerate(segments):
                if seg.get("seconds", 0) >= cur_end:
                    seg_idx = idx
                    break
            mid_idx = (seg_idx + _find_segment_index(segments, next_start)) // 2
            mid_seconds = segments[mid_idx].get("seconds", cur_end) if mid_idx < len(segments) else cur_end
            fill_node = {
                "id": "_fill_",
                "title": f"{_format_time(cur_end)}~{_format_time(next_start)}",
                "node_type": "background",
                "start": int(cur_end),
                "end": int(next_start),
                "time": _format_time(cur_end),
                "summary": f"覆盖 {_format_time(cur_end)} 至 {_format_time(next_start)} 的内容",
                "why_it_matters": "",
                "entities": [],
                "facts": [],
                "quote_or_joke_explainer": "",
            }
            result.insert(i + 1, fill_node)
        i += 1

    return result


def _normalize_timeline(timeline: dict, audio_duration: float) -> dict:
    """
    对 timeline 节点做合法性校验与修正：
    1. 去除越界节点（start >= audio_duration）
    2. clamp end > audio_duration → audio_duration
    3. 确保 start < end
    4. 按 start 排序
    5. 合并重叠超过 80% 的相邻节点
    6. 重新分配 node_id
    """
    nodes = timeline.get("nodes", [])
    if not nodes:
        return timeline

    # Step 1: 过滤越界节点（start >= audio_duration 的直接丢弃）
    filtered = []
    for n in nodes:
        start = n.get("start", 0) or 0
        if start < audio_duration:
            filtered.append(n)

    # Step 2: clamp end，处理无 end 或 end 异常的情况
    for n in filtered:
        end = n.get("end")
        if end is None or end <= 0 or end > audio_duration:
            n["end"] = audio_duration

    # Step 3: 确保 start < end
    for n in filtered:
        start = n.get("start", 0) or 0
        end = n.get("end", 0) or 0
        if end <= start:
            n["end"] = min(start + 60, audio_duration)

    # Step 4: 按 start 排序
    filtered.sort(key=lambda n: n.get("start", 0) or 0)

    # Step 5: 合并严重重叠节点（重叠 > 80%）
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

    # Step 6: 重新分配 node_id
    final_nodes = []
    for i, n in enumerate(merged):
        final_nodes.append({**n, "id": f"node_{i + 1:03d}"})

    return {
        "mode": "timeline",
        "version": 1,
        "title": timeline.get("title", ""),
        "nodes": final_nodes,
    }


def _post_process_chunk_nodes(chunk_nodes: list, chunk_start_seconds: int, segments: list) -> list:
    """
    对单个 chunk 生成的节点列表进行后处理：
    1. 转换 seg_start_idx/seg_end_idx → start/end/time
    2. 对缺少 seg_idx 的节点用 chunk 边界时间兜底
    """
    result = []
    for node in chunk_nodes:
        seg_start = node.get("seg_start_idx")
        seg_end = node.get("seg_end_idx")

        # 解析 start 时间（优先用 segment seconds，兜底用 chunk_start_seconds）
        if seg_start is not None and 0 <= seg_start < len(segments):
            start_val = segments[seg_start].get("seconds", 0)
        elif seg_start is not None and seg_start < 0:
            start_val = 0
        else:
            start_val = chunk_start_seconds

        # 解析 end 时间
        if seg_end is not None and 0 <= seg_end < len(segments):
            end_val = segments[seg_end].get("seconds", 0)
        elif seg_end is not None and seg_end >= len(segments):
            end_val = segments[-1].get("seconds", 0) if segments else chunk_start_seconds
        else:
            end_val = start_val + 60

        if end_val <= start_val:
            end_val = start_val + 60

        anchor_seg = node.get("anchor_seg_idx")
        if anchor_seg is not None and 0 <= anchor_seg < len(segments):
            seek_val = segments[anchor_seg].get("seconds", start_val)
        else:
            # fallback: anchor 与 start 相同
            seek_val = start_val

        clean = {k: v for k, v in node.items()
                 if k not in ("seg_start_idx", "seg_end_idx", "anchor_seg_idx", "start", "end", "time", "id")}
        clean["start"] = start_val
        clean["end"] = end_val
        clean["time"] = _format_time(start_val)
        clean["seek_start"] = seek_val
        result.append(clean)

    return result


def _generate_nodes_for_chunk(api_key: str, chunk_text: str, chunk_index: int, total_chunks: int, segments: list, title_hint: str = "") -> list:
    """
    为一个文本块生成 timeline 节点列表。

    参数:
        api_key: DashScope API Key
        chunk_text: 该块的完整文本（含时间戳）
        chunk_index: 块编号（从 0 开始）
        total_chunks: 总块数
        segments: 完整 transcript_segments（用于推导时间）
        title_hint: 节目标题提示

    返回:
        list[dict]: 该块的节点列表（包含 seg_start_idx/seg_end_idx，由 post-processing 转为时间）
    """
    system_prompt = """你是一个播客与音频内容分析专家，擅长从转录稿中提取结构化的、有价值的时间轴节点。

你必须严格输出 JSON 数组，不要输出任何解释性文字。
每个节点代表一个有意义的内容片段（通常 1-5 分钟）。

【重要】时间信息必须基于转录文本中的 [MM:SS] 时间戳，不允许自由发明时间点。
"""

    # 构建 segment 索引映射供模型参考
    # 仅取前 20 个和最后 5 个 segment 作为上下文示例，避免上下文过长
    if len(segments) <= 25:
        sample_indices = list(range(len(segments)))
    else:
        sample_indices = list(range(20)) + list(range(len(segments) - 5, len(segments)))

    seg_hint_lines = []
    for idx in sample_indices:
        seg = segments[idx]
        seg_time = seg.get("time", "00:00")
        seg_sec = seg.get("seconds", 0)
        seg_text = seg.get("text", "")[:40]
        seg_hint_lines.append(f"  [{idx}] time={seg_time} seconds={seg_sec} text=\"{seg_text}\"")

    seg_hint = "\n".join(seg_hint_lines)

    user_prompt = f"""请分析以下播客转录片段，生成结构化的时间轴节点。

【重要】
- 节点必须基于音频内容自然分段，不要随意切分
- 每个节点要有实质性内容（不是废话引子）
- 节点数量由内容密度决定，重要内容多的段落节点就多，不要人为限制
- 如果转录文本中某段话涉及具体事实（公司名/人名/日期/价格/地点），请尽量提取
- 对于提及的名词，如果是公司/产品/电影/游戏/书籍/地点，请给出简短解释

【时间约束 - 关键】
- 时间必须来自转录文本中的 [MM:SS] 时间戳，不允许自由发明
- 每个节点通过 segment 索引范围指定：seg_start_idx（第几个 segment 开始）, seg_end_idx（第几个 segment 结束）
- 以下是当前转录稿的 segment 索引对应表（text 仅显示前 40 字）：
{seg_hint}

【输出格式】
直接输出 JSON 数组，不要用 markdown 包裹，不要写任何解释：
[
  {{
    "seg_start_idx": 0,   // 节点覆盖范围在第几个 segment 开始
    "seg_end_idx": 5,     // 节点覆盖范围在第几个 segment 结束
    "anchor_seg_idx": 2,  // 点击跳转的真正切入点 segment（选话题真正开始的位置，可以与 seg_start_idx 相同或略靠后）
    "title": "节点标题（10字以内，能概括这段在讲什么）",
    "node_type": "company_news|product|person|topic_change|quote|background|fun_moment|other",
    "summary": "这一段主要说了什么（1-3句话）",
    "why_it_matters": "为什么这个节点重要，值得收录？（1句话）",
    "entities": [
      {{
        "name": "实体名称",
        "type": "company|product|person|location|concept|media|other",
        "description": "在本期语境下的简要解释（1句话）"
      }}
    ],
    "facts": [
      {{
        "label": "事实标签",
        "value": "具体事实内容"
      }}
    ],
    "quote_or_joke_explainer": "如果这段有值得解读的梗/笑话/双关/上下文解释，在此说明；否则为空字符串"
  }}
]

【转录片段 {chunk_index + 1}/{total_chunks}】：
{chunk_text}

直接输出 JSON，不要输出任何其他内容。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    result = _call_llm_json(api_key, messages, temperature=0.3)

    if isinstance(result, list):
        return result
    elif isinstance(result, dict) and "nodes" in result:
        return result["nodes"]
    else:
        print(f"[Timeline] chunk {chunk_index} 返回格式异常: {type(result)}")
        return []


def _merge_timeline_chunks(chunks_results: list, title: str, audio_duration: float, segments: list) -> dict:
    """
    将各 chunk 生成的节点列表合并为一个完整的 timeline.json。

    策略：
    1. 将所有节点按 start 秒数排序
    2. 合并严重重叠节点（> 80%）
    3. 校验并修正越界时间
    4. 重新分配 node_id
    5. 填充过大的时间缺口
    """
    all_nodes = []
    for chunk_nodes in chunks_results:
        if isinstance(chunk_nodes, list):
            all_nodes.extend(chunk_nodes)

    if not all_nodes:
        return {
            "mode": "timeline",
            "version": 1,
            "title": title,
            "nodes": [],
        }

    # 按 start 排序
    all_nodes.sort(key=lambda n: n.get("start", 0) or 0)

    # 合并重叠节点（重叠 > 80%）
    merged = []
    for node in all_nodes:
        if not merged:
            merged.append(node)
            continue
        last = merged[-1]
        last_end = last.get("end", 0) or 0
        last_start = last.get("start", 0) or 0
        n_start = node.get("start", 0) or 0
        n_end = node.get("end", 0) or 0

        overlap = last_end - n_start
        last_dur = last_end - last_start
        if overlap > 0 and last_dur > 0 and overlap / last_dur > 0.8:
            if node.get("summary"):
                last["summary"] = (last.get("summary", "") + " " + node.get("summary", "")).strip()
            if node.get("entities"):
                existing = {e["name"] for e in last.get("entities", [])}
                for e in node["entities"]:
                    if e["name"] not in existing:
                        last.setdefault("entities", []).append(e)
            last["end"] = max(last_end, n_end)
        else:
            merged.append(node)

    # 标准化（过滤越界、clamp、排序）
    timeline_raw = {"mode": "timeline", "version": 1, "title": title, "nodes": merged}
    normalized = _normalize_timeline(timeline_raw, audio_duration)

    # 填充覆盖缺口
    final_nodes = _fill_coverage_gaps(normalized.get("nodes", []), audio_duration, segments)

    return {
        "mode": "timeline",
        "version": 1,
        "title": title,
        "nodes": [{**n, "id": f"node_{i + 1:03d}"} for i, n in enumerate(final_nodes)],
    }


def generate_timeline_json(
    api_key: str,
    podcast_text: str,
    transcript_segments: list,
    title: str = "未命名节目"
) -> dict:
    """
    时间轴模式主入口：为播客音频生成结构化的 timeline.json。

    策略：
    1. 短文本（≤15000 字符）：直接整稿生成
    2. 长文本：按 segments 自然边界分块，各块顺序生成，再合并

    参数:
        api_key: DashScope API Key
        podcast_text: 带时间戳的原始转录文本
        transcript_segments: 转录分段列表（来自 transcriber）
        title: 节目标题

    返回:
        dict: timeline.json 结构
    """
    text_len = len(podcast_text)
    print(f"[Timeline] 开始生成 timeline.json (text_len={text_len}, segments={len(transcript_segments)})")

    # 获取音频总时长（从最后一个 segment 推断）
    audio_duration = 0
    if transcript_segments:
        audio_duration = transcript_segments[-1].get("seconds", 0)
        audio_duration = max(audio_duration, 60)

    # 短文本：整稿生成
    if text_len <= 15000:
        print(f"[Timeline] 短文本策略：整稿生成")
        try:
            nodes = _generate_nodes_for_chunk(api_key, podcast_text, 0, 1, transcript_segments, title)
            processed = _post_process_chunk_nodes(nodes, 0, transcript_segments)
            timeline = _merge_timeline_chunks([processed], title, audio_duration, transcript_segments)
            print(f"[Timeline] 生成成功，共 {len(timeline.get('nodes', []))} 个节点")
            return timeline
        except Exception as e:
            print(f"[Timeline] 整稿生成失败: {e}，尝试分块策略")

    # 长文本：按 segments 分块
    print(f"[Timeline] 长文本策略：分块生成")
    chunks = _split_transcript_by_segments(podcast_text, transcript_segments, max_chars_per_chunk=8000)
    print(f"[Timeline] 分块结果：{len(chunks)} 个块")

    chunk_results = []
    for i, chunk in enumerate(chunks):
        print(f"[Timeline] 处理块 {i + 1}/{len(chunks)} ...")
        try:
            nodes = _generate_nodes_for_chunk(
                api_key, chunk["text"], i, len(chunks), transcript_segments, title
            )
            processed = _post_process_chunk_nodes(
                nodes, chunk.get("start_seconds", 0), transcript_segments
            )
            chunk_results.append(processed)
        except Exception as e:
            print(f"[Timeline] 块 {i + 1} 生成失败: {e}")
            chunk_results.append([])

    timeline = _merge_timeline_chunks(chunk_results, title, audio_duration, transcript_segments)
    print(f"[Timeline] 生成完成，共 {len(timeline.get('nodes', []))} 个节点")
    return timeline