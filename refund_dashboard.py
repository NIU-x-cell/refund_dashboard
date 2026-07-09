import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import timedelta
import time
from config import get_db_conn

# 【必须第一行，全局唯一页面配置】
st.set_page_config(page_title="Ozon退款数据看板", layout="wide")
st.title("Ozon店铺退款退货数据分析看板")

# 初始化登录会话
if "user_auth" not in st.session_state:
    st.session_state.user_auth = {
        "is_login": False,
        "username": "",
        "role": "",
        "dept_code": "",
        "allow_shop_list": []
    }

# ===================== 登录页面函数 =====================
def login_page():
    st.title("账号登录验证")
    username = st.text_input("登录账号")
    pwd = st.text_input("登录密码", type="password")
    if st.button("登录验证"):
        try:
            conn = get_db_conn()
            user_sql = "SELECT * FROM sys_user WHERE username = %s"
            user_df = pd.read_sql(user_sql, conn, params=[username])
            conn.close()
            if len(user_df) == 0:
                st.error("账号不存在！")
                return
            user_row = user_df.iloc[0]
            if user_row["password"] != pwd:
                st.error("密码错误！")
                return
            # 读取该账号绑定店铺
            if user_row["role"] != "admin":
                conn2 = get_db_conn()
                shop_sql = "SELECT `店铺` FROM shop_dept WHERE dept_code = %s"
                shop_df = pd.read_sql(shop_sql, conn2, params=[user_row["dept_code"]])
                conn2.close()
                shop_list = shop_df["店铺"].tolist()
            else:
                shop_list = []
            # 写入会话
            st.session_state.user_auth["is_login"] = True
            st.session_state.user_auth["username"] = username
            st.session_state.user_auth["role"] = user_row["role"]
            st.session_state["dept_code"] = user_row["dept_code"]
            st.session_state.user_auth["allow_shop_list"] = shop_list
            st.success("登录成功，刷新页面...")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"数据库连接失败：{str(e)}")

# ===================== 数据库查询通用缓存函数 =====================
@st.cache_data(ttl=600)
def query_sql(sql, params=None):
    try:
        conn = get_db_conn()
        df = pd.read_sql(sql, conn, params=params)
        conn.close()
        return df
    except Exception as e:
        st.error(f"查询异常：{str(e)}")
        return pd.DataFrame()

# ===================== 工具函数 =====================
def get_growth(curr, last):
    if last == 0:
        return "——"
    rate = (curr - last) / last * 100
    return f"{rate:.2f}%"

def get_all_dept_list():
    dept_df = query_sql("SELECT DISTINCT dept_code FROM shop_dept")
    return dept_df["dept_code"].tolist() if not dept_df.empty else []

def get_shop_by_dept(dept_list):
    if not dept_list:
        return []
    placeholders = ",".join(["%s"] * len(dept_list))
    shop_sql = f"SELECT DISTINCT `店铺` FROM shop_dept WHERE dept_code IN ({placeholders})"
    shop_df = query_sql(shop_sql, params=dept_list)
    return shop_df["店铺"].tolist() if not shop_df.empty else []

# ===================== 未登录拦截 =====================
user_auth = st.session_state.user_auth
if not user_auth["is_login"]:
    login_page()
    st.stop()

# 登录后全局变量提取
username = user_auth["username"]
role = user_auth["role"]
self_dept = user_auth["dept_code"]
is_admin = (role == "admin")

# ===================== 侧边栏筛选 =====================
with st.sidebar:
    if is_admin:
        info_text = f"当前账号：{username} 【超级管理员-全部门权限】"
    else:
        info_text = f"当前账号：{username} 【部门主管-{self_dept}】"
    st.info(info_text)
    if st.button("退出登录"):
        del st.session_state["user_auth"]
        st.rerun()
    st.divider()

    # 部门选择
    all_depts = get_all_dept_list()
    if is_admin:
        select_dept = st.multiselect("选择部门", all_depts, default=all_depts)
    else:
        st.text_input("所属部门", value=self_dept, disabled=True)
        select_dept = [self_dept]
    st.divider()

    # 退款状态
    status_df = query_sql("SELECT DISTINCT `创建退款时订单状态` FROM ozon_ref")
    status_list = status_df["创建退款时订单状态"].tolist() if not status_df.empty else []
    select_status = st.multiselect("退款状态", status_list, default=status_list)
    st.divider()

    # 日期默认近15天
    date_df = query_sql("SELECT MIN(`退款时间`) min_date, MAX(`退款时间`) max_date FROM ozon_ref")
    if date_df.empty or pd.isna(date_df.iloc[0]["min_date"]):
        st.warning("数据库暂无退款记录")
        start_date, end_date = None, None
    else:
        min_db = date_df.iloc[0]["min_date"]
        max_db = date_df.iloc[0]["max_date"]
        default_end = max_db
        default_start = max_db - timedelta(days=15)
        if default_start < min_db:
            default_start = min_db
        start_date, end_date = st.date_input(
            "退款时间区间",
            value=(default_start.date(), default_end.date()),
            min_value=min_db.date(),
            max_value=max_db.date()
        )

