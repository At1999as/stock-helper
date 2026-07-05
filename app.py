# app.py - 增强版（含缓存、备用接口、UI优化及错误处理）
import streamlit as st
import datetime
import pandas as pd
import matplotlib.pyplot as plt
import requests
import json
import re
import time
import math
import akshare as ak
from io import StringIO
from streamlit_echarts import st_echarts

# ---------- 页面配置 ----------
st.set_page_config(page_title="A股智能分析", layout="wide", initial_sidebar_state="expanded")

# ---------- 1. 原始数据获取函数（多源切换，增加缓存） ----------
def format_stock_code(code):
    code = code.strip()
    if len(code) != 6:
        return None
    if code.startswith('6'):
        return 'sh' + code
    elif code.startswith('0') or code.startswith('3'):
        return 'sz' + code
    else:
        # 可扩展北交所等
        return None

def fetch_from_baostock(symbol, start_date, end_date):
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code != '0':
            return None, f"baostock 登录失败：{lg.error_msg}"
        sd = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        ed = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
        bs_code = symbol[:2] + '.' + symbol[2:]
        fields = [
            "date", "code", "open", "high", "low", "close", "preclose",
            "volume", "amount", "adjustflag", "turn", "tradestatus",
            "pctChg", "isST", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM"
        ]
        fields_str = ",".join(fields)
        rs = bs.query_history_k_data_plus(
            bs_code,
            fields=fields_str,
            start_date=sd,
            end_date=ed,
            frequency="d",
            adjustflag="2"
        )
        if rs.error_code != '0':
            bs.logout()
            return None, f"baostock 查询失败：{rs.error_msg}"
        data_list = []
        while (rs.error_code == '0') and rs.next():
            data_list.append(rs.get_row_data())
        bs.logout()
        if not data_list:
            return None, "baostock 返回空数据。"
        col_map = {
            "date": "日期", "code": "代码", "open": "开盘", "high": "最高",
            "low": "最低", "close": "收盘", "preclose": "昨收", "volume": "成交量",
            "amount": "成交额", "adjustflag": "复权状态", "turn": "换手率",
            "tradestatus": "交易状态", "pctChg": "涨跌幅", "isST": "是否ST",
            "peTTM": "市盈率", "pbMRQ": "市净率", "psTTM": "市销率",
            "pcfNcfTTM": "市现率"
        }
        columns = [col_map.get(f, f) for f in fields]
        df = pd.DataFrame(data_list, columns=columns)
        numeric_cols = ['开盘', '最高', '最低', '收盘', '昨收', '成交量', '成交额',
                        '换手率', '涨跌幅', '市盈率', '市净率', '市销率', '市现率']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=['收盘'], inplace=True)
        if df.empty:
            return None, "baostock 数据全部为 NaN。"
        return df, f"baostock 获取成功，共 {len(df)} 条记录，包含 {len(df.columns)} 个字段。"
    except Exception as e:
        return None, f"baostock 异常：{e}"

def fetch_from_ths(symbol, start_date, end_date):
    code = symbol[2:]
    url = f"https://d.10jqka.com.cn/v2/line/hs_{code}/01/last.js"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.10jqka.com.cn/"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = 'gbk'
        text = resp.text
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            return None, "同花顺：未找到有效的 JSON 数据。"
        json_str = match.group()
        data = json.loads(json_str)
        raw_csv = data.get("data", "")
        if not raw_csv:
            return None, "同花顺：返回数据中没有 data 字段。"
        df = pd.read_csv(
            StringIO(raw_csv), header=None,
            names=['日期', '开盘', '最高', '最低', '收盘', '成交量', '成交额',
                   '未知1', '未知2', '未知3', '未知4', '未知5']
        )
        df = df[['日期', '开盘', '最高', '最低', '收盘', '成交量']]
        for col in ['开盘', '最高', '最低', '收盘', '成交量']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.dropna(subset=['收盘'], inplace=True)
        df['日期'] = df['日期'].astype(str).str.strip()
        if start_date:
            df = df[df['日期'] >= start_date]
        if end_date:
            df = df[df['日期'] <= end_date]
        if df.empty:
            return None, "同花顺：指定日期范围内没有数据。"
        df.reset_index(drop=True, inplace=True)
        return df, f"同花顺接口获取成功，共 {len(df)} 条记录。"
    except Exception as e:
        return None, f"同花顺获取失败：{e}"

