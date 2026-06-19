import os
import sys
import json
import locale
from datetime import datetime
from dotenv import load_dotenv
from openai import OpenAI
import anthropic

load_dotenv()

HISTORY_FILE = "conversation_history.json"


def _ensure_utf8():
    """
    Принудительно включаем UTF-8 (оптимизировано для macOS / iMac).
    
    На macOS ошибка 'ascii' codec часто появляется, если в терминале
    переменные LANG / LC_ALL стоят в 'C', 'POSIX' или не-UTF8 локали.
    Это ломает anthropic / httpx при отправке русского текста.
    """
    try:
        # Force, don't just setdefault — we must override whatever the parent process gave us.
        os.environ["PYTHONIOENCODING"] = "utf-8"
        os.environ["PYTHONUTF8"] = "1"

        # macOS-friendly UTF-8 локали — force the best one we can
        candidates = ["en_US.UTF-8", "ru_RU.UTF-8", "UTF-8"]
        chosen = None
        for loc in candidates:
            try:
                locale.setlocale(locale.LC_ALL, loc)
                os.environ["LC_ALL"] = loc
                os.environ["LANG"] = loc
                chosen = loc
                break
            except Exception:
                continue
        if not chosen:
            # Last attempt
            os.environ["LC_ALL"] = "en_US.UTF-8"
            os.environ["LANG"] = "en_US.UTF-8"

        # Всегда пытаемся переобернуть stdout/stderr в UTF-8 (полезно и на macOS)
        import io
        for stream in ("stdout", "stderr"):
            s = getattr(sys, stream, None)
            if s and hasattr(s, "buffer"):
                try:
                    if getattr(s, "encoding", None) != "utf-8":
                        setattr(sys, stream, io.TextIOWrapper(s.buffer, encoding="utf-8", errors="replace"))
                except Exception:
                    pass

    except Exception:
        pass


_ensure_utf8()


def _safe_str(text) -> str:
    """
    Гарантирует чистую unicode-строку (UTF-8).
    На macOS (и особенно когда VPN/прокси в цепочке) очень важно,
    потому что при LANG=C / POSIX библиотеки падают с ascii codec.
    """
    if text is None:
        return ""
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    if isinstance(text, str):
        # Самая агрессивная очистка: убрать всё что не влезает в UTF-8
        try:
            return text.encode("utf-8", errors="replace").decode("utf-8")
        except Exception:
            pass
    # Последний fallback
    return str(text).encode("utf-8", errors="replace").decode("utf-8")

# ==================== КЛИЕНТЫ ДЛЯ ДВУХ РЕЖИМОВ ====================

def _create_openai_client() -> OpenAI:
    """Клиент для обычной модели через OpenAI-совместимый Chat Completions (ProxyAPI)."""
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or "https://api.proxyapi.ru/openai/v1"
    return OpenAI(api_key=api_key, base_url=base_url)

def _create_anthropic_client():
    """Клиент для думающей модели Claude через ProxyAPI."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    base_url = os.getenv("ANTHROPIC_BASE_URL") or "https://api.proxyapi.ru/anthropic"
    return anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url,
    )

openai_client = _create_openai_client()
anthropic_client = _create_anthropic_client()

# Дефолты
DEFAULT_OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
DEFAULT_ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-5"
DEFAULT_THINKING_BUDGET = int(os.getenv("ANTHROPIC_THINKING_BUDGET", "1500"))


def create_chat_session(backend: str = "anthropic", model: str = None, system_prompt: str = None, thinking_budget: int = None):
    """
    Создаёт новую сессию чата.
    backend: "anthropic" (думающая Claude) или "openai" (обычная через Chat Completions).
    """
    if backend == "openai":
        model = model or DEFAULT_OPENAI_MODEL
    else:
        model = model or DEFAULT_ANTHROPIC_MODEL

    # Clean system prompt with the strongest available cleaner
    base_system = system_prompt or "Ты — полезный и дружелюбный ассистент. Отвечай на русском языке."
    try:
        safe_system = _max_clean(base_system)
    except Exception:
        try:
            safe_system = _clean_text_for_anthropic(base_system)
        except Exception:
            safe_system = _safe_str(base_system)

    return {
        "backend": backend,
        "model": model,
        "messages": [],
        "system": safe_system,
        "thinking_budget": thinking_budget or DEFAULT_THINKING_BUDGET,
        "thinking_enabled": False,
    }


# ==================== ПЕРСИСТЕНТНОСТЬ ИСТОРИИ ====================

def load_history() -> list:
    """Загружает историю диалога из файла (между запусками программы)."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            msgs = data.get("messages", [])
            # Очищаем загруженную историю, чтобы не тащить битые строки
            return [
                {"role": m.get("role"), "content": _clean_text_for_anthropic(m.get("content", "")) if not isinstance(m.get("content"), list) else m.get("content")}
                for m in msgs
            ]
    except Exception:
        return []

