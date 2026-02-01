import telebot
import os
import shutil
import hashlib
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS = {718874310, 1341225592}
BASE_DIR = "storage"

bot = telebot.TeleBot(TOKEN)
os.makedirs(BASE_DIR, exist_ok=True)

user_states = {}      # отслеживание действий пользователя
callback_store = {}   # callback_id -> путь (относительный, без BASE_DIR и без .txt)
confirm_store = {}    # callback_id -> {"type": "file/folder", "folder_parts": [...], "file": ...}

# ===== HELPERS =====
def allowed(uid):
    return uid in ALLOWED_USERS

def read_file_lines(folder_parts, file):
    path = os.path.join(BASE_DIR, *folder_parts, f"{file}.txt")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines()

def save_file_lines(folder_parts, file, lines):
    path = os.path.join(BASE_DIR, *folder_parts, f"{file}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def make_callback_id(path):
    cbid = hashlib.md5(path.encode()).hexdigest()[:16]
    callback_store[cbid] = path
    return cbid

def safe_get_path(cbid, call):
    path = callback_store.get(cbid)
    if not path:
        bot.answer_callback_query(call.id, "❌ Путь недействителен. Открой папку снова.")
    return path

# ===== KEYBOARDS =====
def build_folder_keyboard(folder_parts):
    kb = InlineKeyboardMarkup()
    folder_path = os.path.join(BASE_DIR, *folder_parts)
    for f in os.listdir(folder_path):
        full_path = os.path.join(folder_path, f)
        if os.path.isdir(full_path):
            cbid = make_callback_id("/".join(folder_parts + [f]))
            kb.add(InlineKeyboardButton(f"📁 {f}", callback_data=f"folder:{cbid}"))
        elif f.endswith(".txt"):
            file_name = f[:-4]
            cbid = make_callback_id("/".join(folder_parts + [file_name]))
            kb.add(InlineKeyboardButton(f"📄 {file_name}", callback_data=f"file:{cbid}"))
            if allowed(user_states.get('uid', 0)):
                kb.add(InlineKeyboardButton(f"🗑 Удалить {file_name}", callback_data=f"confirm_delfile:{cbid}"))
    if allowed(user_states.get('uid', 0)):
        kb.add(
            InlineKeyboardButton("➕ Новый файл", callback_data="newfile:" + make_callback_id("/".join(folder_parts))),
            InlineKeyboardButton("➕ Новая папка", callback_data="mkfolder_in:" + make_callback_id("/".join(folder_parts))),
            InlineKeyboardButton("🗑 Удалить папку", callback_data="confirm_delfolder:" + make_callback_id("/".join(folder_parts)))
        )
    kb.add(InlineKeyboardButton("⬅ Назад", callback_data="folders" if len(folder_parts) == 1 else "folder:" + make_callback_id("/".join(folder_parts[:-1]))))
    return kb

def build_file_keyboard(folder_parts, file):
    lines = read_file_lines(folder_parts, file)
    kb = InlineKeyboardMarkup()
    for i, line in enumerate(lines):
        cbid = make_callback_id(f"{'/'.join(folder_parts)}/{file}:{i}")
        kb.add(
            InlineKeyboardButton(f"{i+1}. {line}", callback_data=f"line:{cbid}"),
            InlineKeyboardButton("🗑", callback_data=f"delline:{cbid}")
        )
    kb.add(
        InlineKeyboardButton("➕ Добавить строку", callback_data=f"addline:{make_callback_id('/'.join(folder_parts + [file]))}"),
        InlineKeyboardButton("⬅ Назад", callback_data=f"folder:{make_callback_id('/'.join(folder_parts))}")
    )
    return kb

def main_menu():
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("📁 Папки", callback_data="folders")
    )
    return kb

# ===== START =====
@bot.message_handler(commands=["start"])
def start(message):
    bot.send_message(
        message.chat.id,
        "👋 Файловый менеджер\n\nВыбери действие:",
        reply_markup=main_menu()
    )

