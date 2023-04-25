from concurrent.futures import ThreadPoolExecutor
import json
from pprint import pprint, pformat
import sqlite3
from itertools import chain
from threading import RLock

from flask import Flask, request, jsonify, abort
import requests
import openai

from config import config


APP_ID = config['app_id']
APP_SECRET = config['app_secret']
VERIFICATION_TOKEN = config['verification_token']
TOKEN_URL = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
TENANT_ACCESS_TOKEN = ''
REPLY_URL = 'https://open.feishu.cn/open-apis/im/v1/messages/{}/reply'
DB_PATH = 'example.db'  # 相对路径

openai.api_key = config['openai_api_key']
openai.proxy = '[::]:7890'
pool = ThreadPoolExecutor(3)
app = Flask(__name__)
db_lock = RLock()


def color(code: int):
    def warpper(text):
        return '\033[{}m{}\033[0m'.format(code, text)
    return warpper

red = color(31)
green = color(32)
yellow = color(33)
blue = color(34)


def chat_gpt(content, history=None) -> str:
    # 调用 ChatGPT 接口
    if history is not None:
        questions = ({'role': 'user', 'content': conv[0]} for conv in history)
        answers = ({'role': 'assistant', 'content': conv[1]} for conv in history)
        messages = list(chain.from_iterable(zip(questions, answers)))
    else:
        messages = []
    messages += [{'role': 'user', 'content': content}]
    pprint(f'{history=}')
    print(red(messages))
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
    except openai.error.RateLimitError:
        return '手速太快了，休息一下吧'
    print(green(pformat(completion)))
    return completion.choices[0].message.content


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
    # token失效或过期，重新获取
    print(yellow('token expired, renewing...'))
    with requests.post(TOKEN_URL, data={'app_id': APP_ID, 'app_secret': APP_SECRET}) as r:
        TENANT_ACCESS_TOKEN = r.json()['tenant_access_token']
    headers['Authorization'] = 'Bearer ' + TENANT_ACCESS_TOKEN
    with requests.post(url, data=data, headers=headers) as r:
        if r.status_code == 200:
            # 重新获取token，成功回复消息
            print(green('renewed'))
        else:
            # 重新获取token失败
            print(red('renew failed'))
    

# 替换掉@信息，保留用户的问题
def get_qustion(message) -> str:
    question = json.loads(message['content'])['text']
    mentions = message.get('mentions', [])
    for mention in mentions:
        question = question.replace(mention['key'], mention['name'])
    return question


# 从数据库中获取历史记录
def get_history(chat_id):
    with db_lock:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(f'create table if not exists {chat_id} (question text, answer text)')
        cur.execute(f'select * from {chat_id}')
        history = cur.fetchall()
        con.commit()
        con.close()
    return history


# 删除数据库中的历史记录（表）
def delete_history(chat_id):
    with db_lock:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(f'drop table {chat_id}')
        con.commit()
        con.close()


# 将新的对话插入数据库
def insert_new_convestion(chat_id, question, answer):
    with db_lock:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(f'insert into {chat_id} values (?, ?)', (question, answer))
        con.commit()
        con.close()
        

# 处理消息
def handle_message(message):
    chat_id, message_id = message['chat_id'], message['message_id']
    question = get_qustion(message)
    if '/clear' in question:
        delete_history(chat_id)
        reply(message_id, '上下文已清除')
    else:
        answer = chat_gpt(question, get_history(chat_id))
        insert_new_convestion(chat_id, question, answer)
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
    # handle_message(message)
    pool.submit(handle_message, message)  # TODO: 由于openai的每分钟3条信息的限制，需要用其他方法改进
    # ? 这里为了防止chat-GPT太慢了，导致超时，所以咋暂时直接返回ok，https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-/encrypt-key-encryption-configuration-case
    # ? 可以尝试根据event_id来先把回答存下来，再次遇到event_id时直接回答，但可能导致上下文错乱
    return jsonify({'msg': 'ok'})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8713, debug=True)
