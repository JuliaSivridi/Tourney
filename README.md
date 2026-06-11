# Tourney

[![Telegram Bot](https://img.shields.io/badge/@RTS__tourney__bot-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/RTS_tourney_bot)

![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)
![aiogram](https://img.shields.io/badge/aiogram_3-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL_16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)

Telegram-бот для проведения турниров прямо в чате. Поддерживает три формата и предлагает два способа управления: через инлайн-клавиатуру в чате или через полноценный веб-интерфейс (Telegram Mini App).

---

## Форматы турниров

| Формат | Описание |
|--------|----------|
| 🏆 **Single Elimination** | Одно поражение — выбываешь |
| 🔁 **Double Elimination** | Два поражения — выбываешь; есть сетка проигравших |
| 🔄 **Round Robin** | Каждый играет с каждым |

---

## Два способа управления

**Инлайн-режим** — всё прямо в чате: кнопки матчей, результаты, кнопка открытия сетки.

**Mini App (веб-интерфейс):**
- Турнирная сетка с раундами и матч-карточками
- Горизонтальный скролл по сетке
- Сетка победителей (зелёная) и проигравших (красная) для Double Elimination
- Таблица со статистикой игроков
- Кнопка отмены последнего результата

Режимы синхронизируются: начать можно в любом, прогресс и итоги отображаются в обоих.

---

## Требования

- Сервер или VPS с **Docker** и **Docker Compose**
- Telegram-бот (создать у [@BotFather](https://t.me/BotFather))
- Домен с HTTPS и nginx (для Mini App)

---

## Установка

### 1. Клонируйте репозиторий

```bash
git clone git@github.com:JuliaSivridi/Tourney.git
cd Tourney
```

### 2. Создайте конфигурацию

```bash
cp .env.example .env
nano .env
```

```env
BOT_TOKEN=your_telegram_bot_token_here

POSTGRES_USER=tourney
POSTGRES_PASSWORD=your_password
POSTGRES_DB=tourney
POSTGRES_HOST=db
POSTGRES_PORT=5432

WEBAPP_URL=https://yourdomain.com   # публичный адрес Mini App (нужен для кнопки в боте)
WEBAPP_PORT=8003                    # порт, который слушает контейнер
```

### 3. Настройте nginx

Mini App работает по HTTPS. Пробросьте `/tourney-api/` и статику на контейнер:

```nginx
location /tourney-api/ {
    proxy_pass http://127.0.0.1:8003/;
    proxy_set_header Host $host;
}
```

> Бот отдаёт Mini App и API на одном порту: статику из `webapp/`, API по пути `api/`.

### 4. Запустите

```bash
docker compose up -d --build
docker compose logs -f
```

### 5. Зарегистрируйте Mini App у BotFather

В [@BotFather](https://t.me/BotFather):
- `/mybots` → ваш бот → **Bot Settings** → **Menu Button** → укажите `https://yourdomain.com`

---

## Использование

Напишите боту `/start` — он поприветствует и предложит `/newgame`.

### Инлайн-режим

1. `/newgame` — выбрать формат
2. Ввести имена игроков по одному, нажать **Начать турнир**
3. Нажимать на победителя в каждом матче прямо в сообщении

### Веб-интерфейс

1. Нажать кнопку **📊 Сетка турнира** (или открыть Mini App через меню)
2. Выбрать формат, ввести участников, запустить
3. Тапать по игроку в матч-карточке — побеждает тот, по кому нажали

### Команды бота

| Команда | Действие |
|---------|----------|
| `/newgame` | 🎮 Начать новый турнир |
| `/lang` | 🔤 Сменить язык интерфейса |
| `/cancel` | ❌ Отменить текущую настройку |

### Языки

Интерфейс доступен на 6 языках: 🇷🇺 русский, 🇬🇧 английский, 🇩🇪 немецкий, 🇫🇷 французский, 🇵🇹 португальский, 🇺🇦 украинский.

---

## Управление сервисом

```bash
docker compose logs -f        # логи
docker compose restart        # перезапуск
docker compose down           # остановка
docker compose up -d --build  # пересборка после изменений кода
```

---

## Заметки

- **Данные** хранятся в Docker volume `pgdata` — не удаляйте его при обновлениях
- **Состояние турнира** сохраняется в PostgreSQL: если бот перезапустится в середине игры, прогресс не теряется
- **Mini App** обслуживается тем же контейнером что и бот — отдельного сервиса не нужно

---

## Документация

- **Техническая спецификация:** [`docs/tech-spec.md`](docs/tech-spec.md)