if start_date is None or end_date is None:
    st.stop()

# ===================== 筛选数据查询【修复空列表IN语法报错】 =====================
shop_list = get_shop_by_dept(select_dept)
# 修复1：店铺列表为空直接返回空df，不执行SQL
if len(shop_list) == 0 or len(select_status) == 0:
    df_data = pd.DataFrame()
    df_last = pd.DataFrame()
else:
    shop_holder = ",".join(["%s"] * len(shop_list))
    status_holder = ",".join(["%s"] * len(select_status))
    params = shop_list + select_status + [start_date, end_date]
    filter_sql = f"""
    SELECT * FROM ozon_ref
    WHERE `店铺` IN ({shop_holder})
    AND `创建退款时订单状态` IN ({status_holder})
    AND DATE(`退款时间`) BETWEEN %s AND %s
    """
    df_data = query_sql(filter_sql, params=params)

    # 上期同期数据
    days_diff = (end_date - start_date).days
    last_s = start_date - timedelta(days_diff + 1)
    last_e = start_date - timedelta(days=1)
    last_params = shop_list + select_status + [last_s, last_e]
    last_sql = f"""
    SELECT * FROM ozon_ref
    WHERE `店铺` IN ({shop_holder})
    AND `创建退款时订单状态` IN ({status_holder})
    AND DATE(`退款时间`) BETWEEN %s AND %s
    """
    df_last = query_sql(last_sql, params=last_params)

# ===================== 核心指标（全字段加存在判断，杜绝KeyError） =====================
# 按订单号去重，统计真实工单数量（全局统一口径：工单=唯一订单数）
curr_order = df_data["订单号"].nunique() if "订单号" in df_data.columns else 0
# 上期同步修改
last_order = df_last["订单号"].nunique() if ("订单号" in df_last.columns and len(df_last) > 0) else 0
# 安全读取退款金额RMB
if "退款金额RMB" in df_data.columns:
    curr_rmb = df_data["退款金额RMB"].sum()
else:
    curr_rmb = 0
# 安全读取退款数量
qty_col = "退款数量(仅支持2021年12月22日之后创建的退款单)"
if qty_col in df_data.columns:
    curr_qty = df_data[qty_col].sum()
else:
    curr_qty = 0

# 上期指标安全读取
last_order = df_last["订单号"].nunique() if ("订单号" in df_last.columns and len(df_last) > 0) else 0
if "退款金额RMB" in df_last.columns and len(df_last) > 0:
    last_rmb = df_last["退款金额RMB"].sum()
else:
    last_rmb = 0

if qty_col in df_last.columns and len(df_last) > 0:
    last_qty = df_last[qty_col].sum()
else:
    last_qty = 0

# 环比计算（补全两个参数，修复delta报错）
order_grow = get_growth(curr_order, last_order)
rmb_grow = get_growth(curr_rmb, last_rmb)
qty_grow = get_growth(curr_qty, last_qty)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("退款工单总数", curr_order, delta=order_grow, delta_color="inverse")
with col2:
    st.metric("总退款金额(RMB)", f"{curr_rmb:.2f}", delta=rmb_grow, delta_color="inverse")
with col3:
    st.metric("总退款件数", int(curr_qty), delta=qty_grow, delta_color="inverse")
with col4:
    if "店铺" in df_data.columns:
        shop_count = df_data["店铺"].nunique()
    else:
        shop_count = 0
    st.metric("涉及店铺", shop_count)

# ===================== 每日趋势图 =====================
st.divider()
title_text = "全部门每日退货趋势" if is_admin else f"{self_dept} 每日退货趋势"
st.subheader(title_text)
if not df_data.empty and qty_col in df_data.columns:
    day_df = df_data.groupby(df_data["退款时间"].dt.date)[qty_col].sum().reset_index()
    day_df.columns = ["日期", "当日件数"]
    fig = px.line(day_df, x="日期", y="当日件数", markers=True, title="每日退货件数走势")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("当前筛选无数据或缺少退货数量字段")

# ===================== 店铺汇总【全局统一工单口径：nunique订单】 =====================
st.divider()
st.subheader("各店铺退款汇总")
if not df_data.empty and "店铺" in df_data.columns and "退款金额RMB" in df_data.columns and qty_col in df_data.columns:
    shop_sum = df_data.groupby("店铺").agg(
        工单数量=("订单号", "nunique"),
        退款金额RMB=("退款金额RMB", "sum"),
        退货件数=(qty_col,"sum")
    ).reset_index().sort_values("工单数量", ascending=False)
    st.dataframe(shop_sum, use_container_width=True)
else:
    st.info("暂无店铺数据或关键字段缺失")

