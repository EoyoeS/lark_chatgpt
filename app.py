from collections import deque
from concurrent.futures import ThreadPoolExecutor
import json
from pprint import pprint, pformat
import sqlite3
from itertools import islice
from threading import RLock
from time import sleep, time
from queue import Queue
from traceback import format_exc
from typing import Deque
import os

from flask import Flask, request, jsonify, abort
import requests

from config import config


APP_ID = config['app_id']
APP_SECRET = config['app_secret']
VERIFICATION_TOKEN = config['verification_token']
TOKEN_URL = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
TENANT_ACCESS_TOKEN = ''
CHAT_GPT_URL = 'https://api.openai.com/v1/chat/completions'
REPLY_URL = 'https://open.feishu.cn/open-apis/im/v1/messages/{}/reply'

# 表相关
DB_PATH = 'example.db'  # 相对路径
Q_INDEX = 0
A_INDEX = 1
TOKEN_INDEX = 2
TOTAL_INDEX = 3

api_keys = config['openai_api_keys']
proxies = {'https': config['openai_proxy']}
handle_pool = ThreadPoolExecutor()
chatgpt_pool = ThreadPoolExecutor(3 * len(api_keys))
app = Flask(__name__)
message_queue = Queue()
db_locks = {}


def color(code: int):
    def warpper(text):
        return '\033[{}m{}\033[0m'.format(code, text)

    return warpper


red = color(31)
green = color(32)
yellow = color(33)
blue = color(34)


# 从数据库中删除前n条历史记录
def del_history(chat_id, num):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        f'delete from {chat_id} where rowid in (select rowid from {chat_id} limit ?)',
        (num,),
    )
    con.commit()
    con.close()


# 从数据库中获取历史记录
def get_history(chat_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(f'select * from {chat_id}')
    history = cur.fetchall()
    con.commit()
    con.close()
    return history


# 删除数据库中的历史记录（表）
def drop_history(chat_id):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(f'drop table if exists {chat_id}')
    con.commit()
    con.close()
    db_locks.pop(chat_id, None)


# 获取表锁
def history_lock(chat_id):
    if chat_id not in db_locks:
        db_locks[chat_id] = RLock()
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(
            f'create table {chat_id} (question text, answer text, token_size integer, total_size integer)'
        )
        con.commit()
        con.close()
    return db_locks[chat_id]


# 将新的对话插入数据库
def insert_history(chat_id, question, answer, token_size, total_size):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        f'insert into {chat_id} values (?, ?, ?, ?)',
        (question, answer, token_size, total_size),
    )
    con.commit()
    con.close()


def chat_gpt(messages: list, api_key: str) -> tuple:
    # 调用 ChatGPT 接口
    print(blue(messages))
    headers = {
        'Authorization': 'Bearer ' + api_key,
    }
    j = {
        "model": "gpt-3.5-turbo",
        "messages": messages,
    }
    try:
        with requests.post(CHAT_GPT_URL, json=j, headers=headers, proxies=proxies) as r:
            data = r.json()
            reset_time = float(r.headers['x-ratelimit-reset-requests'][:-1])
            status_code = r.status_code
            break_time = r.headers.get('x-ratelimit-reset-tokens', 0.0)
        if break_time.endswith('ms'):
            break_time = int(break_time[:-2]) / 1000
        elif break_time.endswith('s'):
            break_time = float(break_time[:-1])
        else:
            print(yellow('unknown break time'))
            break_time = 20.0
        print(green(pformat(data)))
        if status_code != 200:
            return None, 0, status_code, reset_time, break_time
        answer = data['choices'][0]['message']['content']
        total_size = data['usage']['total_tokens']
        pprint(r.status_code)
    except requests.exceptions.SSLError:
        answer, total_size = '好困，睡着了 (⌯꒪꒫꒪)੭', 0
        status_code, reset_time, break_time = 502, 0.0, 20.0
    return answer, total_size, status_code, reset_time, break_time


# 根据message_id，返回answer
def reply(message_id, answer):
    # 机器人回复消息需要TENANT_ACCESS_TOKEN
    global TENANT_ACCESS_TOKEN
    url = REPLY_URL.format(message_id)
    headers = {
        'Authorization': 'Bearer ' + TENANT_ACCESS_TOKEN,
    }
    data = {
        'content': json.dumps({'text': answer}),
        'msg_type': 'text',
    }
    with requests.post(url, data, headers=headers) as r:
        if r.status_code == 200:
            return 200
    # TODO: token失效或过期（这里可以提前检测），重新获取
    print(yellow('token expired, renewing...'))
    with requests.post(
        TOKEN_URL, data={'app_id': APP_ID, 'app_secret': APP_SECRET}
    ) as r:
        TENANT_ACCESS_TOKEN = r.json()['tenant_access_token']
    headers['Authorization'] = 'Bearer ' + TENANT_ACCESS_TOKEN
    with requests.post(url, data=data, headers=headers) as r:
        if r.status_code == 200:
            # 重新获取token，成功回复消息
            print(green('renewed'))
        else:
            # 重新获取token失败
            print(red('renew failed'))


