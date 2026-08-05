"""
RAG 数据库模块 - SQLite 关系存储 + 本地归档检索索引

管理标签、会话、消息、引用，以及归档内容的向量化和语义检索。
"""

import sqlite3
import os
import uuid
import json
import re
from datetime import datetime
from typing import Optional

# ================= 路径配置（支持 Electron 打包）=================
# 通过环境变量 PODGIST_DATA_DIR 指定用户数据目录

_USER_DATA_DIR = os.environ.get('PODGIST_DATA_DIR', None)

if _USER_DATA_DIR:
    _BASE_DIR = _USER_DATA_DIR
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RAG_DB_DIR = os.path.join(_BASE_DIR, "temp_audio")
ARCHIVE_DIR = os.path.join(_BASE_DIR, "archives")

RAG_DB_PATH = os.path.join(RAG_DB_DIR, "podgist_rag.db")

os.makedirs(RAG_DB_DIR, exist_ok=True)

# ================= SQLite 连接 =================
def get_db_connection():
    """获取 SQLite 数据库连接"""
    conn = sqlite3.connect(RAG_DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    # RAG 索引会在启动后台任务中写入，而对话会同时读取；WAL 能避免两者互相阻塞。
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=15000")
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

    # 可移植的本地检索索引。这里刻意不依赖 Chroma 的默认 ONNX 模型：该模型会在
    # 首次查询时下载，PyInstaller 产物中既没有模型也没有稳定的下载缓存，正是桌面版
    # 智能对话失效的根因。SQLite 是 Python 标准库的一部分，在 macOS/Windows 打包版
    # 均可直接使用。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive_chunks (
            chunk_id TEXT PRIMARY KEY,
            archive_id TEXT NOT NULL,
            archive_name TEXT NOT NULL,
            timestamp TEXT NOT NULL DEFAULT '',
            source_kind TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_archive_chunks_archive_id
        ON archive_chunks(archive_id)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS archive_index_state (
            archive_id TEXT PRIMARY KEY,
            raw_mtime_ns INTEGER NOT NULL DEFAULT 0,
            timeline_mtime_ns INTEGER NOT NULL DEFAULT 0,
            indexed_at TEXT NOT NULL
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
def chunk_text(text: str, chunk_size: int = 800, overlap: int = 200) -> list[dict]:
    """
    将转录文本按字符数切分成块，每块带时间戳信息。

    参数:
        text: 原始转录文本（含 [MM:SS] 时间戳格式）
        chunk_size: 每块最大字符数（默认 500）
        overlap: 相邻块之间的重叠字符数（默认 100）

    返回: list[{"text": str, "timestamp": str, "chunk_index": int}]
    """
    import re
    lines = text.split('\n')
    chunks = []
    current_chunk_chars = []
    current_chunk_len = 0
    first_ts = None  # 用第一个时间戳，不是最后一个
    chunk_index = 0

    for line in lines:
        # 提取时间戳（保留）
        ts_match = re.search(r'\[(\d{1,2}:\d{2}(?::\d{2})?)\]', line)
        if ts_match:
            if first_ts is None:
                first_ts = ts_match.group(1)
            current_ts = ts_match.group(1)

        stripped = line.strip()
        if not stripped:
            continue

        # 移除时间戳后检查内容是否为空
        content = re.sub(r'\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*', '', stripped).strip()
        if not content:
            continue

        line_len = len(stripped) + 1  # +1 for \n

        # 如果加上这行会超过 chunk_size，先保存当前块
        if current_chunk_len + line_len > chunk_size and current_chunk_chars:
            chunks.append({
                "text": '\n'.join(current_chunk_chars),
                "timestamp": first_ts or "",
                "chunk_index": chunk_index
            })
            chunk_index += 1
            # 重置，保留最后 overlap 个字符作为重叠上下文
            overlap_chars = '\n'.join(current_chunk_chars)[-overlap:]
            current_chunk_chars = overlap_chars.split('\n') if overlap_chars.strip() else []
            current_chunk_len = sum(len(l) + 1 for l in current_chunk_chars)
            first_ts = current_ts  # 重叠部分的时间轴起点更新为最后一个时间戳

        current_chunk_chars.append(stripped)
        current_chunk_len += line_len

    # 处理剩余内容
    if current_chunk_chars:
        chunks.append({
            "text": '\n'.join(current_chunk_chars),
            "timestamp": first_ts or "",
            "chunk_index": chunk_index
        })

    return chunks

def _format_timestamp(seconds: object, fallback: str = "") -> str:
    """将时间轴节点的秒数转成和转录一致的 MM:SS 格式。"""
    if isinstance(seconds, (int, float)) and seconds >= 0:
        total = int(seconds)
        return f"{total // 60:02d}:{total % 60:02d}"
    return fallback


def _read_archive_metadata(archive_id: str) -> tuple[str, dict, int, int]:
    """读取归档标题与时间轴；旧归档缺字段时保持可检索。"""
    archive_path = os.path.join(ARCHIVE_DIR, archive_id)
    metadata: dict = {}
    timeline_data: dict = {}
    raw_mtime_ns = 0
    timeline_mtime_ns = 0

    metadata_path = os.path.join(archive_path, "metadata.json")
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                metadata = loaded
        except (OSError, json.JSONDecodeError):
            pass

    timeline_path = os.path.join(archive_path, "timeline.json")
    if os.path.exists(timeline_path):
        try:
            with open(timeline_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                timeline_data = loaded
            timeline_mtime_ns = os.stat(timeline_path).st_mtime_ns
        except (OSError, json.JSONDecodeError):
            pass

    raw_path = os.path.join(archive_path, "raw.txt")
    if os.path.exists(raw_path):
        raw_mtime_ns = os.stat(raw_path).st_mtime_ns

    archive_name = str(metadata.get("title") or timeline_data.get("title") or archive_id)
    return archive_name, timeline_data, raw_mtime_ns, timeline_mtime_ns


def _timeline_chunks(timeline_data: dict) -> list[dict]:
    """把时间轴节点变成可检索、可精确引用的资料块。"""
    chunks: list[dict] = []
    nodes = timeline_data.get("nodes", []) if isinstance(timeline_data, dict) else []
    if not isinstance(nodes, list):
        return chunks

    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            continue
        timestamp = _format_timestamp(node.get("start"), str(node.get("time") or ""))
        parts = [
            str(node.get("title") or ""),
            str(node.get("summary") or ""),
            str(node.get("why_it_matters") or ""),
            str(node.get("quote_or_joke_explainer") or ""),
        ]
        for fact in node.get("facts", []) if isinstance(node.get("facts"), list) else []:
            if isinstance(fact, dict):
                parts.append(f"{fact.get('label', '')}：{fact.get('value', '')}")
        for entity in node.get("entities", []) if isinstance(node.get("entities"), list) else []:
            if isinstance(entity, dict):
                parts.append(f"{entity.get('name', '')}：{entity.get('description', '')}")
        content = "\n".join(part.strip() for part in parts if part and part.strip())
        if content:
            chunks.append({
                "chunk_id": f"timeline_{index}",
                "text": content,
                "timestamp": timestamp,
                "source_kind": "timeline",
            })
    return chunks


def index_archive(archive_id: str, archive_name: str, raw_text: str):
    """索引归档的逐字稿与时间轴，所有数据只落在用户本地 SQLite 中。"""
    resolved_name, timeline_data, raw_mtime_ns, timeline_mtime_ns = _read_archive_metadata(archive_id)
    # 调用方传入显式名称时仍尊重它；旧调用传 archive_id 时自动升级为归档标题。
    display_name = resolved_name if archive_name == archive_id else archive_name
    chunks = [
        {
            "chunk_id": f"raw_{chunk['chunk_index']}",
            "text": chunk["text"],
            "timestamp": chunk["timestamp"],
            "source_kind": "transcript",
        }
        for chunk in chunk_text(raw_text)
    ]
    chunks.extend(_timeline_chunks(timeline_data))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM archive_chunks WHERE archive_id = ?", (archive_id,))
        if chunks:
            cursor.executemany(
                """
                INSERT INTO archive_chunks
                (chunk_id, archive_id, archive_name, timestamp, source_kind, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        f"{archive_id}:{chunk['chunk_id']}", archive_id, display_name,
                        chunk["timestamp"], chunk["source_kind"], chunk["text"],
                    )
                    for chunk in chunks
                ],
            )
        cursor.execute(
            """
            INSERT INTO archive_index_state
            (archive_id, raw_mtime_ns, timeline_mtime_ns, indexed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(archive_id) DO UPDATE SET
                raw_mtime_ns = excluded.raw_mtime_ns,
                timeline_mtime_ns = excluded.timeline_mtime_ns,
                indexed_at = excluded.indexed_at
            """,
            (archive_id, raw_mtime_ns, timeline_mtime_ns, datetime.now().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def ensure_archives_indexed():
    """按文件修改时间补齐索引，保证桌面版第一次提问也能检索历史归档。"""
    if not os.path.isdir(ARCHIVE_DIR):
        return

    conn = get_db_connection()
    try:
        states = {
            row["archive_id"]: (row["raw_mtime_ns"], row["timeline_mtime_ns"])
            for row in conn.execute("SELECT archive_id, raw_mtime_ns, timeline_mtime_ns FROM archive_index_state")
        }
    finally:
        conn.close()

    for archive_id in os.listdir(ARCHIVE_DIR):
        archive_path = os.path.join(ARCHIVE_DIR, archive_id)
        raw_path = os.path.join(archive_path, "raw.txt")
        if not os.path.isdir(archive_path) or not os.path.isfile(raw_path):
            continue
        _, _, raw_mtime_ns, timeline_mtime_ns = _read_archive_metadata(archive_id)
        if states.get(archive_id) == (raw_mtime_ns, timeline_mtime_ns):
            continue
        with open(raw_path, "r", encoding="utf-8") as f:
            index_archive(archive_id, archive_id, f.read())


def delete_archive_vectors(archive_id: str):
    """删除某归档的本地检索记录（保留旧函数名以兼容 API 调用）。"""
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM archive_chunks WHERE archive_id = ?", (archive_id,))
        conn.execute("DELETE FROM archive_index_state WHERE archive_id = ?", (archive_id,))
        conn.commit()
    finally:
        conn.close()


# ================= 本地检索 =================
def _query_terms(query: str) -> set[str]:
    """生成适合中英文混排内容的轻量关键词集合。"""
    normalized = query.lower()
    terms = set(re.findall(r"[a-z0-9][a-z0-9_+.-]*", normalized))
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
    terms.update(chinese[index:index + 2] for index in range(max(0, len(chinese) - 1)))
    terms.update(char for char in chinese if char not in "的了和是我你他她它在有与及或吗呢啊把被对从到")
    return {term for term in terms if len(term) > 1 or "\u4e00" <= term <= "\u9fff"}


def _score_chunk(content: str, terms: set[str], source_kind: str) -> float:
    normalized = content.lower()
    matched = 0
    occurrences = 0
    for term in terms:
        count = normalized.count(term)
        if count:
            matched += 1
            occurrences += min(count, 3)
    if not matched:
        return 0.0
    score = matched * 5.0 + occurrences
    # 时间轴是 PodGist 的主数据结构：它由模型按主题切分、带有节点起点，
    # 因此在同等相关性下优先使用它回答，引用可以直接跳回准确位置。
    if source_kind == "timeline":
        score += 30.0
    return score


def retrieve_relevant_chunks(
    query: str,
    top_k: int = 5,
    archive_ids: list[str] = None,
    tag_ids: list[str] = None
) -> list[dict]:
    """
    在本地 SQLite 索引中检索逐字稿和时间轴节点。

    参数:
        query: 用户问题
        top_k: 返回块数量
        archive_ids: 如果指定，只在这些归档中检索
        tag_ids: 如果指定，只在带这些标签的归档中检索

    返回: list[{"text": str, "archive_id": str, "archive_name": str, "timestamp": str, "distance": float}]
    """
    # 如果指定了 tag_ids，先查出对应的 archive_ids
    if tag_ids:
        archive_ids = set(archive_ids) if archive_ids else set()
        for tag_id in tag_ids:
            tagged_archives = get_archives_by_tag(tag_id)
            archive_ids.update(tagged_archives)
        if not archive_ids:
            return []

    terms = _query_terms(query)
    if not terms:
        return []

    sql = "SELECT archive_id, archive_name, timestamp, source_kind, content FROM archive_chunks"
    params: list[str] = []
    if archive_ids:
        placeholders = ", ".join("?" for _ in archive_ids)
        sql += f" WHERE archive_id IN ({placeholders})"
        params.extend(archive_ids)

    conn = get_db_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    ranked = []
    for row in rows:
        score = _score_chunk(row["content"], terms, row["source_kind"])
        if score:
            ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)

    return [
        {
            "text": row["content"],
            "archive_id": row["archive_id"],
            "archive_name": row["archive_name"],
            "timestamp": row["timestamp"],
            "distance": float(-score),
        }
        for score, row in ranked[:top_k]
    ]

# 初始化数据库
init_db()