def fetch_from_eastmoney(symbol, start_date, end_date):
    for attempt in range(1, 4):
        try:
            df = ak.stock_zh_a_hist(symbol=symbol[2:], period="daily",
                                    start_date=start_date, end_date=end_date, adjust="qfq")
            if df.empty:
                return None, "东方财富返回空数据。"
            df = df[['日期', '开盘', '最高', '最低', '收盘', '成交量']]
            return df, f"东方财富接口获取成功，共 {len(df)} 条记录。"
        except Exception as e:
            if attempt < 3:
                time.sleep(2)   # 重试等待，Streamlit中会阻塞但可接受
            else:
                return None, f"东方财富失败：{e}"
    return None, "东方财富多次尝试失败。"

def fetch_from_sina(symbol, start_date, end_date):
    try:
        # 注意：ak.stock_zh_a_daily 在新版中可能已变动，这里保留原逻辑
        df_sina = ak.stock_zh_a_daily(symbol=symbol[2:], adjust="qfq",
                                      start_date=start_date, end_date=end_date)
        if df_sina.empty:
            return None, "新浪接口未获取到数据。"
        rename_dict = {
            'date': '日期', 'open': '开盘', 'high': '最高',
            'low': '最低', 'close': '收盘', 'volume': '成交量'
        }
        df_sina.rename(columns=rename_dict, inplace=True)
        df_sina = df_sina[['日期', '开盘', '最高', '最低', '收盘', '成交量']]
        return df_sina, f"新浪接口获取成功，共 {len(df_sina)} 条记录。"
    except Exception as e:
        return None, f"新浪接口失败：{e}"

# ---------- 带缓存的历史数据获取 ----------
@st.cache_data(ttl=600, show_spinner=False)
def fetch_cached_stock_data(symbol, start_date, end_date):
    """缓存历史行情数据，有效期10分钟"""
    df, msg = fetch_from_baostock(symbol, start_date, end_date)
    if df is not None:
        return df, msg
    df, msg = fetch_from_ths(symbol, start_date, end_date)
    if df is not None:
        return df, msg
    df, msg = fetch_from_eastmoney(symbol, start_date, end_date)
    if df is not None:
        return df, msg
    df, msg = fetch_from_sina(symbol, start_date, end_date)
    if df is not None:
        return df, msg
    return None, "所有接口均无法获取数据。"

# ---------- 2. 实时估值与资金流向（带缓存，多备用接口） ----------
@st.cache_data(ttl=60, show_spinner=False)
def get_realtime_valuation(symbol):
    code = symbol[2:]
    data = {}
    # 获取实时行情（缓存全市场快照，减少请求）
    try:
        spot = ak.stock_zh_a_spot()
        row = spot[spot['代码'] == code]
        if not row.empty:
            data['pe'] = row['市盈率-动态'].iloc[0]
            data['pb'] = row['市净率'].iloc[0]
            data['total_mv'] = row['总市值'].iloc[0] / 1e8
            data['turnover'] = row['换手率'].iloc[0]
    except Exception as e:
        st.warning(f"获取估值失败：{e}")

    # 资金流向：尝试多个接口
    fund_df = None
    # 尝试标准接口
    try:
        fund_df = ak.stock_fund_flow_individual(symbol=code)
    except Exception:
        pass
    # 若失败，尝试备用接口（不同akshare版本可能不同）
    if fund_df is None or fund_df.empty:
        try:
            # 有些版本使用 stock_fund_flow_individual_em
            fund_df = ak.stock_fund_flow_individual_em(symbol=code)
        except Exception:
            pass
    if fund_df is None or fund_df.empty:
        try:
            # 另一个备选
            fund_df = ak.stock_fund_flow_individual_latest(symbol=code)
        except Exception:
            pass

    if fund_df is not None and not fund_df.empty:
        latest = fund_df.iloc[-1]
        # 根据列名灵活获取，防止变动
        main_col = '主力净流入-净额' if '主力净流入-净额' in latest.index else '主力净流入'
        super_col = '超大单净流入-净额' if '超大单净流入-净额' in latest.index else '超大单净流入'
        big_col = '大单净流入-净额' if '大单净流入-净额' in latest.index else '大单净流入'
        mid_col = '中单净流入-净额' if '中单净流入-净额' in latest.index else '中单净流入'
        small_col = '小单净流入-净额' if '小单净流入-净额' in latest.index else '小单净流入'
        data['main_net'] = latest.get(main_col, 0) / 10000
        data['super_net'] = latest.get(super_col, 0) / 10000
        data['big_net'] = latest.get(big_col, 0) / 10000
        data['mid_net'] = latest.get(mid_col, 0) / 10000
        data['small_net'] = latest.get(small_col, 0) / 10000
    else:
        # 若所有接口均失败，保留空字典
        pass

    return data