# ===== CALLBACKS =====
@bot.callback_query_handler(func=lambda c: True)
def callbacks(call):
    data = call.data
    user_states['uid'] = call.from_user.id

    # Главное меню
    if data == "menu":
        bot.send_message(call.message.chat.id, "Выбери действие:", reply_markup=main_menu())

    # Папки
    elif data == "folders":
        kb = InlineKeyboardMarkup()
        for f in os.listdir(BASE_DIR):
            if os.path.isdir(os.path.join(BASE_DIR, f)):
                cbid = make_callback_id(f)
                kb.add(InlineKeyboardButton(f"📁 {f}", callback_data=f"folder:{cbid}"))
        if allowed(call.from_user.id):
            kb.add(InlineKeyboardButton("➕ Создать папку", callback_data="mkfolder"))
        kb.add(InlineKeyboardButton("⬅ Меню", callback_data="menu"))
        bot.send_message(call.message.chat.id, "📁 Папки:", reply_markup=kb)

    # Открытие папки
    elif data.startswith("folder:"):
        folder_id = data.split(":")[1]
        folder_path_str = safe_get_path(folder_id, call)
        if not folder_path_str: return
        folder_parts = folder_path_str.split("/")
        kb = build_folder_keyboard(folder_parts)
        bot.send_message(call.message.chat.id, f"📁 {'/'.join(folder_parts)}", reply_markup=kb)

    # Новый файл
    elif data.startswith("newfile:"):
        folder_id = data.split(":")[1]
        folder_path_str = safe_get_path(folder_id, call)
        if not folder_path_str: return
        folder_parts = folder_path_str.split("/")
        user_states[call.from_user.id] = {"action": "newfile_name", "folder_parts": folder_parts}
        bot.send_message(call.message.chat.id, "✏️ Введи имя нового файла (без .txt):")

    # Открыть файл
    elif data.startswith("file:"):
        file_id = data.split(":")[1]
        file_path_str = safe_get_path(file_id, call)
        if not file_path_str: return
        parts = file_path_str.split("/")
        folder_parts, file = parts[:-1], parts[-1]
        kb = build_file_keyboard(folder_parts, file)
        bot.send_message(call.message.chat.id, f"📄 {file}", reply_markup=kb)

    # Добавить строку
    elif data.startswith("addline:"):
        folder_file_id = data.split(":")[1]
        folder_file_str = safe_get_path(folder_file_id, call)
        if not folder_file_str: return
        path_parts = folder_file_str.split("/")
        folder_parts, file = path_parts[:-1], path_parts[-1]
        user_states[call.from_user.id] = {"action": "addline", "folder_parts": folder_parts, "file": file}
        bot.send_message(call.message.chat.id, "✏️ Введи текст новой строки:")

    # Подтверждение удаления файла
    elif data.startswith("confirm_delfile:"):
        file_id = data.split(":")[1]
        file_path_str = safe_get_path(file_id, call)
        if not file_path_str: return
        parts = file_path_str.split("/")
        folder_parts, file = parts[:-1], parts[-1]

        confirm_id = make_callback_id(file_path_str + "_confirm")
        confirm_store[confirm_id] = {"type": "file", "folder_parts": folder_parts, "file": file}

        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("Да ✅", callback_data=f"yesdelete:{confirm_id}"),
            InlineKeyboardButton("Нет ❌", callback_data=f"folder:{file_id}")
        )
        bot.send_message(call.message.chat.id, f"❗ Ты точно хочешь удалить файл '{file}'?", reply_markup=kb)

    # Подтверждение удаления папки
    elif data.startswith("confirm_delfolder:"):
        folder_id = data.split(":")[1]
        folder_path_str = safe_get_path(folder_id, call)
        if not folder_path_str: return
        folder_parts = folder_path_str.split("/")

        confirm_id = make_callback_id(folder_path_str + "_confirm")
        confirm_store[confirm_id] = {"type": "folder", "folder_parts": folder_parts}

        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("Да ✅", callback_data=f"yesdelete:{confirm_id}"),
            InlineKeyboardButton("Нет ❌", callback_data=f"folder:{folder_id}")
        )
        bot.send_message(call.message.chat.id, f"❗ Ты точно хочешь удалить папку '{folder_parts[-1]}'?", reply_markup=kb)

    # Подтвержденное удаление
    elif data.startswith("yesdelete:"):
        confirm_id = data.split(":")[1]
        info = confirm_store.pop(confirm_id, None)
        if not info:
            bot.answer_callback_query(call.id, "❌ Срок действия кнопки истёк.")
            return

        if info["type"] == "file":
            full_path = os.path.join(BASE_DIR, *info["folder_parts"], f"{info['file']}.txt")
            if os.path.exists(full_path):
                os.remove(full_path)
            kb = build_folder_keyboard(info["folder_parts"])
            bot.send_message(call.message.chat.id, f"🗑 Файл '{info['file']}' удалён", reply_markup=kb)

        elif info["type"] == "folder":
            full_path = os.path.join(BASE_DIR, *info["folder_parts"])
            if os.path.exists(full_path):
                shutil.rmtree(full_path)
            kb = InlineKeyboardMarkup()
            for f in os.listdir(BASE_DIR):
                if os.path.isdir(os.path.join(BASE_DIR, f)):
                    cbid = make_callback_id(f)
                    kb.add(InlineKeyboardButton(f"📁 {f}", callback_data=f"folder:{cbid}"))
            if allowed(call.from_user.id):
                kb.add(InlineKeyboardButton("➕ Создать папку", callback_data="mkfolder"))
            kb.add(InlineKeyboardButton("⬅ Меню", callback_data="menu"))
            bot.send_message(call.message.chat.id, f"🗑 Папка удалена", reply_markup=kb)

