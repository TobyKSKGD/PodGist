"""
RAG 检索与生成模块

负责：接收用户问题 → 检索相关片段 → 组装 System Prompt → 调用 LLM 流式生成
"""

from openai import OpenAI
from backend.rag_db import retrieve_relevant_chunks, get_archive_tags
import re

SYSTEM_PROMPT_TEMPLATE = """你是一个专业的私人知识库助理，结合音频归档资料与自身知识回答用户问题。

【参考资料库】:
{injected_retrieved_context}

【回答规则】:
1. 优先参考音频库中的内容，结合自身知识给出完整回答。如果音频库中没有相关内容，正常回答即可，不必声明。
2. 引用观点或数据时，必须在对应句子末尾严格标注来源及时间戳，格式要求：「来源：《{{archive_name}}》[{{timestamp}}]」。
3. 如果用户问题可以多个参考资料共同回答，合并引用。
4. 回答应当结构清晰、语言自然，禁止直接罗列参考资料。"""


def build_retrieved_context(chunks: list[dict]) -> str:
    """将检索到的文本块格式化为上下文"""
    if not chunks:
        return "（音频库中暂无相关记录，请结合自身知识回答）"

    blocks = []
    for i, chunk in enumerate(chunks):
        archive_name = chunk.get("archive_name", "未知归档")
        timestamp = chunk.get("timestamp", "")
        ts_suffix = f" [{timestamp}]" if timestamp else ""
        blocks.append(
            f"【参考{i + 1}】来源：《{archive_name}》{ts_suffix}\n{chunk['text']}"
        )
    return "\n\n".join(blocks)


def generate_chat_response(
    api_key: str,
    query: str,
    archive_ids: list[str] = None,
    tag_ids: list[str] = None,
    top_k: int = 5,
    stream: bool = True
):
    """
    RAG 对话生成器（支持流式和非流式）。

    参数:
        api_key: DeepSeek API Key
        query: 用户问题
        archive_ids: 限定检索的归档 ID 列表（None 表示全库）
        tag_ids: 限定检索的标签 ID 列表
        top_k: 召回片段数量
        stream: 是否流式返回

    Yields:
        dict: 事件类型和内容
    """
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    # Step 1: 检索相关片段
    chunks = retrieve_relevant_chunks(
        query=query,
        top_k=top_k,
        archive_ids=archive_ids,
        tag_ids=tag_ids
    )

    # Step 2: 构建上下文
    retrieved_context = build_retrieved_context(chunks)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        injected_retrieved_context=retrieved_context
    )

    # Step 3: 提取引用信息（包含 archive_name 和 timestamp）
    # 构建 {archive_id: {archive_name, timestamp}} 映射，取每个归档的第一个时间戳
    archive_refs: dict[str, dict] = {}
    for c in chunks:
        aid = c["archive_id"]
        if aid not in archive_refs:
            archive_refs[aid] = {
                "archive_id": aid,
                "archive_name": c.get("archive_name", aid),
                "timestamp": c.get("timestamp", "")
            }
    referenced_archives = list(archive_refs.values())

    # Step 4: 构建消息历史
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]

    # Step 5: 流式调用 LLM
    if stream:
        stream_response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.3,
            stream=True
        )

        full_content = ""
        for chunk in stream_response:
            token = chunk.choices[0].delta.content or ""
            full_content += token
            yield {
                "type": "token",
                "content": token,
                "referenced_archives": referenced_archives
            }

        yield {
            "type": "done",
            "content": full_content,
            "referenced_archives": referenced_archives
        }
    else:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.3,
            stream=False
        )
        full_content = response.choices[0].message.content
        yield {
            "type": "done",
            "content": full_content,
            "referenced_archives": referenced_archives
        }


def extract_references_from_response(content: str, referenced_archives: list[str]) -> list[dict]:
    """
    从 LLM 回复中提取引用标注，解析出 archive_id。

    格式：「来源：《归档名》[MM:SS]」
    返回: list[{"archive_id": str, "archive_name": str, "timestamp": str}]
    """
    refs = []
    pattern = r'「来源：《([^》]+)》\[([^\]]+)\]」'
    matches = re.findall(pattern, content)
    archive_name_to_id = {}

    for archive_name, timestamp in matches:
        # 惰性获取 archive_id（需要查表或前端传）
        if archive_name not in archive_name_to_id:
            from backend.rag_db import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            # 模糊匹配（归档目录名通常包含原始名）
            cursor.execute(
                "SELECT id FROM chat_references WHERE archive_id LIKE ? LIMIT 1",
                (f"%{archive_name}%",)
            )
            # 实际上需要通过 ChromaDB metadata 反查，这里暂时用名称匹配
            archive_name_to_id[archive_name] = archive_name  # 降级：存名称

        refs.append({
            "archive_name": archive_name,
            "archive_id": archive_name_to_id.get(archive_name, archive_name),
            "timestamp": timestamp
        })

    return refs
