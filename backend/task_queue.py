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
# 优先使用 PODGIST_DATA_DIR（Electron 打包环境），否则回退到项目根目录
_USER_DATA_DIR = os.environ.get('PODGIST_DATA_DIR')
if _USER_DATA_DIR:
    DB_DIR = os.path.join(_USER_DATA_DIR, "temp_audio")
else:
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

    # 时间轴富化任务与主任务分离：外部资料、实体图片失败或变慢时，
    # 不应阻塞用户拿到已经生成的核心时间轴。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timeline_enrichment_jobs (
            archive_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            error_msg TEXT,
            create_time TEXT NOT NULL,
            update_time TEXT NOT NULL
        )
    """)

    # 节点级队列支持流媒体式优先级：当前播放/跳转节点优先，其余内容后台补齐。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timeline_node_enrichment_jobs (
            archive_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            priority INTEGER NOT NULL DEFAULT 1000,
            attempts INTEGER NOT NULL DEFAULT 0,
            error_msg TEXT,
            create_time TEXT NOT NULL,
            update_time TEXT NOT NULL,
            PRIMARY KEY (archive_id, node_id)
        )
    """)

    # 实体资料跨归档缓存。这里只缓存远程链接，不缓存本地文件名：
    # 本地图片属于各自归档，不能跨归档复用路径。
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS entity_enrichment_cache (
            entity_key TEXT PRIMARY KEY,
            ref_url TEXT,
            ref_title TEXT,
            source_tier TEXT,
            remote_image_url TEXT,
            image_source_url TEXT,
            image_source_region TEXT,
            updated_at TEXT NOT NULL
        )
    """)

    # 给既有缓存补充图片来源元数据；不删除或重写任何用户已有任务数据。
    cache_columns = {row[1] for row in cursor.execute("PRAGMA table_info(entity_enrichment_cache)")}
    if "image_source_url" not in cache_columns:
        cursor.execute("ALTER TABLE entity_enrichment_cache ADD COLUMN image_source_url TEXT")
    if "image_source_region" not in cache_columns:
        cursor.execute("ALTER TABLE entity_enrichment_cache ADD COLUMN image_source_region TEXT")

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

    # 检查 mode 字段是否存在
    try:
        cursor.execute("SELECT mode FROM tasks LIMIT 1")
    except:
        cursor.execute("ALTER TABLE tasks ADD COLUMN mode TEXT DEFAULT 'summary'")

    conn.commit()
    conn.close()


def add_task(source, task_type, engine="sensevoice", max_timeline_items=15, name=None, mode="summary"):
    """
    添加新任务到队列。

    参数:
        source (str): 任务来源（URL 或本地文件路径）
        task_type (str): 任务类型 (local / bilibili / xiaoyuzhou)
        engine (str): 转录引擎 (whisper / sensevoice)
        max_timeline_items (int): 时间轴上限
        name (str, optional): 任务显示名称
        mode (str, optional): 导入模式 ('summary' 或 'timeline')

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
        INSERT INTO tasks (id, source, name, type, status, engine, max_timeline_items, create_time, mode)
        VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?, ?)
    """, (task_id, source, name, task_type, engine, max_timeline_items, create_time, mode))

    conn.commit()
    conn.close()

    return task_id


def fetch_bilibili_title(url):
    """获取B站视频标题"""
    try:
        from backend.downloader import get_bilibili_video_info
        info = get_bilibili_video_info(url)
        return info.get('title') if info.get('success') else None
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


def create_enrichment_job(archive_id):
    """创建或重新排队一个归档的非阻塞实体富化任务。"""
    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO timeline_enrichment_jobs
            (archive_id, status, attempts, error_msg, create_time, update_time)
        VALUES (?, 'PENDING', 0, NULL, ?, ?)
        ON CONFLICT(archive_id) DO UPDATE SET
            status = 'PENDING', error_msg = NULL, update_time = excluded.update_time
    """, (archive_id, now, now))
    conn.commit()
    conn.close()


def claim_next_enrichment_job():
    """原子地领取一个待处理富化任务；当前仅由单个富化线程调用。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM timeline_enrichment_jobs WHERE status = 'PENDING' ORDER BY create_time ASC LIMIT 1")
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    now = datetime.now().isoformat()
    cursor.execute("""
        UPDATE timeline_enrichment_jobs
        SET status = 'PROCESSING', attempts = attempts + 1, update_time = ?
        WHERE archive_id = ?
    """, (now, row['archive_id']))
    conn.commit()
    job = dict(row)
    job['status'] = 'PROCESSING'
    job['attempts'] = (job.get('attempts') or 0) + 1
    conn.close()
    return job


def get_enrichment_job(archive_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM timeline_enrichment_jobs WHERE archive_id = ?", (archive_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def complete_enrichment_job(archive_id):
    _update_enrichment_job(archive_id, 'COMPLETED')


def fail_enrichment_job(archive_id, error_msg):
    _update_enrichment_job(archive_id, 'FAILED', error_msg)


def _update_enrichment_job(archive_id, status, error_msg=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE timeline_enrichment_jobs
        SET status = ?, error_msg = ?, update_time = ?
        WHERE archive_id = ?
    """, (status, error_msg, datetime.now().isoformat(), archive_id))
    conn.commit()
    conn.close()


