import os
import re
import json
import uuid
import asyncio
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Thread

from flask import Flask
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# Put Telegram numeric user IDs here:
# ADMIN_IDS=123456789,987654321
# AGENT_IDS=111111111,222222222
ADMIN_IDS = {
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

AGENT_IDS = {
    int(x.strip())
    for x in os.getenv("AGENT_IDS", "").split(",")
    if x.strip().isdigit()
}

# Admins are automatically treated as agents too.
AGENT_IDS.update(ADMIN_IDS)

UPI_ID = os.getenv(
    "UPI_ID",
    "pratikraj10107@okhdfcbank"
).strip()

BOT_NAME = "INSTAGRAM GROWTH BOT"

# Rates are per 1K
RATES = {
    "followers": 35.00,
    "views": 0.01,
    "likes": 1.30,
}

LIMITS = {
    "followers": {
        "min": 1_000,
        "max": 50_000_000,
    },
    "views": {
        "min": 500_000,
        "max": 50_000_000,
    },
    "likes": {
        "min": 10_000,
        "max": 50_000_000,
    },
}

SERVICE_NAMES = {
    "followers": "Instagram Followers",
    "views": "Instagram Views",
    "likes": "Instagram Likes",
}

DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "data.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# In-memory user workflow sessions.
sessions = {}


# ============================================================
# FLASK SERVER FOR RENDER WEB SERVICE
# ============================================================

app = Flask(__name__)


@app.get("/")
def home():
    return "Instagram Growth Bot is running."


@app.get("/health")
def health():
    return "OK"


def run_web():
    port = int(os.environ.get("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


# ============================================================
# DATA STORAGE
# ============================================================

def default_data():
    return {
        "orders": {},
        "tokens": {},
        "users": {},
    }


def load_data():
    if not DATA_FILE.exists():
        return default_data()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return default_data()

        data.setdefault("orders", {})
        data.setdefault("tokens", {})
        data.setdefault("users", {})

        return data

    except Exception:
        return default_data()


data = load_data()


def save_data():
    temp_file = DATA_DIR / "data.tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )

    temp_file.replace(DATA_FILE)


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def iso_now():
    return now_utc().isoformat()


def format_money(amount):
    amount = float(amount)

    if amount.is_integer():
        return f"₹{int(amount):,}"

    return f"₹{amount:,.2f}"


def calculate_amount(service, quantity):
    return (quantity / 1000) * RATES[service]


def service_display(service):
    return SERVICE_NAMES.get(service, service)


def is_admin(user_id):
    return user_id in ADMIN_IDS


def is_agent(user_id):
    return user_id in AGENT_IDS


def clean_username(user):
    if user.username:
        return f"@{user.username}"
    return "No username"


def generate_order_id():
    while True:
        order_id = f"IG{secrets.randbelow(9_000_000) + 1_000_000}"

        if order_id not in data["orders"]:
            return order_id


def generate_token():
    alphabet = string.ascii_uppercase + string.digits

    while True:
        raw = "".join(
            secrets.choice(alphabet)
            for _ in range(12)
        )

        token = f"IG-{raw[:4]}-{raw[4:8]}-{raw[8:]}"

        if token not in data["tokens"]:
            return token


def get_user_orders(user_id):
    orders = []

    for order in data["orders"].values():
        if order.get("user_id") == user_id:
            orders.append(order)

    orders.sort(
        key=lambda x: x.get("created_at", ""),
        reverse=True,
    )

    return orders


def get_order(order_id):
    return data["orders"].get(order_id)


def valid_instagram_link(text):
    if not text:
        return False

    text = text.strip()

    pattern = re.compile(
        r"^https?://(?:www\.)?instagram\.com/"
        r"[^\s]+$",
        re.IGNORECASE,
    )

    return bool(pattern.match(text))


def make_progress_bar(percent):
    total = 10
    filled = int(percent / 10)

    return "█" * filled + "░" * (total - filled)


# ============================================================
# KEYBOARDS
# ============================================================

def main_menu_keyboard(user_id=None):
    rows = [
        [
            InlineKeyboardButton(
                "🛒 New Order",
                callback_data="new_order",
            ),
            InlineKeyboardButton(
                "📦 My Orders",
                callback_data="my_orders",
            ),
        ],
        [
            InlineKeyboardButton(
                "📋 Service Menu",
                callback_data="service_menu",
            ),
            InlineKeyboardButton(
                "🎫 Submit Token",
                callback_data="submit_token",
            ),
        ],
        [
            InlineKeyboardButton(
                "🔑 Make Token",
                callback_data="make_token",
            ),
            InlineKeyboardButton(
                "❓ Help",
                callback_data="help",
            ),
        ],
    ]

    return InlineKeyboardMarkup(rows)


def back_menu_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔙 Main Menu",
                callback_data="main_menu",
            )
        ]
    ])