def answer_from_chatgpt(
    question, chat_id, history: list, api_key: str, reset_times: list
):
    # 设历史记录中第num条到最后一条的token总数是小于等于4097的，求num的最小值
    num = 0
    pre_total_size = history[-1][TOTAL_INDEX] if history else 0
    while pre_total_size > 4097:
        pre_total_size -= history[num][TOKEN_INDEX]
        num += 1
    it = islice(history, num, None)
    messages = sum(
        (
            [{'role': 'user', 'content': q}, {'role': 'assistant', 'content': a}]
            for q, a, _, _ in it
        ),
        [],
    )
    messages += [{'role': 'user', 'content': question}]
    while True:
        t = max(max(reset_times[0].popleft(), reset_times[1]) - time(), 0.0)
        print(yellow(f'waiting {t} seconds...'))
        sleep(t)
        # 得到chatgpt的回复
        answer, total_size, status_code, reset_time, break_time = chat_gpt(
            messages, api_key
        )
        reset_times[0].append(time() + reset_time)
        reset_times[1] = time() + break_time
        if status_code == 200:
            break
        # TODO: 受到taken限制，openai会返回发送的总token数，可以尝试从这方面修改
        if status_code == 400:
            if len(messages) == 1:
                # 新消息太长了
                return '输入太长了 (@_@;)'  # 新消息太长了要丢弃，不能影响历史记录
            print(yellow('popping...'))
            messages.pop(0)
            messages.pop(0)
            pre_total_size -= history[num][TOKEN_INDEX]
            num += 1
        if status_code == 502:
            return answer
    token_size = total_size - pre_total_size
    del_history(chat_id, num)  # 删除前num条历史记录
    insert_history(chat_id, question, answer, token_size, total_size)
    return answer


# 替换掉@信息，保留用户的问题
def get_qustion(message) -> str:
    question = json.loads(message['content'])['text']
    mentions = message.get('mentions', [])
    for mention in mentions:
        question = question.replace(mention['key'], mention['name'], 1)
    return question


# 处理消息
def handle_message(message):
    chat_id, message_id = message['chat_id'], message['message_id']
    with history_lock(chat_id):
        question = get_qustion(message)
        if '@_all' not in question:
            message_queue.put((question, message_id, chat_id))
            sleep(0.1)
            if not message_queue.empty():
                reply(message_id, '正在思考中，请等一下 ๑ᵒᯅᵒ๑')


# 一个api key一个线程
def chatgpt_doing(api_key: str):
    reset_times = [deque([0, 0, 0]), 0]
    while True:
        question, message_id, chat_id = message_queue.get()
        if '/clear' in question:
            drop_history(chat_id)
            db_locks.pop(chat_id, None)
            answer = '上下文已清除 ❛‿˂̵✧'
        else:
            try:
                answer = answer_from_chatgpt(
                    question,
                    chat_id,
                    get_history(chat_id),
                    api_key,
                    reset_times,
                )
            except Exception as e:
                with open('error.log', 'a') as f:
                    f.write(format_exc() + '\n')
                print(red(format_exc()))
                answer = '出错了，我也不知道为什么 ¯\_(ツ)_/¯'
        reply(message_id, answer)


@app.route('/api', methods=['POST'])
def api():
    request_data = request.get_json()
    pprint(request_data)
    headers = request_data['header']
    # 校验verification token和app_id
    if headers.get('token') != VERIFICATION_TOKEN or headers.get('app_id') != APP_ID:
        abort(403)
    message = request_data['event']['message']
    handle_pool.submit(handle_message, message)
    return jsonify({'msg': 'ok'})


if __name__ == '__main__':
    # 删库（跑路）
    if os.path.isfile(DB_PATH):
        os.remove(DB_PATH)
        print(yellow('database dropped'))
    # 一个api key有3个线程
    for api_key in api_keys:
        chatgpt_pool.submit(chatgpt_doing, api_key)
    app.run(host='0.0.0.0', port=8713)
