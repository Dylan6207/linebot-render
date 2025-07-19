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

# ====== 1. 取得環境變數與 API Token 設定 ======
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
BOT_TAG = "@Dylan-Auto"  # LINE群組內呼叫機器人時的顯示名稱

assert LINE_CHANNEL_ACCESS_TOKEN, "LINE_Channel access token 未設定"
assert LINE_CHANNEL_SECRET, "Channel secret 未設定"
assert PERPLEXITY_API_KEY, "Perplexity API key 未設定"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ====== 2. 權限暫存（正式環境建議用 Redis/DB） ======
#   記錄某 group_id（群組）或 user_id（私聊）是否允許分析圖片，下次圖片訊息只在權限打開時才處理
user_image_permission = {}

@app.route("/", methods=['GET'])
def index():
    """入口測試用，可判斷服務運作狀態"""
    return "LINE Bot + Perplexity (多模態) OK!"

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 事件接收並分派處理"""
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ====== 3. 支援私訊與群組分開判斷 ======
def get_unique_user_key(event):
    """
    - 群組中用 group_id（任何人在同一群組講到'圖'關鍵字、一律啟動該群組分析權限）
    - 私聊直接用 user_id
    """
    if getattr(event.source, "group_id", None):
        return event.source.group_id
    return getattr(event.source, "user_id", "anonymous")

# ====== 4. 只在群組訊息有tag BOT時才理會，私訊全部皆理 ======
def should_reply_in_group(event, bot_tag):
    """
    - 群組必須tag BOT名才會觸發（減少群噪）
    - 私聊一律自動觸發
    """
    if getattr(event.source, "group_id", None):
        # 圖片訊息沒有 text，這裡僅用於文字事件
        return getattr(event.message, "text", "") and bot_tag in event.message.text
    return True

# ====== 5. 判斷句子中是否含'圖'、'照片'等常用觸發詞 ======
def is_request_image_mode(text):
    """
    - 可擴充如：'圖片', '相片', '分析圖' 等常見表達
    - 只要出現任一即進入圖片流程
    """
    keywords = ["圖", "圖片", "照片", "分析圖", "看圖"]
    return any(k in text for k in keywords)

# ====== 6. 文字訊息處理主流程 ======
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    # 判斷是否需要回覆：群組需tag BOT，私訊則不需
    if not should_reply_in_group(event, BOT_TAG):
        return
    user_key = get_unique_user_key(event)
    text = getattr(event.message, "text", "").replace(BOT_TAG, "").strip().lower()

    # （一）訊息內含關鍵字：進入圖片分析權限
    if is_request_image_mode(text):
        user_image_permission[user_key] = True
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請傳送您想分析的圖片。")
        )
        return

    # （二）之前已進入圖片分析流程，但現在收到的是文字，則結束該狀態
    if user_image_permission.get(user_key, False):
        user_image_permission[user_key] = False
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="已取消圖片分析服務。如還需分析請再於訊息說明欲看『圖』、『照片』等。")
        )
        return

    # （三）一般文本提問，呼叫 Perplexity 聊天回覆
    reply = get_perplexity_reply(text)
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply or "抱歉，AI 沒有回應，請稍後再試 🙇")
    )

# ====== 7. 處理圖片訊息流程 ======
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    # 在圖片訊息請勿用 should_reply_in_group，因圖片沒 text，需純以權限判斷
    user_key = get_unique_user_key(event)
    print("DEBUG handle_image: user_key =", user_key)
    print("DEBUG handle_image: user_image_permission dict =", user_image_permission)

    # 僅當權限啟動時才允許進行圖片辨識
    if user_image_permission.get(user_key, False):
        message_id = event.message.id
        img_response = line_bot_api.get_message_content(message_id)
        # 將圖片二進位資料合併
        binary = b"".join(chunk for chunk in img_response.iter_content())
        # base64 編碼
        img_base64 = base64.b64encode(binary).decode("utf-8")
        mime = "image/jpeg"  # LINE 除貼圖外均為 jpg

        # 組成多模態 payload，請求 Perplexity API
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
        # 分析完畢立即關閉該權限
        user_image_permission[user_key] = False
    else:
        # 未啟動權限時直接提示，避免無限制耗費讀流量
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="如需圖片分析，請先於訊息說明想看『圖』、『照片』或相關字眼。")
        )

# ====== 8. Perplexity API的一般聊天流程 ======
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

# ====== 9. Perplexity API請求共用函式 ======
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

