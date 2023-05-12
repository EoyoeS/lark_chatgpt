## 配置

配置文件：config.py

- `APP_ID`：机器人ID，用于接口验证

- `APP_SECRET`：机器人密码

- `VERIFICATION_TOKEN`：机器人的Verification token，用于接口验证

- `openai_api_keys`：多个openai api key

- `OPENAI_PROXY`：代理（https）

- `DB_PATH`：sqlite文件路径（相对路径，每次启动会覆盖新建）

如：
```python
APP_ID = 'cli_xxxxxxxxxxxxxxxx'
APP_SECRET = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
VERIFICATION_TOKEN = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
openai_api_keys = [
    'sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
]
OPENAI_PROXY = '[::]:7890'

DB_PATH = 'example.db'  # 相对路径
```
## 注

首次在飞书建立接口时，需要验证challenge，自行验证