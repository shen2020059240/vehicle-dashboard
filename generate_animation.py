import streamlit as st
import pandas as pd
import json
import base64
import hashlib
from math import radians, sin, cos, asin, sqrt
from datetime import datetime
import io

# 导入数据库模块
import db

# 初始化数据库
db.init_db()


# ====================== 工具函数 ======================
def haversine_distance(lat1, lon1, lat2, lon2):
    if any(pd.isna(x) for x in [lat1, lon1, lat2, lon2]):
        return 0.0
    R = 6371.0
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return 2 * R * asin(sqrt(a))


@st.cache_data
def simplify_trajectory(coords, tolerance=0.01):
    if len(coords) < 3:
        return coords, list(range(len(coords)))
    simplified = [coords[0]]
    kept_indices = [0]
    for i in range(1, len(coords) - 1):
        dist = haversine_distance(simplified[-1][0], simplified[-1][1], coords[i][0], coords[i][1])
        if dist > tolerance:
            simplified.append(coords[i])
            kept_indices.append(i)
    simplified.append(coords[-1])
    kept_indices.append(len(coords) - 1)
    return simplified, kept_indices


def parse_datetime_robust(series):
    try:
        return pd.to_datetime(series, format='%d/%m/%Y %I:%M:%S %p', dayfirst=True, errors='coerce')
    except:
        return pd.to_datetime(series, errors='coerce', dayfirst=True)


def compute_trajectory_stats(df):
    df = df.sort_values('DateTime').reset_index(drop=True)
    df['Distance_km'] = 0.0
    for i in range(1, len(df)):
        dist = haversine_distance(df.loc[i - 1, 'Latitude'], df.loc[i - 1, 'Longitude'],
                                  df.loc[i, 'Latitude'], df.loc[i, 'Longitude'])
        df.loc[i, 'Distance_km'] = dist
    df['Cum_km'] = df['Distance_km'].cumsum()
    return df


def compute_cycle_kpi(df):
    if df.empty or len(df) < 2:
        return {"total_km": 0, "days": 0, "avg_daily_km": 0, "idle_hours": 0,
                "idle_ratio": 0, "effective_hours": 0, "effective_ratio": 0, "trip_rate": 0}
    df = df.copy()
    df['Date'] = df['DateTime'].dt.date
    days = df['Date'].nunique()
    total_km = df['Cum_km'].iloc[-1]
    total_hours = (df['DateTime'].iloc[-1] - df['DateTime'].iloc[0]).total_seconds() / 3600
    idle_seconds = 0
    for i in range(1, len(df)):
        if df.loc[i, 'Distance_km'] < 0.1 and df.loc[i - 1, 'Distance_km'] < 0.1:
            delta = (df.loc[i, 'DateTime'] - df.loc[i - 1, 'DateTime']).total_seconds()
            if delta > 300:
                idle_seconds += delta
    idle_hours = idle_seconds / 3600
    effective_hours = total_hours - idle_hours if total_hours > 0 else 0
    return {
        "total_km": round(total_km, 2),
        "days": days,
        "avg_daily_km": round(total_km / days, 2) if days > 0 else 0,
        "idle_hours": round(idle_hours, 2),
        "idle_ratio": round(idle_hours / total_hours * 100, 1) if total_hours > 0 else 0,
        "effective_hours": round(effective_hours, 2),
        "effective_ratio": round(effective_hours / total_hours * 100, 1) if total_hours > 0 else 0,
        "trip_rate": round(days / max((df['Date'].max() - df['Date'].min()).days, 1) * 100, 1)
    }