def service_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👥 Followers",
                callback_data="service_followers",
            )
        ],
        [
            InlineKeyboardButton(
                "👀 Views",
                callback_data="service_views",
            )
        ],
        [
            InlineKeyboardButton(
                "❤️ Likes",
                callback_data="service_likes",
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back",
                callback_data="main_menu",
            )
        ],
    ])


# ============================================================
# TEXT
# ============================================================

WELCOME_TEXT = """
╔══════════════════════════════╗
      📸 <b>INSTAGRAM GROWTH BOT</b>
╚══════════════════════════════╝

👋 <b>Welcome!</b>

Grow your Instagram with our
simple and easy ordering system.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🛒 New Order
📦 My Orders
📋 Service Menu
🎫 Submit Token
🔑 Make Token
❓ Help

👇 <b>Select an option below</b>
"""


SERVICE_MENU_TEXT = """
╔══════════════════════════════╗
      📋 <b>SMM SERVICE MENU 🔥</b>
╚══════════════════════════════╝

👥 <b>INSTAGRAM FOLLOWERS</b>
💰 1K Followers — <b>₹35</b>
📌 Minimum Order — <b>1K</b>
📌 Maximum Order — <b>50M</b>

👀 <b>INSTAGRAM VIEWS</b>
💰 1K Views — <b>₹0.01</b>
📌 Minimum Order — <b>500K</b>
📌 Maximum Order — <b>50M</b>

❤️ <b>INSTAGRAM LIKES</b>
💰 1K Likes — <b>₹1.30</b>
📌 Minimum Order — <b>10K</b>
📌 Maximum Order — <b>50M</b>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📉 Drop Rate: ~10%
🔄 Refill: 2 Months
⚡ Order Completion: 1–15 Hours

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💬 Sir, agar koi question hai to
aap mujhse pooch sakte hain. 😊
"""


HELP_TEXT = """
╔══════════════════════════════╗
            ❓ <b>HELP</b>
╚══════════════════════════════╝

🛒 <b>New Order</b>
Create a new Instagram service order.

📦 <b>My Orders</b>
View only your own orders.

🎫 <b>Submit Token</b>
Submit a one-time token received from
an agent.

💳 <b>Payment</b>
After order confirmation, the bot shows
the exact payable amount and payment QR.

📸 <b>Payment Receipt</b>
Send your payment screenshot through
the bot after completing payment.

🔐 <b>Token Validity</b>
Tokens remain valid for 7 days and can
be used only once.

💬 For questions, contact the admin.
"""


