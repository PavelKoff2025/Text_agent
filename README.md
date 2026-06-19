# TextAgent — пример работы с Chat Completions API

Простой пример на Python с использованием официального модуля `openai`, который поддерживает **сохранение контекста** (режим диалога).

## Проблема с официальным OpenAI

Если вы запускаете код и получаете ошибку:

```
openai.PermissionDeniedError: Error code: 403 - {'error': {'code': 'unsupported_country_region_territory', ...}}
```

Это означает, что **OpenAI не поддерживает вашу страну/регион** (Россия и ряд других).  
Прямые запросы на `api.openai.com` блокируются.

Решение — использовать любой **совместимый с OpenAI API** провайдер через переменную `OPENAI_BASE_URL`.

## Быстрый старт

1. Скопируйте пример окружения:
   ```bash
   cp .env.example .env
   ```

2. Откройте `.env` и настройте провайдер (см. примеры ниже).

3. Установите зависимости (уже сделано в `.venv`):
   ```bash
   .venv/bin/pip install -r requirements.txt
   ```

4. Запустите интерактивный чат (как у преподавателя):
   ```bash
   .venv/bin/python text_agent.py
   ```

   Или запустите тестовый демо с несколькими сообщениями:
   ```bash
   .venv/bin/python chat_test.py
   ```

## Интерактивный диалог (как у преподавателя)

Запустите:

```bash
python text_agent.py
```

Вы увидите:

```
Начните диалог с ИИ. Введите 'exit' для выхода.

Вы: Привет!
AI: Привет! Чем могу помочь?

Вы: В китае йены или юани?
AI: В Китае используется валюта под названием юань...
```

Особенности:
- Полноценный цикл ввода-вывода (`input()`)
- **Контекст сохраняется** — модель видит всю историю сообщений, поэтому помнит предыдущие реплики
- Для выхода введите `exit`, `выход`, `quit` или `q`

## Рекомендуемые провайдеры

### 0. ProxyAPI.ru (рекомендация преподавателя)

Самый простой вариант, если вы проходите курс — используете **свой обычный ключ OpenAI**, но идёте через российский прокси.

**Шаги:**
1. У вас уже есть `OPENAI_API_KEY` (начинается на `sk-` или `sk-proj-`)
2. Добавьте в `.env`:
   ```env
   OPENAI_BASE_URL=https://api.proxyapi.ru/openai/v1
   OPENAI_MODEL=gpt-4o-mini
   ```

Это именно то, что показывал преподаватель на скриншоте:
```python
OpenAI(..., base_url="https://api.proxyapi.ru/openai/v1")
```

### 1. Groq (лучший выбор для начала)

- Очень быстрый inference
- Бесплатный тарифный план
- Полностью совместим с OpenAI API

**Шаги:**
1. Перейдите: https://console.groq.com/keys
2. Создайте API ключ
3. В `.env`:
   ```env
   OPENAI_API_KEY=gsk_ваш_ключ_сюда
   OPENAI_BASE_URL=https://api.groq.com/openai/v1
   OPENAI_MODEL=llama-3.3-70b-versatile
   ```

Хорошие модели:
- `llama-3.3-70b-versatile` — качественная
- `llama-3.1-8b-instant` — очень быстрая

### 2. OpenRouter

- Много разных моделей (включая Llama, Claude, Gemini и т.д.)
- Удобный единый API

**Шаги:**
1. https://openrouter.ai/keys
2. В `.env`:
   ```env
   OPENAI_API_KEY=sk-or-ваш_ключ
   OPENAI_BASE_URL=https://openrouter.ai/api/v1
   OPENAI_MODEL=meta-llama/llama-3.1-70b-instruct
   ```

### 3. Ollama (локально, без интернета для инференса)

- Запускаете модель у себя на компьютере
- Полностью бесплатно
- Не требует внешних ключей

**Шаги:**
1. Установите Ollama: https://ollama.com
2. Скачайте модель:
   ```bash
   ollama pull llama3.2
   ```
3. В `.env`:
   ```env
   OPENAI_API_KEY=ollama
   OPENAI_BASE_URL=http://localhost:11434/v1
   OPENAI_MODEL=llama3.2
   ```

### 4. Официальный OpenAI

Работает **только** если вы находитесь в поддерживаемой стране.

```env
OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL не указывайте
OPENAI_MODEL=gpt-4o-mini
```

## Как работает сохранение контекста

