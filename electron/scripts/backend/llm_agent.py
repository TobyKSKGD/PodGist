from openai import OpenAI
import time


def get_podcast_summary(api_key, podcast_text, max_timeline_items=15, temperature=0.3):
    """
    使用大语言模型生成音频结构化摘要和时间轴。

    参数:
        api_key (str): 大语言模型 API 密钥
        podcast_text (str): 带时间戳的音频转录文本
        max_timeline_items (int): 时间轴最大条目数，默认 15
        temperature (float): 温度参数，默认 0.3

    返回:
        str: 结构化的 Markdown 格式摘要，包含短标题、关键词、节目概述和详细时间轴
    """
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    prompt_text = f"""
    请阅读以下【带有时间戳】的音频逐字稿，严格按照以下Markdown格式输出你的分析。

    【输出格式要求】
    请直接在第1行输出15字以内的短标题（纯文本，不要任何标点、前缀或Markdown符号）。
    从第2行开始，严格按照以下模板排版：

    > **总结引擎**：DeepSeek
    > **🏷️ 核心关键词**：[提取3-5个核心关键词，用逗号隔开]

    ### 节目总体概述
    [请用大约300字详细、全面地总结本期节目的核心主旨、探讨的具体议题以及整体氛围。要求信息丰富、结构清晰，可分段。]

    ### 细致高光时间轴
    [强制限制：为了保证报告的阅读体验，你提取的高光时间轴节点【最多不超过 {max_timeline_items} 条】！请站在全局视角，仅提炼最核心的议题切换点，并准确引用对应时间轴。禁止事无巨细地记流水账。]
    [排版警告：为了防止前端显示错乱，每一条时间轴必须单独占一行，且必须以 Markdown 无序列表符号 `-` 开头！]
    - [MM:SS] 详细描述1...
    - [MM:SS] 详细描述2...

    音频全文如下：\n{podcast_text}
    """

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是一个严谨且专业的音频内容分析专家，擅长结构化总结长文本，并且绝对服从格式和排版要求。"},
            {"role": "user", "content": prompt_text}
        ],
        temperature=temperature
    )
    return response.choices[0].message.content


def _call_llm_with_retry(client, messages, max_retries=2, temperature=0.3):
    """
    带重试机制的 LLM 调用。

    参数:
        client: OpenAI 客户端
        messages: 消息列表
        max_retries: 最大重试次数
        temperature: 温度参数

    返回:
        str: LLM 响应内容

    异常:
        Exception: 如果所有重试都失败
    """
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < max_retries - 1:
                # 第一次失败后，等待 2 秒再试
                time.sleep(2)
                # 第二次尝试时稍微调高 temperature，打破死锁
                temperature = min(temperature + 0.2, 0.7)
            else:
                raise e


def _split_text_into_chunks(podcast_text, chunk_size=2000):
    """
    将文本按行数分割成多个块。

    参数:
        podcast_text (str): 原始文本
        chunk_size (int): 每块的行数阈值

    返回:
        list: 文本块列表
    """
    lines = podcast_text.split('\n')
    if len(lines) <= chunk_size:
        return [podcast_text]

    chunks = []
    for i in range(0, len(lines), chunk_size):
        chunk = '\n'.join(lines[i:i + chunk_size])
        chunks.append(chunk)
    return chunks


def _merge_summaries(part_summaries, client):
    """
    合并多个部分的摘要。

    参数:
        part_summaries (list): 各部分的摘要
        client: OpenAI 客户端

    返回:
        str: 合并后的摘要
    """
    merge_prompt = f"""
    请将以下多个部分的摘要合并成一个完整的摘要。

    要求：
    1. 保留原始格式（短标题、关键词、概述、时间轴）
    2. 时间轴总数不超过 15 条
    3. 去除重复内容
    4. 按时间顺序排列

    ----

    {chr(10).join(f'【Part {i+1}】\n{s}' for i, s in enumerate(part_summaries))}
    """

    messages = [
        {"role": "system", "content": "你是一个严谨且专业的音频内容分析专家，擅长合并和整理摘要。"},
        {"role": "user", "content": merge_prompt}
    ]

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.3
    )
    return response.choices[0].message.content


