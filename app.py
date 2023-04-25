import os
from concurrent.futures import ThreadPoolExecutor
import json
from pprint import pprint

from flask import Flask, request, jsonify, abort
import requests
import openai


APP_ID = os.environ.get('APP_ID')
APP_SECRET = os.environ.get('APP_SECRET')
VERIFICATION_TOKEN = os.environ.get('VERIFICATION_TOKEN')
TOKEN_URL = 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal'
TENANT_ACCESS_TOKEN = ''

openai.api_key = os.environ.get('OPENAI_API_KEY')
openai.proxy = '[::]:7890'
pool = ThreadPoolExecutor(3)
app = Flask(__name__)


def chat_gpt(content):
    # 调用 ChatGPT 接口
    try:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "user",
                    "content": content,
                }
            ],
        )
    except openai.error.RateLimitError:
        return '手速太快了，休息一下吧'
    return completion.choices[0].message.content


def handle_message(message):
    global TENANT_ACCESS_TOKEN
    url = (
        f'https://open.feishu.cn/open-apis/im/v1/messages/{message["message_id"]}/reply'
    )
    data = {
        'content': json.dumps({'text': chat_gpt(message['content'])}),
        # 'content': message['content'],
        'msg_type': 'text',
    }

    def reply():
        # TODO: 这里没有上下文，群聊信息可能会用到不同成员
        headers = {
            'Authorization': 'Bearer ' + TENANT_ACCESS_TOKEN,
        }
        with requests.post(url, data, headers=headers) as resp:
            # print(resp.status_code)
            return resp.status_code

    if reply() != 200:
        # 获取新的 token
        with requests.post(
            TOKEN_URL, data={'app_id': APP_ID, 'app_secret': APP_SECRET}
        ) as resp:
            # print(resp.json())
            TENANT_ACCESS_TOKEN = resp.json()['tenant_access_token']
        reply()


@app.route('/api', methods=['POST'])
def api():
    request_data = request.get_json()
    # pprint(request_data)
    headers = request_data['header']
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