# ---------- 3. ECharts 绘图函数（增强空值处理） ----------
def clean_value(v):
    """将 None 或 NaN 转换为 0，并保留空值标记"""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return 0
    return v

def plot_fund_flow_echarts(main, super_flow, big, mid, small):
    main = clean_value(main)
    super_flow = clean_value(super_flow)
    big = clean_value(big)
    mid = clean_value(mid)
    small = clean_value(small)

    # 判断是否全部为0（可能无数据）
    if all(v == 0 for v in [main, super_flow, big, mid, small]):
        st.info("当日资金流向数据均为0，可能由于停牌或数据缺失。")
        return

    categories = ['主力资金', '超大单', '大单', '中单', '小单']
    values = [main, super_flow, big, mid, small]
    # 颜色：正数绿色，负数红色，零用灰色
    colors = []
    for v in values:
        if v > 0:
            colors.append('#52c41a')
        elif v < 0:
            colors.append('#c72a2a')
        else:
            colors.append('#d9d9d9')

    options = {
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "shadow"},
            "formatter": lambda params: f"{params[0]['name']}<br/>净额: {params[0]['value']:.2f} 亿元"
        },
        "grid": {"left": "10%", "right": "6%", "top": "10%", "bottom": "12%"},
        "xAxis": {"type": "category", "data": categories, "axisLabel": {"fontSize": 13}},
        "yAxis": {"type": "value", "name": "净额 (亿元)",
                  "splitLine": {"lineStyle": {"color": "#e9edf2", "type": "dashed"}}},
        "series": [{
            "type": "bar",
            "data": [{"value": round(v, 2), "itemStyle": {"color": colors[i]}} for i, v in enumerate(values)],
            "barWidth": "35%",
            "label": {
                "show": True,
                "position": "top",
                "formatter": lambda p: f"{p.value:.2f}",
                "fontSize": 12,
                "fontWeight": 600
            }
        }]
    }
    st_echarts(options, height="320px")

def plot_price_map_echarts(current_price, high, low, target):
    current_price = clean_value(current_price)
    high = clean_value(high)
    low = clean_value(low)
    target = clean_value(target)

    items = ['当前股价', '近期高点', '近期低点', '机构目标价']
    values = [current_price, high, low, target]
    colors = ['#2d8cf0', '#ff7a45', '#52c41a', '#b33636']

    options = {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "grid": {"left": "18%", "right": "8%", "top": "8%", "bottom": "10%"},
        "xAxis": {"type": "value", "name": "价格 (元)", "splitLine": {"show": False}},
        "yAxis": {"type": "category", "data": items[::-1], "axisLabel": {"fontSize": 13}},
        "series": [{
            "type": "bar",
            "data": [{"value": v, "itemStyle": {"color": colors[i]}} for i, v in enumerate(values[::-1])],
            "barWidth": "25%",
            "label": {
                "show": True,
                "position": "right",
                "formatter": lambda p: f"{p.value:.2f}元",
                "fontSize": 12
            }
        }]
    }
    st_echarts(options, height="280px")

# ---------- 4. 主界面 ----------
st.title("📈 A股智能分析仪表盘")
st.markdown("多数据源切换，实时估值与资金流向可视化（数据缓存10分钟，估值缓存1分钟）")

with st.sidebar:
    st.header("⚙️ 参数设置")
    code_input = st.text_input("6位股票代码", value="600584", help="例如：600584（长电科技）")
    time_option = st.radio("时间范围", ["近1年", "近3个月", "自定义"], index=0)
    today = datetime.date.today()
    # 整理日期逻辑
    if time_option == "近1年":
        start_date = today - datetime.timedelta(days=365)
        end_date = today
    elif time_option == "近3个月":
        start_date = today - datetime.timedelta(days=90)
        end_date = today
    else:  # 自定义
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("起始", today - datetime.timedelta(days=30))
        with col2:
            end_date = st.date_input("结束", today)
    fetch_btn = st.button("🚀 获取深度数据", type="primary")

