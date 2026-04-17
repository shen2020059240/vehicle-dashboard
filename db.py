"""
db.py - SQLite 数据库管理（支持批次自定义命名）
"""

import sqlite3
import json
from datetime import datetime

DB_PATH = "vehicle_data.db"

def init_db():
    """初始化数据库表，如果不存在则创建，并执行迁移"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS vehicle_trajectories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_name TEXT,
            upload_date TEXT,
            coords_json TEXT,
            cum_km_json TEXT,
            times_json TEXT,
            total_km REAL,
            point_count INTEGER,
            batch_id TEXT,
            batch_name TEXT
        )
    ''')
    conn.commit()
    conn.close()
    # 迁移旧数据：如果 batch_name 列不存在则添加，并将已有记录的 batch_name 设为 batch_id
    migrate_add_batch_name()

def migrate_add_batch_name():
    """为旧表增加 batch_name 列（如果不存在），并填充默认值"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE vehicle_trajectories ADD COLUMN batch_name TEXT")
        # 将已有记录的 batch_name 设置为 batch_id
        c.execute("UPDATE vehicle_trajectories SET batch_name = batch_id WHERE batch_name IS NULL")
        conn.commit()
    except sqlite3.OperationalError:
        # 列已存在，忽略
        pass
    finally:
        conn.close()

def save_vehicle_batch(vehicles_dict, batch_name=None, batch_id=None):
    """
    保存一个批次的所有车辆轨迹数据
    :param vehicles_dict: 字典，格式 {vehicle_name: {'coords':..., 'cum_km':..., 'times':...}}
    :param batch_name: 自定义批次名称（如 "2026年3月数据"），若为 None 则使用 batch_id
    :param batch_id: 批次唯一标识，若为 None 则自动生成时间戳
    :return: batch_id
    """
    if batch_id is None:
        batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    if batch_name is None:
        batch_name = batch_id

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for name, data in vehicles_dict.items():
        # 注意：vehicles_dict 中可能包含 'df' 字段，我们只存储必要字段
        c.execute('''
            INSERT INTO vehicle_trajectories 
            (vehicle_name, upload_date, coords_json, cum_km_json, times_json, total_km, point_count, batch_id, batch_name)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            name,
            datetime.now().isoformat(),
            json.dumps(data['coords']),
            json.dumps(data['cum_km']),
            json.dumps(data['times']),
            data['cum_km'][-1] if data['cum_km'] else 0,
            len(data['coords']),
            batch_id,
            batch_name
        ))
    conn.commit()
    conn.close()
    return batch_id

def load_batch_by_id(batch_id):
    """
    根据 batch_id 加载一个批次的所有车辆数据（只包含轨迹信息，不含 df）
    :return: 字典 {vehicle_name: {'coords':..., 'cum_km':..., 'times':...}}
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT vehicle_name, coords_json, cum_km_json, times_json FROM vehicle_trajectories
        WHERE batch_id = ?
    ''', (batch_id,))
    rows = c.fetchall()
    conn.close()
    vehicles = {}
    for name, coords_json, cum_km_json, times_json in rows:
        vehicles[name] = {
            'coords': json.loads(coords_json),
            'cum_km': json.loads(cum_km_json),
            'times': json.loads(times_json),
        }
    return vehicles

def get_all_batches():
    """
    获取所有批次的信息
    :return: 列表，每个元素为 (batch_id, batch_name, 最早上传时间, 车辆数)
             按上传时间降序排列
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT batch_id, batch_name, MIN(upload_date) as first_upload, COUNT(*) as vehicle_count
        FROM vehicle_trajectories
        GROUP BY batch_id, batch_name
        ORDER BY first_upload DESC
    ''')
    batches = c.fetchall()
    conn.close()
    # 格式化时间字符串（去掉毫秒和时区信息）
    formatted = []
    for b in batches:
        batch_id, batch_name, upload_time, cnt = b
        # upload_time 格式类似 "2025-04-17T12:34:56.123456"，截取到秒
        if upload_time:
            upload_time = upload_time.split('.')[0].replace('T', ' ')
        formatted.append((batch_id, batch_name, upload_time, cnt))
    return formatted

def delete_batch(batch_id):
    """删除指定批次的所有记录"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM vehicle_trajectories WHERE batch_id = ?', (batch_id,))
    conn.commit()
    conn.close()

def get_latest_batch():
    """获取最新批次的 ID 和名称（按上传时间）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT batch_id, batch_name, MAX(upload_date)
        FROM vehicle_trajectories
        GROUP BY batch_id, batch_name
        ORDER BY MAX(upload_date) DESC
        LIMIT 1
    ''')
    row = c.fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return None, None