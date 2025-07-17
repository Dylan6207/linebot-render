from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
import os

app = Flask(__name__)

# === 記得改成你自己的 ===
CHANNEL_ACCESS_TOKEN = os.environ.get("c7ITPvO3FIsT2l89ICa7qBQrJlraMjWAP9x+8+5QppKQR4+suDSCfGENaewZ1/pirwZFLOSwxEFXW2jjEcVosABZScRQ3ukmE4QgkWMtc7VLya84wn0q7NURMNKyIRCZfMsK7aUh34mYrjdsAAgP4gdB04t89/1O/w1cDnyilFU=")
CHANNEL_SECRET = os.environ.get("88e7b34c82814b602556160a16d93c6b")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

@app.route("/", methods=['GET'])
def index():
    return "LINE Bot Render 部署成功！"

@app.route("/webhook", methods=['POST'])
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
    reply_text = f"你剛剛說：{user_text}"
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