# ============================================================
# START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    sessions.pop(user.id, None)

    data["users"][str(user.id)] = {
        "user_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "last_seen": iso_now(),
    }

    save_data()

    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(user.id),
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id
    action = query.data

    # ---------------- MAIN MENU ----------------

    if action == "main_menu":
        sessions.pop(user_id, None)

        await query.edit_message_text(
            WELCOME_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    # ---------------- NEW ORDER ----------------

    if action == "new_order":
        sessions[user_id] = {
            "state": "choose_service"
        }

        await query.edit_message_text(
            "╔══════════════════════════════╗\n"
            "        📱 <b>SELECT SERVICE</b>\n"
            "╚══════════════════════════════╝\n\n"
            "Choose the service you want:",
            parse_mode=ParseMode.HTML,
            reply_markup=service_keyboard(),
        )
        return

    # ---------------- SERVICE ----------------

    if action.startswith("service_"):
        service = action.replace(
            "service_",
            "",
            1,
        )

        if service not in SERVICE_NAMES:
            return

        sessions[user_id] = {
            "state": "waiting_quantity",
            "service": service,
        }

        minimum = LIMITS[service]["min"]
        maximum = LIMITS[service]["max"]

        rate = RATES[service]

        await query.edit_message_text(
            f"╔══════════════════════════════╗\n"
            f"      📦 <b>{SERVICE_NAMES[service].upper()}</b>\n"
            f"╚══════════════════════════════╝\n\n"
            f"💰 Rate: <b>{format_money(rate)} / 1K</b>\n\n"
            f"📌 Minimum: <b>{minimum:,}</b>\n"
            f"📌 Maximum: <b>{maximum:,}</b>\n\n"
            f"🔢 <b>Send quantity using numbers only.</b>\n\n"
            f"Example:\n"
            f"<code>{minimum}</code>\n"
            f"<code>{minimum * 2}</code>\n"
            f"<code>1000000</code>\n\n"
            f"⚠️ Only numbers are accepted.\n"
            f"❌ No letters or symbols.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="cancel",
                    )
                ]
            ]),
        )
        return

    # ---------------- SERVICE MENU ----------------

    if action == "service_menu":
        await query.edit_message_text(
            SERVICE_MENU_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu_keyboard(),
        )
        return

    # ---------------- HELP ----------------

    if action == "help":
        await query.edit_message_text(
            HELP_TEXT,
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu_keyboard(),
        )
        return

    # ---------------- MY ORDERS ----------------

    if action == "my_orders":
        orders = get_user_orders(user_id)

        if not orders:
            text = (
                "╔══════════════════════════════╗\n"
                "          📦 <b>MY ORDERS</b>\n"
                "╚══════════════════════════════╝\n\n"
                "You don't have any orders yet."
            )

            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=back_menu_keyboard(),
            )
            return

        lines = [
            "╔══════════════════════════════╗",
            "          📦 <b>MY ORDERS</b>",
            "╚══════════════════════════════╝",
            "",
        ]

        for order in orders[:20]:
            lines.append(
                f"🆔 <b>#{order['order_id']}</b>\n"
                f"📦 {service_display(order['service'])}\n"
                f"🔢 {order['quantity']:,}\n"
                f"💰 {format_money(order['amount'])}\n"
                f"💳 {order.get('payment_status', 'Pending')}\n"
                f"📅 {order.get('created_at', '')[:19]}\n"
            )

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu_keyboard(),
        )
        return

    # ---------------- SUBMIT TOKEN ----------------

    if action == "submit_token":
        sessions[user_id] = {
            "state": "waiting_token"
        }

        await query.edit_message_text(
            "╔══════════════════════════════╗\n"
            "          🎫 <b>SUBMIT TOKEN</b>\n"
            "╚══════════════════════════════╝\n\n"
            "Please send your one-time token.\n\n"
            "🔐 Token validity: <b>7 days</b>\n"
            "♻️ Each token can be used only once.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="cancel",
                    )
                ]
            ]),
        )
        return

    # ---------------- MAKE TOKEN ----------------

    if action == "make_token":
        if not is_agent(user_id):
            await query.answer(
                "⛔ Agent only — you are not authorized.",
                show_alert=True,
            )
            return

        sessions[user_id] = {
            "state": "agent_choose_service"
        }

        await query.edit_message_text(
            "🔑 <b>AGENT / ADMIN — MAKE TOKEN</b>\n\n"
            "Create an order for a customer.\n"
            "Choose the service:",
            parse_mode=ParseMode.HTML,
            reply_markup=service_keyboard(),
        )
        return

    # ---------------- AGENT PREVIEW ----------------

    if action == "agent_create_token":
        if not is_agent(user_id):
            await query.answer(
                "⛔ Agent only.",
                show_alert=True,
            )
            return

        session = sessions.get(user_id, {})

        if session.get("state") != "agent_preview":
            return

        service = session["service"]
        quantity = session["quantity"]
        link = session["link"]

        order_id = generate_order_id()
        token = generate_token()

        created = now_utc()
        expires = created + timedelta(days=7)

        amount = calculate_amount(
            service,
            quantity,
        )

        order = {
            "order_id": order_id,
            "user_id": None,
            "username": None,
            "first_name": None,
            "telegram_id": None,
            "service": service,
            "quantity": quantity,
            "link": link,
            "rate_per_1k": RATES[service],
            "amount": round(amount, 2),
            "token": token,
            "token_expires": expires.isoformat(),
            "token_used": False,
            "created_by": user_id,
            "created_at": iso_now(),
            "payment_status": "Pending",
            "receipt_file_id": None,
            "receipt_type": None,
        }

        data["orders"][order_id] = order

        data["tokens"][token] = {
            "order_id": order_id,
            "created_at": created.isoformat(),
            "expires_at": expires.isoformat(),
            "used": False,
        }

        save_data()

        sessions.pop(user_id, None)

        await query.edit_message_text(
            "╔══════════════════════════════╗\n"
            "        🔐 <b>TOKEN CREATED</b>\n"
            "╚══════════════════════════════╝\n\n"
            f"🆔 Order ID: <b>#{order_id}</b>\n\n"
            f"🎫 Token:\n"
            f"<code>{token}</code>\n\n"
            f"📦 Service: {service_display(service)}\n"
            f"🔢 Quantity: {quantity:,}\n"
            f"💰 Amount: {format_money(amount)}\n"
            f"🔗 Link: {link}\n\n"
            f"⏳ Valid for: <b>7 days</b>\n"
            f"♻️ One-time use only\n\n"
            "Send this token to the customer.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_menu_keyboard(),
        )
        return

    # ---------------- USER ORDER PREVIEW ----------------

    if action == "confirm_order":
        session = sessions.get(user_id, {})

        if session.get("state") != "preview":
            return

        service = session["service"]
        quantity = session["quantity"]
        link = session["link"]

        amount = calculate_amount(
            service,
            quantity,
        )

        order_id = generate_order_id()

        order = {
            "order_id": order_id,
            "user_id": user_id,
            "username": user.username,
            "first_name": user.first_name,
            "telegram_id": user_id,
            "service": service,
            "quantity": quantity,
            "link": link,
            "rate_per_1k": RATES[service],
            "amount": round(amount, 2),
            "token": None,
            "token_expires": None,
            "token_used": False,
            "created_by": user_id,
            "created_at": iso_now(),
            "payment_status": "Pending",
            "receipt_file_id": None,
            "receipt_type": None,
        }

        data["orders"][order_id] = order
        save_data()

        sessions[user_id] = {
            "state": "awaiting_payment",
            "order_id": order_id,
        }

        await send_payment(
            query,
            order,
        )

        return

    # ---------------- AGENT CONFIRM PAYMENT ----------------

    if action == "payment_complete":
        session = sessions.get(user_id, {})
        order_id = session.get("order_id")

        if not order_id:
            await query.answer(
                "Order session expired. Open My Orders.",
                show_alert=True,
            )
            return

        order = get_order(order_id)

        if not order:
            return

        sessions[user_id] = {
            "state": "waiting_receipt",
            "order_id": order_id,
        }

        await query.edit_message_text(
            "╔══════════════════════════════╗\n"
            "       📤 <b>PAYMENT RECEIPT</b>\n"
            "╚══════════════════════════════╝\n\n"
            f"🆔 Order: <b>#{order_id}</b>\n"
            f"💰 Amount: <b>{format_money(order['amount'])}</b>\n\n"
            "Please send your payment screenshot here.\n\n"
            "📸 The receipt will be forwarded to\n"
            "the admin for manual verification.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="cancel",
                    )
                ]
            ]),
        )
        return

    # ---------------- CANCEL ----------------

    if action == "cancel":
        sessions.pop(user_id, None)

        await query.edit_message_text(
            "❌ <b>Cancelled.</b>\n\n"
            "Your current action has been cancelled.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    # ---------------- CHANGE DETAILS ----------------

    if action == "change_details":
        session = sessions.get(user_id, {})

        if session:
            session["state"] = "waiting_quantity"

            service = session["service"]

            await query.edit_message_text(
                f"🔄 <b>CHANGE QUANTITY</b>\n\n"
                f"Service: {service_display(service)}\n\n"
                f"Send the new quantity using numbers only.\n"
                f"Minimum: {LIMITS[service]['min']:,}\n"
                f"Maximum: {LIMITS[service]['max']:,}",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "❌ Cancel",
                            callback_data="cancel",
                        )
                    ]
                ]),
            )
        return


