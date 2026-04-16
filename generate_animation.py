import streamlit as st
import pandas as pd
import json
import base64
from math import radians, sin, cos, asin, sqrt
from datetime import datetime
import io


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


def simplify_trajectory(coords, tolerance=0.005):
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


# ====================== 周期KPI计算 ======================
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


# ====================== 加载文件 ======================
def load_vehicle_from_uploaded_file(uploaded_file):
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
        simplified_coords, kept_indices = simplify_trajectory(coords)

        df_simp = pd.DataFrame(simplified_coords, columns=['Latitude', 'Longitude'])
        df_simp['DateTime'] = df['DateTime'].iloc[kept_indices].reset_index(drop=True)
        df_simp = compute_trajectory_stats(df_simp)

        vehicle_name = uploaded_file.name.replace('.xlsx', '').replace('.xls', '')
        return vehicle_name, df_simp

    except Exception as e:
        st.toast(f"❌ 解析 {uploaded_file.name} 失败: {e}", icon="❌")
        return None


# ====================== 加载HTML模板 ======================
def load_html_template():
    try:
        with open("animation_template.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        st.error("❌ 未找到 animation_template.html 文件！")
        st.stop()


# ====================== 生成动画HTML ======================
def generate_animation_html(vehicles_data):
    if not vehicles_data:
        return None

    template = load_html_template()

    color_palette = ['#e63939', '#1d3557', '#457b9d', '#2a9d8f', '#e76f51', '#f4a261', '#8338ec']
    for i, name in enumerate(vehicles_data.keys()):
        vehicles_data[name]['color'] = color_palette[i % len(color_palette)]

    vehicles_list = []
    global_min_time = None
    global_max_time = None

    for name, data in vehicles_data.items():
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

with st.sidebar:
    st.header("⚙️ 配置")
    preview_height = st.slider("动画预览高度 (px)", 600, 1200, 950, step=50)

uploaded_files = st.file_uploader("上传 Excel 文件（可多选）", type=["xlsx", "xls"], accept_multiple_files=True)

vehicles = {}

if uploaded_files:
    progress_bar = st.progress(0, text="解析文件中...")
    for i, file in enumerate(uploaded_files):
        result = load_vehicle_from_uploaded_file(file)
        if result:
            name, df_simp = result
            base_name = name
            counter = 1
            while name in vehicles:
                name = f"{base_name}_{counter}"
                counter += 1
            vehicles[name] = {
                'coords': df_simp[['Latitude', 'Longitude']].values.tolist(),
                'cum_km': df_simp['Cum_km'].tolist(),
                'times': df_simp['DateTime'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
                'df': df_simp.copy()
            }
        progress_bar.progress((i + 1) / len(uploaded_files))
    progress_bar.empty()

    if vehicles:
        st.success(f"✅ 成功加载 {len(vehicles)} 辆车")

        # ==================== 使用 Tabs 分离两个页面 ====================
        tab1, tab2 = st.tabs(["📊 周期KPI看板", "🎬 轨迹动画预览"])

        # ==================== Tab 1: KPI看板 ====================
        with tab1:
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

        # ==================== Tab 2: 动画预览 ====================
        with tab2:
            if st.button("🎬 生成并预览动画", type="primary", use_container_width=True):
                with st.spinner("生成动画中..."):
                    html_content = generate_animation_html(vehicles)
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
    st.info("👈 请先在左侧上传 Excel 文件")

st.caption("KPI看板与动画预览已分离成两个独立页面")