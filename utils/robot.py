# 根据message_id，返回answer
import json
from queue import Queue
import time
import requests
from utils.chatgpt import to_gaurd
from utils.db import (
    history_lock,
    get_history,
    drop_history,
    insert_history,
)
from utils.log import green, red, yellow, logger
from config import APP_ID, APP_SECRET
from traceback import format_exc

REPLY_URL = 'https://open.feishu.cn/open-apis/im/v1/messages/{}/reply'
TOKEN_URL = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
tenant_access_token = ''
message_queue = Queue(maxsize=1)


# 替换掉@信息，保留用户的问题
def get_qustion(message) -> str:
    question = json.loads(message['content'])['text']
    mentions = message.get('mentions', [])
    for mention in mentions:
        question = question.replace(mention['key'], mention['name'], 1)
    return question


def reply(message_id, answer):
    # 机器人回复消息需要TENANT_ACCESS_TOKEN
    global tenant_access_token
    url = REPLY_URL.format(message_id)
    headers = {
        'Authorization': 'Bearer ' + tenant_access_token,
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
        tenant_access_token = r.json()['tenant_access_token']
    headers['Authorization'] = 'Bearer ' + tenant_access_token
    with requests.post(url, data=data, headers=headers) as r:
        if r.status_code == 200:
            # 重新获取token，成功回复消息
            print(green('renewed'))
        else:
            # 重新获取token失败
            print(red('renew failed'))


# 处理消息
def handle_message(message):
    chat_id, message_id = message['chat_id'], message['message_id']
    question = get_qustion(message)
    if '@_all' not in question:
        if message_queue.full():
            reply(message_id, '正在思考人生，请等一下 ๑ᵒᯅᵒ๑')
        else:
            message_queue.put((chat_id, message_id, question))


def think(api_key: str):
    # 一个线程处理一个问题
    wait_point = 0.0
    while True:
        try:
            chat_id, message_id, question = message_queue.get()
            with history_lock(chat_id):
                if '/clear' in question:
                    drop_history(chat_id)
                    reply(message_id, '上下文已清除 ❛‿˂̵✧')
                    continue
                # 由于api限制，需要控制请求速度
                time.sleep(max(wait_point - time.time(), 0))
                resp = to_gaurd(api_key, question, get_history(chat_id))
                wait_point = resp.wait_point
                if resp.total_size != -1:
                    insert_history(
                        chat_id,
                        question,
                        resp.ans,
                        resp.total_size,
                    )
                reply(message_id, resp.ans)
        except Exception as e:
            print(red(e))
            logger.error(format_exc())