if fetch_btn:
    full_code = format_stock_code(code_input)
    if full_code is None:
        st.error("❌ 代码格式错误，请输入6位数字（如600584）")
        st.stop()

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    with st.spinner(f"正在获取 {full_code} 数据..."):
        df, msg = fetch_cached_stock_data(full_code, start_str, end_str)

    if df is None or df.empty:
        st.error(f"❌ 数据获取失败：{msg}")
        st.stop()

    st.success(f"✅ {msg}")

    # ---- 展示数据表格 ----
    st.subheader("📊 行情数据预览（最近10天）")
    cols = ['日期', '开盘', '收盘', '最高', '最低', '成交量']
    show_cols = [c for c in cols if c in df.columns]
    st.dataframe(df[show_cols].tail(10), use_container_width=True)

    # ---- 获取实时估值与资金流向（带缓存） ----
    extra = get_realtime_valuation(full_code)

    # ---- 估值卡片 ----
    if extra and any(k in extra for k in ['pe', 'pb', 'total_mv', 'turnover']):
        st.subheader("💎 核心估值指标")
        col1, col2, col3, col4 = st.columns(4)
        if 'pe' in extra and extra['pe']:
            pe = extra['pe']
            delta = "高估" if pe > 50 else ("合理" if pe > 0 else "异常")
            col1.metric("动态市盈率", f"{pe:.2f}", delta=delta)
        if 'pb' in extra and extra['pb']:
            col2.metric("市净率 (LF)", f"{extra['pb']:.2f}")
        if 'total_mv' in extra and extra['total_mv']:
            col3.metric("总市值", f"{extra['total_mv']:.2f} 亿元")
        if 'turnover' in extra and extra['turnover']:
            col4.metric("换手率", f"{extra['turnover']:.2f}%")
    else:
        st.info("未能获取实时估值数据（接口可能受限）")

    # ---- 资金流向图 ----
    if extra and 'main_net' in extra:
        st.subheader("💰 当日资金流向全景")
        plot_fund_flow_echarts(
            main=extra.get('main_net'),
            super_flow=extra.get('super_net'),
            big=extra.get('big_net'),
            mid=extra.get('mid_net'),
            small=extra.get('small_net')
        )
        # 显示主资金动态
        main_net = extra.get('main_net', 0)
        if main_net < 0:
            st.warning(f"⚠️ 主力资金今日净流出 {abs(main_net):.2f} 亿元，资金态度偏空")
        elif main_net > 0:
            st.success(f"✅ 主力资金今日净流入 {main_net:.2f} 亿元，资金态度偏多")
        else:
            st.info("主力资金今日无明显进出")
    else:
        st.info("未能获取当日资金流向数据，可能接口频率限制，请稍后重试")

    # ---- 关键价位图谱 ----
    if not df.empty and '收盘' in df.columns:
        st.subheader("📈 关键价位参考")
        current = df['收盘'].iloc[-1]
        max_price = df['最高'].max()
        min_price = df['最低'].min()
        # 机构目标价：此处使用一个简单示意（后续可接入AI预测）
        target_price = round(current * 0.8, 2)  # 仅演示，实际可替换
        plot_price_map_echarts(
            current_price=current,
            high=max_price,
            low=min_price,
            target=target_price
        )
        st.caption("💡 机构目标价当前为示意值（当前价*0.8），后续可接入AI模型提供精确预测")
    else:
        st.warning("数据不足，无法绘制价位图")

    # ---- Matplotlib 走势图（保留） ----
    st.subheader("📉 收盘价走势图 (Matplotlib)")
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(df['日期'], df['收盘'], color='blue', linewidth=1.5)
    ax.set_title(f'{full_code} 收盘价走势')
    ax.set_xlabel('日期')
    ax.set_ylabel('价格（元）')
    ax.grid(True, linestyle='--', alpha=0.7)
    plt.xticks(rotation=45)
    st.pyplot(fig)

else:
    st.info("👈 左侧输入股票代码，点击「获取深度数据」开始分析")