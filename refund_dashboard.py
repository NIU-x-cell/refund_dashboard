import streamlit as st
import pandas as pd
import pymysql
import plotly.express as px
from config import get_db_conn
from datetime import timedelta

# ---------------------- 页面基础配置 ----------------------
st.set_page_config(page_title="Ozon退款数据看板", layout="wide")
st.title("Ozon店铺退款数据管理看板")


# ---------------------- 数据库查询通用函数（缓存优化） ----------------------
@st.cache_data(ttl=600)
def query_sql(sql):
    conn = get_db_conn()
    df = pd.read_sql(sql, conn)
    conn.close()
    return df


# ---------------------- 登录模块（新增读取is_admin超级管理员标识） ----------------------
def login_page():
    st.subheader("账号登录")
    username = st.text_input("登录账号")
    password = st.text_input("登录密码", type="password")
    login_btn = st.button("登录")
    if login_btn:
        # 查询账号+是否总管理员
        user_sql = f"SELECT * FROM sys_user WHERE username='{username}' AND password='{password}'"
        user_df = query_sql(user_sql)
        if len(user_df) == 0:
            st.error("账号或密码错误，请重新输入")
            return None
        user_info = user_df.iloc[0].to_dict()
        # 存入session：dept、管理员标识
        st.session_state["user"] = user_info
        st.success("登录成功，正在跳转数据页面...")
        st.rerun()
    return None


# ---------------------- 获取全部部门列表 ----------------------
def get_all_dept_list():
    dept_df = query_sql("SELECT DISTINCT dept_code FROM shop_dept")
    return dept_df["dept_code"].tolist()


# ---------------------- 根据选中部门获取对应店铺列表 ----------------------
def get_shop_by_dept(dept_list):
    dept_str = "','".join(dept_list)
    shop_df = query_sql(f"SELECT DISTINCT `店铺` FROM shop_dept WHERE dept_code IN ('{dept_str}')")
    return shop_df["店铺"].tolist()


