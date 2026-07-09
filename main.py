import streamlit as st
from streamlit import Page
import pandas as pd
from config import get_db_conn

# 初始化会话存储登录信息
if "user_auth" not in st.session_state:
    st.session_state.user_auth = {
        is_login: False,
        username: "",
        role: "",
        dept_code: "",
        allow_shop_list: []
    }

# 登录页面
def login_page():
    st.title("Ozon退款退货数据分析看板【本地测试版】")
    username = st.text_input("登录账号")
    pwd = st.text_input("登录密码", type="password")
    if st.button("登录验证"):
        conn = get_db_conn()
        user_sql = f"SELECT * FROM sys_user WHERE username = '{username}'"
        user_df = pd.read_sql(user_sql, conn)
        if len(user_df) == 0:
            st.error("账号不存在！")
            return
        user_row = user_df.iloc[0]
        if user_row["password"] != pwd:
            st.error("密码错误！")
            return
        # 管理员无店铺限制，部门账号读取绑定店铺
        if user_row["role"] != "admin":
            shop_sql = f"SELECT `店铺` FROM shop_dept WHERE dept_code = '{user_row['dept_code']}'"
            shop_df = pd.read_sql(shop_sql, conn)
            shop_list = shop_df["店铺"].tolist()
        else:
            shop_list = []
        # 写入会话
        st.session_state.user_auth["is_login"] = True
        st.session_state.user_auth["username"] = username
        st.session_state.user_auth["role"] = user_row["role"]
        st.session_state.user_auth["dept_code"] = user_row["dept_code"]
        st.session_state.user_auth["allow_shop_list"] = shop_list
        st.rerun()

# 未登录拦截
if not st.session_state.user_auth["is_login"]:
    login_page()
    st.stop()

# 动态侧边栏菜单
page_list = [
    Page("pages/0_dept_analysis.py", title="部门退款数据分析", icon="📦")
]
# 管理员额外页面
if st.session_state.user_auth["role"] == "admin":
    page_list.append(Page("pages/admin_overview.py", title="全平台总数据", icon="📊"))

nav = st.navigation(page_list)
nav.run()