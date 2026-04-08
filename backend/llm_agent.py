import time
from dashscope import Generation
from http import HTTPStatus

# 模型降级梯队：按质量和速度排序，质量优先，速度其次
MODEL_FALLBACK_LIST = ['qwen-plus', 'qwen-turbo', 'qwen-max']
# 分块摘要阶段用更快模型，merge 阶段用更强模型
CHUNK_MODEL = 'qwen-turbo'  # 分块摘要用 turbo，加速处理


def _call_llm_with_retry(api_key, messages, max_retries=2, temperature=0.3, model=None):
    """
    带重试 + 模型降级的 LLM 调用（DashScope Qwen）。

    参数:
        api_key: DashScope API 密钥
        messages: 消息列表
        max_retries: 每个模型的最大重试次数
        temperature: 温度参数
        model: 可选，指定单个模型；默认 None 会使用 MODEL_FALLBACK_LIST 逐个降级

    返回:
        str: LLM 响应内容

    异常:
        Exception: 如果所有模型 + 所有重试都失败
    """
    models_to_try = [model] if model else list(MODEL_FALLBACK_LIST)
    last_err = None

    for m in models_to_try:
        for attempt in range(max_retries):
            try:
                response = Generation.call(
                    model=m,
                    messages=messages,
                    result_format="message",
                    temperature=temperature,
                    api_key=api_key,
                    request_timeout=600
                )
                if response.status_code == HTTPStatus.OK:
                    print(f"[LLM] {m} 调用成功")
                    return response.output.choices[0].message.content
                else:
                    err_msg = f"status={response.code} msg={response.message}"
                    # 检测速率限制：如果是限流错误，增加更长的等待时间
                    is_rate_limit = (response.status_code == 429 or
                                     response.code in ('RateLimitError', 'ThrottlingException', 'TooManyRequestsException'))
                    print(f"[LLM] {m} attempt {attempt+1} 失败: {err_msg}" + (" (检测到限流，增加等待时间)" if is_rate_limit else ""))
                    last_err = Exception(f"LLM error ({m}): {err_msg}")
                    # 限流时增加等待时间
                    if is_rate_limit:
                        time.sleep(15)
            except Exception as e:
                err_type = type(e).__name__
                err_msg = str(e)
                # 检测是否是限流相关异常
                is_rate_limit = any(x in err_msg.lower() for x in ['rate', 'limit', 'throttle', '429', 'too many'])
                print(f"[LLM] {m} attempt {attempt+1} 异常 [{err_type}]: {err_msg}" + (" (检测到限流，增加等待时间)" if is_rate_limit else ""))
                last_err = Exception(f"[{err_type}] {err_msg}")
                if is_rate_limit:
                    time.sleep(15)

            if attempt < max_retries - 1:
                time.sleep(2)
                temperature = min(temperature + 0.2, 0.7)
            else:
                print(f"[LLM] {m} 全部重试失败，切换下一个模型...")

        # 当前模型全部重试失败，换下一个模型
        # 增加延迟，避免触发 DashScope 速率限制
        time.sleep(5)
        temperature = 0.3  # 重置 temperature

    # 所有模型都失败了
    raise Exception(f"所有模型 {models_to_try} 都调用失败，最终错误: {last_err}")


def _split_text_into_chunks_safely(podcast_text, max_chars=12000, overlap_lines=8):
    """
    按字符数分块，优先保证每块不超过 max_chars。
    - 如果文本整体 <= max_chars，直接返回单块
    - 否则按行累积，超出 max_chars 时切割，保留 overlap_lines 行作为下一块的开头重叠

    参数:
        podcast_text: 原始转录文本
        max_chars: 每块最大字符数（近似 token 量）
        overlap_lines: 块与块之间的重叠行数

    返回:
        list[str]: 文本块列表
    """
    if not podcast_text:
        return []

    lines = podcast_text.split('\n')
    total_len = len(podcast_text)
    total_lines = len(lines)

    print(f"[LLM] 文本长度={total_len}字符 行数={total_lines}，max_chars={max_chars}")

    if total_len <= max_chars:
        print(f"[LLM] 文本较短，跳过 chunk，直接返回原文")
        return [podcast_text]

    chunks = []
    current_lines = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for '\n'
        if current_lines and current_len + line_len > max_chars:
            # 当前块已达到上限，切割
            chunks.append('\n'.join(current_lines))
            # 保留 overlap_lines 作为下一块的开头
            if overlap_lines > 0:
                overlap = current_lines[-overlap_lines:]
                current_lines = overlap[:]
                current_len = sum(len(x) + 1 for x in current_lines)
            else:
                current_lines = []
                current_len = 0

        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append('\n'.join(current_lines))

    print(f"[LLM] 分块完成，共 {len(chunks)} 块")
    for i, c in enumerate(chunks):
        print(f"[LLM]   chunk[{i}] len={len(c)} chars")

    return chunks