def save_history(messages: list):
    """Сохраняет текущую историю в файл."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "saved_at": datetime.now().isoformat(),
                "messages": messages
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[WARN] Не удалось сохранить историю: {e}")


def _clean_text_for_anthropic(text: str) -> str:
    """Глубокая очистка текста специально перед отправкой в Anthropic API на macOS."""
    if not text:
        return ""
    s = _safe_str(text)
    # Удаляем проблемные управляющие символы, оставляем только печатаемые + базовые whitespace
    s = "".join(ch if ch.isprintable() or ch in "\n\t\r" else " " for ch in s)
    # Убираем surrogate escapes (часто появляются при плохом decode)
    s = s.encode("utf-8", "replace").decode("utf-8")
    # Нормализация
    import unicodedata
    try:
        s = unicodedata.normalize("NFKC", s)
    except Exception:
        pass
    # Ещё один round-trip
    s = s.encode("utf-8", "replace").decode("utf-8")
    return s


def _max_clean(text: str) -> str:
    """
    Самая агрессивная очистка строки для macOS.
    Несколько принудительных round-trip через UTF-8.
    Используется прямо перед отправкой в Anthropic, чтобы победить 'ascii' codec.
    """
    if text is None:
        return ""
    s = _safe_str(text)
    for _ in range(4):
        s = s.encode("utf-8", "replace").decode("utf-8")
    return s


def _sanitize_session_for_anthropic(session: dict):
    """Полностью очищает system и все сообщения в сессии перед вызовом Anthropic."""
    if "system" in session:
        session["system"] = _clean_text_for_anthropic(session.get("system"))
    if "messages" in session:
        cleaned = []
        for m in session["messages"]:
            role = m.get("role")
            content = m.get("content")
            if isinstance(content, list):
                new_blocks = []
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "text":
                        new_blocks.append({"type": "text", "text": _clean_text_for_anthropic(b.get("text", ""))})
                    else:
                        new_blocks.append(b)
                cleaned.append({"role": role, "content": new_blocks})
            else:
                cleaned.append({"role": role, "content": _clean_text_for_anthropic(content)})
        session["messages"] = cleaned


def _to_anthropic_messages(messages):
    """Конвертирует историю в формат Anthropic с агрессивной очисткой под macOS."""
    result = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if isinstance(content, list):
            # Уже в блочном формате — чистим каждый text
            cleaned_blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    cleaned_blocks.append({
                        "type": "text",
                        "text": _clean_text_for_anthropic(block.get("text", ""))
                    })
                else:
                    cleaned_blocks.append(block)
            result.append({"role": role, "content": cleaned_blocks})
        else:
            safe_text = _clean_text_for_anthropic(content)
            result.append({
                "role": role,
                "content": [{"type": "text", "text": safe_text}]
            })
    return result


def _send_openai(session: dict, user_message: str) -> str:
    """Обычная модель через OpenAI-совместимый Chat Completions."""
    session["messages"].append({"role": "user", "content": user_message})

    # Подготавливаем сообщения для OpenAI (с system если есть)
    msgs = []
    if session.get("system"):
        msgs.append({"role": "system", "content": _safe_str(session["system"])})
    msgs.extend(session["messages"])

    try:
        response = openai_client.chat.completions.create(
            model=session["model"],
            messages=msgs,
            max_tokens=2048,
            timeout=60,
        )
        answer = response.choices[0].message.content or ""
    except Exception as e:
        raise RuntimeError(f"OpenAI API ошибка: {e}")

    session["messages"].append({"role": "assistant", "content": _safe_str(answer)})
    return answer


def _send_anthropic_normal(session: dict, user_message: str) -> str:
    """Обычная отправка в Anthropic без thinking (для режима 'обычная')."""
    cleaned_user = _clean_text_for_anthropic(user_message)
    session["messages"].append({"role": "user", "content": cleaned_user})

    _sanitize_session_for_anthropic(session)

    # Use the strongest cleaner for the actual request
    def _max_clean_local(t: str) -> str:
        if t is None:
            return ""
        s = _safe_str(t)
        for _ in range(4):
            s = s.encode("utf-8", "replace").decode("utf-8")
        return s

    system_prompt = _max_clean_local(session.get("system") or "")

    # Build a super-clean messages list
    clean_messages = []
    for m in session.get("messages", []):
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            new_blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    new_blocks.append({"type": "text", "text": _max_clean_local(block.get("text", ""))})
                else:
                    new_blocks.append(block)
            clean_messages.append({"role": role, "content": new_blocks})
        else:
            clean_messages.append({"role": role, "content": _max_clean_local(content)})

    # Precompute ASCII-safe fallback
    def _ascii_safe(msgs, sp):
        safe_msgs = []
        for m in msgs:
            if isinstance(m.get("content"), list):
                nb = []
                for b in m["content"]:
                    if isinstance(b, dict) and b.get("type") == "text":
                        nb.append({"type": "text", "text": "".join(c if ord(c) < 128 else "?" for c in _max_clean_local(b.get("text", "")))})
                    else:
                        nb.append(b)
                safe_msgs.append({"role": m["role"], "content": nb})
            else:
                safe_msgs.append({"role": m["role"], "content": "".join(c if ord(c) < 128 else "?" for c in _max_clean_local(m.get("content", "")))})
        safe_sp = "".join(c if ord(c) < 128 else "?" for c in _max_clean_local(sp)) if sp else None
        return safe_sp, safe_msgs

    ascii_sp, ascii_msgs = _ascii_safe(clean_messages, system_prompt)

    try:
        response = anthropic_client.messages.create(
            model=session["model"],
            system=system_prompt if system_prompt else None,
            messages=clean_messages,
            max_tokens=2048,
            timeout=60,
        )
        text = ""
        for block in response.content:
            if block.type == "text":
                text += block.text or ""
    except Exception as e:
        # If it smells like the ascii/encoding problem, retry with ASCII-only payload
        low = str(e).lower()
        if isinstance(e, UnicodeEncodeError) or any(k in low for k in ("ascii", "codec", "encode", "ordinal")):
            try:
                response = anthropic_client.messages.create(
                    model=session["model"],
                    system=ascii_sp if ascii_sp else None,
                    messages=ascii_msgs,
                    max_tokens=2048,
                    timeout=60,
                )
                text = ""
                for block in response.content:
                    if block.type == "text":
                        text += block.text or ""
            except Exception as e2:
                raise RuntimeError(f"Anthropic API ошибка (даже после ASCII-очистки): {e2}")
        else:
            raise RuntimeError(f"Anthropic API ошибка: {e}")

    session["messages"].append({"role": "assistant", "content": _safe_str(text)})
    return text


def send_message(session: dict, user_message: str) -> str:
    """
    Универсальная отправка для обычного режима (без показа reasoning).
    Выбирает backend на основе session["backend"].
    """
    backend = session.get("backend", "anthropic")

    if backend == "openai":
        return _send_openai(session, user_message)
    else:
        return _send_anthropic_normal(session, user_message)


def send_message_with_thinking(session: dict, user_message: str, budget: int = None) -> tuple[str, str]:
    """
    Функция взаимодействия с думающей моделью (Claude от Anthropic).
    Интегрирована из testagent.py. Используется только в режиме "думающая модель".
    """
    cleaned_user = _clean_text_for_anthropic(user_message)
    session["messages"].append({"role": "user", "content": cleaned_user})

    _sanitize_session_for_anthropic(session)

    budget = budget or session.get("thinking_budget") or DEFAULT_THINKING_BUDGET

    # === Maximum defense sanitization right before the API call ===
    # We force every single text field through UTF-8 multiple times.
    # This has proven necessary on some macOS setups (especially with VPNs or custom terminals).
    def _max_clean(t: str) -> str:
        if t is None:
            return ""
        s = _safe_str(t)
        # Several forced round-trips
        for _ in range(4):
            s = s.encode("utf-8", "replace").decode("utf-8")
        return s

    system_prompt = _max_clean(session.get("system") or "")

    # Completely rebuild the messages payload that will be sent
    payload_messages = []
    for m in session.get("messages", []):
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, list):
            new_blocks = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    new_blocks.append({
                        "type": "text",
                        "text": _max_clean(block.get("text", ""))
                    })
                else:
                    new_blocks.append(block)
            payload_messages.append({"role": role, "content": new_blocks})
        else:
            payload_messages.append({"role": role, "content": _max_clean(content)})

    # Prepare an ASCII-only fallback payload in advance. We will use it if the normal call fails
    # with any kind of encoding / codec / unicode error (very common on macOS with certain locales).
    def _make_ascii_safe_payload(msgs, sys_prompt):
        safe_msgs = []
        for m in msgs:
            if isinstance(m.get("content"), list):
                new_blocks = []
                for b in m["content"]:
                    if isinstance(b, dict) and b.get("type") == "text":
                        txt = _max_clean(b.get("text", ""))
                        safe = "".join(c if ord(c) < 128 else "?" for c in txt)
                        new_blocks.append({"type": "text", "text": safe})
                    else:
                        new_blocks.append(b)
                safe_msgs.append({"role": m["role"], "content": new_blocks})
            else:
                txt = _max_clean(m.get("content", ""))
                safe = "".join(c if ord(c) < 128 else "?" for c in txt)
                safe_msgs.append({"role": m["role"], "content": safe})
        safe_sys = "".join(c if ord(c) < 128 else "?" for c in _max_clean(sys_prompt)) if sys_prompt else None
        return safe_sys, safe_msgs

    ascii_system_fallback, ascii_messages_fallback = _make_ascii_safe_payload(payload_messages, system_prompt)

    try:
        response = anthropic_client.messages.create(
            model=session["model"],
            system=system_prompt if system_prompt else None,
            messages=payload_messages,
            max_tokens=4096,
            thinking={
                "type": "enabled",
                "budget_tokens": budget,
            },
            timeout=120,
        )
    except Exception as e:
        # Decide if this looks like an encoding problem
        is_encode_error = isinstance(e, UnicodeEncodeError)
        msg = str(e)
        low = msg.lower()
        looks_like_codec = any(k in low for k in ("ascii", "codec", "encode", "ordinal not in range", "utf-8", "unicode"))

        if is_encode_error or looks_like_codec:
            # Use the prebuilt ASCII-safe version and retry
            try:
                response = anthropic_client.messages.create(
                    model=session["model"],
                    system=ascii_system_fallback if ascii_system_fallback else None,
                    messages=ascii_messages_fallback,
                    max_tokens=4096,
                    thinking={
                        "type": "enabled",
                        "budget_tokens": budget,
                    },
                    timeout=120,
                )
            except Exception as e2:
                raise RuntimeError(f"Anthropic thinking API ошибка (даже после полной ASCII-очистки): {e2}")
        else:
            raise RuntimeError(f"Anthropic thinking API ошибка: {e}")

    # Разбор ThinkingBlock + TextBlock
    thinking_parts = []
    final_parts = []

    for block in response.content:
        if block.type == "thinking":
            th = getattr(block, "thinking", None)
            if th:
                thinking_parts.append(th)
        if hasattr(block, "thinking") and getattr(block, "thinking", None) and block.type != "thinking":
            thinking_parts.append(block.thinking)
        if block.type == "text":
            txt = getattr(block, "text", None)
            if txt:
                final_parts.append(txt)

    thinking_text = "\n\n".join([_safe_str(t) for t in thinking_parts if t]).strip() or "(модель не вернула размышления)"
    final_answer = _safe_str("".join(final_parts)).strip()

    # Store using the strongest cleaner we have
    try:
        stored_answer = _max_clean(final_answer)
    except Exception:
        stored_answer = _safe_str(final_answer)
    session["messages"].append({"role": "assistant", "content": stored_answer})

    # Попробуем показать usage, если есть (показатели)
    usage = getattr(response, "usage", None)
    if usage:
        print(f"[usage] input={getattr(usage, 'input_tokens', '?')} output={getattr(usage, 'output_tokens', '?')}")

    return thinking_text, final_answer


# ==================== ИНТЕРАКТИВНЫЙ ДИАЛОГ ====================

def _print_thinking(thinking: str, answer: str):
    """
    Красивый вывод результата от думающей модели (reasoning).
    """
    print("\n" + "═" * 60)
    print("🧠  РАЗМЫШЛЕНИЯ МОДЕЛИ (thinking / reasoning)")
    print("═" * 60)
    print(_safe_str(thinking))
    print("\n" + "─" * 60)
    print("💬  ОТВЕТ")
    print("─" * 60)
    print(_safe_str(answer))
    print("═" * 60 + "\n")


def select_mode():
    """
    Выбор режима в начале работы программы.
    По умолчанию — думающая модель (Claude 4.5 Sonnet с reasoning).
    """
    print("=== Выбор режима работы ===")
    print("1. Думающая модель (Claude 4.5 Sonnet + отображение reasoning) — по умолчанию")
    print("2. Обычная модель (OpenAI-совместимый Chat Completions)")
    choice = input("Выберите режим [1]: ").strip()

    if choice == "" or choice == "1":
        print("\n✓ Выбран режим: ДУМАЮЩАЯ (Claude 4.5 Sonnet + reasoning)\n")
        return "anthropic"
    else:
        print("\n✓ Выбран режим: ОБЫЧНАЯ (OpenAI Chat Completions)\n")
        return "openai"


def print_startup_info(session: dict, history_loaded: int):
    """Понятные логи запуска (соответствует требованиям)."""
    print("=== TextAgent — запуск ===")
    print(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Backend: {session['backend'].upper()}  (ProxyAPI)")
    print(f"Model:   {session['model']}")
    if session["backend"] == "anthropic":
        print(f"Thinking: enabled, budget={session['thinking_budget']} токенов (reasoning)")
    else:
        print("Thinking: disabled (обычный Chat Completions)")
    proxy = os.getenv("ANTHROPIC_BASE_URL") if session["backend"] == "anthropic" else os.getenv("OPENAI_BASE_URL")
    print(f"Proxy URL: {proxy or 'по умолчанию'}")
    if history_loaded > 0:
        print(f"История: загружено {history_loaded} сообщений из {HISTORY_FILE}")
    else:
        print("История: новая сессия (будет сохранена в conversation_history.json)")
    print("========================\n")


if __name__ == "__main__":
    print("=== Консольный ассистент через ProxyAPI ===\n")

    # === 1. Выбор режима в начале (по умолчанию — думающая) ===
    backend = select_mode()

    # Создаём сессию с правильным backend
    session = create_chat_session(
        backend=backend,
        system_prompt="Ты — полезный и дружелюбный ассистент. Отвечай на русском языке."
    )

    # === 2. Загрузка истории между запусками ===
    previous_messages = load_history()
    if previous_messages:
        session["messages"] = previous_messages
    history_loaded_count = len(session["messages"])

    # === 3. Настройка режима ===
    if backend == "anthropic":
        session["thinking_enabled"] = True
        show_thinking = True
    else:
        session["thinking_enabled"] = False
        show_thinking = False

    # === 4. Понятные логи запуска ===
    print_startup_info(session, history_loaded_count)

    print("Начните диалог. Введите 'exit' / 'выход' / 'quit' для выхода.")
    print("Команды:")
    if backend == "anthropic":
        print("  /thinking off          — временно скрыть reasoning")
        print("  /thinking 2000         — изменить бюджет токенов reasoning")
    else:
        print("  (в обычном режиме reasoning не доступен)")
    print("  /model <название>")
    print("  /system <новый промпт>\n")

    # === 5. Основной цикл ===
    try:
        while True:
            try:
                user_input = input("Вы: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[INFO] Прерывание. Сохраняю историю...")
                save_history(session["messages"])
                print("Диалог завершён.")
                break

            if not user_input:
                continue

            # Корректная обработка команд выхода
            if user_input.lower() in ("exit", "выход", "quit", "q"):
                print("[INFO] Команда выхода. Сохраняю историю...")
                save_history(session["messages"])
                print("Диалог завершён.")
                break

            lower = user_input.lower()

            # Команды управления (работают в зависимости от режима)
            if lower.startswith("/thinking"):
                if session["backend"] != "anthropic":
                    print("Эта команда доступна только в режиме думающей модели.\n")
                    continue
                parts = user_input.split(maxsplit=1)
                if len(parts) > 1:
                    arg = parts[1].strip().lower()
                    if arg in ("on", "true", "yes"):
                        show_thinking = True
                        session["thinking_enabled"] = True
                        print("✓ Thinking / reasoning ВКЛЮЧЁН\n")
                    elif arg in ("off", "false", "no"):
                        show_thinking = False
                        session["thinking_enabled"] = False
                        print("✓ Thinking / reasoning ВЫКЛЮЧЕН\n")
                    elif arg.isdigit():
                        budget = int(arg)
                        session["thinking_budget"] = budget
                        show_thinking = True
                        session["thinking_enabled"] = True
                        print(f"✓ Бюджет reasoning изменён: {budget} токенов\n")
                    else:
                        print("Используйте: /thinking off | 1500 | 2000 ...\n")
                else:
                    status = "ON" if show_thinking else "OFF"
                    print(f"Thinking: {status}, бюджет={session['thinking_budget']}\n")
                continue

            if lower.startswith("/model "):
                new_model = user_input.split(maxsplit=1)[1].strip()
                session["model"] = new_model
                print(f"✓ Модель изменена на: {new_model}\n")
                continue

            if lower.startswith("/system "):
                new_system = user_input.split(maxsplit=1)[1].strip()
                session["system"] = new_system
                print("✓ System prompt обновлён.\n")
                continue

            # === Отправка сообщения ===
            try:
                if (show_thinking or session.get("thinking_enabled")) and session["backend"] == "anthropic":
                    thinking, answer = send_message_with_thinking(session, user_input)
                    _print_thinking(thinking, answer)
                else:
                    reply = send_message(session, user_input)
                    print(f"AI: {reply}\n")

                # Сохраняем историю после каждого обмена (чтобы не потерять)
                save_history(session["messages"])

            except Exception as e:
                print(f"[ERROR] Ошибка при запросе к API: {e}")
                print("Возможные причины: неверный ключ, проблемы с сетью/ProxyAPI, таймаут.\n")
                # Не прерываем диалог — пользователь может продолжить

    finally:
        # Гарантированно сохраняем историю при любом выходе
        save_history(session["messages"])