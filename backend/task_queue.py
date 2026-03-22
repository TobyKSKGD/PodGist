"""
任务队列模块 - SQLite 数据库管理

提供任务队列的增删改查、状态流转等功能。
"""

import sqlite3
import os
import uuid
from datetime import datetime
from pathlib import Path

# 数据库文件路径
DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "temp_audio")
DB_PATH = os.path.join(DB_DIR, "podgist_tasks.db")

# 确保目录存在
os.makedirs(DB_DIR, exist_ok=True)


def get_db_connection():
    """
    获取数据库连接。

    返回:
        sqlite3.Connection: 数据库连接对象
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    初始化数据库表结构。
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            name TEXT,
            type TEXT NOT NULL,
            status TEXT DEFAULT 'PENDING',
            engine TEXT,
            max_timeline_items INTEGER DEFAULT 15,
            create_time TEXT,
            complete_time TEXT,
            result_path TEXT,
            error_msg TEXT
        )
    """)

    # 检查 name 字段是否存在，不存在则添加
    try:
        cursor.execute("SELECT name FROM tasks LIMIT 1")
    except:
        cursor.execute("ALTER TABLE tasks ADD COLUMN name TEXT")

    # 检查 progress_status 字段是否存在
    try:
        cursor.execute("SELECT progress_status FROM tasks LIMIT 1")
    except:
        cursor.execute("ALTER TABLE tasks ADD COLUMN progress_status TEXT")

    conn.commit()
    conn.close()


def add_task(source, task_type, engine="sensevoice", max_timeline_items=15, name=None):
    """
    添加新任务到队列。

    参数:
        source (str): 任务来源（URL 或本地文件路径）
        task_type (str): 任务类型 (local / bilibili / xiaoyuzhou)
        engine (str): 转录引擎 (whisper / sensevoice)
        max_timeline_items (int): 时间轴上限
        name (str, optional): 任务显示名称

    返回:
        str: 任务 ID
    """
    task_id = str(uuid.uuid4())
    create_time = datetime.now().isoformat()

    # 如果没有提供 name，从 source 解析
    if not name:
        if task_type == "local":
            name = os.path.basename(source)
        elif task_type == "bilibili":
            # 尝试获取真实标题
            name = fetch_bilibili_title(source)
            if not name:
                # 如果获取失败，使用 ID
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(source)
                path_parts = parsed.path.strip('/').split('/')
                if path_parts and path_parts[-1].startswith('BV'):
                    name = path_parts[-1]
                else:
                    params = parse_qs(parsed.query)
                    if 'bvid' in params:
                        name = params['bvid'][0]
                    else:
                        bv_match = [p for p in path_parts if p.startswith('BV')]
                        name = bv_match[0] if bv_match else source.split('/')[-1]
        elif task_type == "xiaoyuzhou":
            # 尝试获取真实标题
            name = fetch_xiaoyuzhou_title(source)
            if not name:
                name = source.split('/')[-1]
        else:
            # 从 URL 提取
            name = source.split("/")[-1][:50] if len(source.split("/")[-1]) > 50 else source.split("/")[-1]

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO tasks (id, source, name, type, status, engine, max_timeline_items, create_time)
        VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?)
    """, (task_id, source, name, task_type, engine, max_timeline_items, create_time))

    conn.commit()
    conn.close()

    return task_id


def fetch_bilibili_title(url):
    """获取B站视频标题"""
    try:
        import yt_dlp
        ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': False}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('title', None)
    except Exception as e:
        print(f"[TaskQueue] 获取B站标题失败: {e}")
        return None


def fetch_xiaoyuzhou_title(url):
    """获取小宇宙播客标题"""
    try:
        import requests
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            import re
            title_match = re.search(r'<meta\s+(?:property|name)="og:title"\s+content="([^"]+)"', response.text)
            if title_match:
                return title_match.group(1)
        return None
    except Exception as e:
        print(f"[TaskQueue] 获取小宇宙标题失败: {e}")
        return None


def get_task(task_id):
    """
    获取单个任务信息。

    参数:
        task_id (str): 任务 ID

    返回:
        dict: 任务信息字典
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


