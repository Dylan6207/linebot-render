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

# ===== 1. 環境與 API 設定 =====
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
BOT_TAG = "@Dylan-Auto"  # 在 LINE 群組時用來 Tag 機器人的名稱

assert LINE_CHANNEL_ACCESS_TOKEN, "LINE_Channel access token 未設定"
assert LINE_CHANNEL_SECRET, "Channel secret 未設定"
assert PERPLEXITY_API_KEY, "Perplexity API key 未設定"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ===== 2. 權限暫存結構（建議正式環境用 Redis/資料庫） =====
# 權限主鍵：群組模式 group_id:user_id，私訊 user_id
# 值為 timestamp（權限取得時間）
user_image_permission = {}
PERMISSION_DURATION = 120  # 權限有效秒數（2分鐘）

@app.route("/", methods=['GET'])
def index():
    """首頁測試確認 Server 狀態"""
    return "LINE Bot + Perplexity (多模態) OK!"

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 事件入口"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ===== 3. 權限主鍵產生 =====
def get_group_user_key(event):
    """群組模式: group_id:user_id, 私聊: user_id"""
    if getattr(event.source, "group_id", None) and getattr(event.source, "user_id", None):
        return f"{event.source.group_id}:{event.source.user_id}"
    return getattr(event.source, "user_id", "anonymous")

# ===== 4. 只在群組文字訊息含@BOT時才處理，私訊皆回 =====
def should_reply_in_group(event, bot_tag):
    """群組需@BOT才觸發，私訊皆回應。僅供文字訊息使用。"""
    if getattr(event.source, "group_id", None):
        return getattr(event.message, "text", "") and bot_tag in event.message.text
    return True

# ===== 5. 是否為圖片分析請求的關鍵字判斷 =====
def is_request_image_mode(text):
    """通用多自然語句方式，只要出現'圖', '照片'等即可判斷觸發圖片分析權限"""
    keywords = ["圖", "圖片", "照片", "分析圖", "看圖"]
    return any(k in text for k in keywords)

# ===== 6. 權限管理核心 =====
def grant_image_permission(user_key):
    """授權時記錄權限 key 的時間戳"""
    user_image_permission[user_key] = time.time()

def check_image_permission(user_key, valid_duration=PERMISSION_DURATION):
    """
    若權限有效回 True, 逾時自動失效並刪除回 False
    """
    now = time.time()
    timestamp = user_image_permission.get(user_key)
    if timestamp and (now - timestamp) < valid_duration:
        return True
    elif timestamp:
        del user_image_permission[user_key]
    return False

# ===== 7. 處理文字訊息 =====
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    # 僅群組需tag BOT名才理會，私訊皆理
    if not should_reply_in_group(event, BOT_TAG):
        return
    key = get_group_user_key(event)
    text = getattr(event.message, "text", "").replace(BOT_TAG, "").strip().lower()

    # （一）tag且有圖關鍵字→授權圖片分析（權限組合 key, 僅對該用戶/群有效）
    if is_request_image_mode(text):
        grant_image_permission(key)
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請在兩分鐘內上傳您想分析的圖片。")
        )
        return

    # （二）獲權後，若對方又先發文字→取消該權限（避免誤觸多圖）
    if key in user_image_permission:
        del user_image_permission[key]
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="已取消圖片分析服務。如還需請再次@Dylan-Auto並說明圖需求。")
        )
        return

    # （三）一般文字問題 → AI 聊天
    reply = get_perplexity_reply(text)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply or "抱歉，AI 沒有回應，請稍後再試 🙇")
    )

# ===== 8. 處理圖片訊息 =====
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    key = get_group_user_key(event)
    is_group = getattr(event.source, "group_id", None) is not None

    # (A) 私訊：用戶直接貼圖皆允許（自動授權）
    if not is_group:
        do_image_analysis(event, key)
        return

    # (B) 群組：只有授權且仍在2分鐘內才進行分析，其餘一律 silent（完全不回應）
    if check_image_permission(key):
        do_image_analysis(event, key)
        return
    # 群組下未授權、權限逾時、或非特定用戶圖片時完全不理會
    return

# ===== 9. 圖片分析公用函式 =====
def do_image_analysis(event, key):
    """呼叫 Perplexity 多模態接口進行圖片分析，並回傳LINE。"""
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
    # 分析完即移除該權限
    if key in user_image_permission:
        del user_image_permission[key]

# ===== 10. Perplexity API一般聊天 =====
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

# ===== 11. Perplexity API HTTP 封裝 =====
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