# ===================== TOP15饼图 + SKU排行【复刻旧版预聚合逻辑】 =====================
st.divider()
st.subheader("商品退货占比TOP15")
if not df_data.empty and "sku中文名" in df_data.columns and "店铺" in df_data.columns and qty_col in df_data.columns and "退款金额RMB" in df_data.columns and "SKU" in df_data.columns:
    qty_col = "退款数量(仅支持2021年12月22日之后创建的退款单)"
    # 【复刻旧版：一次性预聚合店铺+商品，全局复用】
    sku_summary = df_data.groupby(["店铺", "sku中文名", "SKU"]).agg(
        退货工单数量=("订单号", "nunique"),
        退货总件数=(qty_col, "sum"),
        退款总金额RMB=("退款金额RMB", "sum")
    ).reset_index()

    # TOP15饼图数据源：按商品汇总总件数
    top15 = sku_summary.groupby("sku中文名")["退货总件数"].sum().reset_index().sort_values("退货总件数", ascending=False).head(15)
    fig_pie = px.pie(top15, values="退货总件数", names="sku中文名", hole=0.1, title="TOP15商品退货件数占比")
    st.plotly_chart(fig_pie, use_container_width=True)

    st.divider()
    st.subheader("全商品退货排行")
    sku_full = sku_summary.sort_values("退货工单数量", ascending=False)
    st.dataframe(sku_full, height=400, use_container_width=True)

    if len(sku_summary) > 0:
        sku_valid = sku_summary[sku_summary["退货总件数"] > 0].copy()
        if len(sku_valid) > 0:
            sku_sorted = sku_valid.sort_values("退货工单数量", ascending=False)
            top_sku = sku_sorted.iloc[0]
            st.success(f"🔥 退货最多单品(单店铺维度)：{top_sku['sku中文名']}｜店铺：{top_sku['店铺']}｜该店铺退货件数：{int(top_sku['退货总件数'])}")
        else:
            st.info("当前筛选下无有效退货商品数据")

    # ===================== 单品维度分店铺明细查询【完全复刻你截图旧版逻辑】 =====================
    st.divider()
    st.subheader("单品维度分店铺明细查询")
    # 1、构造下拉选项：按商品总工单降序
    sku_opt_df = sku_summary.groupby("sku中文名")["退货工单数量"].sum().reset_index()
    sku_opt_df = sku_opt_df.sort_values("退货工单数量", ascending=False).reset_index(drop=True)
    sku_opt_df["展示名称"] = sku_opt_df["sku中文名"] + " (" + sku_opt_df["退货工单数量"].astype(str) + "单)"
    opt_list = sku_opt_df["展示名称"].tolist()

    select_sku_show = st.selectbox("选择商品品类", options=opt_list)
    select_sku_name = select_sku_show.split(" (")[0]

    # 2、筛选当前商品，直接复用预聚合sku_summary，不再groupby
    filter_sku_shop = sku_summary[sku_summary["sku中文名"] == select_sku_name].copy()
    total_sku_all_order = filter_sku_shop["退货工单数量"].sum()

    # 3、重命名字段，和旧版完全一致
    sku_shop_table = filter_sku_shop.rename(columns={
        "退货工单数量": "该店铺工单数量",
        "退款总金额RMB": "退款总金额RMB",
        "退货总件数": "退货总件数"
    })

    # 计算工单占比
    sku_shop_table["该店铺工单占此商品总工单比例"] = (sku_shop_table["该店铺工单数量"] / total_sku_all_order * 100).round(2).astype(str) + "%"
    # 店铺工单降序排序
    sku_shop_table = sku_shop_table.sort_values(by="该店铺工单数量", ascending=False).reset_index(drop=True)
    # 固定展示列
    show_cols = ["店铺", "该店铺工单数量", "退款总金额RMB", "退货总件数", "该店铺工单占此商品总工单比例"]
    st.dataframe(sku_shop_table[show_cols], use_container_width=True, height=500)
else:
    st.info("无商品数据或关键字段缺失")

# ===================== 原始明细 =====================
st.divider()
st.subheader("退款订单明细")
st.dataframe(df_data, height=400, use_container_width=True)

# ===================== Excel导出【同步修正分组工单口径】 =====================
shop_sum = pd.DataFrame()
sku_full = pd.DataFrame()
if not df_data.empty and "店铺" in df_data.columns and "退款金额RMB" in df_data.columns and qty_col in df_data.columns:
    shop_sum = df_data.groupby("店铺").agg(
        工单数量=("订单号", "nunique"),
        退款金额RMB=("退款金额RMB", "sum"),
        退货件数=(qty_col,"sum")
    ).reset_index().sort_values("工单数量", ascending=False)
if not df_data.empty and "sku中文名" in df_data.columns:
    sku_full = df_data.groupby(["店铺", "sku中文名", "SKU"]).agg(
        工单数量=("订单号", "nunique"),
        退货件数=(qty_col,"sum"),
        退款金额RMB=("退款金额RMB","sum")
    ).reset_index().sort_values("退货件数", ascending=False)

if not df_data.empty:
    def export_excel():
        from io import BytesIO
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df_data.to_excel(w, sheet_name="明细", index=False)
            if not shop_sum.empty:
                shop_sum.to_excel(w, sheet_name="店铺汇总", index=False)
            if not sku_full.empty:
                sku_full.to_excel(w, sheet_name="商品排行", index=False)
        buf.seek(0)
        return buf.read()
    excel_data = export_excel()
    st.download_button(
        label="导出筛选全部数据",
        data=excel_data,
        file_name="Ozon退款报表.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
