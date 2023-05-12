import json
from pprint import pprint
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request, jsonify, abort

from config import (
    APP_ID,
    VERIFICATION_TOKEN,
    openai_api_keys,
)
from utils.log import logger
from utils.db import init_history
from utils.robot import handle_message, think

app = Flask(__name__)


@app.route('/api', methods=['POST'])
def api():
    request_data = request.get_json()
    pprint(request_data)
    headers = request_data['header']
    # 校验verification token和app_id
    if headers.get('token') != VERIFICATION_TOKEN or headers.get('app_id') != APP_ID:
        abort(403)
    message = request_data['event']['message']
    handle_message(message)
    return jsonify({'msg': 'ok'})


@app.after_request
def after_request(response):
    logger.info(
        json.dumps(
            {
                'ip': request.headers.get('X-Real-IP', request.remote_addr),
                'method': request.method,
                'path': request.path,
                'data': request.get_json(),
                'status_code': response.status_code,
            },
            ensure_ascii=False,
        )
    )
    return response


if __name__ == '__main__':
    init_history()
    # 启动多个线程，每个线程使用一个api_key
    chatgpt_pool = ThreadPoolExecutor()
    for api_key in openai_api_keys:
        chatgpt_pool.submit(think, api_key)
    app.run(host='0.0.0.0', port=8713)