@st.cache_data
def load_vehicle_from_uploaded_file(uploaded_file, tolerance=0.01):
    try:
        df_sample = pd.read_excel(uploaded_file, nrows=20, header=None)
        header_row = 6
        for i in range(min(15, len(df_sample))):
            row = df_sample.iloc[i].astype(str).str.lower()
            if any('date/time' in str(cell) or ('date' in str(cell) and 'time' in str(cell)) for cell in row):
                header_row = i
                break
        df = pd.read_excel(uploaded_file, header=header_row)
        df.columns = [str(col).strip() for col in df.columns]
        col_map = {}
        for col in df.columns:
            cl = col.lower()
            if 'date' in cl and 'time' in cl:
                col_map['time'] = col
            elif 'latitude' in cl or 'lat' in cl:
                col_map['lat'] = col
            elif 'longitude' in cl or 'lon' in cl or 'lng' in cl:
                col_map['lon'] = col
        if 'time' not in col_map or 'lat' not in col_map or 'lon' not in col_map:
            st.toast(f"⚠️ {uploaded_file.name} 缺少必要列", icon="⚠️")
            return None
        df = df[[col_map['time'], col_map['lat'], col_map['lon']]].rename(columns={
            col_map['time']: 'DateTime',
            col_map['lat']: 'Latitude',
            col_map['lon']: 'Longitude'
        })
        df['DateTime'] = parse_datetime_robust(df['DateTime'])
        df['Latitude'] = pd.to_numeric(df['Latitude'], errors='coerce')
        df['Longitude'] = pd.to_numeric(df['Longitude'], errors='coerce')
        df = df.dropna(subset=['DateTime', 'Latitude', 'Longitude']).reset_index(drop=True)
        if len(df) < 3:
            st.toast(f"⚠️ {uploaded_file.name} 数据点过少", icon="⚠️")
            return None
        coords = df[['Latitude', 'Longitude']].values.tolist()
        simplified_coords, kept_indices = simplify_trajectory(coords, tolerance=tolerance)
        df_simp = pd.DataFrame(simplified_coords, columns=['Latitude', 'Longitude'])
        df_simp['DateTime'] = df['DateTime'].iloc[kept_indices].reset_index(drop=True)
        df_simp = compute_trajectory_stats(df_simp)
        vehicle_name = uploaded_file.name.replace('.xlsx', '').replace('.xls', '')
        return vehicle_name, df_simp
    except Exception as e:
        st.toast(f"❌ 解析 {uploaded_file.name} 失败: {e}", icon="❌")
        return None