# ============================================================
# PAYMENT
# ============================================================

async def send_payment(query, order):
    amount = order["amount"]
    order_id = order["order_id"]

    # UPI deep link with fixed amount.
    upi_url = (
        "upi://pay"
        f"?pa={UPI_ID}"
        f"&pn=Instagram%20Growth%20Bot"
        f"&am={amount:.2f}"
        "&cu=INR"
        f"&tn=Order%20{order_id}"
    )

    # QR generation is done using qrcode.
    try:
        import qrcode

        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )

        qr.add_data(upi_url)
        qr.make(fit=True)

        image = qr.make_image()

        qr_path = DATA_DIR / f"qr_{order_id}.png"
        image.save(qr_path)

        caption = (
            "╔══════════════════════════════╗\n"
            "            💳 <b>PAYMENT</b>\n"
            "╚══════════════════════════════╝\n\n"
            f"🆔 Order ID: <b>#{order_id}</b>\n"
            f"📦 Service: {service_display(order['service'])}\n"
            f"🔢 Quantity: {order['quantity']:,}\n"
            f"💰 Amount Payable: <b>{format_money(amount)}</b>\n\n"
            f"🏦 UPI ID:\n"
            f"<code>{UPI_ID}</code>\n\n"
            "📱 Scan the QR code and pay the exact amount.\n\n"
            "After payment, send your screenshot\n"
            "using the button below."
        )

        with open(qr_path, "rb") as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "📤 Payment Complete / Send Receipt",
                            callback_data="payment_complete",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Cancel",
                            callback_data="cancel",
                        )
                    ],
                ]),
            )

        await query.edit_message_text(
            "💳 <b>Payment QR generated.</b>\n\n"
            "Please use the QR message below to complete payment.",
            parse_mode=ParseMode.HTML,
        )

        try:
            qr_path.unlink()
        except Exception:
            pass

    except Exception as e:
        print("QR ERROR:", e)

        await query.edit_message_text(
            "⚠️ Payment QR could not be generated.\n\n"
            f"Please use this UPI ID:\n"
            f"<code>{UPI_ID}</code>\n\n"
            f"Amount: <b>{format_money(amount)}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📤 Payment Complete / Send Receipt",
                        callback_data="payment_complete",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="cancel",
                    )
                ],
            ]),
        )


