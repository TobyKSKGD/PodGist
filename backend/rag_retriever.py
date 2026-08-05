"""
RAG 检索与生成模块

负责：接收用户问题 → 检索相关片段 → 组装 System Prompt → 调用 LLM 流式生成
"""

from dashscope import Generation
from http import HTTPStatus
from backend.rag_db import ensure_archives_indexed, retrieve_relevant_chunks
import re

SYSTEM_PROMPT_TEMPLATE = """你是一个专业的私人知识库助理，结合音频归档资料与自身知识回答用户问题。

【参考资料库】:
{injected_retrieved_context}

【回答规则】:
1. 如果参考资料库中"暂无相关记录"，先告知用户"音频库中暂无相关记录"，然后用自己的知识正常回答。
2. 如果参考资料库中有相关内容，优先引用音频库回答，并可适当补充自身知识。
3. 引用观点或数据时，必须在对应句子末尾严格标注来源及时间戳，格式要求：「来源：《{{archive_name}}》[{{timestamp}}]」。归档标题必须逐字使用参考资料中的完整标题，禁止用“……”或其他省略写法替代。
4. 如果用户问题可以多个参考资料共同回答，合并引用。
5. 每个来源标记只能包含一个时间戳；同一观点涉及多个时间点时，分别写成完整的来源标记，禁止在一个来源后连续输出多个 [时间戳]。
6. 回答应当结构清晰、语言自然，禁止直接罗列参考资料。来源标记结束后不要追加引号、句号、列表符号或单独的标点行。"""


def build_retrieved_context(chunks: list[dict]) -> str:
    """将检索到的文本块格式化为上下文"""
    if not chunks:
        return "暂无相关记录"

    blocks = []
    for i, chunk in enumerate(chunks):
        archive_name = chunk.get("archive_name", "未知归档")
        timestamp = chunk.get("timestamp", "")
        ts_suffix = f" [{timestamp}]" if timestamp else ""
        blocks.append(
            f"【参考{i + 1}】来源：《{archive_name}》{ts_suffix}\n{chunk['text']}"
        )
    return "\n\n".join(blocks)


def _ensure_citations(content: str, chunks: list[dict]) -> str:
    """即使模型漏掉标注，也给出实际参与回答的可追溯来源。"""
    # 归档标题本身可能带有嵌套书名号。以紧邻时间戳的外层 `》` 判断引用，
    # 避免把已有的正文引用误判成“无引用”并在末尾重复追加参考来源列表。
    if not chunks or re.search(
        r"《.+?》\s*\[\d{1,2}:\d{2}(?::\d{2})?\]",
        content,
        re.DOTALL,
    ):
        return content

    unique_refs = []
    seen = set()
    for chunk in chunks:
        ref = (chunk.get("archive_name", "未知归档"), chunk.get("timestamp", ""))
        if ref in seen:
            continue
        seen.add(ref)
        timestamp = ref[1] or "未标注时间"
        unique_refs.append(f"- 《{ref[0]}》[{timestamp}]")
        if len(unique_refs) == 5:
            break
    return f"{content.rstrip()}\n\n参考来源：\n" + "\n".join(unique_refs)


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
        api_key: DashScope API Key
        query: 用户问题
        archive_ids: 限定检索的归档 ID 列表（None 表示全库）
        tag_ids: 限定检索的标签 ID 列表
        top_k: 召回片段数量
        stream: 是否流式返回

    Yields:
        dict: 事件类型和内容
    """

    # 首次启动时，后台索引可能尚未跑完；这里按文件修改时间补齐，确保用户的
    # 第一个问题就能命中已有归档，而不是得到一个空知识库。
    ensure_archives_indexed()

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

    # Step 3: 提取引用信息（包含 archive_name 和 timestamp）。
    # 按“归档 + 时间戳”去重，不能只保留归档的第一个时间戳，否则同一归档的
    # 后续来源无法在前端可靠地还原标题和跳转位置。
    archive_refs: dict[tuple[str, str], dict] = {}
    for c in chunks:
        aid = c["archive_id"]
        timestamp = c.get("timestamp", "")
        ref_key = (aid, timestamp)
        if ref_key not in archive_refs:
            archive_refs[ref_key] = {
                "archive_id": aid,
                "archive_name": c.get("archive_name", aid),
                "timestamp": timestamp
            }
    referenced_archives = list(archive_refs.values())

    # Step 4: 构建消息历史
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query}
    ]

    # Step 5: 调用通义千问 LLM
    if stream:
        stream_response = Generation.call(
            model="qwen-plus",
            messages=messages,
            result_format="message",
            stream=True,
            incremental_output=True,
            api_key=api_key
        )

        full_content = ""
        prev_content = ""
        stream_error = None
        for chunk in stream_response:
            if chunk.status_code != HTTPStatus.OK:
                stream_error = getattr(chunk, "message", "通义千问请求失败")
                continue
            # incremental_output=True 时，content 是累积的增量
            content = chunk.output.choices[0].message.content or ""
            # 提取得新增的部分
            token = content[len(prev_content):] if content.startswith(prev_content) else content
            full_content += token
            prev_content = content
            yield {
                "type": "token",
                "content": token,
                "referenced_archives": referenced_archives
            }

        if stream_error and not full_content:
            raise RuntimeError(f"通义千问请求失败: {stream_error}")
        full_content = _ensure_citations(full_content, chunks)

        yield {
            "type": "done",
            "content": full_content,
            "referenced_archives": referenced_archives
        }
    else:
        response = Generation.call(
            model="qwen-plus",
            messages=messages,
            result_format="message",
            stream=False,
            api_key=api_key
        )
        if response.status_code == HTTPStatus.OK:
            full_content = response.output.choices[0].message.content or ""
        else:
            raise RuntimeError(f"通义千问请求失败: {response.message}")
        full_content = _ensure_citations(full_content, chunks)
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