def load_html_template():
    try:
        with open("animation_template.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        st.error("❌ 未找到 animation_template.html 文件！")
        st.stop()


@st.cache_data
def generate_animation_html(vehicles_data_slim):
    if not vehicles_data_slim:
        return None
    template = load_html_template()
    color_palette = ['#e63939', '#1d3557', '#457b9d', '#2a9d8f', '#e76f51', '#f4a261', '#8338ec']
    for i, name in enumerate(vehicles_data_slim.keys()):
        vehicles_data_slim[name]['color'] = color_palette[i % len(color_palette)]
    vehicles_list = []
    global_min_time = None
    global_max_time = None
    for name, data in vehicles_data_slim.items():
        cum = data['cum_km']
        segment_dists = [cum[i + 1] - cum[i] for i in range(len(cum) - 1)]
        total_dist = cum[-1] if cum else 0
        timestamps = []
        for ts in data['times']:
            try:
                dt = pd.to_datetime(ts)
                timestamps.append(dt.timestamp() * 1000)
            except:
                timestamps.append(0)
        valid_ts = [t for t in timestamps if t > 0]
        if valid_ts:
            v_min = min(valid_ts)
            v_max = max(valid_ts)
            if global_min_time is None or v_min < global_min_time:
                global_min_time = v_min
            if global_max_time is None or v_max > global_max_time:
                global_max_time = v_max
        vehicles_list.append({
            'name': name,
            'coords': data['coords'],
            'times': data['times'],
            'timestamps': timestamps,
            'color': data['color'],
            'segmentDistances': segment_dists,
            'totalDistance': total_dist,
            'cumKm': cum
        })
    use_time_mode = (global_min_time is not None and global_max_time is not None and global_min_time < global_max_time)
    if not use_time_mode:
        global_min_time = global_max_time = 0
    follow_options = '<option value="">无</option>' + ''.join(
        f'<option value="{v["name"]}">{v["name"]}</option>' for v in vehicles_list)
    html_content = template.replace('{VEHICLES_JSON}', json.dumps(vehicles_list)) \
        .replace('{FOLLOW_OPTIONS}', follow_options) \
        .replace('{USE_TIME_MODE}', 'selected' if use_time_mode else '') \
        .replace('{GLOBAL_MIN_TIME}', str(global_min_time)) \
        .replace('{GLOBAL_MAX_TIME}', str(global_max_time))
    return html_content


# ====================== Streamlit 主界面 ======================
st.set_page_config(page_title="车辆轨迹动画生成器", layout="wide")
st.title("🚚 多车辆轨迹动画生成器 - 周期看板版")

# 初始化 session_state
if 'current_vehicles' not in st.session_state:
    st.session_state['current_vehicles'] = {}
if 'current_vehicles_slim' not in st.session_state:
    st.session_state['current_vehicles_slim'] = {}
if 'current_batch_id' not in st.session_state:
    st.session_state['current_batch_id'] = None

# 侧边栏配置
with st.sidebar:
    st.header("⚙️ 配置")
    preview_height = st.slider("动画预览高度 (px)", 600, 1200, 950, step=50)
    simplify_tolerance = st.slider(
        "轨迹抽稀程度 (km)",
        min_value=0.001, max_value=0.1, value=0.01, step=0.001,
        help="值越大，轨迹点越少，动画越流畅。推荐 0.01~0.05"
    )
    st.markdown("---")
    st.subheader("📁 上传新批次")
    uploaded_files = st.file_uploader(
        "上传 Excel 文件（可多选）",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        key="batch_upload"
    )
    batch_name_input = st.text_input(
        "批次名称",
        value=f"{datetime.now().strftime('%Y年%m月')} 数据",
        help="为本次上传的数据起个名字，例如「2026年3月运营数据」"
    )
    if uploaded_files and st.button("保存为新批次", type="primary", use_container_width=True):
        with st.spinner("解析并保存中..."):
            vehicles_temp = {}
            for file in uploaded_files:
                result = load_vehicle_from_uploaded_file(file, tolerance=simplify_tolerance)
                if result:
                    name, df_simp = result
                    base_name = name
                    counter = 1
                    while name in vehicles_temp:
                        name = f"{base_name}_{counter}"
                        counter += 1
                    vehicles_temp[name] = {
                        'coords': df_simp[['Latitude', 'Longitude']].values.tolist(),
                        'cum_km': df_simp['Cum_km'].tolist(),
                        'times': df_simp['DateTime'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
                        'df': df_simp.copy()
                    }
            if vehicles_temp:
                batch_id = db.save_vehicle_batch(vehicles_temp, batch_name=batch_name_input)
                st.success(f"✅ 成功保存 {len(vehicles_temp)} 辆车，批次「{batch_name_input}」已入库")
                # 自动加载刚保存的批次
                st.session_state['current_vehicles'] = vehicles_temp
                st.session_state['current_vehicles_slim'] = {name: {k: v[k] for k in ['coords', 'cum_km', 'times']}
                                                             for name, v in vehicles_temp.items()}
                st.session_state['current_batch_id'] = batch_id
                st.rerun()
            else:
                st.error("没有成功解析任何文件")

# ====================== 主界面 Tabs ======================
tab1, tab2, tab3 = st.tabs(["📊 周期KPI看板", "🎬 轨迹动画预览", "🗄️ 批次管理"])

# ---------- Tab 1: KPI 看板 ----------
with tab1:
    vehicles = st.session_state['current_vehicles']
    if vehicles:
        st.subheader("📅 周期筛选")
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("起始日期", value=pd.Timestamp.now() - pd.Timedelta(days=7))
        with col2:
            end_date = st.date_input("结束日期", value=pd.Timestamp.now())
        st.subheader("📊 周期运营核心KPI")
        kpi_rows = []
        for name, v in vehicles.items():
            df_filtered = v['df'][(v['df']['DateTime'].dt.date >= start_date) &
                                  (v['df']['DateTime'].dt.date <= end_date)]
            kpi = compute_cycle_kpi(df_filtered)
            kpi_rows.append({
                "车辆": name,
                "总里程(km)": kpi["total_km"],
                "日均里程(km)": kpi["avg_daily_km"],
                "出车率(%)": kpi["trip_rate"],
                "怠速时长(h)": kpi["idle_hours"],
                "怠速占比(%)": kpi["idle_ratio"],
                "有效行驶占比(%)": kpi["effective_ratio"]
            })
        st.dataframe(pd.DataFrame(kpi_rows), use_container_width=True, hide_index=True)
        if st.button("📥 导出周期运营报表（Excel）", type="primary", use_container_width=True):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                pd.DataFrame(kpi_rows).to_excel(writer, sheet_name="核心KPI", index=False)
                for name, v in vehicles.items():
                    v['df'].to_excel(writer, sheet_name=name[:30], index=False)
            output.seek(0)
            st.download_button(
                label="下载完整报表",
                data=output,
                file_name=f"卡车运营报表_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
    else:
        st.info("暂无车辆数据，请先在左侧上传新批次或在「批次管理」中加载已有批次")

# ---------- Tab 2: 动画预览 ----------
with tab2:
    vehicles_slim = st.session_state['current_vehicles_slim']
    if vehicles_slim:
        # 生成缓存签名
        data_signature = hashlib.md5(
            json.dumps({name: {'coords_len': len(v['coords']), 'cum_km_last': v['cum_km'][-1]}
                        for name, v in vehicles_slim.items()}, sort_keys=True).encode()
        ).hexdigest()
        if 'cached_html' not in st.session_state or st.session_state.get('html_signature') != data_signature:
            with st.spinner("生成动画中...（首次加载较慢，后续秒开）"):
                html_content = generate_animation_html(vehicles_slim)
                if html_content:
                    st.session_state['cached_html'] = html_content
                    st.session_state['html_signature'] = data_signature
        else:
            html_content = st.session_state['cached_html']

        if st.button("🎬 生成并预览动画", type="primary", use_container_width=True):
            if html_content:
                b64 = base64.b64encode(html_content.encode('utf-8')).decode()
                st.markdown(
                    f'<a href="data:text/html;base64,{b64}" download="车辆轨迹动画_可点击缩放.html" style="font-size:18px;">📥 下载 HTML 文件</a>',
                    unsafe_allow_html=True)
                st.subheader("🎥 实时预览")
                st.components.v1.html(html_content, height=preview_height, scrolling=True)
            else:
                st.error("动画生成失败")
    else:
        st.info("暂无车辆数据，请先加载批次")

# ---------- Tab 3: 批次管理 ----------
with tab3:
    st.subheader("🗄️ 批次管理")
    batches = db.get_all_batches()
    if batches:
        for batch_id, batch_name, upload_time, vehicle_count in batches:
            col1, col2, col3, col4, col5 = st.columns([2, 3, 2, 1, 1])
            with col1:
                st.write(f"**{batch_name}**")
            with col2:
                st.write(f"`{batch_id}`")
            with col3:
                st.write(f"{upload_time}  ({vehicle_count} 辆车)")
            with col4:
                if st.button("📂 加载", key=f"load_{batch_id}"):
                    vehicles_slim = db.load_batch_by_id(batch_id)
                    if vehicles_slim:
                        # 重建 full 数据用于 KPI
                        vehicles_full = {}
                        for name, data in vehicles_slim.items():
                            df_rebuilt = pd.DataFrame({
                                'Latitude': [c[0] for c in data['coords']],
                                'Longitude': [c[1] for c in data['coords']],
                                'DateTime': pd.to_datetime(data['times'])
                            })
                            df_rebuilt = compute_trajectory_stats(df_rebuilt)
                            vehicles_full[name] = {
                                'coords': data['coords'],
                                'cum_km': data['cum_km'],
                                'times': data['times'],
                                'df': df_rebuilt
                            }
                        st.session_state['current_vehicles'] = vehicles_full
                        st.session_state['current_vehicles_slim'] = vehicles_slim
                        st.session_state['current_batch_id'] = batch_id
                        st.success(f"已加载批次「{batch_name}」")
                        st.rerun()
            with col5:
                if st.button("🗑️ 删除", key=f"del_{batch_id}"):
                    db.delete_batch(batch_id)
                    st.success(f"批次「{batch_name}」已删除")
                    if st.session_state.get('current_batch_id') == batch_id:
                        # 清空当前显示的数据
                        st.session_state['current_vehicles'] = {}
                        st.session_state['current_vehicles_slim'] = {}
                        st.session_state['current_batch_id'] = None
                        for key in ['cached_html', 'html_signature']:
                            if key in st.session_state:
                                del st.session_state[key]
                    st.rerun()
    else:
        st.info("暂无历史批次，请先在左侧上传新批次")

    if st.button("🔄 刷新批次列表"):
        st.rerun()

st.caption("KPI看板、动画预览与批次管理已整合 | 数据持久化使用 SQLite")