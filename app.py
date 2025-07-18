from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import os
import json

app = Flask(__name__)

# 環境變數或直接填寫金鑰
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 核心：只對被@Tag的訊息做回應
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # 檢查是否為群組訊息
    if event.source.type in ['group', 'room']:
        msg = event.message
        # 新版 line-bot-sdk 部分版本message會自動帶 mention
        mention_obj = getattr(msg, 'mention', None)
        if mention_obj and hasattr(mention_obj, 'mentionees'):
            for m in mention_obj.mentionees:
                if hasattr(m, 'is_self') and m.is_self:
                    # 被 Tag 才回應
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=f'被 @ 叫到，請問有什麼需要幫忙？')
                    )
                    return
        # 如果沒被tag就略過不回應
        return
    else:
        # 私聊可直接回（可修改成你要的規則）
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text='私聊自動回覆內容')
        )

