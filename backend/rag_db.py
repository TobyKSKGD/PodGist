"""
RAG 数据库模块 - SQLite 关系存储 + ChromaDB 向量存储

管理标签、会话、消息、引用，以及归档内容的向量化和语义检索。
"""

import sqlite3
import os
import uuid
import chromadb
from chromadb.config import Settings as ChromaSettings
from datetime import datetime
from typing import Optional

# ================= 路径配置 =================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAG_DB_DIR = os.path.join(BASE_DIR, "temp_audio")
RAG_DB_PATH = os.path.join(RAG_DB_DIR, "podgist_rag.db")
CHROMA_DB_PATH = os.path.join(RAG_DB_DIR, "chroma_db")

os.makedirs(RAG_DB_DIR, exist_ok=True)

# ================= ChromaDB 客户端 =================
_chroma_client = None

def get_chroma_client():
    """获取 ChromaDB 客户端（单例）"""
    global _chroma_client
    if _chroma_client is None:
        _chroma_client = chromadb.PersistentClient(
            path=CHROMA_DB_PATH,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
    return _chroma_client

def get_archive_chunks_collection():
    """获取归档片段向量集合"""
    client = get_chroma_client()
    return client.get_or_create_collection(
        name="archive_chunks",
        metadata={"description": "归档音频的文本片段向量库"}
    )

# ================= SQLite 连接 =================
def get_db_connection():
    """获取 SQLite 数据库连接"""
    conn = sqlite3.connect(RAG_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ================= 表初始化 =================
def init_db():
    """初始化所有 RAG 相关表结构"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Tags 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
    """)

    # Archive_Tags 表（多对多）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive_tags (
            archive_id TEXT NOT NULL,
            tag_id TEXT NOT NULL,
            PRIMARY KEY (archive_id, tag_id),
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
    """)

    # Chat_Sessions 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # Chat_Messages 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        )
    """)

    # Chat_References 表（溯源）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            archive_id TEXT NOT NULL,
            cited_timestamp TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()

# ================= 标签管理 =================
def create_tag(name: str) -> str:
    """创建标签"""
    tag_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO tags (id, name, created_at) VALUES (?, ?, ?)",
            (tag_id, name.strip(), created_at)
        )
        conn.commit()
        return tag_id
    except sqlite3.IntegrityError:
        # 标签已存在，查询并返回现有 ID
        cursor.execute("SELECT id FROM tags WHERE name = ?", (name.strip(),))
        row = cursor.fetchone()
        return row["id"] if row else None
    finally:
        conn.close()

def get_all_tags():
    """获取所有标签"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tags ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_tag(tag_id: str):
    """删除标签"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    conn.commit()
    conn.close()

def set_archive_tags(archive_id: str, tag_ids: list[str]):
    """设置归档的标签（覆盖式）"""
    conn = get_db_connection()
    cursor = conn.cursor()
    # 删除旧关联
    cursor.execute("DELETE FROM archive_tags WHERE archive_id = ?", (archive_id,))
    # 插入新关联
    for tag_id in tag_ids:
        cursor.execute(
            "INSERT OR IGNORE INTO archive_tags (archive_id, tag_id) VALUES (?, ?)",
            (archive_id, tag_id)
        )
    conn.commit()
    conn.close()

def get_archive_tags(archive_id: str) -> list[dict]:
    """获取归档的所有标签"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.* FROM tags t
        JOIN archive_tags at ON t.id = at.tag_id
        WHERE at.archive_id = ?
    """, (archive_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_archives_by_tag(tag_id: str) -> list[str]:
    """获取指定标签下的所有归档 ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT archive_id FROM archive_tags WHERE tag_id = ?",
        (tag_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [row["archive_id"] for row in rows]

# ================= 会话管理 =================
def create_chat_session(title: str = "新对话") -> str:
    """创建新会话"""
    session_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (session_id, title, now, now)
    )
    conn.commit()
    conn.close()
    return session_id

def get_chat_sessions(order_by: str = "updated_at DESC") -> list[dict]:
    """获取所有会话（按更新时间倒序）"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT * FROM chat_sessions ORDER BY {order_by}")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_chat_session(session_id: str) -> Optional[dict]:
    """获取单个会话"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_chat_session_title(session_id: str, title: str):
    """更新会话标题"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title, datetime.now().isoformat(), session_id)
    )
    conn.commit()
    conn.close()

def delete_chat_session(session_id: str):
    """删除会话（级联删除消息和引用）"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    conn.commit()
    conn.close()

# ================= 消息管理 =================
def add_chat_message(session_id: str, role: str, content: str) -> str:
    """添加聊天消息"""
    msg_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_messages (id, session_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (msg_id, session_id, role, content, created_at)
    )
    # 更新会话的 updated_at
    cursor.execute(
        "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
        (created_at, session_id)
    )
    conn.commit()
    conn.close()
    return msg_id

def get_chat_messages(session_id: str) -> list[dict]:
    """获取会话的所有消息"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ================= 引用管理 =================
