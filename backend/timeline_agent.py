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
    - 纯粹的 { ... }
    - Markdown ```json ... ``` 包裹
    """
    content = content.strip()
    # 去掉 markdown 代码块
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    # 纯 JSON
    if content.startswith('{'):
        return json.loads(content)
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


def _generate_nodes_for_chunk(api_key: str, chunk_text: str, chunk_index: int, total_chunks: int, title_hint: str = "") -> list:
    """
    为一个文本块生成 timeline 节点列表。

    参数:
        api_key: DashScope API Key
        chunk_text: 该块的完整文本（含时间戳）
        chunk_index: 块编号（从 0 开始）
        total_chunks: 总块数
        title_hint: 节目标题提示（用于 entity linking）

    返回:
        list[dict]: 该块的节点列表
    """
    system_prompt = """你是一个播客与音频内容分析专家，擅长从转录稿中提取结构化的、有价值的时间轴节点。

你必须严格输出 JSON 数组，不要输出任何解释性文字。
每个节点代表一个有意义的内容片段（通常 1-5 分钟）。
"""

    user_prompt = f"""请分析以下播客转录片段，生成结构化的时间轴节点。

【重要】
- 节点必须基于音频内容自然分段，不要随意切分
- 每个节点要有实质性内容（不是废话引子）
- 节点数量由内容密度决定，重要内容多的段落节点就多，不要人为限制
- 如果转录文本中某段话涉及具体事实（公司名/人名/日期/价格/地点），请尽量提取
- 对于提及的名词，如果是公司/产品/电影/游戏/书籍/地点，请给出简短解释

【输出格式】
直接输出 JSON 数组，不要用 markdown 包裹，不要写任何解释：
[
  {{
    "id": "node_001",
    "start": 26,
    "end": 177,
    "time": "00:26",
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


def _merge_timeline_chunks(chunks_results: list, title: str, api_key: str) -> dict:
    """
    将各 chunk 生成的节点列表合并为一个完整的 timeline.json。

    策略：
    1. 将所有节点按 start 秒数排序
    2. 去掉明显重叠/碎片节点（合并时间重叠超过 50% 的相邻节点）
    3. 重新分配 node_id（格式 node_001, node_002 ...）
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

    # 合并重叠节点（时间重叠超过 50% 且标题相似）
    merged = []
    for node in all_nodes:
        if not merged:
            merged.append(node)
            continue
        last = merged[-1]
        last_end = last.get("end", 0) or 0
        last_start = last.get("start", 0) or 0
        node_start = node.get("start", 0) or 0

        overlap = last_end - node_start
        last_duration = last_end - last_start
        if overlap > 0 and overlap / max(last_duration, 1) > 0.5:
            # 重叠超过 50%，合并：将新节点内容合并到 last
            if node.get("summary"):
                last["summary"] = (last.get("summary", "") + " " + node.get("summary")).strip()
            if node.get("entities"):
                existing_names = {e["name"] for e in last.get("entities", [])}
                for e in node["entities"]:
                    if e["name"] not in existing_names:
                        last.setdefault("entities", []).append(e)
            last["end"] = max(last_end, node.get("end", 0) or 0)
        else:
            merged.append(node)

    # 重新分配 node_id
    final_nodes = []
    for i, node in enumerate(merged):
        final_nodes.append({
            **node,
            "id": f"node_{i + 1:03d}",
        })

    return {
        "mode": "timeline",
        "version": 1,
        "title": title,
        "nodes": final_nodes,
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
    2. 长文本：按 segments 自然边界分块，各块并行生成，再合并

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

    # 短文本：整稿生成
    if text_len <= 15000:
        print(f"[Timeline] 短文本策略：整稿生成")
        try:
            nodes = _generate_nodes_for_chunk(api_key, podcast_text, 0, 1, title)
            timeline = _merge_timeline_chunks([nodes], title, api_key)
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
            nodes = _generate_nodes_for_chunk(api_key, chunk["text"], i, len(chunks), title)
            # 为节点补充时间范围
            for node in nodes:
                if not node.get("start") and chunk.get("start_seconds"):
                    node["start"] = chunk["start_seconds"]
                if not node.get("end") and chunk.get("end_seconds"):
                    node["end"] = chunk["end_seconds"]
            chunk_results.append(nodes)
        except Exception as e:
            print(f"[Timeline] 块 {i + 1} 生成失败: {e}")
            chunk_results.append([])

    timeline = _merge_timeline_chunks(chunk_results, title, api_key)
    print(f"[Timeline] 生成完成，共 {len(timeline.get('nodes', []))} 个节点")
    return timeline