def _merge_summaries(part_summaries, api_key):
    """
    合并多个部分的摘要（使用高质量模型 qwen-plus）。

    参数:
        part_summaries: 各部分的摘要列表
        api_key: DashScope API 密钥

    返回:
        str: 合并后的摘要
    """
    merge_prompt = f"""
请将以下多个部分的摘要合并成一个完整的播客摘要。

【输出格式要求】严格遵循以下格式，不要输出任何提示词或说明文字：
**核心话题**：[一句话概括]
**关键词**：[关键词列表]
**概述**：
[详细概述内容]
**时间轴**：
[MM:SS] 事件1
[MM:SS] 事件2
...

合并以下多个摘要（去重、保留最有价值的内容，按时间顺序排列）：
""" + '\n'.join(f'【Part {i+1}】\n{s}' for i, s in enumerate(part_summaries))

    messages = [
        {"role": "system", "content": "你是一个严谨且专业的音频内容分析专家，擅长合并和整理摘要。"},
        {"role": "user", "content": merge_prompt}
    ]

    return _call_llm_with_retry(api_key, messages, max_retries=2, temperature=0.3)


def get_podcast_summary_robust(api_key, podcast_text, max_timeline_items=15):
    """
    健壮版：生成音频结构化摘要。

    策略：
    - 短文本（<=15000字符）：先尝试整稿两次（Prompt Throttling）
    - 长文本（>15000字符）：直接进入 Map-Reduce 分块总结
    - 所有策略失败：返回明确标记的 fallback 文案，不再伪装成"超时"

    参数:
        api_key: DashScope API 密钥
        podcast_text: 带时间戳的音频转录文本
        max_timeline_items: 时间轴最大条目数

    返回:
        str: 结构化的 Markdown 格式摘要
    """
    text_len = len(podcast_text)
    line_count = len(podcast_text.split('\n'))

    print(f"[LLM] text_len={text_len} line_count={line_count} max_timeline_items={max_timeline_items}")

    # ---------- 构建基础 prompt ----------
    prompt_base = f"""
你是一个播客与音频内容分析专家。请阅读以下【带有时间戳】的音频逐字稿，输出一期节目的结构化摘要。

【重要】你的输出必须严格遵循以下格式，不要包含任何提示词、说明文字或解释，直接输出摘要内容：

**核心话题**：[一句话概括本期核心主题，不超过30字]

**关键词**：[3-5个核心关键词，用逗号隔开]

**概述**：
[用200-400字详细总结本期节目的核心主旨、探讨的具体议题、讨论深度和整体氛围。内容要丰富完整，可以分段。]

**时间轴**：
[按时间顺序列出本期节目的关键时间节点，每条格式为：[MM:SS] 事件描述。只列出真正值得记录的高光时刻和议题切换点，不要事无巨细地记流水账。]

音频全文如下：
{podcast_text}
"""

    # ---------- 决定走哪条路线 ----------
    USE_FULLTEXT_STRATEGY = (text_len <= 15000)

    if USE_FULLTEXT_STRATEGY:
        # === 短文本：先尝试整稿（Prompt Throttling）===
        print(f"[LLM] 策略: 整稿尝试 (text_len={text_len} <= 15000)")

        messages = [
            {"role": "system", "content": "你是一个播客与音频内容分析专家，擅长将长篇音频转录稿提炼为结构清晰、内容丰富的摘要，严格遵循用户要求的输出格式，绝不输出任何提示词或说明文字。"},
            {"role": "user", "content": prompt_base}
        ]

        try:
            result = _call_llm_with_retry(api_key, messages, max_retries=2, temperature=0.3)
            print(f"[LLM] 整稿尝试1 成功")
            return result
        except Exception as e:
            print(f"[LLM] 整稿尝试1 失败: {e}")

        # 尝试2：使用更高 temperature 鼓励更完整的输出
        messages[1]["content"] = prompt_base

        try:
            result = _call_llm_with_retry(api_key, messages, max_retries=2, temperature=0.5)
            print(f"[LLM] 整稿尝试2 成功")
            return result
        except Exception as e:
            print(f"[LLM] 整稿尝试2 失败: {e}")
    else:
        print(f"[LLM] 策略: 直接 Map-Reduce (text_len={text_len} > 15000)，跳过整稿")

    # ---------- 长文本或整稿失败：Map-Reduce ----------
    print(f"[LLM] 进入 Map-Reduce 分块总结...")

    # 分块：按字符数 + overlap
    chunks = _split_text_into_chunks_safely(podcast_text, max_chars=12000, overlap_lines=8)

    if len(chunks) == 1:
        # 分块后只有 1 块，说明文本本身较短但还是失败了
        # 最后再试一次整稿（兜底）
        print(f"[LLM] 只有1个 chunk，最后尝试整稿...")
        messages = [
            {"role": "system", "content": "你是一个播客与音频内容分析专家，擅长将长篇音频转录稿提炼为结构清晰、内容丰富的摘要，严格遵循用户要求的输出格式，绝不输出任何提示词或说明文字。"},
            {"role": "user", "content": prompt_base}
        ]
        try:
            return _call_llm_with_retry(api_key, messages, max_retries=2, temperature=0.3)
        except Exception as e:
            print(f"[LLM] 最终整稿兜底也失败: {e}")

    # 对每个 chunk 分别摘要（用更快的 turbo 模型）
    part_summaries = []
    for i, chunk in enumerate(chunks):
        chunk_prompt = f"""
请阅读以下【带有时间戳】的音频片段，提取关键信息。

【输出格式】严格遵循以下格式：
**核心话题**：[1-2句话]
**时间轴**：
[MM:SS] 事件描述
...

片段 {i+1}/{len(chunks)}（共 {len(chunk)} 字符）：
{chunk}
"""
        chunk_messages = [
            {"role": "system", "content": "你是一个播客与音频内容分析专家，擅长提炼关键信息，严格遵循格式要求输出。"},
            {"role": "user", "content": chunk_prompt}
        ]

        try:
            # 分块用 turbo 加速，不需要降级（已在最底层）
            part_result = _call_llm_with_retry(api_key, chunk_messages, max_retries=2, temperature=0.4, model=CHUNK_MODEL)
            part_summaries.append(part_result)
            print(f"[LLM] chunk[{i}]/{len(chunks)} 摘要成功")
        except Exception as e:
            print(f"[LLM] chunk[{i}]/{len(chunks)} 摘要失败: {e}")
            # 失败的 chunk 跳过，不阻塞其他块
            continue

    # 合并
    if part_summaries:
        try:
            merged = _merge_summaries(part_summaries, api_key)
            print(f"[LLM] Map-Reduce 合并成功，共 {len(part_summaries)} 个块")
            return merged
        except Exception as e:
            print(f"[LLM] Map-Reduce 合并失败: {e}")

    # ---------- 最终兜底：所有策略全部失败 ----------
    # 不再伪装成"超时"，给用户准确描述
    fallback_text = f"""<!-- PODGIST_SUMMARY_FALLBACK -->
AI 总结暂时未生成，但您的音频已成功转录！

> **提示**：本次失败可能由音频过长（{text_len}字符 / {line_count}行）、网络波动、模型限流或上下文过大导致。
>
> 您可以稍后重试，或直接查看下方原始转录稿。

---

### 原始转录稿（{text_len} 字符）

```
{podcast_text[:5000]}...
```
"""
    print(f"[LLM] 所有策略失败，返回 fallback（text_len={text_len}）")
    return fallback_text