def add_chat_reference(session_id: str, archive_id: str, cited_timestamp: str = None):
    """记录一次引用"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO chat_references (session_id, archive_id, cited_timestamp, created_at) VALUES (?, ?, ?, ?)",
        (session_id, archive_id, cited_timestamp, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def get_archive_references(archive_id: str) -> list[dict]:
    """获取引用了某归档的所有会话"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT cs.id, cs.title, cs.updated_at,
               cr.cited_timestamp, cr.created_at as ref_created_at
        FROM chat_references cr
        JOIN chat_sessions cs ON cr.session_id = cs.id
        WHERE cr.archive_id = ?
        ORDER BY cr.created_at DESC
    """, (archive_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

# ================= 向量入库 =================
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[dict]:
    """
    将文本按段落切分成块，每块带时间戳信息。

    返回: list[{"text": str, "timestamp": str, "chunk_index": int}]
    """
    # 按行分割，保留时间戳格式 [MM:SS] 或 [HH:MM:SS]
    import re
    lines = text.split('\n')
    chunks = []
    current_chunk_lines = []
    current_ts = None
    chunk_index = 0

    for line in lines:
        # 提取时间戳
        ts_match = re.search(r'\[(\d{1,2}:\d{2}(?::\d{2})?)\]', line)
        if ts_match:
            current_ts = ts_match.group(1)

        # 跳过空行
        stripped = line.strip()
        if not stripped:
            continue

        # 移除时间戳后检查是否为空
        content = re.sub(r'\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*', '', stripped).strip()
        if not content:
            continue

        current_chunk_lines.append(stripped)

        # 当累积行数达到 chunk_size 时，切一块
        if len(current_chunk_lines) >= chunk_size:
            chunk_text = '\n'.join(current_chunk_lines)
            chunks.append({
                "text": chunk_text,
                "timestamp": current_ts or "",
                "chunk_index": chunk_index
            })
            # 保留 overlap 行作为重叠上下文
            current_chunk_lines = current_chunk_lines[-overlap:]
            chunk_index += 1

    # 处理剩余内容
    if current_chunk_lines:
        chunks.append({
            "text": '\n'.join(current_chunk_lines),
            "timestamp": current_ts or "",
            "chunk_index": chunk_index
        })

    return chunks

def index_archive(archive_id: str, archive_name: str, raw_text: str):
    """
    将归档的原始转录文本分块并向量化，存入 ChromaDB。
    同时记录每块对应的归档信息。
    """
    chunks = chunk_text(raw_text)
    if not chunks:
        return

    collection = get_archive_chunks_collection()

    # 为每块生成 ID、embedding 和 metadata
    ids = [f"{archive_id}_chunk_{c['chunk_index']}" for c in chunks]
    documents = [c["text"] for c in chunks]
    metadatas = [
        {
            "archive_id": archive_id,
            "archive_name": archive_name,
            "timestamp": c["timestamp"],
            "chunk_index": c["chunk_index"]
        }
        for c in chunks
    ]

    # 写入 ChromaDB
    collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

def delete_archive_vectors(archive_id: str):
    """删除某归档的所有向量（当归档被删除时调用）"""
    collection = get_archive_chunks_collection()
    # ChromaDB 不直接支持按 metadata 删除，需要先查询再删除
    try:
        results = collection.get(where={"archive_id": archive_id})
        if results and results["ids"]:
            collection.delete(ids=results["ids"])
    except Exception:
        pass

# ================= 向量检索 =================
def retrieve_relevant_chunks(
    query: str,
    top_k: int = 5,
    archive_ids: list[str] = None,
    tag_ids: list[str] = None
) -> list[dict]:
    """
    混合检索：给定查询，返回最相关的文本块。

    参数:
        query: 用户问题
        top_k: 返回块数量
        archive_ids: 如果指定，只在这些归档中检索
        tag_ids: 如果指定，只在带这些标签的归档中检索

    返回: list[{"text": str, "archive_id": str, "archive_name": str, "timestamp": str, "distance": float}]
    """
    collection = get_archive_chunks_collection()

    # 如果指定了 tag_ids，先查出对应的 archive_ids
    if tag_ids:
        archive_ids = set(archive_ids) if archive_ids else set()
        for tag_id in tag_ids:
            tagged_archives = get_archives_by_tag(tag_id)
            archive_ids.update(tagged_archives)
        archive_ids = list(archive_ids) if archive_ids else None

    # 构建查询条件
    where_filter = None
    if archive_ids:
        if len(archive_ids) == 1:
            where_filter = {"archive_id": archive_ids[0]}
        else:
            where_filter = {"archive_id": {"$in": archive_ids}}

    # 执行向量检索
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    # 格式化结果
    chunks = []
    if results and results["documents"] and results["documents"][0]:
        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i] if results["distances"] else 0.0
            chunks.append({
                "text": doc,
                "archive_id": meta.get("archive_id", ""),
                "archive_name": meta.get("archive_name", ""),
                "timestamp": meta.get("timestamp", ""),
                "distance": float(distance)
            })

    return chunks

# ================= Embedding 模型（惰性加载）=================
_embedding_model = None

def get_embedding_model():
    """获取 Sentence Transformer 模型（单例，惰性加载）"""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        # 使用轻量模型，CPU 可用
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embedding_model

def compute_embeddings(texts: list[str]) -> list[list[float]]:
    """计算文本列表的 embeddings"""
    model = get_embedding_model()
    return model.encode(texts, convert_to_numpy=True).tolist()

# 初始化数据库
init_db()
