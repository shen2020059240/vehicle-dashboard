"""
db.py - SQLite 数据库管理（批次存储）
"""

import sqlite3
import json
import pandas as pd
from datetime import datetime
import streamlit as st

DB_PATH = "vehicle_data.db"


def init_db():
    """初始化数据库表"""
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
            batch_id TEXT
        )
    ''')
    conn.commit()
    conn.close()


def save_vehicle_batch(vehicles_dict, batch_id=None):
    """将 vehicles 字典（与内存结构一致）存入数据库"""
    if batch_id is None:
        batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for name, data in vehicles_dict.items():
        # 注意：vehicles_dict 中可能包含 'df' 字段，但我们只存必要字段
        c.execute('''
            INSERT INTO vehicle_trajectories 
            (vehicle_name, upload_date, coords_json, cum_km_json, times_json, total_km, point_count, batch_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            name,
            datetime.now().isoformat(),
            json.dumps(data['coords']),
            json.dumps(data['cum_km']),
            json.dumps(data['times']),
            data['cum_km'][-1] if data['cum_km'] else 0,
            len(data['coords']),
            batch_id
        ))
    conn.commit()
    conn.close()
    return batch_id


def load_latest_batch():
    """加载最新一批数据，返回 vehicles 字典（不含 df，需后续补充 df）"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT batch_id, MAX(upload_date) FROM vehicle_trajectories
    ''')
    row = c.fetchone()
    if not row or not row[0]:
        conn.close()
        return {}, None
    latest_batch_id = row[0]

    c.execute('''
        SELECT vehicle_name, coords_json, cum_km_json, times_json FROM vehicle_trajectories
        WHERE batch_id = ?
    ''', (latest_batch_id,))
    rows = c.fetchall()
    conn.close()

    vehicles = {}
    for name, coords_json, cum_km_json, times_json in rows:
        vehicles[name] = {
            'coords': json.loads(coords_json),
            'cum_km': json.loads(cum_km_json),
            'times': json.loads(times_json),
            # 注意：这里没有 df，后面需要从 coords 和 times 重建
        }
    return vehicles, latest_batch_id


def load_batch_by_id(batch_id):
    """根据 batch_id 加载指定批次"""
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
    """返回所有批次ID及上传时间、车辆数"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT batch_id, MIN(upload_date) as first_upload, COUNT(*) as vehicle_count
        FROM vehicle_trajectories
        GROUP BY batch_id
        ORDER BY first_upload DESC
    ''')
    batches = c.fetchall()
    conn.close()
    return batches


def delete_batch(batch_id):
    """删除指定批次的所有记录"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM vehicle_trajectories WHERE batch_id = ?', (batch_id,))
    conn.commit()
    conn.close()