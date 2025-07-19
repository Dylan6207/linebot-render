import os
import base64
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import (MessageEvent, TextMessage, TextSendMessage, ImageMessage)
from linebot.exceptions import InvalidSignatureError
import re

app = Flask(__name__)

# ====== 環境變數設置區 ======
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
BOT_TAG = "@Dylan-Auto"  # LINE群組內呼叫機器人時使用的顯示名稱

assert LINE_CHANNEL_ACCESS_TOKEN, "LINE_Channel access token 未設定"
assert LINE_CHANNEL_SECRET, "Channel secret 未設定"
assert PERPLEXITY_API_KEY, "Perplexity API key 未設定"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== 記錄每位用戶是否正在啟動圖片分析，建議正式環境時用 Redis 或 DB ======
user_image_permission = {}

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

# ====== 工具：判斷群組內是否需回覆（需要被tag到才理會訊息） ======
def should_reply_in_group(event, bot_tag):
    # 若是群組才需要檢查tag；私訊一律回覆
    if getattr(event.source, "group_id", None):
        return bot_tag in getattr(event.message, "text", "")
    return True

# ====== 處理文字訊息：引導圖片服務、AI 聊天，一律清楚回覆 ======
# 只要文字中有「圖」即可啟動圖片分析
def is_request_image_mode(text):
    return "圖" in text
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    if not should_reply_in_group(event, BOT_TAG):
        return
    user_id = event.source.user_id
    text = event.message.text.replace(BOT_TAG, "").strip().lower()

   # Step 1：用戶訊息內含「圖」字皆視為啟動圖片分析
    if is_request_image_mode(text):
        user_image_permission[user_id] = True
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請傳送您想分析的圖片。")
        )
        return

    # Step 2：若啟動傳圖模式卻又輸入文字，則取消圖片收件
    if user_image_permission.get(user_id, False):
        user_image_permission[user_id] = False
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="已取消圖片分析服務。如需再次分析請包含『圖』字。")
        )
        return

    # Step 3：一般 Perplexity 聊天模式
    reply = get_perplexity_reply(text)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply or "抱歉，AI 沒有回應，請稍後再試 🙇")
    )

# ====== 處理圖片訊息：只在傳圖模式啟動時才處理圖片分析 ======
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    if not should_reply_in_group(event, BOT_TAG):
        return
    user_id = event.source.user_id

    # 僅允許先前輸入「傳圖」後，再傳圖片進行AI辨識
    if user_image_permission.get(user_id, False):
        message_id = event.message.id
        img_response = line_bot_api.get_message_content(message_id)
        binary = b"".join(chunk for chunk in img_response.iter_content())
        img_base64 = base64.b64encode(binary).decode("utf-8")
        mime = "image/jpeg"
        payload = {
            "model": "sonar-pro",
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": "請分析這張圖片"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_base64}"}}
                ]
            }]
        }
        reply = perplexity_api_call(payload)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply or "AI 看不懂這張圖，請換一張再試 🙇")
        )
        # 圖片分析後即關閉圖片模式，避免誤觸連刷圖片
        user_image_permission[user_id] = False
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="如需圖片分析，請先輸入『傳圖』以開始。")
        )

# ====== 一般對話：呼叫 Perplexity 模型回覆 ======
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

# ====== 呼叫 Perplexity API 的共用方法 ======
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