# ============================================================
# TEXT MESSAGE HANDLER
# ============================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    session = sessions.get(user_id)

    if not session:
        await update.message.reply_text(
            "Please choose an option from the menu.",
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    state = session.get("state")

    # ========================================================
    # USER QUANTITY
    # ========================================================

    if state == "waiting_quantity":

        # Strict numbers only.
        if not re.fullmatch(r"[0-9]+", text):
            await update.message.reply_text(
                "❌ <b>Invalid quantity.</b>\n\n"
                "Please send <b>numbers only</b>.\n"
                "Letters, spaces, dots and symbols are not allowed.",
                parse_mode=ParseMode.HTML,
            )
            return

        try:
            quantity = int(text)
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid number."
            )
            return

        service = session["service"]

        minimum = LIMITS[service]["min"]
        maximum = LIMITS[service]["max"]

        if quantity < minimum:
            await update.message.reply_text(
                f"❌ Minimum quantity is <b>{minimum:,}</b>.",
                parse_mode=ParseMode.HTML,
            )
            return

        if quantity > maximum:
            await update.message.reply_text(
                f"❌ Maximum quantity is <b>{maximum:,}</b>.",
                parse_mode=ParseMode.HTML,
            )
            return

        session["quantity"] = quantity
        session["state"] = "waiting_link"

        await update.message.reply_text(
            "🔗 <b>SEND INSTAGRAM LINK</b>\n\n"
            "Please send the Instagram profile/post link.\n\n"
            "Example:\n"
            "<code>https://instagram.com/...</code>\n\n"
            "⚠️ Send one valid Instagram link only.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="cancel",
                    )
                ]
            ]),
        )
        return

    # ========================================================
    # USER LINK
    # ========================================================

    if state == "waiting_link":

        if not valid_instagram_link(text):
            await update.message.reply_text(
                "❌ <b>Invalid Instagram link.</b>\n\n"
                "Please send a valid Instagram URL.",
                parse_mode=ParseMode.HTML,
            )
            return

        session["link"] = text
        session["state"] = "preview"

        service = session["service"]
        quantity = session["quantity"]
        amount = calculate_amount(
            service,
            quantity,
        )

        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "        🧾 <b>ORDER PREVIEW</b>\n"
            "╚══════════════════════════════╝\n\n"
            f"📦 Service: <b>{service_display(service)}</b>\n"
            f"🔢 Quantity: <b>{quantity:,}</b>\n"
            f"💰 Rate: <b>{format_money(RATES[service])} / 1K</b>\n"
            f"💵 Total Amount: <b>{format_money(amount)}</b>\n\n"
            f"🔗 Link:\n"
            f"{text}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Please check your order details.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Confirm Order",
                        callback_data="confirm_order",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✏️ Change Details",
                        callback_data="change_details",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="cancel",
                    )
                ],
            ]),
        )
        return

    # ========================================================
    # TOKEN SUBMISSION
    # ========================================================

    if state == "waiting_token":

        token = text.upper().strip()

        token_info = data["tokens"].get(token)

        if not token_info:
            await update.message.reply_text(
                "❌ <b>INVALID TOKEN</b>\n\n"
                "This token does not exist.",
                parse_mode=ParseMode.HTML,
            )
            return

        if token_info.get("used"):
            await update.message.reply_text(
                "❌ <b>TOKEN ALREADY USED</b>\n\n"
                "This token can only be used once.",
                parse_mode=ParseMode.HTML,
            )
            return

        try:
            expires = datetime.fromisoformat(
                token_info["expires_at"]
            )

            if now_utc() > expires:
                await update.message.reply_text(
                    "⏰ <b>TOKEN EXPIRED</b>\n\n"
                    "This token was valid for 7 days only.",
                    parse_mode=ParseMode.HTML,
                )
                return

        except Exception:
            await update.message.reply_text(
                "❌ Token information is invalid."
            )
            return

        order_id = token_info["order_id"]
        order = get_order(order_id)

        if not order:
            await update.message.reply_text(
                "❌ Order connected to this token was not found."
            )
            return

        # Bind order to the actual customer.
        order["user_id"] = user_id
        order["telegram_id"] = user_id
        order["username"] = user.username
        order["first_name"] = user.first_name
        order["last_name"] = user.last_name

        save_data()

        sessions[user_id] = {
            "state": "token_preview",
            "order_id": order_id,
        }

        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "       ✅ <b>TOKEN VERIFIED</b>\n"
            "╚══════════════════════════════╝\n\n"
            f"🆔 Order ID: <b>#{order_id}</b>\n"
            f"📦 Service: <b>{service_display(order['service'])}</b>\n"
            f"🔢 Quantity: <b>{order['quantity']:,}</b>\n"
            f"💰 Amount: <b>{format_money(order['amount'])}</b>\n\n"
            f"🔗 Link:\n{order['link']}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Your order details have been found.\n"
            "Confirm to continue to payment.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💳 Confirm Order",
                        callback_data="token_confirm_payment",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="cancel",
                    )
                ],
            ]),
        )
        return

    # ========================================================
    # AGENT SERVICE
    # ========================================================

    if state == "agent_choose_service":
        # This state is reached through a service button.
        return

    # ========================================================
    # AGENT QUANTITY
    # ========================================================

    if state == "agent_waiting_quantity":

        if not re.fullmatch(r"[0-9]+", text):
            await update.message.reply_text(
                "❌ Send numbers only.",
            )
            return

        quantity = int(text)
        service = session["service"]

        minimum = LIMITS[service]["min"]
        maximum = LIMITS[service]["max"]

        if quantity < minimum:
            await update.message.reply_text(
                f"❌ Minimum: {minimum:,}"
            )
            return

        if quantity > maximum:
            await update.message.reply_text(
                f"❌ Maximum: {maximum:,}"
            )
            return

        session["quantity"] = quantity
        session["state"] = "agent_waiting_link"

        await update.message.reply_text(
            "🔗 Send the customer's Instagram link."
        )
        return

    # ========================================================
    # AGENT LINK
    # ========================================================

    if state == "agent_waiting_link":

        if not valid_instagram_link(text):
            await update.message.reply_text(
                "❌ Please send a valid Instagram link."
            )
            return

        session["link"] = text
        session["state"] = "agent_preview"

        service = session["service"]
        quantity = session["quantity"]
        amount = calculate_amount(
            service,
            quantity,
        )

        await update.message.reply_text(
            "╔══════════════════════════════╗\n"
            "      🔑 <b>AGENT ORDER PREVIEW</b>\n"
            "╚══════════════════════════════╝\n\n"
            f"📦 Service: {service_display(service)}\n"
            f"🔢 Quantity: {quantity:,}\n"
            f"💰 Amount: {format_money(amount)}\n"
            f"🔗 Link: {text}\n\n"
            "Create a one-time token for this order?",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔑 Make Token",
                        callback_data="agent_create_token",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data="cancel",
                    )
                ],
            ]),
        )
        return

    # ========================================================
    # RECEIPT TEXT
    # ========================================================

    if state == "waiting_receipt":
        await update.message.reply_text(
            "📸 Please send your payment screenshot as an image."
        )
        return