def get_podcast_summary(api_key, podcast_text, max_timeline_items=15, temperature=0.3):
    """
    使用大语言模型生成音频结构化摘要和时间轴。

    参数:
        api_key (str): 大语言模型 API 密钥
        podcast_text (str): 带时间戳的音频转录文本
        max_timeline_items (int): 时间轴最大条目数，默认 15
        temperature (float): 温度参数，默认 0.3

    返回:
        str: 结构化的 Markdown 格式摘要
    """
    # 统一走健壮版本，带完整降级和分块
    return get_podcast_summary_robust(api_key, podcast_text, max_timeline_items=max_timeline_items)


def search_in_podcast(api_key, search_query, podcast_text):
    """
    在音频转录文本中搜索相关内容。

    参数:
        api_key: DashScope API 密钥
        search_query: 用户搜索查询
        podcast_text: 带时间戳的音频转录文本

    返回:
        str: 搜索结果描述
    """
    search_prompt = f"""
用户想在这期音频中寻找关于"{search_query}"的内容。
请你在以下带有时间戳的音频全文中寻找。如果找到了，请告诉用户该内容大致在哪个时间段 [MM:SS]，并简述他们聊了什么。如果没提到，请如实回答。
音频全文：\n{podcast_text}
"""
    messages = [{"role": "user", "content": search_prompt}]

    return _call_llm_with_retry(api_key, messages, max_retries=2, temperature=0.2)