Ключевой момент — мы передаём **всю историю** сообщений при каждом запросе:

```python
session["messages"].append({"role": "user", "content": user_message})
response = client.chat.completions.create(
    model=session["model"],
    messages=session["messages"],   # ← вся история здесь
    ...
)
session["messages"].append({"role": "assistant", "content": assistant_message})
```

Благодаря этому модель «помнит» предыдущие реплики.

## Основные функции

| Функция                | Что делает                                      |
|------------------------|-------------------------------------------------|
| `create_chat_session()` | Создаёт новую сессию с пустой историей          |
| `send_message()`        | Отправляет сообщение + сохраняет контекст       |
| `get_conversation_history()` | Возвращает текущую историю диалога         |
| `reset_chat()`          | Очищает историю (оставляет system prompt)       |

## Переменные окружения

| Переменная          | Описание                                      | Пример значения                          |
|---------------------|-----------------------------------------------|------------------------------------------|
| `OPENAI_API_KEY`    | API-ключ провайдера                           | `sk-...` или `gsk_...`                   |
| `OPENAI_BASE_URL`   | Адрес API (если не OpenAI)                    | `https://api.proxyapi.ru/openai/v1`      |
| `OPENAI_MODEL`      | Модель по умолчанию                           | `llama-3.3-70b-versatile`                |

## Структура проекта

```
TextAgent/
├── .env.example
├── .venv/                 # виртуальное окружение
├── chat_test.py           # основной код + демо
├── requirements.txt
└── README.md
```

## Полезные ссылки

- Официальная документация OpenAI Chat Completions: https://platform.openai.com/docs/guides/chat-completions
- ProxyAPI.ru (рекомендуется на курсе): https://proxyapi.ru
- Groq: https://groq.com
- OpenRouter: https://openrouter.ai
- Ollama: https://ollama.com

Удачи с экспериментами!

## Telegram-бот

Проект поддерживает запуск в виде Telegram-бота с теми же возможностями:

- Переключение между обычной моделью и думающей (Claude 4.5 Sonnet + отображение reasoning)
- Сохранение истории диалога (отдельный файл на каждого пользователя)
- Конфигурация через `.env`

### Запуск бота

1. Получи токен у [@BotFather](https://t.me/BotFather) и добавь в `.env`:
   ```env
   TELEGRAM_BOT_TOKEN=123456:ABCDEF...
   ```

2. Установи зависимости (если ещё не сделал):
   ```bash
   .venv/bin/pip install -r requirements.txt
   ```

3. Запусти бота:
   ```bash
   .venv/bin/python bot.py
   ```

В боте доступны команды:
- `/start`
- `/mode thinking` / `/mode normal`
- `/thinking 1500`
- `/reset`
- `/status`

По умолчанию бот запускается в режиме думающей модели.

---

## Переход на Anthropic (Claude) — как на уроке

Преподаватель показал использование библиотеки `anthropic` через ProxyAPI.ru с поддержкой **thinking** (размышления модели).

### 1. Установите зависимость

```bash
.venv/bin/pip install -r requirements.txt
```

(в requirements уже добавлен `anthropic`)

### 2. Настройте .env

```env
ANTHROPIC_API_KEY=ваш-ключ-от-proxyapi-для-anthropic
ANTHROPIC_BASE_URL=https://api.proxyapi.ru/anthropic
ANTHROPIC_MODEL=claude-sonnet-4-5
```

### 3. Запустите интерактивный чат

```bash
.venv/bin/python text_agent.py
```

### 4. Включите вывод размышлений (thinking)

Внутри программы:

```
/thinking on
```

или сразу с бюджетом токенов:

```
/thinking 1000
```

Пример кода, как на скрине урока:

```python
import anthropic
from dotenv import load_dotenv
import os
load_dotenv()

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url="https://api.proxyapi.ru/anthropic",
)

message = client.messages.create(
    model="claude-sonnet-4-5",
    thinking={
        "type": "enabled",
        "budget_tokens": 500
    },
    messages=[
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Привет!"}
            ]
        }
    ]
)
```

### Команды в text_agent.py

- `/thinking on` — включить показ размышлений
- `/thinking 800` — включить + задать бюджет токенов
- `/thinking off` — выключить
- `/model claude-sonnet-4-5` — сменить модель

Thinking — это прямой аналог того, что раньше пытались сделать через OpenAI Responses API. С Anthropic это работает чище.