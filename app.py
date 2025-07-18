from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from linebot.exceptions import InvalidSignatureError
import os

app = Flask(__name__)

# === 記得改成你自己的 ===
#assert CHANNEL_ACCESS_TOKEN, "環境變數 CHANNEL_ACCESS_TOKEN 由Render 的環境變數託管"
#assert LINE_CHANNEL_SECRET, "環境變數 LINE_CHANNEL_SECRET 的環境變數託設定"
#with open("line_secret.json", "r") as f:
#    secret = json.load(f)
CHANNEL_ACCESS_TOKEN = os.environ.get("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")

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
