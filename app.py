from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import requests

app = Flask(__name__)

# 讀取環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET  = os.environ.get("LINE_CHANNEL_SECRET")
PERPLEXITY_API_KEY   = os.environ.get("PERPLEXITY_API_KEY")

assert LINE_CHANNEL_ACCESS_TOKEN, "LINE_CHANNEL_ACCESS_TOKEN 未設定"
assert LINE_CHANNEL_SECRET, "LINE_CHANNEL_SECRET 未設定"
assert PERPLEXITY_API_KEY, "PERPLEXITY_API_KEY 未設定"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@app.route("/", methods=['GET'])
def index():
    return "LINE Bot + Perplexity 串接 OK！"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text
    source = event.source

    # 檢查是否為群組 & 是否被 tag
    is_group = hasattr(source, 'group_id') and source.group_id is not None

    # 指定 bot 名稱
    TAG_NAME = "@Dylan-Auto"

    should_reply = False
    if is_group:
        # 如果文字中有 @Dylan-Auto 就觸發
        if TAG_NAME in user_text:
            should_reply = True
    else:
        # 私訊模式永遠回應
        should_reply = True

    if not should_reply:
        return  # 群組不被 tag 就略過回應

    reply_text = get_perplexity_reply(user_text)
    if not reply_text:
        reply_text = "抱歉，AI 沒有回應，請稍後再試 🙇"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))

def get_perplexity_reply(user_input):
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "sonar-pro",  # 建議用官方最新支援模型
        "messages": [
            {"role": "system", "content": "你是 LINE 機器人，用親切且精簡的語氣回答，繁體中文。"},
            {"role": "user", "content": user_input}
        ]
    }
    try:
        resp = requests.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        print("Perplexity API 錯誤：", e)
        return None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

