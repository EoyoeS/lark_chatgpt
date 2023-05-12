# 发送消息，将回复交给Guard
from dataclasses import dataclass
from pprint import pformat
import re
import time

import requests

from utils.log import red, green, logger
from config import OPENAI_PROXY

CHAT_GPT_URL = 'https://api.openai.com/v1/chat/completions'


@dataclass
class GuardResponse:
    __slots__ = ('ans', 'wait_point', 'total_size')
    ans: str
    wait_point: float
    total_size: int


@dataclass
class ChatResponse:
    __slots__ = ('ans', 'wait_time', 'total_size', 'status')
    ans: str
    total_size: int
    status: int
    wait_time: float


def str_to_second(time: str):
    if time.endswith('ms'):
        return float(time[:-2]) / 1000
    elif time.endswith('s'):
        return float(time[:-1])
    else:
        return float(time)


def ask_chatgpt(api_key, messages):
    headers = {
        'Authorization': 'Bearer ' + api_key,
    }
    j = {
        "model": "gpt-3.5-turbo",
        "messages": messages,
    }
    try:
        with requests.post(
            CHAT_GPT_URL, json=j, headers=headers, proxies={'https': OPENAI_PROXY}
        ) as resp:
            data = resp.json()
            headers = resp.headers
            status = resp.status_code
    except Exception as e:
        print(red(e))
        logger.warning(e)
        return ChatResponse('error', 0, 500, 20.0)
    print(green(pformat(data)))
    print(green(pformat(dict(headers))))
    print(green(status))
    if (remain := int(headers['x-ratelimit-remaining-requests'])) > 0:
        wait_time = 0.0
    else:
        wait_time = str_to_second(headers['x-ratelimit-reset-requests']) - (
            20 * (2 - remain)
        )
    wait_time = max(wait_time, str_to_second(headers['x-ratelimit-reset-tokens']))
    if status == 200:
        return ChatResponse(
            data['choices'][0]['message']['content'],
            data['usage']['total_tokens'],
            status,
            wait_time,
        )
    patterm = r'your messages resulted in (\d+) tokens'
    total_size = int(re.search(patterm, data['error']['message']).group(1))
    return ChatResponse('too long', total_size, 400, wait_time)


# 处理问题和历史记录，依照chatGPT的回复生成答案，并返回
def to_gaurd(api_key, question, history):
    pre_total_size = history[-1][2] if history else 0
    messages = sum(
        (
            [{'role': 'user', 'content': q}, {'role': 'assistant', 'content': a}]
            for q, a, _ in history
        ),
        [],
    ) + [{'role': 'user', 'content': question}]
    resp = ask_chatgpt(api_key, messages)
    wait_point = time.time() + resp.wait_time
    if resp.status == 200:
        ans = resp.ans
        total_size = resp.total_size
    elif resp.status == 400:
        if resp.total_size - pre_total_size > 4097:
            ans = '输入太长了 (@_@;)'
        else:
            ans = '上下文太长了，我忘记了，你可以输入/clear清除上下文'
        total_size = -1
    elif resp.status == 500:
        ans = '出错了，我也不知道为什么 ¯\_(ツ)_/¯'
        total_size = -1
    return GuardResponse(ans, wait_point, total_size)
