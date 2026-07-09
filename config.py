import pymysql
import ssl
import streamlit as st

def get_db_conn():
    cfg = st.secrets["db"]
    ssl_ctx = ssl.create_default_context(cafile="/etc/ssl/certs/ca-certificates.crt")
    conn = pymysql.connect(
        host=cfg["host"],
        port=int(cfg["port"]),
        user=cfg["user"],
        password=cfg["password"],
        database=cfg["database"],
        charset="utf8mb4",
        connect_timeout=15,
        ssl=ssl_ctx
    )
    return conn