def get_podcast_summary_robust(api_key, podcast_text, max_timeline_items=15):
    """
    健壮版：使用大语言模型生成音频结构化摘要，包含三层防御机制：
    1. 策略 A：Prompt Throttling（输出限制）
    2. 策略 C：Retry（重试机制）
    3. 策略 B：Map-Reduce（分块处理）

    参数:
        api_key (str): 大语言模型 API 密钥
        podcast_text (str): 带时间戳的音频转录文本
        max_timeline_items (int): 时间轴最大条目数，默认 15

    返回:
        str: 结构化的 Markdown 格式摘要
    """
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    # ========== 策略 A：Prompt Throttling ==========
    # 构建带有输出限制的 prompt
    prompt_text = f"""
    请阅读以下【带有时间戳】的音频逐字稿，严格按照以下Markdown格式输出你的分析。

    【输出格式要求】
    请直接在第1行输出15字以内的短标题（纯文本，不要任何标点、前缀或Markdown符号）。
    从第2行开始，严格按照以下模板排版：

    > **总结引擎**：DeepSeek
    > **🏷️ 核心关键词**：[提取3-5个核心关键词，用逗号隔开]

    ### 节目总体概述
    [请用大约300字详细、全面地总结本期节目的核心主旨、探讨的具体议题以及整体氛围。要求信息丰富、结构清晰，可分段。]

    ### 细致高光时间轴
    [强制限制：为了保证报告的阅读体验，你提取的高光时间轴节点【最多不超过 {max_timeline_items} 条】！请站在全局视角，仅提炼最核心的议题切换点，并准确引用对应时间轴。禁止事无巨细地记流水账。]
    [排版警告：为了防止前端显示错乱，每一条时间轴必须单独占一行，且必须以 Markdown 无序列表符号 `-` 开头！]
    - [MM:SS] 详细描述1...
    - [MM:SS] 详细描述2...

    音频全文如下：\n{podcast_text}
    """

    messages = [
        {"role": "system", "content": "你是一个严谨且专业的音频内容分析专家，擅长结构化总结长文本，并且绝对服从格式和排版要求。"},
        {"role": "user", "content": prompt_text}
    ]

    # ========== 策略 C：Retry 机制 ==========
    # 第一次尝试：使用策略 A
    try:
        result = _call_llm_with_retry(client, messages, max_retries=2, temperature=0.3)
        return result
    except Exception as e:
        print(f"第一次调用失败: {e}")

    # 第二次尝试：减少输出条数，降低难度
    reduced_items = max(8, max_timeline_items // 2)
    prompt_text_v2 = prompt_text.replace(
        f"最多不超过 {max_timeline_items} 条",
        f"最多不超过 {reduced_items} 条"
    )
    messages[1]["content"] = prompt_text_v2

    try:
        result = _call_llm_with_retry(client, messages, max_retries=2, temperature=0.5)
        return result
    except Exception as e:
        print(f"第二次调用失败: {e}")

    # ========== 策略 B：Map-Reduce ==========
    # 如果还是失败，尝试分块处理
    print("尝试使用 Map-Reduce 分块处理...")

    # 按行数分割文本
    chunks = _split_text_into_chunks(podcast_text, chunk_size=1500)

    if len(chunks) > 1:
        # 对每个块进行摘要
        part_summaries = []
        for i, chunk in enumerate(chunks):
            chunk_prompt = f"""
            请阅读以下【带有时间戳】的音频片段，简要提取关键信息。

            【输出格式】（只需输出核心内容，不要过多细节）：
            1. 核心话题（1-2句话）
            2. 时间轴（不超过 5 条）

            片段 {i+1}/{len(chunks)}：
            {chunk}
            """
            chunk_messages = [
                {"role": "system", "content": "你是一个专业的音频内容分析专家。"},
                {"role": "user", "content": chunk_prompt}
            ]

            try:
                part_result = _call_llm_with_retry(client, chunk_messages, max_retries=1, temperature=0.4)
                part_summaries.append(part_result)
            except Exception as e:
                print(f"块 {i+1} 处理失败: {e}")
                continue

        # 合并结果
        if part_summaries:
            try:
                merged = _merge_summaries(part_summaries, client)
                return merged
            except Exception as e:
                print(f"合并失败: {e}")

    # ========== 最终兜底 ==========
    # 所有策略都失败了，返回友好提示
    fallback_text = f"""大模型思考超时了，但您的音频已被成功转录！

> **提示**：由于音频时长较长或网络波动，AI 总结未能完成。
>
> 您可以在下方查看完整的原始转录稿，或稍后重试。

---

### 原始转录稿（{len(podcast_text)} 字符）

```
{podcast_text[:5000]}...
```
"""
    return fallback_text


def search_in_podcast(api_key, search_query, podcast_text):
    """
    在音频转录文本中搜索相关内容，返回匹配的时间段和描述。

    参数:
        api_key (str): 大语言模型 API 密钥
        search_query (str): 用户搜索查询
        podcast_text (str): 带时间戳的音频转录文本

    返回:
        str: 搜索结果描述，包含匹配的时间段和内容简述
    """
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    search_prompt = f"""
    用户想在这期音频中寻找关于"{search_query}"的内容。
    请你在以下带有时间戳的音频全文中寻找。如果找到了，请告诉用户该内容大致在哪个时间段 [MM:SS]，并简述他们聊了什么。如果没提到，请如实回答。
    音频全文：\n{podcast_text}
    """
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": search_prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content
