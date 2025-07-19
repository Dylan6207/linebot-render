import os
import base64
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageMessage
)
from linebot.exceptions import InvalidSignatureError

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

# ====== 用於圖片分析權限記錄（建議正式用 Redis/DB）======
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

# ====== 工具：判斷群組內是否需回覆（需被@才回）======
def should_reply_in_group(event, bot_tag):
    if getattr(event.source, "group_id", None):
        return bot_tag in getattr(getattr(event, "message", {}), "text", "")
    return True

# ====== 輔助：BOT 加入群組後，任何人說出含「圖」字問題，群組內所有成員接下來只要傳圖都能被分析。 ======
def get_unique_user_key(event):
    # 群組模式下只用 group_id，保證 key 對得上
    if getattr(event.source, "group_id", None):
        return event.source.group_id
    return getattr(event.source, "user_id", "anonymous")

# ====== 功能：偵測是否啟動圖片模式（多關鍵字判斷）======
def is_request_image_mode(text):
    keywords = ["圖", "圖片", "照片", "分析圖", "看圖"]
    return any(k in text for k in keywords)

# ====== 處理文字訊息 匹配關鍵字進入圖片權限模式/一般對話 ======
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    if not should_reply_in_group(event, BOT_TAG):
        return
    user_key = get_unique_user_key(event)
    text = event.message.text.replace(BOT_TAG, "").strip().lower()

    if is_request_image_mode(text):
        user_image_permission[user_key] = True
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請傳送您想分析的圖片。")
        )
        return

    if user_image_permission.get(user_key, False):
        user_image_permission[user_key] = False
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="已取消圖片分析服務。如還需分析請再提到『圖』、『照片』等。")
        )
        return

    reply = get_perplexity_reply(text)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply or "抱歉，AI 沒有回應，請稍後再試 🙇")
    )

# ====== 處理圖片訊息 只允許開啟權限用戶分析圖片 ======
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_key = get_unique_user_key(event)
    print("DEBUG: user_key=", user_key)
    print("DEBUG: user_image_permission dict=", user_image_permission
    if not should_reply_in_group(event, BOT_TAG):
        return
    user_key = get_unique_user_key(event)

    if user_image_permission.get(user_key, False):
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
        user_image_permission[user_key] = False
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="如需圖片分析，請先在文字訊息中包含『圖』、『照片』等字眼告知我。")
        )

# ====== 一般對話呼叫 Perplexity API ======
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

# ====== Perplexity API 呼叫工具 ======
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