# ============================================================
# TOKEN CONFIRM PAYMENT CALLBACK
# ============================================================

async def token_confirm_payment(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id

    session = sessions.get(user_id, {})
    order_id = session.get("order_id")

    if session.get("state") != "token_preview":
        await query.answer(
            "Session expired.",
            show_alert=True,
        )
        return

    order = get_order(order_id)

    if not order:
        return

    token = order.get("token")

    if not token:
        await query.answer(
            "Token information missing.",
            show_alert=True,
        )
        return

    token_info = data["tokens"].get(token)

    if not token_info:
        return

    if token_info.get("used"):
        await query.answer(
            "Token already used.",
            show_alert=True,
        )
        return

    try:
        expires = datetime.fromisoformat(
            token_info["expires_at"]
        )

        if now_utc() > expires:
            await query.answer(
                "Token expired.",
                show_alert=True,
            )
            return

    except Exception:
        return

    # Token becomes used only when customer confirms.
    token_info["used"] = True
    order["token_used"] = True

    save_data()

    sessions[user_id] = {
        "state": "awaiting_payment",
        "order_id": order_id,
    }

    await send_payment(
        query,
        order,
    )


# ============================================================
# RECEIPT HANDLER
# ============================================================

async def photo_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user
    user_id = user.id

    session = sessions.get(user_id, {})

    if session.get("state") != "waiting_receipt":
        await update.message.reply_text(
            "Please select an option from the menu.",
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    order_id = session.get("order_id")
    order = get_order(order_id)

    if not order:
        await update.message.reply_text(
            "❌ Order not found."
        )
        sessions.pop(user_id, None)
        return

    photo = update.message.photo[-1]

    order["receipt_file_id"] = photo.file_id
    order["receipt_type"] = "photo"
    order["receipt_received_at"] = iso_now()
    order["payment_status"] = "Receipt Submitted"

    save_data()

    await update.message.reply_text(
        "✅ <b>RECEIPT SENT</b>\n\n"
        f"🆔 Order ID: <b>#{order_id}</b>\n\n"
        "Your payment screenshot has been sent "
        "to the admin for manual verification.\n\n"
        "Please wait for manual processing.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu_keyboard(user_id),
    )

    sessions.pop(user_id, None)

    # Send receipt to every admin.
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo.file_id,
                caption=(
                    "🔔 <b>NEW PAYMENT RECEIPT</b>\n\n"
                    f"🆔 Order ID: <b>#{order_id}</b>\n"
                    f"👤 Name: {user.first_name}\n"
                    f"🔹 Username: {clean_username(user)}\n"
                    f"🆔 Telegram ID: <code>{user_id}</code>\n\n"
                    f"📦 Service: {service_display(order['service'])}\n"
                    f"🔢 Quantity: {order['quantity']:,}\n"
                    f"💰 Amount: {format_money(order['amount'])}\n"
                    f"🔗 Link: {order['link']}\n\n"
                    "💳 Status: <b>Receipt Submitted</b>\n\n"
                    "⚠️ Please verify payment manually."
                ),
                parse_mode=ParseMode.HTML,
            )

        except Exception as e:
            print(
                f"Could not send receipt to admin "
                f"{admin_id}: {e}"
            )


# ============================================================
# AGENT SERVICE CALLBACK FIX
# ============================================================

async def agent_service_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id

    if not is_agent(user_id):
        await query.answer(
            "⛔ Agent only.",
            show_alert=True,
        )
        return

    service = query.data.replace(
        "service_",
        "",
        1,
    )

    if service not in SERVICE_NAMES:
        return

    sessions[user_id] = {
        "state": "agent_waiting_quantity",
        "service": service,
    }

    await query.edit_message_text(
        f"🔑 <b>AGENT ORDER</b>\n\n"
        f"Service: <b>{service_display(service)}</b>\n\n"
        f"📌 Minimum: {LIMITS[service]['min']:,}\n"
        f"📌 Maximum: {LIMITS[service]['max']:,}\n\n"
        "🔢 Send quantity using numbers only.",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="cancel",
                )
            ]
        ]),
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    print("BOT ERROR:", context.error)


