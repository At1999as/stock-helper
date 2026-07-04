# app.py
# data_fetcher.py
import akshare as ak
import pandas as pd
import matplotlib.pyplot as plt
import datetime
import time
import requests
import json
import re
from io import StringIO

requests.adapters.DEFAULT_RETRIES = 3


def format_stock_code(code):
    code = code.strip()
    if len(code) != 6:
        return None
    if code.startswith('6'):
        return 'sh' + code
    elif code.startswith('0') or code.startswith('3'):
        return 'sz' + code
    else:
        return None


# ---------- 数据源1：baostock ----------
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


# ---------- 数据源2：同花顺 ----------
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


# ---------- 数据源3：东方财富 ----------
def fetch_from_eastmoney(symbol, start_date, end_date):
    for attempt in range(1, 4):
        try:
            df = ak.stock_zh_a_hist(symbol=symbol, period="daily",
                                    start_date=start_date, end_date=end_date, adjust="qfq")
            if df.empty:
                return None, "东方财富返回空数据。"
            df = df[['日期', '开盘', '最高', '最低', '收盘', '成交量']]
            return df, f"东方财富接口获取成功，共 {len(df)} 条记录。"
        except Exception as e:
            if attempt < 3:
                time.sleep(2)
            else:
                return None, f"东方财富失败：{e}"
    return None, "东方财富多次尝试失败。"


# ---------- 数据源4：新浪 ----------
def fetch_from_sina(symbol, start_date, end_date):
    try:
        df_sina = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq",
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


# ---------- 主获取函数（依次尝试，返回 (df, message)） ----------
def fetch_stock_data(symbol, start_date, end_date):
    # baostock
    df, msg = fetch_from_baostock(symbol, start_date, end_date)
    if df is not None:
        return df, msg
    # 同花顺
    df, msg = fetch_from_ths(symbol, start_date, end_date)
    if df is not None:
        return df, msg
    # 东方财富
    df, msg = fetch_from_eastmoney(symbol, start_date, end_date)
    if df is not None:
        return df, msg
    # 新浪
    df, msg = fetch_from_sina(symbol, start_date, end_date)
    if df is not None:
        return df, msg
    return None, "所有接口均无法获取数据。"


# ---------- 统计函数（供界面调用，返回字典） ----------
def calc_statistics(df):
    if df is None or df.empty or '收盘' not in df.columns:
        return None
    latest_close = df['收盘'].iloc[-1]
    first_close = df['收盘'].iloc[0]
    change_pct = (latest_close - first_close) / first_close * 100
    stats = {
        'start_date': df['日期'].iloc[0],
        'end_date': df['日期'].iloc[-1],
        'change_pct': change_pct,
        'max_high': df['最高'].max() if '最高' in df.columns else None,
        'min_low': df['最低'].min() if '最低' in df.columns else None,
        'avg_volume': df['成交量'].mean() if '成交量' in df.columns else None,
    }
    if '换手率' in df.columns:
        stats['avg_turnover'] = df['换手率'].mean()
    if '市盈率' in df.columns:
        stats['avg_pe'] = df['市盈率'].mean()
    return stats


# ---------- 绘图函数（返回 matplotlib 的 figure） ----------
def plot_close_trend(df, symbol):
    if df is None or df.empty or '收盘' not in df.columns:
        return None
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei']
    plt.rcParams['axes.unicode_minus'] = False
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df['日期'], df['收盘'], color='blue', linewidth=1.5, label='收盘价')
    ax.set_title(f'{symbol} 收盘价走势')
    ax.set_xlabel('日期')
    ax.set_ylabel('价格（元）')
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.legend()
    plt.xticks(rotation=45)
    plt.tight_layout()
    return fig


import streamlit as st
import datetime
import pandas as pd


# 设置页面标题和图标
st.set_page_config(page_title="A股分析小助手", layout="wide")

st.title("📈 A股股票数据小助手")
st.markdown("输入股票代码，一键获取数据、统计和走势图")

