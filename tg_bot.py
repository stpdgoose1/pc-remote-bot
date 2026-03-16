import asyncio
import json
import os
import websockets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

# ── CONFIG ──
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")  # Вставь свой токен

# Прокси — если Telegram заблокирован раскомментируй одну строку:
# PROXY = "socks5://127.0.0.1:9150"  # Tor Browser
# PROXY = "socks5://127.0.0.1:1080"  # Другой прокси
PROXY = None

CONFIG_FILE = "bot_config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"pcs": {}}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f)

config = load_config()

async def send_to_pc(ip, port, action, params={}):
    try:
        uri = f"ws://{ip}:{port}"
        async with websockets.connect(uri, open_timeout=5) as ws:
            await ws.send(json.dumps({"action": action, **params}))
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            return json.loads(response)
    except Exception as e:
        return {"ok": False, "error": str(e)}

def main_menu():
    keyboard = [
        [InlineKeyboardButton("📊 Статистика", callback_data="stats"),
         InlineKeyboardButton("⚙️ Процессы", callback_data="processes")],
        [InlineKeyboardButton("💤 Сон", callback_data="sleep"),
         InlineKeyboardButton("🔄 Рестарт", callback_data="restart"),
         InlineKeyboardButton("⏻ Выкл", callback_data="shutdown")],
        [InlineKeyboardButton("🔌 Сменить ПК", callback_data="change_pc")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_pc(chat_id):
    return config["pcs"].get(str(chat_id))

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    pc = get_pc(chat_id)
    if pc:
        await update.message.reply_text(
            f"👋 С возвращением!\n\n🖥 Подключён к: *{pc['name']}*\n🌐 IP: `{pc['ip']}`",
            reply_markup=main_menu(), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "👋 Привет! Я *PC Remote Bot*.\n\nОтправь IP-адрес компьютера:\n\n`192.168.X.X`",
            parse_mode="Markdown"
        )
        context.user_data["waiting_for"] = "ip"

async def cmd_connect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔌 Введи IP-адрес ПК:\n\n`192.168.X.X`", parse_mode="Markdown")
    context.user_data["waiting_for"] = "ip"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    waiting = context.user_data.get("waiting_for")

    if waiting == "ip":
        parts = text.split(".")
        if len(parts) == 4 and all(p.isdigit() for p in parts):
            context.user_data["temp_ip"] = text
            keyboard = [
                [InlineKeyboardButton("📶 Дома (Wi-Fi)", callback_data="mode_wifi"),
                 InlineKeyboardButton("🌍 Не дома (Telegram)", callback_data="mode_tg")]
            ]
            await update.message.reply_text(
                f"IP: `{text}`\n\nГде ты сейчас?",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown"
            )
            context.user_data["waiting_for"] = "mode"
        else:
            await update.message.reply_text("❌ Неверный формат. Введи IP вида `192.168.X.X`", parse_mode="Markdown")

    elif waiting == "name":
        context.user_data["temp_name"] = text
        ip = context.user_data.get("temp_ip", "")
        mode = context.user_data.get("temp_mode", "wifi")
        msg = await update.message.reply_text("⏳ Подключаюсь...")
        result = await send_to_pc(ip, 8765, "ping")
        if result.get("ok"):
            config["pcs"][str(chat_id)] = {"ip": ip, "port": 8765, "name": text, "mode": mode}
            save_config(config)
            context.user_data["waiting_for"] = None
            await msg.edit_text(
                f"✅ *Подключено!*\n\n🖥 ПК: *{text}*\n🌐 IP: `{ip}`",
                reply_markup=main_menu(), parse_mode="Markdown"
            )
        else:
            await msg.edit_text(f"❌ Не удалось подключиться к `{ip}`\n\nПроверь что агент запущен на ПК.", parse_mode="Markdown")
            context.user_data["waiting_for"] = "ip"

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    action = query.data
    pc = get_pc(chat_id)

    if action == "mode_wifi":
        context.user_data["temp_mode"] = "wifi"
        await query.edit_message_text("📶 *Режим Wi-Fi*\n\nКак назвать этот ПК?", parse_mode="Markdown")
        context.user_data["waiting_for"] = "name"
        return
    elif action == "mode_tg":
        context.user_data["temp_mode"] = "telegram"
        await query.edit_message_text("🌍 *Режим Telegram*\n\nКак назвать этот ПК?", parse_mode="Markdown")
        context.user_data["waiting_for"] = "name"
        return
    elif action == "change_pc":
        await query.edit_message_text("🔌 Введи новый IP-адрес ПК:\n\n`192.168.X.X`", parse_mode="Markdown")
        context.user_data["waiting_for"] = "ip"
        return
    elif action == "menu":
        if pc:
            await query.edit_message_text(f"🖥 *{pc['name']}*\nВыбери действие:", reply_markup=main_menu(), parse_mode="Markdown")
        return

    if not pc:
        await query.edit_message_text("❌ ПК не подключён. Напиши /connect")
        return

    if action == "stats":
        await query.edit_message_text("⏳ Загружаю статистику...")
        res = await send_to_pc(pc["ip"], pc["port"], "stats")
        if res.get("ok"):
            s = res["data"]
            text = (f"📊 *Ресурсы — {pc['name']}*\n\n"
                    f"🔲 CPU: `{s['cpu']}%`\n"
                    f"💾 RAM: `{s['ram']}%` ({s['ram_used']}/{s['ram_total']} ГБ)\n"
                    f"💿 Диск: `{s['disk']}%`\n"
                    f"🌡 Температура: `{s['temp']}°C`")
        else:
            text = f"❌ Ошибка: {res.get('error', 'нет связи')}"
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data="stats"),
                     InlineKeyboardButton("◀️ Назад", callback_data="menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif action == "processes":
        await query.edit_message_text("⏳ Загружаю процессы...")
        res = await send_to_pc(pc["ip"], pc["port"], "processes")
        if res.get("ok"):
            procs = res["data"][:10]
            lines = [f"⚙️ *Процессы — {pc['name']}*\n"]
            for p in procs:
                lines.append(f"`{p['name'][:18]:<18}` {p['cpu']}% / {p['ram']}MB")
            text = "\n".join(lines)
        else:
            text = f"❌ Ошибка: {res.get('error', 'нет связи')}"
        keyboard = [[InlineKeyboardButton("🔄 Обновить", callback_data="processes"),
                     InlineKeyboardButton("◀️ Назад", callback_data="menu")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif action == "sleep":
        await send_to_pc(pc["ip"], pc["port"], "sleep")
        await query.edit_message_text("💤 ПК уходит в сон",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu")]]))
    elif action == "restart":
        await send_to_pc(pc["ip"], pc["port"], "restart")
        await query.edit_message_text("🔄 ПК перезагружается через 5 сек",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu")]]))
    elif action == "shutdown":
        await send_to_pc(pc["ip"], pc["port"], "shutdown")
        await query.edit_message_text("⏻ ПК выключается через 5 сек",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="menu")]]))

def main():
    if PROXY:
        request = HTTPXRequest(proxy=PROXY)
        app = Application.builder().token(BOT_TOKEN).request(request).build()
    else:
        app = Application.builder().token(BOT_TOKEN).connect_timeout(30).read_timeout(30).write_timeout(30).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("connect", cmd_connect))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
