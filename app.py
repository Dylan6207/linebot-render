import os
import time
import base64
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageMessage
)
from linebot.exceptions import InvalidSignatureError

app = Flask(__name__)

# ====== 1. 環境及API設定 ======
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
BOT_TAG = "@Dylan-Auto"  # 在群組中@的顯示名稱

assert LINE_CHANNEL_ACCESS_TOKEN, "LINE_Channel access token 未設定"
assert LINE_CHANNEL_SECRET, "Channel secret 未設定"
assert PERPLEXITY_API_KEY, "Perplexity API key 未設定"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== 2. 權限暫存（正式建議用 Redis/DB）======
#   記錄權限給每個"group_id:user_id"，內容為權限獲取時的時間戳 
user_image_permission = {}  # key: "group_id:user_id" or "user_id" ; value: time.time()

PERMISSION_DURATION = 120  # 權限維持秒數(2分鐘)

@app.route("/", methods=['GET'])
def index():
    """首頁測試用，可判斷服務是否在線。"""
    return "LINE Bot + Perplexity (多模態) OK!"

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 事件接收與訊息分派。"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ====== 3. 取得權限主鍵（群組唯一：group_id:user_id；私聊：user_id） ======
def get_group_user_key(event):
    """若在群組，key為group_id:user_id；私聊只用user_id。"""
    if getattr(event.source, "group_id", None) and getattr(event.source, "user_id", None):
        return f"{event.source.group_id}:{event.source.user_id}"
    return getattr(event.source, "user_id", "anonymous")

# ====== 4. 只在群組訊息@BOT時回應；私訊皆回 ======
def should_reply_in_group(event, bot_tag):
    """群組必須@BOT且內容有text才觸發，私訊皆回。"""
    if getattr(event.source, "group_id", None):
        return getattr(event.message, "text", "") and bot_tag in event.message.text
    return True

# ====== 5. 是否觸發圖片模式（含'圖'、'照片'等關鍵字） ======
def is_request_image_mode(text):
    """自訂所有能啟動圖片分析的語詞。"""
    keywords = ["圖", "圖片", "照片", "分析圖", "看圖"]
    return any(k in text for k in keywords)

# ====== 6. 權限管理，授權時記錄時間戳 ======
def grant_image_permission(user_key):
    """授予指定user_key圖片分析權限，記入當下時間戳。"""
    user_image_permission[user_key] = time.time()

def check_image_permission(user_key, valid_duration=PERMISSION_DURATION):
    """
    檢查圖片分析權限是否仍在有效期內：
      - 有且在指定秒數內返回True
      - 否則刪除權限並回False
    """
    now = time.time()
    timestamp = user_image_permission.get(user_key)
    if timestamp and (now - timestamp) < valid_duration:
        return True
    elif timestamp:
        del user_image_permission[user_key]
    return False

# ====== 7. 處理文字訊息 ======
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    # 僅群組要tag BOT才處理
    if not should_reply_in_group(event, BOT_TAG):
        return
    key = get_group_user_key(event)
    text = getattr(event.message, "text", "").replace(BOT_TAG, "").strip().lower()

    # （1）觸發圖片模式，授予權限
    if is_request_image_mode(text):
        grant_image_permission(key)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="請在兩分鐘內上傳您想分析的圖片。"
            )
        )
        return

    # （2）若已處於權限模式但再發文字，則關閉（防止誤觸連串圖片）
    if key in user_image_permission:
        del user_image_permission[key]
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="已取消圖片分析服務。如還需請再次@Dylan-Auto並說明圖需求。")
        )
        return

    # （3）其它一般文字對話
    reply = get_perplexity_reply(text)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply or "抱歉，AI 沒有回應，請稍後再試 🙇")
    )

# ====== 8. 處理圖片訊息（需檢查權限及過期） ======
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    key = get_group_user_key(event)
    # 僅有效權限且未過期才允許圖片分析（一次性；分析完或逾時自動失效）
    if check_image_permission(key):
        message_id = event.message.id
        img_response = line_bot_api.get_message_content(message_id)
        binary = b"".join(chunk for chunk in img_response.iter_content())
        img_base64 = base64.b64encode(binary).decode("utf-8")
        mime = "image/jpeg"  # LINE 圖片幾乎都是 jpeg
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
        # 權限自動過期（check_image_permission已處理）
    else:
        # 超過時效或 never 被授權→清楚提醒用戶  
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="超過兩分鐘未貼圖，或尚未指派圖片分析，請再次@Dylan-Auto並說明圖需求。"
            )
        )

# ====== 9. Perplexity API一般聊天 ======
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

# ====== 10. Perplexity API 多模態對話呼叫 ======
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
