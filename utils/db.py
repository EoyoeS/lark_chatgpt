import os
import sqlite3
from threading import RLock

from config import DB_PATH

from utils.log import yellow

db_locks = {}

# 初始化数据库（删库跑路）
def init_history():
    if os.path.isfile(DB_PATH):
        os.remove(DB_PATH)
        print(yellow('database dropped'))


# 获取表锁
def history_lock(chat_id):
    if chat_id not in db_locks:
        db_locks[chat_id] = RLock()
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(
            f'create table {chat_id} (question text, answer text, total_size integer)'
        )
        con.commit()
        con.close()
    return db_locks[chat_id]


# 删除数据库中的历史记录（表）
def drop_history(chat_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(f'drop table if exists {chat_id}')
    con.commit()
    con.close()
    db_locks.pop(chat_id, None)


# 将新的对话插入数据库
def insert_history(chat_id, question, answer, total_size):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        f'insert into {chat_id} values (?, ?, ?)',
        (question, answer, total_size),
    )
    con.commit()
    con.close()


# # 从数据库中删除前n条历史记录
# def del_history(db_path, chat_id, num):
#     con = sqlite3.connect(db_path)
#     cur = con.cursor()
#     cur.execute(
#         f'delete from {chat_id} where rowid in (select rowid from {chat_id} limit ?)',
#         (num,),
#     )
#     con.commit()
#     con.close()


# 从数据库中获取历史记录
def get_history(chat_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(f'select * from {chat_id}')
    history = cur.fetchall()
    con.commit()
    con.close()
    return history