# ============================================================
# CLEANUP EXPIRED TOKENS
# ============================================================

async def cleanup_expired_tokens():
    while True:
        try:
            current = now_utc()

            changed = False

            for token, info in list(
                data["tokens"].items()
            ):
                if info.get("used"):
                    continue

                try:
                    expires = datetime.fromisoformat(
                        info["expires_at"]
                    )

                    if current > expires:
                        # Keep record but mark expired.
                        info["expired"] = True
                        changed = True

                except Exception:
                    continue

            if changed:
                save_data()

        except Exception as e:
            print("Cleanup error:", e)

        await asyncio.sleep(3600)


# ============================================================
# MAIN
# ============================================================

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    if not ADMIN_IDS:
        raise RuntimeError(
            "ADMIN_IDS environment variable is missing."
        )

    print("Starting Instagram Growth Bot...")
    print("Admins:", ADMIN_IDS)
    print("Agents:", AGENT_IDS)

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    # Special token confirmation callback first.
    application.add_handler(
        CallbackQueryHandler(
            token_confirm_payment,
            pattern="^token_confirm_payment$",
        )
    )

    # Agent service callback must be before general callback.
    application.add_handler(
        CallbackQueryHandler(
            agent_service_callback,
            pattern="^service_(followers|views|likes)$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(callback_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            photo_handler,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    # Start cleanup task.
    async def post_init(app_instance):
        asyncio.create_task(
            cleanup_expired_tokens()
        )

    application.post_init = post_init

    # Start Render web server.
    web_thread = Thread(
        target=run_web,
        daemon=True,
    )

    web_thread.start()

    print("Web server started.")
    print("Telegram polling started.")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
