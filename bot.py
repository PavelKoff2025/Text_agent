import os
import sys
import asyncio
import logging
import html
import re

# === UTF-8 принудительно (macOS/iMac) ===
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"
os.environ["LC_ALL"] = "en_US.UTF-8"
os.environ["LANG"] = "en_US.UTF-8"

from dotenv import load_dotenv

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from text_agent import (
    create_chat_session,
    send_message,
    send_message_with_thinking,
    _max_clean,
    _clean_text_for_anthropic,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Хранилище сессий: chat_id -> session dict
user_sessions: dict[int, dict] = {}


# ──────────────────────────────────────────────
# Markdown → Telegram HTML
# ──────────────────────────────────────────────

def _md_to_html(text: str) -> str:
    """
    Конвертирует базовую markdown-разметку в Telegram HTML.
    Порядок важен: сначала экранируем HTML-символы, потом вставляем теги.
    """
    # 1. Экранируем HTML-спецсимволы (чтобы < > & неломали parse_mode=HTML)
    text = html.escape(text)

    # 2. Заголовки ### ## # → жирный текст (однострочные)
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)

    # 3. Жирный: **text** и __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text, flags=re.DOTALL)
    text = re.sub(r'__(.+?)__',     r'<b>\1</b>', text, flags=re.DOTALL)

    # 4. Курсив: *text* и _text_ (не задеваем уже вставленные теги)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)',       r'<i>\1</i>', text)

    # 5. Инлайн-код: `code`
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # 6. Маркированные списки: "- " → "• "
    text = re.sub(r'^[ \t]*[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 7. Горизонтальные линии --- или *** → пустая строка
    text = re.sub(r'^[-*]{3,}$', '', text, flags=re.MULTILINE)

    return text.strip()


# ──────────────────────────────────────────────
# Клавиатуры
# ──────────────────────────────────────────────

def main_keyboard() -> InlineKeyboardMarkup:
    """Главная клавиатура с основными действиями."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🧠 Думающая модель", callback_data="mode:thinking"),
            InlineKeyboardButton("💬 Обычная модель",  callback_data="mode:normal"),
        ],
        [
            InlineKeyboardButton("🔄 Сбросить историю", callback_data="action:reset"),
            InlineKeyboardButton("📊 Статус",           callback_data="action:status"),
        ],
    ])


def mode_keyboard(current_backend: str) -> InlineKeyboardMarkup:
    """Клавиатура переключения режимов с отметкой текущего."""
    thinking_label = "✅ 🧠 Думающая (Claude)" if current_backend == "anthropic" else "🧠 Думающая (Claude)"
    normal_label   = "✅ 💬 Обычная (GPT)"    if current_backend == "openai"    else "💬 Обычная (GPT)"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(thinking_label, callback_data="mode:thinking")],
        [InlineKeyboardButton(normal_label,   callback_data="mode:normal")],
    ])


# ──────────────────────────────────────────────
# История
# ──────────────────────────────────────────────

def _history_path(chat_id: int) -> str:
    return f"history_{chat_id}.json"


def _load_history_for_chat(chat_id: int) -> list:
    import json
    path = _history_path(chat_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_msgs = data.get("messages", [])
            cleaned = []
            for m in raw_msgs:
                role = m.get("role")
                content = m.get("content")
                if isinstance(content, list):
                    new_blocks = []
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            txt = b.get("text", "")
                            for _ in range(3):
                                txt = txt.encode("utf-8", "replace").decode("utf-8")
                            new_blocks.append({"type": "text", "text": txt})
                        else:
                            new_blocks.append(b)
                    cleaned.append({"role": role, "content": new_blocks})
                else:
                    txt = content or ""
                    for _ in range(3):
                        txt = txt.encode("utf-8", "replace").decode("utf-8")
                    cleaned.append({"role": role, "content": txt})
            return cleaned
    except Exception:
        return []


def _save_history_for_chat(chat_id: int, messages: list):
    import json
    from datetime import datetime
    try:
        with open(_history_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(
                {"saved_at": datetime.now().isoformat(), "messages": messages},
                f, ensure_ascii=False, indent=2,
            )
    except Exception as e:
        logger.warning(f"Не удалось сохранить историю для {chat_id}: {e}")


# ──────────────────────────────────────────────
# Сессии
# ──────────────────────────────────────────────

def get_session(chat_id: int) -> dict:
    if chat_id not in user_sessions:
        session = create_chat_session(backend="anthropic")
        session["thinking_enabled"] = True

        previous = _load_history_for_chat(chat_id)
        if previous:
            session["messages"] = [
                {
                    "role": m.get("role"),
                    "content": _max_clean(m.get("content")) if isinstance(m.get("content"), str) else m.get("content"),
                }
                for m in previous
            ]

        user_sessions[chat_id] = session
    return user_sessions[chat_id]


# ──────────────────────────────────────────────
# Хелпер: индикатор «печатает»
# ──────────────────────────────────────────────

async def _typing_loop(context: ContextTypes.DEFAULT_TYPE, chat_id: int, stop_event: asyncio.Event):
    """Периодически шлёт ChatAction.TYPING пока stop_event не выставлен."""
    try:
        while not stop_event.is_set():
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            try:
                await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=4.5)
            except asyncio.TimeoutError:
                pass
    except Exception:
        pass


# ──────────────────────────────────────────────
# Команды
# ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    mode_label = "🧠 ДУМАЮЩАЯ (Claude 4.5 Sonnet)" if session["backend"] == "anthropic" else "💬 ОБЫЧНАЯ"
    history_count = len(session.get("messages", []))
    history_note = f"История: {history_count} сообщений загружено." if history_count else "История: новая сессия."

    text = (
        "👋 <b>Привет! Я твой ИИ-ассистент в Telegram.</b>\n\n"
        f"Текущий режим: <b>{mode_label}</b>\n"
        f"{history_note}\n\n"
        "Просто пиши сообщения, а кнопки ниже помогут управлять режимами."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    await _send_status(update.message.reply_text, session)


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await _do_reset(chat_id)
    await update.message.reply_text(
        "✅ История диалога сброшена. Начинаем с чистого листа!",
        reply_markup=main_keyboard(),
    )


async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    args = context.args
    if not args:
        await update.message.reply_text(
            "Выбери режим:",
            reply_markup=mode_keyboard(session["backend"]),
        )
        return

    choice = args[0].lower()
    msg = await _apply_mode(chat_id, choice)
    session = get_session(chat_id)
    await update.message.reply_text(msg, reply_markup=mode_keyboard(session["backend"]))


# ──────────────────────────────────────────────
# Callback-кнопки
# ──────────────────────────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    data = query.data

    if data.startswith("mode:"):
        choice = data.split(":", 1)[1]
        msg = await _apply_mode(chat_id, choice)
        session = get_session(chat_id)
        await query.edit_message_text(msg, reply_markup=mode_keyboard(session["backend"]))

    elif data == "action:reset":
        await _do_reset(chat_id)
        await query.edit_message_text(
            "✅ История диалога сброшена. Начинаем с чистого листа!",
            reply_markup=main_keyboard(),
        )

    elif data == "action:status":
        session = get_session(chat_id)
        text = _status_text(session)
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


# ──────────────────────────────────────────────
# Основной обработчик сообщений
# ──────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    # Чистим входящий текст
    raw_text = update.message.text or ""
    try:
        user_text = _max_clean(raw_text)
    except Exception:
        try:
            user_text = _clean_text_for_anthropic(raw_text)
        except Exception:
            user_text = raw_text.encode("utf-8", "replace").decode("utf-8")

    # Запускаем индикатор «печатает» в фоне
    stop_typing = asyncio.Event()
    typing_task = asyncio.create_task(_typing_loop(context, chat_id, stop_typing))

    try:
        if session.get("backend") == "anthropic" and session.get("thinking_enabled", False):
            thinking, answer = await asyncio.get_event_loop().run_in_executor(
                None, lambda: send_message_with_thinking(session, user_text)
            )

            stop_typing.set()
            await typing_task

            # Reasoning — отдельным сообщением (тоже рендерим как HTML)
            if thinking and thinking != "(модель не вернула размышления)":
                safe_thinking = html.escape(thinking)
                if len(safe_thinking) > 3800:
                    safe_thinking = safe_thinking[:3800] + "\n<i>…(обрезано)</i>"
                await update.message.reply_text(
                    f"🧠 <b>Размышления модели:</b>\n\n{safe_thinking}",
                    parse_mode=ParseMode.HTML,
                )

            # Основной ответ: конвертируем markdown → HTML
            html_answer = _md_to_html(answer)
            await _send_long(update, html_answer, parse_mode=ParseMode.HTML)

        else:
            answer = await asyncio.get_event_loop().run_in_executor(
                None, lambda: send_message(session, user_text)
            )

            stop_typing.set()
            await typing_task

            html_answer = _md_to_html(answer)
            await _send_long(update, html_answer, parse_mode=ParseMode.HTML)

        _save_history_for_chat(chat_id, session.get("messages", []))

    except Exception as e:
        stop_typing.set()
        await typing_task
        logger.exception("Ошибка при обработке сообщения")
        await update.message.reply_text(
            f"⚠️ Ошибка: {str(e)[:300]}",
            reply_markup=main_keyboard(),
        )


# ──────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────

async def _send_long(update: Update, text: str, parse_mode: str = None, chunk: int = 4000):
    """Отправляет текст, разбивая на части если > chunk символов."""
    if len(text) <= chunk:
        await update.message.reply_text(text, parse_mode=parse_mode, reply_markup=main_keyboard())
        return
    # Разбиваем по абзацам, чтобы не резать на полуслове
    parts = []
    current = ""
    for paragraph in text.split("\n\n"):
        if len(current) + len(paragraph) + 2 > chunk:
            if current:
                parts.append(current.strip())
            current = paragraph
        else:
            current = (current + "\n\n" + paragraph) if current else paragraph
    if current:
        parts.append(current.strip())

    for i, part in enumerate(parts):
        kb = main_keyboard() if i == len(parts) - 1 else None
        await update.message.reply_text(part, parse_mode=parse_mode, reply_markup=kb)


async def _apply_mode(chat_id: int, choice: str) -> str:
    session = get_session(chat_id)
    if choice in ("thinking", "claude", "anthropic"):
        session["backend"] = "anthropic"
        session["thinking_enabled"] = True
        session["model"] = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
        return "✅ Режим: <b>🧠 Думающая модель</b> (Claude 4.5 Sonnet + reasoning)"
    elif choice in ("normal", "openai", "gpt"):
        session["backend"] = "openai"
        session["thinking_enabled"] = False
        session["model"] = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return "✅ Режим: <b>💬 Обычная модель</b> (GPT-4o mini)"
    return "❓ Неизвестный режим."


async def _do_reset(chat_id: int):
    current = get_session(chat_id)
    backend = current.get("backend", "anthropic")
    new_session = create_chat_session(backend=backend)
    if backend == "anthropic":
        new_session["thinking_enabled"] = True
    user_sessions[chat_id] = new_session
    _save_history_for_chat(chat_id, [])


def _status_text(session: dict) -> str:
    mode_name = "🧠 ДУМАЮЩАЯ (Claude + reasoning)" if session["backend"] == "anthropic" else "💬 ОБЫЧНАЯ (GPT)"
    budget_info = f"\n🪙 Бюджет reasoning: <b>{session.get('thinking_budget', 1500)}</b> токенов" if session["backend"] == "anthropic" else ""
    msgs = len(session.get("messages", []))
    return (
        f"📊 <b>Статус</b>\n\n"
        f"Режим: <b>{mode_name}</b>\n"
        f"Модель: <code>{session['model']}</code>"
        f"{budget_info}\n"
        f"📝 Сообщений в истории: <b>{msgs}</b>"
    )


async def _send_status(reply_fn, session: dict):
    await reply_fn(_status_text(session), parse_mode=ParseMode.HTML, reply_markup=main_keyboard())


# ──────────────────────────────────────────────
# main
# ──────────────────────────────────────────────

async def post_init(application):
    logger.info("Telegram бот запущен и готов к работе.")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN не найден в .env")
        return

    app = (
        ApplicationBuilder()
        .token(token)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start",    start))
    app.add_handler(CommandHandler("mode",     mode_cmd))
    app.add_handler(CommandHandler("reset",    reset_cmd))
    app.add_handler(CommandHandler("status",   status_cmd))
    app.add_handler(CommandHandler("thinking", _thinking_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запускается… Нажми Ctrl+C для остановки.")
    app.run_polling()


async def _thinking_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Устанавливает бюджет токенов для reasoning."""
    chat_id = update.effective_chat.id
    session = get_session(chat_id)

    if session["backend"] != "anthropic":
        await update.message.reply_text(
            "Бюджет thinking доступен только в режиме думающей модели.",
            reply_markup=mode_keyboard(session["backend"]),
        )
        return

    args = context.args
    if not args or not args[0].isdigit():
        await update.message.reply_text("Используй: /thinking 1500")
        return

    budget = int(args[0])
    session["thinking_budget"] = budget
    session["thinking_enabled"] = True
    await update.message.reply_text(
        f"✅ Бюджет размышлений: <b>{budget}</b> токенов",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard(),
    )


if __name__ == "__main__":
    main()