# ---------------------- 数据筛选与看板主体 ----------------------
def dashboard_main():
    user = st.session_state["user"]
    all_depts = get_all_dept_list()
    is_admin = user.get("is_admin", 0) == 1
    self_dept = user["dept_code"]

    # 侧边栏展示身份
    if is_admin:
        role_text = f"当前登录：{user['username']} | 超级管理员（可查看全部门）"
    else:
        role_text = f"当前登录：{user['username']} | 普通主管-{self_dept}"
    with st.sidebar:
        st.info(role_text)
        if st.button("退出登录"):
            del st.session_state["user"]
            st.rerun()
        st.divider()

        # ========== 改动点：替换为部门选择，删除原店铺多选 ==========
        if is_admin:
            # 超级管理员：可多选所有部门
            select_dept = st.multiselect("选择部门", options=all_depts, default=all_depts)
        else:
            # 普通部门账号：仅展示自身部门，固定不可修改
            st.text_input("当前所属部门", value=self_dept, disabled=True)
            select_dept = [self_dept]
        st.divider()

        # 原有退款状态筛选完全不动
        status_list = query_sql("SELECT DISTINCT `创建退款时订单状态` FROM ozon_ref")["创建退款时订单状态"].tolist()
        select_status = st.multiselect("退款状态", options=status_list, default=status_list)

        # ========== 日期默认改为最近半个月（15天） ==========
        date_min_df = query_sql("SELECT MIN(`退款时间`) AS min_date, MAX(`退款时间`) AS max_date FROM ozon_ref")
        min_db_date = date_min_df.iloc[0]["min_date"]
        max_db_date = date_min_df.iloc[0]["max_date"]

        # 计算默认起始：最大日期往前推15天
        default_end = max_db_date
        default_start = default_end - timedelta(days=15)
        # 兜底：如果往前15天早于数据库最早日期，就用数据库最小日期
        if default_start < min_db_date:
            default_start = min_db_date

        start_date, end_date = st.date_input(
            "退款时间区间",
            value=(default_start.date(), default_end.date()),
            min_value=min_db_date.date(),
            max_value=max_db_date.date()
        )

    # 根据选中部门拿到对应所有店铺
    shop_all = get_shop_by_dept(select_dept)
    shop_str = "','".join(shop_all)
    status_str = "','".join(select_status)
    filter_sql = f"""
    SELECT * FROM ozon_ref
    WHERE `店铺` IN ('{shop_str}')
      AND `创建退款时订单状态` IN ('{status_str}')
      AND DATE(`退款时间`) BETWEEN '{start_date}' AND '{end_date}'
    """
    df_data = query_sql(filter_sql)

    # ========== 计算上期同期（同天数上一个区间）数据用于环比 ==========
    days_range = (end_date - start_date).days
    last_start = start_date - timedelta(days=days_range + 1)
    last_end = start_date - timedelta(days=1)
    last_sql = f"""
    SELECT * FROM ozon_ref
    WHERE `店铺` IN ('{shop_str}')
      AND `创建退款时订单状态` IN ('{status_str}')
      AND DATE(`退款时间`) BETWEEN '{last_start}' AND '{last_end}'
    """
    df_last = query_sql(last_sql)
    # 本期指标
    curr_order = len(df_data)
    curr_rmb = df_data["退款金额RMB"].sum()
    curr_qty = df_data["退款数量(仅支持2021年12月22日之后创建的退款单)"].sum()
    # 上期同期指标
    last_order = len(df_last)
    last_rmb = df_last["退款金额RMB"].sum() if len(df_last) > 0 else 0
    last_qty = df_last["退款数量(仅支持2021年12月22日之后创建的退款单)"].sum() if len(df_last) > 0 else 0

    # 环比增长率计算，避免除0报错
    def get_growth(curr, last):
        if last == 0:
            return "——"
        rate = (curr - last) / last * 100
        return f"{rate:.2f}%"

    order_grow = get_growth(curr_order, last_order)
    rmb_grow = get_growth(curr_rmb, last_rmb)
    qty_grow = get_growth(curr_qty, last_qty)

    # 核心指标卡片
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("退款工单总数", value=curr_order, delta=order_grow, delta_color="inverse")
    with col2:
        st.metric("总退款金额(RMB)", value=f"{curr_rmb:.2f}", delta=rmb_grow, delta_color="inverse")
    with col3:
        st.metric("总退款商品件数", value=int(curr_qty), delta=qty_grow, delta_color="inverse")
    with col4:
        shop_count = df_data["店铺"].nunique()
        st.metric("涉及店铺数量", value=shop_count)

    # ========== 图表2：每日退货趋势折线图 ==========
    st.divider()
    if is_admin:
        trend_title = "全部门每日退货件数趋势"
    else:
        trend_title = f"{self_dept} 部门每日退货件数趋势"
    st.subheader(trend_title)
    day_trend = df_data.groupby(df_data["退款时间"].dt.date)[
        "退款数量(仅支持2021年12月22日之后创建的退款单)"].sum().reset_index()
    day_trend.columns = ["日期", "当日退货件数"]

    fig_line = px.line(
        day_trend,
        x="日期",
        y="当日退货件数",
        markers=True,
        title="每日退货件数走势",
        labels={"当日退货件数": "退货总件数"}
    )
    st.plotly_chart(fig_line, use_container_width=True)

    st.divider()
    # 店铺维度汇总
    st.subheader("各店铺退款汇总")
    shop_summary = df_data.groupby("店铺").agg(
        退款工单总数=("订单号", "count"),
        退款总金额RMB=("退款金额RMB", "sum"),
        退款总件数=("退款数量(仅支持2021年12月22日之后创建的退款单)", "sum")
    ).reset_index()
    shop_summary = shop_summary.sort_values(by="退款工单总数", ascending=False).reset_index(drop=True)
    st.dataframe(shop_summary, use_container_width=True)

    # ========== 图表1：退货商品占比饼图 ==========
    st.divider()
    st.subheader("各商品退货件数占比分布")
    sku_summary = df_data.groupby(["店铺", "sku中文名"]).agg(
        退货工单数量=("订单号", "count"),
        退货总件数=("退款数量(仅支持2021年12月22日之后创建的退款单)", "sum"),
        退款总金额RMB=("退款金额RMB", "sum")
    ).reset_index()
    sku_summary = sku_summary.sort_values(by="退货总件数", ascending=False).reset_index(drop=True)
    top15_pie = sku_summary.head(15)

    fig_pie = px.pie(
        top15_pie,
        values="退货总件数",
        names="sku中文名",
        title="筛选区间TOP15商品退货件数占比",
        hole=0.1
    )
    st.plotly_chart(fig_pie, use_container_width=True)

    # ========== 商品SKU中文名退货排行模块 ==========
    st.divider()
    st.subheader("各商品SKU退货排行（按退货件数倒序）")
    sku_summary_full = df_data.groupby(["店铺", "sku中文名", "SKU"]).agg(
        退货工单数量=("订单号", "count"),
        退货总件数=("退款数量(仅支持2021年12月22日之后创建的退款单)", "sum"),
        退款总金额RMB=("退款金额RMB", "sum")
    ).reset_index()
    sku_summary_full = sku_summary_full.sort_values(by="退货总件数", ascending=False).reset_index(drop=True)
    st.dataframe(sku_summary_full, use_container_width=True, height=400)
    top1_sku = sku_summary_full.iloc[0]
    st.success(
        f"🔥 当前筛选区间退货量最高商品：【{top1_sku['sku中文名']}】，所属店铺：{top1_sku['店铺']}，累计退货件数：{int(top1_sku['退货总件数'])}")

    # ====================== 单品维度分店铺明细查询【修复统计+排序】 ======================
    st.divider()
    st.subheader("单品维度分店铺明细查询")
    # 1、构造下拉选项：商品名称(总工单)，按商品总工单降序
    sku_opt_df = sku_summary.groupby("sku中文名")["退货工单数量"].sum().reset_index()
    sku_opt_df = sku_opt_df.sort_values("退货工单数量", ascending=False).reset_index(drop=True)
    sku_opt_df["展示名称"] = sku_opt_df["sku中文名"] + " (" + sku_opt_df["退货工单数量"].astype(str) + ")"
    opt_list = sku_opt_df["展示名称"].tolist()
    select_sku_show = st.selectbox("选择商品品类", options=opt_list)
    select_sku_name = select_sku_show.split(" (")[0]

    # 2、筛选当前商品所有店铺聚合数据（sku_summary已经是店铺+商品聚合，无需再次groupby）
    filter_sku_shop = sku_summary[sku_summary["sku中文名"] == select_sku_name].copy()
    # 当前商品全部总工单（占比分母）
    total_sku_all_order = filter_sku_shop["退货工单数量"].sum()

    # 3、重命名字段，直接使用已聚合好的真实工单、金额、件数
    sku_shop_table = filter_sku_shop.rename(columns={
        "退货工单数量": "该店铺工单数量",
        "退款总金额RMB": "退款总金额RMB",
        "退货总件数": "退货总件数"
    })
    # 计算占比
    sku_shop_table["该店铺工单占此商品总工单比例"] = (sku_shop_table[
                                                          "该店铺工单数量"] / total_sku_all_order * 100).round(
        2).astype(str) + "%"

    # 核心：按该品类下店铺工单数【从高到低】强制排序
    sku_shop_table = sku_shop_table.sort_values(by="该店铺工单数量", ascending=False).reset_index(drop=True)

    # 只展示需要的列
    show_cols = ["店铺", "该店铺工单数量", "退款总金额RMB", "退货总件数", "该店铺工单占此商品总工单比例"]
    st.dataframe(sku_shop_table[show_cols], use_container_width=True)
    # =============================================================================

    st.divider()
    # 原始明细表格（保持你最初版本，不分页，原样）
    st.subheader("退款订单明细")
    st.dataframe(df_data, use_container_width=True, height=400)

    # 导出Excel功能
    def export_excel():
        output = pd.ExcelWriter("退款数据导出.xlsx", engine="openpyxl")
        df_data.to_excel(output, sheet_name="明细数据", index=False)
        shop_summary.to_excel(output, sheet_name="店铺汇总", index=False)
        sku_summary_full.to_excel(output, sheet_name="商品退货排行", index=False)
        output.close()
        with open("退款数据导出.xlsx", "rb") as f:
            return f.read()

    excel_bytes = export_excel()
    st.download_button(
        label="导出全部筛选数据Excel",
        data=excel_bytes,
        file_name="Ozon退款数据导出.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ---------------------- 页面路由控制 ----------------------
if "user" not in st.session_state:
    login_page()
else:
    dashboard_main()