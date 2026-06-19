import os
from openai import OpenAI
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла (если есть)
load_dotenv()

# Инициализация клиента
# Поддерживает как официальный OpenAI, так и совместимые API (ProxyAPI.ru, Groq, OpenRouter, Ollama и др.)
# Если вы в регионе, где OpenAI заблокирован — используйте OPENAI_BASE_URL
def _create_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")  # например: https://api.proxyapi.ru/openai/v1
    return OpenAI(api_key=api_key, base_url=base_url)

client = _create_client()

# Определяем текущего провайдера для сообщений
def _get_provider_info() -> tuple[str, str]:
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    if not base_url:
        return "OpenAI (официальный)", "https://api.openai.com/v1"
    if "proxyapi" in base_url.lower():
        return "ProxyAPI.ru", base_url
    if "groq" in base_url.lower():
        return "Groq", base_url
    if "openrouter" in base_url.lower():
        return "OpenRouter", base_url
    if "localhost" in base_url or "127.0.0.1" in base_url:
        return "Ollama (локально)", base_url
    return "Совместимый провайдер", base_url

CURRENT_PROVIDER, CURRENT_BASE_URL = _get_provider_info()


def create_chat_session(model: str = None, system_prompt: str = None):
    """
    Создаёт новую сессию чата с поддержкой сохранения контекста.
    
    Если model не указан — берётся из OPENAI_MODEL или выбирается разумный default
    в зависимости от провайдера.
    
    Возвращает словарь с историей сообщений, который нужно передавать
    в send_message() для поддержания диалога.
    """
    messages = []
    
    if model is None:
        model = os.getenv("OPENAI_MODEL") or _get_default_model()

    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    
    return {
        "model": model,
        "messages": messages
    }


def _get_default_model() -> str:
    """Выбирает разумную модель по умолчанию в зависимости от провайдера."""
    base = os.getenv("OPENAI_BASE_URL", "").lower()
    if "proxyapi" in base:
        return "gpt-4o-mini"               # настоящие модели OpenAI через прокси
    if "groq" in base:
        return "llama-3.3-70b-versatile"   # или "llama-3.1-8b-instant" для скорости
    if "openrouter" in base:
        return "meta-llama/llama-3.1-70b-instruct"
    if "localhost" in base or "127.0.0.1" in base:
        return "llama3.2"                  # или имя модели, которую вы скачали в ollama
    # По умолчанию пытаемся использовать дешёвую модель OpenAI
    return "gpt-4o-mini"


def send_message(session: dict, user_message: str, temperature: float = 0.7) -> str:
    """
    Отправляет сообщение в чат и возвращает ответ ассистента.
    
    Важно: session["messages"] обновляется автоматически, сохраняя
    весь контекст диалога (и запросы пользователя, и ответы модели).
    
    Это позволяет нейросети "помнить" предыдущие сообщения.
    """
    # Добавляем сообщение пользователя в историю
    session["messages"].append({
        "role": "user",
        "content": user_message
    })
    
    # Вызываем Chat Completions API
    response = client.chat.completions.create(
        model=session["model"],
        messages=session["messages"],
        temperature=temperature,
    )
    
    # Получаем ответ ассистента
    assistant_message = response.choices[0].message.content
    
    # Добавляем ответ ассистента в историю (это критично для контекста!)
    session["messages"].append({
        "role": "assistant",
        "content": assistant_message
    })
    
    return assistant_message


def get_conversation_history(session: dict) -> list:
    """Возвращает текущую историю диалога."""
    return session["messages"].copy()


def reset_chat(session: dict, system_prompt: str = None):
    """Сбрасывает историю чата, оставляя только system prompt (если был)."""
    session["messages"].clear()
    if system_prompt:
        session["messages"].append({"role": "system", "content": system_prompt})


# ==================== ДЕМО / ТЕСТ ====================

if __name__ == "__main__":
    print("=== Тест Chat Completions API с поддержкой диалога ===\n")
    print(f"Провайдер: {CURRENT_PROVIDER}")
    print(f"Base URL:  {CURRENT_BASE_URL or '(официальный OpenAI)'}")
    print(f"Модель по умолчанию: {_get_default_model()}\n")

    if CURRENT_PROVIDER == "ProxyAPI.ru":
        print("→ Используется ProxyAPI.ru — запросы идут на реальные модели OpenAI (gpt-4o-mini и др.)\n")
    
    # Проверяем наличие API ключа
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  ВНИМАНИЕ: OPENAI_API_KEY не найден!")
        print("   Установите переменную окружения или создайте файл .env\n")
    
    # Если пользователь использует официальный OpenAI — предупреждаем о региональных ограничениях
    if not os.getenv("OPENAI_BASE_URL"):
        print("ℹ️  Вы используете официальный OpenAI.")
        print("   В некоторых странах (включая Россию) прямой доступ к api.openai.com заблокирован.")
        print("   Чтобы заработало — укажите в .env альтернативный провайдер через OPENAI_BASE_URL.\n")
        print("   Рекомендуемый вариант:")
        print("     • ProxyAPI.ru (простой прокси на реальные модели OpenAI)")
        print("       OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1")
        print("       (используйте свой обычный OPENAI_API_KEY от OpenAI)\n")
        print("   Другие быстрые варианты:")
        print("     • Groq (бесплатно, очень быстро): https://console.groq.com/keys")
        print("       OPENAI_BASE_URL=https://api.groq.com/openai/v1")
        print("     • OpenRouter: https://openrouter.ai/keys")
        print("       OPENAI_BASE_URL=https://openrouter.ai/api/v1\n")
    
    # Создаём сессию чата с системным промптом
    session = create_chat_session(
        system_prompt="Ты — дружелюбный помощник. Отвечай кратко и по делу."
    )
    
    # Первый вопрос
    print("Пользователь: Привет! Меня зовут Павел.")
    reply1 = send_message(session, "Привет! Меня зовут Павел.")
    print(f"Ассистент: {reply1}\n")
    
    # Второй вопрос — проверяем, что модель помнит имя
    print("Пользователь: Как меня зовут?")
    reply2 = send_message(session, "Как меня зовут?")
    print(f"Ассистент: {reply2}\n")
    
    # Третий вопрос — проверяем накопление контекста
    print("Пользователь: А какое у меня любимое число? (угадай)")
    reply3 = send_message(session, "А какое у меня любимое число? (угадай)")
    print(f"Ассистент: {reply3}\n")
    
    # Показываем полную историю
    print("=== Полная история диалога ===")
    for msg in get_conversation_history(session):
        print(f"[{msg['role']}] {msg['content']}")
    
    print("\n✅ Диалог успешно завершён. Контекст сохранялся между сообщениями.")