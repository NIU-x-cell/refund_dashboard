import pandas as pd
import numpy as np
from config import get_db_conn


def import_refund_data(batch_size=1000):
    # 读取Excel
    df = pd.read_excel("6.22-7.07（ozon））_NEW.xlsx")
    all_cols = df.columns.tolist()
    print("Excel全部列名：", all_cols)
    print(f"待导入总行数：{len(df)}")

    # 批量预处理全部数据（向量化处理，速度远高于单行循环）
    df = df.astype(object)
    # 表格内 "--" 统一替换为 None
    df = df.replace("--", None)
    # 所有空值NaN替换为 None，数据库存NULL
    df = df.where(pd.notna(df), None)

    # 拼接插入SQL
    col_sql = ",".join([f"`{c}`" for c in all_cols])
    place_sql = ",".join(["%s"] * len(all_cols))
    insert_sql = f"INSERT INTO ozon_ref ({col_sql}) VALUES ({place_sql})"

    # 建立数据库连接
    conn = get_db_conn()
    cur = conn.cursor()

    # 转为元组列表用于批量插入
    data_tuples = [tuple(row) for _, row in df.iterrows()]
    total = len(data_tuples)
    success_count = 0

    try:
        # 分片批量提交，减少网络交互，大幅提速
        for start in range(0, total, batch_size):
            batch_data = data_tuples[start:start + batch_size]
            cur.executemany(insert_sql, batch_data)
            conn.commit()
            success_count += len(batch_data)
            print(f"导入进度：{success_count}/{total} 条")
        print(f"✅ 全部导入完成，总计{success_count}条退款数据")
    except Exception as err:
        # 出错回滚，避免半批脏数据入库
        conn.rollback()
        print(f"❌ 导入失败，已回滚全部操作，错误详情：{err}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    import_refund_data(batch_size=1000)