# ---------- 侧边栏：输入参数 ----------
with st.sidebar:
    st.header("⚙️ 参数设置")
    code_input = st.text_input("6位股票代码", value="600000", help="例如：600000（浦发银行）")
    # 时间范围选择
    time_option = st.radio(
        "时间范围",
        ["近1年", "近3年", "近5年", "自定义"],
        index=0
    )
    if time_option == "自定义":
        col1, col2 = st.columns(2)
        with col1:
            start_date = st.date_input("起始日期", datetime.date.today() - datetime.timedelta(days=365))
        with col2:
            end_date = st.date_input("结束日期", datetime.date.today())
    else:
        today = datetime.date.today()
        if time_option == "近1年":
            start_date = today - datetime.timedelta(days=365)
        elif time_option == "近3年":
            start_date = today - datetime.timedelta(days=365*3)
        else:  # 近5年
            start_date = today - datetime.timedelta(days=365*5)
        end_date = today

    fetch_btn = st.button("🚀 获取数据", type="primary")

# ---------- 主区域 ----------
# 当点击按钮时执行
if fetch_btn:
    # 校验代码
    full_code = format_stock_code(code_input)
    if full_code is None:
        st.error("❌ 代码格式错误，请输入6位数字（如 600000）")
        st.stop()

    # 格式化日期为字符串 YYYYMMDD
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    with st.spinner(f"正在获取 {full_code} 从 {start_str} 到 {end_str} 的数据..."):
        df, msg = fetch_stock_data(full_code, start_str, end_str)

    if df is None:
        st.error(f"❌ 数据获取失败：{msg}")
        st.stop()

    # 成功获取，展示成功信息
    st.success(f"✅ {msg}")

    # ---------- 1. 数据预览（表格） ----------
    st.subheader("📋 数据预览（最近5天）")
    # 显示最近5天，并选择常见列
    base_cols = ['日期', '开盘', '收盘', '最高', '最低', '成交量']
    available_cols = [c for c in base_cols if c in df.columns]
    st.dataframe(df[available_cols].tail(5), use_container_width=True)

    # ---------- 2. 统计信息 ----------
    st.subheader("📊 统计摘要")
    stats = calc_statistics(df)
    if stats:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("起始日期", stats['start_date'])
        col2.metric("结束日期", stats['end_date'])
        # 涨跌幅用红色/绿色显示
        change = stats['change_pct']
        col3.metric("区间涨跌幅", f"{change:.2f}%", delta=f"{change:.2f}%")
        if stats['max_high'] is not None:
            col4.metric("最高价", f"{stats['max_high']:.2f} 元")
        # 第二行
        col5, col6, col7 = st.columns(3)
        if stats['min_low'] is not None:
            col5.metric("最低价", f"{stats['min_low']:.2f} 元")
        if stats['avg_volume'] is not None:
            col6.metric("日均成交量", f"{stats['avg_volume']:.0f} 手")
        if 'avg_turnover' in stats:
            col7.metric("平均换手率", f"{stats['avg_turnover']:.2f}%")
        if 'avg_pe' in stats:
            with st.expander("更多估值指标"):
                st.write(f"平均市盈率：{stats['avg_pe']:.2f}")

    # ---------- 3. 走势图 ----------
    st.subheader("📉 收盘价走势图")
    fig = plot_close_trend(df, full_code)
    if fig:
        st.pyplot(fig)
    else:
        st.warning("无法绘制走势图（缺少收盘价数据）")

    # ---------- 4. 额外：原始数据下载（可选） ----------
    st.subheader("💾 导出数据")
    csv = df.to_csv(index=False, encoding='utf-8-sig')
    st.download_button(
        label="下载完整数据 (CSV)",
        data=csv,
        file_name=f"{full_code}_data.csv",
        mime="text/csv",
    )
else:
    # 第一次进入页面时的提示
    st.info("👈 在左侧输入股票代码和时间范围，点击「获取数据」开始分析")