def get_all_tasks(status=None, order_by="create_time ASC"):
    """
    获取所有任务。

    参数:
        status (str, optional): 按状态过滤 (PENDING/PROCESSING/COMPLETED/FAILED)
        order_by (str): 排序方式

    返回:
        list: 任务列表
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if status:
        cursor.execute(f"SELECT * FROM tasks WHERE status = ? ORDER BY {order_by}", (status,))
    else:
        cursor.execute(f"SELECT * FROM tasks ORDER BY {order_by}")

    rows = cursor.fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_pending_tasks():
    """
    获取所有等待中的任务（按创建时间排序）。

    返回:
        list: 等待中的任务列表
    """
    return get_all_tasks(status="PENDING", order_by="create_time ASC")


def get_processing_task():
    """
    获取当前正在处理的任务（最多1个）。

    返回:
        dict: 正在处理的任务，如果没有则返回 None
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM tasks WHERE status = 'PROCESSING' LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    if row:
        return dict(row)
    return None


def get_failed_tasks():
    """
    获取所有失败的任务。

    返回:
        list: 失败任务列表
    """
    return get_all_tasks(status="FAILED", order_by="create_time DESC")


def update_task_status(task_id, status, error_msg=None, result_path=None):
    """
    更新任务状态。

    参数:
        task_id (str): 任务 ID
        status (str): 新状态 (PENDING/PROCESSING/COMPLETED/FAILED)
        error_msg (str, optional): 错误信息
        result_path (str, optional): 结果路径
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    complete_time = datetime.now().isoformat() if status in ("COMPLETED", "FAILED") else None

    cursor.execute("""
        UPDATE tasks
        SET status = ?, error_msg = ?, result_path = ?, complete_time = ?
        WHERE id = ?
    """, (status, error_msg, result_path, complete_time, task_id))

    conn.commit()
    conn.close()


def update_task_name(task_id, name):
    """
    更新任务名称。

    参数:
        task_id (str): 任务 ID
        name (str): 新名称
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tasks SET name = ? WHERE id = ?
    """, (name, task_id))

    conn.commit()
    conn.close()


def update_progress_status(task_id, status):
    """
    更新任务进度状态。

    参数:
        task_id (str): 任务 ID
        status (str): 进度状态描述
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tasks SET progress_status = ? WHERE id = ?
    """, (status, task_id))

    conn.commit()
    conn.close()


def mark_processing(task_id):
    """
    将任务标记为处理中。

    参数:
        task_id (str): 任务 ID
    """
    update_task_status(task_id, "PROCESSING")


def mark_completed(task_id, result_path):
    """
    将任务标记为完成。

    参数:
        task_id (str): 任务 ID
        result_path (str): 归档路径
    """
    update_task_status(task_id, "COMPLETED", result_path=result_path)


def mark_failed(task_id, error_msg):
    """
    将任务标记为失败。

    参数:
        task_id (str): 任务 ID
        error_msg (str): 错误信息
    """
    update_task_status(task_id, "FAILED", error_msg=error_msg)


def reset_processing_to_pending():
    """
    重置所有 PROCESSING 状态的任务为 PENDING（用于启动时的灾难恢复）。
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE tasks SET status = 'PENDING' WHERE status = 'PROCESSING'
    """)

    affected = cursor.rowcount
    conn.commit()
    conn.close()

    return affected


def delete_task(task_id):
    """
    删除任务。

    参数:
        task_id (str): 任务 ID
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    conn.commit()
    conn.close()


def clear_completed():
    """
    清除所有已完成的任务。
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM tasks WHERE status = 'COMPLETED'")

    affected = cursor.rowcount
    conn.commit()
    conn.close()

    return affected


def get_queue_stats():
    """
    获取队列统计信息。

    返回:
        dict: 统计数据
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    stats = {}
    for status in ("PENDING", "PROCESSING", "COMPLETED", "FAILED"):
        cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = ?", (status,))
        stats[status] = cursor.fetchone()[0]

    conn.close()

    return stats


# 初始化数据库
init_db()
