from openai import OpenAI

def get_podcast_summary(api_key, podcast_text):
    """
    使用大语言模型生成播客结构化摘要和时间轴。

    参数:
        api_key (str): 大语言模型 API 密钥
        podcast_text (str): 带时间戳的播客转录文本

    返回:
        str: 结构化的 Markdown 格式摘要，包含短标题、关键词、节目概述和详细时间轴
    """
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    prompt_text = f"""
    请阅读以下【带有时间戳】的播客逐字稿，严格按照以下Markdown格式输出你的分析。

    【输出格式要求】
    请直接在第1行输出15字以内的短标题（纯文本，不要任何标点、前缀或Markdown符号）。
    从第2行开始，严格按照以下模板排版：

    > **🤖 总结引擎**：DeepSeek
    > **🏷️ 核心关键词**：[提取3-5个核心关键词，用逗号隔开]

    ### 📝 节目总体概述
    [请用大约300字详细、全面地总结本期节目的核心主旨、探讨的具体议题以及整体氛围。要求信息丰富、结构清晰，可分段。]

    ### ⏱️ 细致高光时间轴
    [请尽可能细致、密集地提取节目中的话题切换点、高光金句或有趣的细节。时间戳越密越好！]
    [⚠️排版警告：为了防止前端显示错乱，每一条时间轴必须单独占一行，且必须以 Markdown 无序列表符号 `-` 开头！]
    - [MM:SS] 详细描述1...
    - [MM:SS] 详细描述2...

    播客全文如下：\n{podcast_text}
    """
    
    response = client.chat.completions.create(
        model="deepseek-chat", 
        messages=[
            {"role": "system", "content": "你是一个严谨且专业的播客内容分析专家，擅长结构化总结长文本，并且绝对服从格式和排版要求。"},
            {"role": "user", "content": prompt_text}
        ],
        temperature=0.3
    )
    return response.choices[0].message.content

def search_in_podcast(api_key, search_query, podcast_text):
    """
    在播客转录文本中搜索相关内容，返回匹配的时间段和描述。

    参数:
        api_key (str): 大语言模型 API 密钥
        search_query (str): 用户搜索查询
        podcast_text (str): 带时间戳的播客转录文本

    返回:
        str: 搜索结果描述，包含匹配的时间段和内容简述
    """
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    search_prompt = f"""
    用户想在这期播客中寻找关于“{search_query}”的内容。
    请你在以下带有时间戳的播客全文中寻找。如果找到了，请告诉用户该内容大致在哪个时间段 [MM:SS]，并简述他们聊了什么。如果没提到，请如实回答。
    播客全文：\n{podcast_text}
    """
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": search_prompt}],
        temperature=0.2
    )
    return response.choices[0].message.content