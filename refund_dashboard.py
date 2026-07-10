import streamlit as st
import pandas as pd
import pymysql
import plotly.express as px
from config import get_db_conn
from datetime import timedelta
from io import BytesIO

# ---------------------- 页面基础配置 ----------------------
st.set_page_config(page_title="Ozon退款数据看板", layout="wide")
st.title("Ozon店铺退款数据管理看板")


# ---------------------- 数据库查询通用函数（缓存优化，新增params兼容防SQL注入） ----------------------
@st.cache_data(ttl=600)
def query_sql(sql, params=None):
    conn = get_db_conn()
    if params:
        df = pd.read_sql(sql, conn, params=params)
    else:
        df = pd.read_sql(sql, conn)
    conn.close()
    return df


# ---------------------- 登录模块（参数化SQL，防止账号带引号崩溃） ----------------------
def login_page():
    st.subheader("账号登录")
    username = st.text_input("登录账号")
    password = st.text_input("登录密码", type="password")
    login_btn = st.button("登录")
    if login_btn:
        user_sql = "SELECT * FROM sys_user WHERE username=%s AND password=%s"
        user_df = query_sql(user_sql, params=[username, password])
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


# ---------------------- 根据选中部门获取对应店铺列表（参数化防SQL报错） ----------------------
def get_shop_by_dept(dept_list):
    holders = ",".join(["%s"] * len(dept_list))
    shop_df = query_sql(f"SELECT DISTINCT `店铺` FROM shop_dept WHERE dept_code IN ({holders})", params=dept_list)
    return shop_df["店铺"].tolist()


