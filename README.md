# TextAgent

Python-агент для работы с языковыми моделями через Chat Completions API и Anthropic API. Поддерживает **сохранение контекста диалога**, **режим thinking** (расширенные рассуждения Claude) и **Telegram-бота** с inline-интерфейсом.

## Возможности

- 🤖 Два бэкенда: OpenAI-совместимый (gpt-4o-mini, llama и др.) и Anthropic (Claude)
- 🧠 Режим **thinking** — видите внутренние рассуждения модели перед ответом
- 💾 Автосохранение истории диалога между сессиями
- 📱 Telegram-бот с inline-кнопками и индикатором «печатает»
- 🌍 Поддержка альтернативных провайдеров (ProxyAPI, Groq, OpenRouter, Ollama)
- 🔒 Конфигурация через `.env`, секреты не попадают в репозиторий

## Быстрый старт

```bash
# 1. Клонируйте репозиторий
git clone https://github.com/PavelKoff2025/Text_agent.git
cd Text_agent

# 2. Создайте виртуальное окружение и установите зависимости
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Настройте переменные окружения
cp .env.example .env
# Откройте .env и вставьте ваши API-ключи

# 4. Запустите консольный агент
.venv/bin/python text_agent.py

# 5. Или Telegram-бот
.venv/bin/python bot.py
```

## Структура проекта

```
TextAgent/
├── text_agent.py      # Ядро агента (консольный режим)
├── bot.py             # Telegram-бот
├── chat_test.py       # Минимальный пример Chat Completions
├── requirements.txt
├── .env.example       # Шаблон переменных окружения
└── README.md
```

## Конфигурация (.env)

```env
# OpenAI-совместимый бэкенд
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1   # или другой провайдер
OPENAI_MODEL=gpt-4o-mini

# Anthropic (Claude + thinking)
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_BASE_URL=https://api.proxyapi.ru/anthropic
ANTHROPIC_MODEL=claude-sonnet-4-5
ANTHROPIC_THINKING_BUDGET=1500

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABCDEF...
```

## Провайдеры

Если прямой доступ к `api.openai.com` недоступен из вашего региона, используйте переменную `OPENAI_BASE_URL` для указания альтернативного провайдера.

### ProxyAPI.ru

Российский прокси для OpenAI и Anthropic API. Принимает ключи этих же сервисов.

```env
OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1
ANTHROPIC_BASE_URL=https://api.proxyapi.ru/anthropic
```

### Groq

Бесплатный и очень быстрый inference. Полностью совместим с OpenAI API.

```env
OPENAI_API_KEY=gsk_ваш_ключ
OPENAI_BASE_URL=https://api.groq.com/openai/v1
OPENAI_MODEL=llama-3.3-70b-versatile
```

### OpenRouter

Единый API для сотен моделей (Llama, Claude, Gemini, Mistral и др.).

```env
OPENAI_API_KEY=sk-or-ваш_ключ
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=meta-llama/llama-3.1-70b-instruct
```

### Ollama (локально)

Запуск моделей локально без интернета.

```env
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_MODEL=llama3.2
```

## Telegram-бот

Бот предоставляет полный доступ к агенту через Telegram с удобным интерфейсом.

### Запуск

```bash
.venv/bin/python bot.py
```

### Команды

| Команда | Описание |
|---|---|
| `/start` | Приветствие и главное меню |
| `/mode thinking` | Переключить на Claude (режим thinking) |
| `/mode normal` | Переключить на обычную модель |
| `/thinking 1500` | Установить бюджет токенов для рассуждений |
| `/reset` | Сбросить историю диалога |
| `/status` | Текущий режим и статистика |

Все ключевые действия также доступны через **inline-кнопки** под каждым ответом.

## Как работает сохранение контекста

При каждом запросе к API передаётся полная история диалога:

```python
session["messages"].append({"role": "user", "content": user_message})
response = client.chat.completions.create(
    model=session["model"],
    messages=session["messages"],  # ← вся история
)
session["messages"].append({"role": "assistant", "content": response_text})
```

История автоматически сохраняется на диск после каждого обмена и загружается при следующем запуске.

## Режим thinking (Anthropic Claude)

В режиме thinking модель предоставляет подробные внутренние рассуждения перед финальным ответом. Telegram-бот выводит их отдельным блоком:

```
🧠 Размышления модели:
Пользователь спрашивает о... Нужно учесть...

Вот мой ответ:
...
```

Бюджет токенов для рассуждений настраивается через `ANTHROPIC_THINKING_BUDGET` или команду `/thinking`.

## Зависимости

```
openai>=1.0.0
anthropic>=0.40.0
python-telegram-bot>=20.0
python-dotenv>=1.0.0
```

## Ссылки

- [OpenAI Chat Completions API](https://platform.openai.com/docs/guides/chat-completions)
- [Anthropic API](https://docs.anthropic.com)
- [python-telegram-bot](https://python-telegram-bot.org)
- [ProxyAPI.ru](https://proxyapi.ru)
- [Groq](https://groq.com)
- [OpenRouter](https://openrouter.ai)
- [Ollama](https://ollama.com)

## Лицензия

MIT