# ===== TEXT HANDLER =====
@bot.message_handler(func=lambda m: m.from_user.id in user_states)
def handle_text(message):
    state = user_states.pop(message.from_user.id)
    uid = message.from_user.id

    if state["action"] == "mkfolder":
        folder_parts = state["folder_parts"]
        name = message.text.strip()
        path = os.path.join(BASE_DIR, *folder_parts, name)
        os.makedirs(path, exist_ok=True)
        kb = build_folder_keyboard(folder_parts)
        bot.send_message(message.chat.id, f"✅ Папка '{name}' создана", reply_markup=kb)

    elif state["action"] == "newfile_name":
        folder_parts = state["folder_parts"]
        filename = message.text.strip()
        path = os.path.join(BASE_DIR, *folder_parts, f"{filename}.txt")
        if os.path.exists(path):
            bot.send_message(message.chat.id, "❌ Файл уже существует. Попробуй другое имя.")
            return
        user_states[uid] = {"action": "newfile_text", "folder_parts": folder_parts, "file": filename}
        bot.send_message(message.chat.id, "✏️ Введи первую строку файла:")

    elif state["action"] == "newfile_text":
        folder_parts = state["folder_parts"]
        file = state["file"]
        save_file_lines(folder_parts, file, [message.text])
        kb = build_file_keyboard(folder_parts, file)
        bot.send_message(message.chat.id, f"✅ Файл '{file}' создан", reply_markup=kb)

    elif state["action"] == "addline":
        folder_parts = state["folder_parts"]
        file = state["file"]
        lines = read_file_lines(folder_parts, file)
        lines.append(message.text)
        save_file_lines(folder_parts, file, lines)
        kb = build_file_keyboard(folder_parts, file)
        bot.send_message(message.chat.id, f"✅ Строка добавлена в '{file}'", reply_markup=kb)

# ===== RUN =====
print("Бот запущен")
bot.infinity_polling()