def reset_processing_enrichment_jobs():
    """应用中断后，让未完成的富化任务能在下次启动时恢复。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE timeline_enrichment_jobs SET status = 'PENDING' WHERE status = 'PROCESSING'")
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected


def get_entity_enrichment_cache(entity_key):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM entity_enrichment_cache WHERE entity_key = ?", (entity_key,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_entity_enrichment_cache(
    entity_key,
    ref_url,
    ref_title,
    source_tier,
    remote_image_url,
    image_source_url="",
    image_source_region="",
):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO entity_enrichment_cache
            (entity_key, ref_url, ref_title, source_tier, remote_image_url, image_source_url, image_source_region, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_key) DO UPDATE SET
            ref_url = excluded.ref_url,
            ref_title = excluded.ref_title,
            source_tier = excluded.source_tier,
            remote_image_url = excluded.remote_image_url,
            image_source_url = excluded.image_source_url,
            image_source_region = excluded.image_source_region,
            updated_at = excluded.updated_at
    """, (
        entity_key, ref_url, ref_title, source_tier, remote_image_url,
        image_source_url, image_source_region, datetime.now().isoformat(),
    ))
    conn.commit()
    conn.close()


def create_node_enrichment_jobs(archive_id, node_ids):
    """为新时间轴创建节点级富化任务，首节点及其后两项优先。"""
    now = datetime.now().isoformat()
    rows = []
    for index, node_id in enumerate(node_ids):
        priority = 10 + index if index < 3 else 1000 + index
        rows.append((archive_id, node_id, priority, now, now))
    if not rows:
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT INTO timeline_node_enrichment_jobs
            (archive_id, node_id, status, priority, attempts, error_msg, create_time, update_time)
        VALUES (?, ?, 'PENDING', ?, 0, NULL, ?, ?)
        ON CONFLICT(archive_id, node_id) DO NOTHING
    """, rows)
    conn.commit()
    conn.close()


def prioritize_node_enrichment(archive_id, node_ids):
    """提升当前节点及其相邻节点；已完成节点无需重复请求。"""
    if not node_ids:
        return
    now = datetime.now().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    for offset, node_id in enumerate(node_ids):
        # 第一个元素是当前节点；其余是相邻预加载节点。
        priority = offset
        cursor.execute("""
            UPDATE timeline_node_enrichment_jobs
            SET priority = ?, status = 'PENDING', error_msg = NULL, update_time = ?
            WHERE archive_id = ? AND node_id = ? AND status IN ('PENDING', 'FAILED')
        """, (priority, now, archive_id, node_id))
    conn.commit()
    conn.close()


def claim_next_node_enrichment_job():
    """领取当前优先级最高的节点富化任务。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM timeline_node_enrichment_jobs
        WHERE status = 'PENDING'
        ORDER BY priority ASC, create_time ASC
        LIMIT 1
    """)
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    now = datetime.now().isoformat()
    cursor.execute("""
        UPDATE timeline_node_enrichment_jobs
        SET status = 'PROCESSING', attempts = attempts + 1, update_time = ?
        WHERE archive_id = ? AND node_id = ?
    """, (now, row['archive_id'], row['node_id']))
    conn.commit()
    job = dict(row)
    job['status'] = 'PROCESSING'
    job['attempts'] = (job.get('attempts') or 0) + 1
    conn.close()
    return job


def complete_node_enrichment_job(archive_id, node_id):
    _update_node_enrichment_job(archive_id, node_id, 'COMPLETED')


def fail_node_enrichment_job(archive_id, node_id, error_msg):
    _update_node_enrichment_job(archive_id, node_id, 'FAILED', error_msg)


def _update_node_enrichment_job(archive_id, node_id, status, error_msg=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE timeline_node_enrichment_jobs
        SET status = ?, error_msg = ?, update_time = ?
        WHERE archive_id = ? AND node_id = ?
    """, (status, error_msg, datetime.now().isoformat(), archive_id, node_id))
    conn.commit()
    conn.close()


def reset_processing_node_enrichment_jobs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE timeline_node_enrichment_jobs SET status = 'PENDING' WHERE status = 'PROCESSING'")
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected


def get_archive_enrichment_status(archive_id):
    """返回节点级汇总状态，兼容旧版整期富化任务。"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT status, COUNT(*) AS count
        FROM timeline_node_enrichment_jobs
        WHERE archive_id = ?
        GROUP BY status
    """, (archive_id,))
    counts = {row['status']: row['count'] for row in cursor.fetchall()}
    conn.close()
    if counts:
        if counts.get('PROCESSING') or counts.get('PENDING'):
            return 'PROCESSING'
        if counts.get('FAILED') and not counts.get('COMPLETED'):
            return 'FAILED'
        return 'COMPLETED'
    legacy = get_enrichment_job(archive_id)
    return legacy.get('status') if legacy else None


# 初始化数据库
init_db()