# ---------------------- 数据筛选与看板主体（完全保留原版线性逻辑，无多余分支） ----------------------
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

        # 部门选择逻辑不变
        if is_admin:
            select_dept = st.multiselect("选择部门", options=all_depts, default=all_depts)
        else:
            st.text_input("当前所属部门", value=self_dept, disabled=True)
            select_dept = [self_dept]
        st.divider()

        # 退款状态筛选完全不动
        status_list = query_sql("SELECT DISTINCT `创建退款时订单状态` FROM ozon_ref")["创建退款时订单状态"].tolist()
        select_status = st.multiselect("退款状态", options=status_list, default=status_list)

        # 日期逻辑原版保留
        date_min_df = query_sql("SELECT MIN(`退款时间`) AS min_date, MAX(`退款时间`) AS max_date FROM ozon_ref")
        min_db_date = date_min_df.iloc[0]["min_date"]
        max_db_date = date_min_df.iloc[0]["max_date"]

        default_end = max_db_date
        default_start = default_end - timedelta(days=15)
        if default_start < min_db_date:
            default_start = min_db_date

        start_date, end_date = st.date_input(
            "退款时间区间",
            value=(default_start.date(), default_end.date()),
            min_value=min_db_date.date(),
            max_value=max_db_date.date()
        )

    # ========= 修复：JOIN两张表匹配部门，解决店铺名称不一致查不到数据 =========
    status_holders = ",".join(["%s"] * len(select_status))
    filter_sql = f"""
    SELECT DISTINCT t.* FROM ozon_ref t
    INNER JOIN shop_de s ON TRIM(t.店铺) = TRIM(s.店铺)
    WHERE s.dept_code IN ({','.join(['%s']*len(select_dept))})
      AND t.`创建退款时订单状态` IN ({status_holders})
      AND DATE(t.`退款时间`) BETWEEN %s AND %s
    """
    params_main = select_dept + select_status + [start_date, end_date]
    df_data = query_sql(filter_sql, params=params_main)

    # 上期同期查询同步改成JOIN写法
    days_range = (end_date - start_date).days
    last_start = start_date - timedelta(days=days_range + 1)
    last_end = start_date - timedelta(days=1)
    last_sql = f"""
    SELECT DISTINCT t.* FROM ozon_ref t
    INNER JOIN shop_dept s ON TRIM(t.店铺) = TRIM(s.店铺)
    WHERE s.dept_code IN ({','.join(['%s']*len(select_dept))})
      AND t.`创建退款时订单状态` IN ({status_holders})
      AND DATE(t.`退款时间`) BETWEEN %s AND %s
    """
    params_last = select_dept + select_status + [last_start, last_end]
    df_last = query_sql(last_sql, params=params_last)

    # 指标计算原版不动
    curr_order = len(df_data)
    curr_rmb = df_data["退款金额RMB"].sum()
    curr_qty = df_data["退款数量(仅支持2021年12月22日之后创建的退款单)"].sum()

    last_order = len(df_last)
    last_rmb = df_last["退款金额RMB"].sum() if len(df_last) > 0 else 0
    last_qty = df_last["退款数量(仅支持2021年12月22日之后创建的退款单)"].sum() if len(df_last) > 0 else 0

    # 环比函数
    def get_growth(curr, last):
        if last == 0:
            return "——"
        rate = (curr - last) / last * 100
        return f"{rate:.2f}%"

    order_grow = get_growth(curr_order, last_order)
    rmb_grow = get_growth(curr_rmb, last_rmb)
    qty_grow = get_growth(curr_qty, last_qty)

    # 指标卡片
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

    # ========= 修复趋势图：增加日期转换兜底，防止dt报错页面崩溃 =========
    st.divider()
    trend_title = "全部门每日退货件数趋势" if is_admin else f"{self_dept} 部门每日退货件数趋势"
    st.subheader(trend_title)
    if not df_data.empty:
        df_data["tmp_refund_dt"] = pd.to_datetime(df_data["退款时间"], errors="coerce")
        valid_df = df_data[df_data["tmp_refund_dt"].notna()]
        if not valid_df.empty:
            day_trend = valid_df.groupby(valid_df["tmp_refund_dt"].dt.date)[
                "退款数量(仅支持2021年12月22日之后创建的退款单)"].sum().reset_index()
            day_trend.columns = ["日期", "当日退货件数"]
            fig_line = px.line(day_trend, x="日期", y="当日退货件数", markers=True, title="每日退货件数走势", labels={"当日退货件数": "退货总件数"})
            st.plotly_chart(fig_line, width="stretch")
        else:
            st.info("当前筛选无有效日期数据，无法生成趋势图")
    else:
        st.info("暂无匹配退款数据")

    st.divider()
    # 店铺汇总表格
    st.subheader("各店铺退款汇总")
    shop_summary = df_data.groupby("店铺").agg(
        退款工单总数=("订单号", "count"),
        退款总金额RMB=("退款金额RMB", "sum"),
        退款总件数=("退款数量(仅支持2021年12月22日之后创建的退款单)","sum")
    ).reset_index().sort_values(by="退款工单总数", ascending=False).reset_index(drop=True)
    st.dataframe(shop_summary, width="stretch")

    # 饼图
    st.divider()
    st.subheader("各商品退货件数占比分布")
    sku_summary = df_data.groupby(["店铺", "sku中文名"]).agg(
        退货工单数量=("订单号", "count"),
        退货总件数=("退款数量(仅支持2021年12月22日之后创建的退款单)", "sum"),
        退款总金额RMB=("退款金额RMB", "sum")
    ).reset_index().sort_values(by="退货总件数", ascending=False).reset_index(drop=True)
    top15_pie = sku_summary.head(15)
    fig_pie = px.pie(top15_pie, values="退货总件数", names="sku中文名", title="筛选区间TOP15商品退货件数占比", hole=0.1)
    st.plotly_chart(fig_pie, width="stretch")

    # SKU排行
    st.divider()
    st.subheader("各商品SKU退货排行（按退货件数倒序）")
    sku_summary_full = df_data.groupby(["店铺", "sku中文名", "SKU"]).agg(
        退货工单数量=("订单号", "count"),
        退货总件数=("退款数量(仅支持2021年12月22日之后创建的退款单)", "sum"),
        退款总金额RMB=("退款金额RMB", "sum")
    ).reset_index().sort_values(by="退货总件数", ascending=False).reset_index(drop=True)
    st.dataframe(sku_summary_full, width="stretch", height=400)
    top1_sku = sku_summary.iloc[0]
    st.success(f"🔥 当前筛选区间退货量最高商品：【{top1_sku['sku中文名']}】，所属店铺：{top1_sku['店铺']}，累计退货件数：{int(top1_sku['退货总件数'])}")

    # 单品查询
    st.divider()
    st.subheader("单品维度分店铺明细查询")
    sku_opt_df = sku_summary.groupby("sku中文名")["退货工单数量"].sum().reset_index().sort_values("退货工单数量", ascending=False).reset_index(drop=True)
    sku_opt_df["展示名称"] = sku_opt_df["sku中文名"] + " (" + sku_opt_df["退货工单数量"].astype(str) + ")"
    opt_list = sku_opt_df["展示名称"].tolist()
    select_sku_show = st.selectbox("选择商品品类", options=opt_list)
    select_sku_name = select_sku_show.split(" (")[0]

    filter_sku_shop = sku_summary[sku_summary["sku中文名"] == select_sku_name].copy()
    total_sku_all_order = filter_sku_shop["退货工单数量"].sum()
    sku_shop_table = filter_sku_shop.rename(columns={
        "退货工单数量": "该店铺工单数量",
        "退款总金额RMB": "退款总金额RMB",
        "退货总件数": "退货总件数"
    })
    sku_shop_table["该店铺工单占此商品总工单比例"] = (sku_shop_table["该店铺工单数量"] / total_sku_all_order * 100).round(2).astype(str) + "%"
    sku_shop_table = sku_shop_table.sort_values(by="该店铺工单数量", ascending=False).reset_index(drop=True)
    show_cols = ["店铺", "该店铺工单数量", "退款总金额RMB", "退货总件数", "该店铺工单占此商品总工单比例"]
    st.dataframe(sku_shop_table[show_cols], width="stretch")


    st.divider()
    # ========= 删除原始退款明细表格，不展示大数据表 =========

    # 导出Excel：内存方案，不生成本地文件，仅3张汇总表
    def export_excel():
        buf = BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as output:
            if not shop_summary.empty:
                shop_summary.to_excel(output, sheet_name="店铺汇总", index=False)
            if not sku_summary_full.empty:
                sku_summary_full.to_excel(output, sheet_name="商品退货排行", index=False)
            if not sku_shop_table.empty:
                sku_shop_table.to_excel(output, sheet_name="单品店铺明细", index=False)
        buf.seek(0)
        return buf.getvalue()

    excel_bytes = export_excel()
    st.download_button(
        label="导出汇总数据Excel",
        data=excel_bytes,
        file_name="Ozon退款汇总数据.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# 页面路由控制
if "user" not in st.session_state:
    login_page()
else:
    dashboard_main()
