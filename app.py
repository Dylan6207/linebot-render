#images 會大幅增加 request tokens，請注意流量與費用
#LINE 群組或私訊出現圖片訊息時，event 物件 message.type 會是 "image"
#Perplexity 支援 image_url 格式，可直接丟 base64 圖片字串
#  base64 編碼 
import os
import base64
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import (MessageEvent, TextMessage, TextSendMessage,
                            ImageMessage)
from linebot.exceptions import InvalidSignatureError

app = Flask(__name__)

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
BOT_TAG = "@Dylan-Auto"  # 可自訂

assert LINE_CHANNEL_ACCESS_TOKEN, "LINE_Channel access token 未設定"
assert LINE_CHANNEL_SECRET, "Channel secret 未設定"
assert PERPLEXITY_API_KEY, "Perplexity API key 未設定"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@app.route("/", methods=['GET'])
def index():
    return "LINE Bot + Perplexity (多模態) OK!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

def should_reply_in_group(event, bot_tag):
    # 若私訊，直接回；若群組需被點名 tag
    if getattr(event.source, "group_id", None):
        return bot_tag in getattr(event.message, "text", "")
    return True

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    if not should_reply_in_group(event, BOT_TAG):
        return
    q = event.message.text.replace(BOT_TAG, "").strip()
    reply = get_perplexity_reply(q)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply or "抱歉，AI 沒有回應，請稍後再試 🙇")
    )

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if not should_reply_in_group(event, BOT_TAG):
        return
    # 下載圖片內容
    message_id = event.message.id
    img_response = line_bot_api.get_message_content(message_id)
    binary = b"".join(chunk for chunk in img_response.iter_content())
    img_base64 = base64.b64encode(binary).decode("utf-8")
    mime = "image/jpeg"  # LINE 除少數貼圖外一般都是 jpg

    # 用戶有無搭配訊息文字，如無則提供預設描述
    q = getattr(event.message, "text", "") or "請幫我描述這張照片"

    # 組合 payload 多模態
    payload = {
        "model": "sonar-pro",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": q},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{img_base64}"
                    }}
                ]
            }
        ]
    }
    reply = perplexity_api_call(payload)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply or "AI 看不懂這張圖，請換一張再試 🙇")
    )

def get_perplexity_reply(user_input):
    if not user_input.strip():
        user_input = "請用繁體中文介紹一下你自己"
    payload = {
        "model": "sonar-pro",
        "messages": [
            {"role": "system", "content": "你是 LINE 小幫手，繁體中文作答，語氣親切精簡。"},
            {"role": "user", "content": user_input}
        ]
    }
    return perplexity_api_call(payload)

def perplexity_api_call(payload):
    try:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json"
            },
            json=payload, timeout=25)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print("Perplexity API Error:", e)
        return None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run("0.0.0.0", port=port)
