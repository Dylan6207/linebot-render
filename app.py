from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
import os
import requests

# Flask 初始化
app = Flask(__name__)

# 環境變數設定
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET  = os.environ.get("LINE_CHANNEL_SECRET")
PERPLEXITY_API_KEY   = os.environ.get("PERPLEXITY_API_KEY")  # ⚠️ 建議也設定在 Render 的環境變數

# 檢查參數
assert CHANNEL_ACCESS_TOKEN, "CHANNEL_ACCESS_TOKEN 未設定"
assert LINE_CHANNEL_SECRET, "LINE_CHANNEL_SECRET 未設定"
assert PERPLEXITY_API_KEY, "PERPLEXITY_API_KEY 未設定"

# 初始化 LINE Bot
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


@app.route("/", methods=['GET'])
def index():
    return "LINE Bot + Perplexity 串接成功！"


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


# 使用者傳訊息 → 呼叫 Perplexity 回覆內容 → 回傳 LINE
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text
    reply_text = get_perplexity_reply(user_text)

    if reply_text:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="抱歉，AI 沒有回應，請稍後再試 🙇")
        )


# 呼叫 Perplexity API 的函數
def get_perplexity_reply(user_input):
    url = "https://api.perplexity.ai/chat/completions"
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "sonar-small-chat",  # 🚀 可改成 sonar-medium-chat / sonar-small-online 等
        "messages": [
            {"role": "system", "content": "你是 LINE 機器人，用精簡且友善的語氣回答問題。"},
            {"role": "user", "content": user_input}
        ]
    }
    response = requests.post(url, headers=headers, json=payload)
    print(response.status_code, response.text)  # 建議 log 下來排查
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data['choices'][0]['message']['content']
    except Exception as e:
        print("Perplexity API 錯誤：", e)
        return None


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
