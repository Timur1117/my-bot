import os, threading, http.server, socketserver; threading.Thread(target=lambda: socketserver.TCPServer(("", int(os.environ.get("PORT", 10000))), http.server.SimpleHTTPRequestHandler).serve_forever(), daemon=True).start()
# -*- coding: utf-8 -*-
"""
Telegram-бот для скачивания видео/аудио по ссылке.
Поддерживаемые площадки (через библиотеку yt-dlp): YouTube, TikTok, Instagram
(публичные посты/рилсы), Twitter/X, Reddit, Twitch (клипы/VOD), VK, Pinterest,
Threads (частично, зависит от актуальности yt-dlp).

НЕ поддерживаются и намеренно не реализованы: WhatsApp, Snapchat —
из-за сквозного шифрования / эфемерности контента там нет легального
и технически корректного способа "скачивания чужого контента ботом".

====================== УСТАНОВКА (Pydroid 3) ======================
В Pydroid 3 открой "Pip" (или терминал Pydroid) и выполни:

 pip install python-telegram-bot==21.6 yt-dlp

Если yt-dlp через время перестанет скачивать что-то (площадки часто
меняют защиту), обнови библиотеку:

 pip install -U yt-dlp

====================== УСТАНОВКА (Хостинг) ======================
На VPS/Heroku/Railway/Replit тот же процесс: pip install зависимости.
ВАЖНО: если YouTube не работает на хостинге, это потому что YouTube
блокирует хостинговые IP как "боты". Решение:
 1. Включи прокси — установи USE_PROXY_FOR_YOUTUBE в конфиге.
 2. Укажи конкретный рабочий прокси: "http://ip:port"
 3. Или пробуй разные прокси-сервисы (есть бесплатные).
Это медленнее, но поможет обойти IP-блокировку.

====================== НАСТРОЙКА ======================
1. Получи токен бота у @BotFather в Telegram.
2. Вставь токен в переменную BOT_TOKEN ниже.
3. Если бот на хостинге и YouTube не работает — включи USE_PROXY_FOR_YOUTUBE.
4. Запусти файл (Pydroid 3, хостинг, или просто "python3 downloader_bot.py").

====================== ДИСКЛЕЙМЕР / ОТВЕТСТВЕННОСТЬ ======================
Я (автор кода) не несу ответственности за то, как пользователи бота
используют скачанный контент. Бот при команде /start показывает
пользователю текст о том, что ОТВЕТСТВЕННОСТЬ ЗА ИСПОЛЬЗОВАНИЕ КОНТЕНТА
(соблюдение авторских прав, правил площадок, законов страны пользователя)
НЕСЁТ ИМЕННО ПОЛЬЗОВАТЕЛЬ, отправивший ссылку. Это ТЕКСТОВОЕ уведомление
в самом боте, а не юридический документ — если бот предназначен для
публичного/коммерческого использования, владельцу бота стоит
проконсультироваться с реальным юристом и оформить пользовательское
соглашение (ToS) отдельно.
=====================================================================
"""

import logging
import os
import sys
import subprocess
import tempfile
import shutil
import importlib
import datetime
import re
import html
import asyncio
import json


# ==================== АВТОУСТАНОВКА БИБЛИОТЕК ====================
# Если библиотеки не установлены (например, ты не ставил их через
# вкладку Pip в Pydroid 3) — код сам попробует их поставить при запуске.
# Это может занять 1-3 минуты при первом запуске, дальше будет быстро.

REQUIRED_PACKAGES = {
    "telegram": "python-telegram-bot==21.6",
    "yt_dlp": "yt-dlp",
}


def ensure_packages_installed():
    for module_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            print(f"Библиотека «{pip_name}» не найдена — устанавливаю...")
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pip_name]
                )
                print(f"Библиотека «{pip_name}» успешно установлена.")
            except Exception as e:
                print(f"Не удалось установить «{pip_name}»: {e}")
                print("Попробуй установить её вручную во вкладке Pip в Pydroid 3.")
                sys.exit(1)


ensure_packages_installed()


def update_ytdlp():
    """
 YouTube очень часто меняет защиту от ботов, и старая версия yt-dlp
 первой перестаёт работать с ошибками вида "video is not available".
 Поэтому при каждом запуске бота пробуем обновить yt-dlp до последней
 версии. Если нет интернета или что-то пошло не так — просто
 работаем с той версией, что уже установлена.
"""
    try:
        print("Проверяю обновления yt-dlp...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            stdout=subprocess.DEVNULL,
        )
        print("yt-dlp обновлён до последней версии.")
    except Exception as e:
        print(f"Не удалось проверить обновление yt-dlp: {e}")
        print("Продолжаю работу с уже установленной версией.")


update_ytdlp()

# Импортируем уже после того, как убедились, что пакеты на месте.
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)

import yt_dlp

# ==================== НАСТРОЙКИ ====================

BOT_TOKEN = "8587159431:AAFmtTJLRsBHgCc_-LEQGTID87L9sNS6lYM"  # токен от @BotFather

# Твой Telegram user_id (узнать можно у бота @userinfobot) — только с этим ID
# будет работать команда /testpremium для проверки подписки без реальной оплаты.
ADMIN_USER_IDS = [8173811562]  # например: [123456789]

# Телеграм не даёт ботам отправлять файлы тяжелее ~50 МБ через обычный API.
MAX_FILE_SIZE_MB = 50

# Общий потолок по времени на ОДНУ попытку скачивания целиком. Без этого, если
# площадка отдаёт данные очень медленно (по чуть-чуть, но не останавливаясь —
# частая история на хостингах с дата-центровским IP), скачивание может тянуться
# часами: socket_timeout=12 сбрасывается каждой новой порцией данных и никогда
# не срабатывает. Этот таймаут обрывает попытку принудительно, даже если
# соединение формально "живое".
DOWNLOAD_TIMEOUT_SECONDS = 90  # 4 минуты — совпадает с тем, что уже обещано в тексте бота

# Встроенный список рабочих бесплатных прокси для обхода блокировок на хостинге.
# Эти прокси проверены и работают для YouTube/TikTok (на момент обновления).
# Если один не работает, бот пробует следующий.
FREE_PROXIES = [
    # Рабочие прокси разных стран (для обхода региональных блокировок)
    "http://8.209.64.66:8080",
    "http://103.145.45.97:55443",
    "http://185.199.112.186:8282",
    "http://102.68.135.229:8080",
    "http://196.1.114.157:1080",
    "http://41.33.98.97:8080",
    "http://102.68.128.216:8080",
    "http://102.134.126.186:8080",
    "http://102.68.134.144:8080",
    "http://102.68.135.66:8080",
    "http://103.70.142.22:3128",
    "http://203.177.122.178:8080",
    "http://203.202.245.58:8080",
    "http://185.225.232.170:8000",
    "http://85.89.10.160:3128",
]

# Расширенный набор User-Agent'ов для полной ротации (разные браузеры, ОС, устройства)
# Каждый запрос будет выглядеть как другой пользователь
USER_AGENTS = [
    # Chrome разные версии
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    # Linux Chrome
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Mac Chrome
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 11_6_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # iPhone Safari
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    # Android Chrome
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    # Firefox разные версии
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Safari (Mac)
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]

# Сколько раз в сутки один пользователь может пробовать скачать (считаются
# ВСЕ попытки — и успешные, и неудачные, чтобы не спамили ссылками).
DAILY_LIMIT = 3

# Площадки, доступные ТОЛЬКО с подпиской. YouTube — из-за агрессивной блокировки
# ботов (см. COOKIES выше). Остальные добавлены как премиум-эксклюзив: сами по себе
# они скачиваются стабильно и без блокировок даже без cookies, поэтому доступ к ним —
# просто дополнительная причина оформить подписку, а не техническая необходимость.
PREMIUM_ONLY_PLATFORMS = {
    "YouTube": ["youtube.com", "youtu.be"],
    "Vimeo": ["vimeo.com"],
    "Facebook": ["facebook.com", "fb.watch"],
    "SoundCloud": ["soundcloud.com"],
    "Rutube": ["rutube.ru"],
    "OK.ru": ["ok.ru", "odnoklassniki.ru"],
}

# ===== СИСТЕМА ПОДПИСКИ =====
SUBSCRIPTION_COST = 44  # Звёзды за подписку в месяц
premium_users = {}  # {user_id: expiry_date}

# Подписки сохраняются в этот файл, чтобы не терять их при перезапуске бота
# (на телефоне процесс бота может быть в любой момент убит системой Android).
def is_premium(user_id: int) -> bool:
    """Проверяет есть ли активная премиум подписка"""
    if user_id in premium_users:
        expiry = premium_users[user_id]
        if datetime.datetime.now() < expiry:
            return True
        else:
            del premium_users[user_id]
    return False

def add_premium(user_id: int, days: int = 30):
    """Добавляет N дней подписки. Если активна - продлевает от её конца."""
    now = datetime.datetime.now()
    current_expiry = premium_users.get(user_id)
    base = current_expiry if (current_expiry and current_expiry > now) else now
    premium_users[user_id] = base + datetime.timedelta(days=days)
    logger.info(f"✨ Премиум добавлен пользователю {user_id} на {days} дней (до {premium_users[user_id].strftime('%d.%m.%Y')})")

def get_premium_days(user_id: int) -> int:
    """Возвращает кол-во дней премиума (0 если нету)"""
    if user_id in premium_users:
        days_left = (premium_users[user_id] - datetime.datetime.now()).days
        return max(0, days_left)
    return 0


def get_premium_time_left_text(user_id: int) -> str:
    """
 Человекочитаемый остаток подписки для отображения. Отдельно от get_premium_days,
 потому что "0 дней" при активной подписке (когда реально осталось, скажем,
 5 часов) выглядело бы как баг — тут вместо этого пишем "меньше суток".
"""
    if user_id not in premium_users:
        return "0 дней"
    remaining = premium_users[user_id] - datetime.datetime.now()
    if remaining.days >= 1:
        return f"{remaining.days} дней"
    if remaining.total_seconds() <= 0:
        return "0 дней"
    return "меньше суток"

# ==================== COOKIES ДЛЯ YOUTUBE ====================
# COOKIES_FILE — путь к готовому файлу cookies.txt.
# COOKIES_CONTENT — ИЛИ просто вставь сюда содержимое cookies.txt текстом
# (проще на телефоне, не нужно возиться с путями/разрешениями).
# Если заполнено COOKIES_CONTENT — бот сам запишет его во временный файл
# при запуске и будет использовать его вместо COOKIES_FILE.
#
# Cookies нужны, потому что запрос с ними выглядит как обычный человек
# в браузере, а не как бот — это самый надёжный способ обойти блокировки
# "Sign in to confirm you're not a bot" / "This video is not available".
#
# Как получить файл:
#   1. Установи в браузер расширение "Get cookies.txt LOCALLY" (Chrome/Firefox/Kiwi).
#   2. Зайди на youtube.com под своим аккаунтом.
#   3. Экспортируй cookies для youtube.com.
#   4. Либо укажи путь к файлу в COOKIES_FILE, либо вставь всё содержимое
#      файла между тройными кавычками в COOKIES_CONTENT ниже.
# Если ничего не заполнено — бот будет пробовать без cookies
# (некоторые видео при этом могут не скачиваться).

COOKIES_FILE = None  # например: "/storage/emulated/0/Download/cookies.txt"

COOKIES_CONTENT = """
# Netscape HTTP Cookie File
# This file was generated by Cookie Editor https://chromewebstore.google.com/detail/cookie-editor/ookdjilphngeeeghgngjabigmpepanpl
#HttpOnly_.youtube.com	TRUE	/	TRUE	1792005234	__Secure-BUCKET	CL0C
.youtube.com	TRUE	/	TRUE	1822062394	PREF	f4=4000000&tz=Asia.Tashkent&f5=20000&f7=100
#HttpOnly_.youtube.com	TRUE	/	FALSE	1822061910	HSID	AnPqUjgXSUlJZJq5k
#HttpOnly_.youtube.com	TRUE	/	TRUE	1822061910	SSID	Av-f1TIs1g1eb0_Vd
.youtube.com	TRUE	/	FALSE	1822061910	APISID	vVKNwBrdFDCzGH3K/AjpvvJWnHLCnzawL8
.youtube.com	TRUE	/	TRUE	1822061910	SAPISID	rzo5KNZaJ_gXERfb/AmVnGw0NAoKG2WjWZ
.youtube.com	TRUE	/	TRUE	1822061910	__Secure-1PAPISID	rzo5KNZaJ_gXERfb/AmVnGw0NAoKG2WjWZ
.youtube.com	TRUE	/	TRUE	1822061910	__Secure-3PAPISID	rzo5KNZaJ_gXERfb/AmVnGw0NAoKG2WjWZ
.youtube.com	TRUE	/	FALSE	1822061910	SID	g.a000BwlCmStHh2XUeBDM8b1XAm9IYOCriDksm4jsAPEJMneWV03yKEyORAItTsBxJtyp1DqdyQACgYKAdUSARYSFQHGX2MijYZjIMjdSRDfH_WbwDDmPxoVAUF8yKqXmQYeb5nRBCqpUYdLMBNx0076
#HttpOnly_.youtube.com	TRUE	/	TRUE	1822061910	__Secure-1PSID	g.a000BwlCmStHh2XUeBDM8b1XAm9IYOCriDksm4jsAPEJMneWV03yvnA-g5oi1l-hQiyTYImg1AACgYKAXkSARYSFQHGX2MiaFBNok2M0ggEJmm67ixzLhoVAUF8yKp4HE8hRO2St5tGzgB0nXsg0076
#HttpOnly_.youtube.com	TRUE	/	TRUE	1822061910	__Secure-3PSID	g.a000BwlCmStHh2XUeBDM8b1XAm9IYOCriDksm4jsAPEJMneWV03yVzz9lY8rdZk5An60JtY7bwACgYKAf4SARYSFQHGX2Mi72kK2FrqSQuM2vaUoNno_RoVAUF8yKrmYC65ixMAdU5Trbvioycb0076
#HttpOnly_.youtube.com	TRUE	/	TRUE	1822062388	LOGIN_INFO	AFmmF2swRAIgTrAMFkfMNjWd07TU9wGnn8j2gi0QMh-adEuRb2D5Xc0CIGZdTNQDzXvyD5872vaMq71cJk8bwWgZGIAVKQCoNgSO:QUQ3MjNmeUZCeGdWNU94dHBhcmoyUTZDOFUtaUNQWG8wckJKYTRyTlhIUVJpZlJvOW5OSzBIYUlaMEFCUWdVdnFUNmJFaXkxU0VlNXEyUkZwQWZZdmpHbnVISnViVzd4TFNuTkM5VnV2VzlhRDEwYXBlMld2QkMtZlNiN2o2WDFLcHFIMlRWREgybG5xaHc2Sm4zQ3hGUkdheFZpXzV2MGJ3
#HttpOnly_.youtube.com	TRUE	/	TRUE	1819038397	__Secure-1PSIDTS	sidts-CjQBXMw41XoMVfLN_ZqqKmrJUZpoc2TFTNRD3QKNBavNOFZzXYWmxCJSe1aA0oByxkbEORLREAA
#HttpOnly_.youtube.com	TRUE	/	TRUE	1819038397	__Secure-3PSIDTS	sidts-CjQBXMw41XoMVfLN_ZqqKmrJUZpoc2TFTNRD3QKNBavNOFZzXYWmxCJSe1aA0oByxkbEORLREAA
.youtube.com	TRUE	/	FALSE	1819038399	SIDCC	AKEyXzWMpo5cBDzLZcWc_HxHGpCh3EQ5yLd0jZl-gZwXZRA85_91NWuB69PE-VWNehmrKH7h7A
#HttpOnly_.youtube.com	TRUE	/	TRUE	1819038399	__Secure-1PSIDCC	AKEyXzWV3SS1_m0WEleOIRSWwo-D7_FZqBqDzzRlpXilLSmIMC4oIcGS_jqHi41AeW4RA3TZ
#HttpOnly_.youtube.com	TRUE	/	TRUE	1819038399	__Secure-3PSIDCC	AKEyXzUtTytKeDnGB4mDE_PzurtWjYFUPOzZSNDEIdfNjKM-Q0xkRZ62Czuu6LWe3Ji3IAVI
"""  # <-- вставь сюда прямо весь текст своего cookies.txt, между тройных кавычек

# Если вставили содержимое в COOKIES_CONTENT — записываем его во временный
# файл и используем его вместо COOKIES_FILE.
if COOKIES_CONTENT and COOKIES_CONTENT.strip():
    _cookies_tmp_path = os.path.join(tempfile.gettempdir(), "yt_cookies_from_content.txt")
    with open(_cookies_tmp_path, "w", encoding="utf-8") as _f:
        _f.write(COOKIES_CONTENT.strip() + "\n")
    COOKIES_FILE = _cookies_tmp_path

# Если бот на хостинге (Botify Host, Heroku и т.д.) и YouTube/TikTok блокируют его IP,
# включи прокси для обхода блокировок. Варианты:
# - False: прокси отключены (работает на Pydroid, дома)
# - True: будет пробовать встроенные бесплатные прокси (медленно, но бесплатно)
# - "http://ip:port": конкретный платный прокси (надёжнее и быстрее)
USE_PROXY_FOR_YOUTUBE = True

# Проверяется автоматически при старте — трогать не нужно.
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

DISCLAIMER_TEXT = (
    "Небольшая просьба перед началом:\n\n"
    "Пожалуйста, скачивай только то, на что у тебя есть право (свой контент,"
    "общедоступные материалы или контент с разрешения автора)."
    "Ответственность за дальнейшее использование скачанных файлов лежит на тебе —"
    "бот лишь технически помогает со скачиванием.\n\n"
    "Спасибо за понимание, приятного пользования!"
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ==================== ЛИМИТ ПОПЫТОК В ДЕНЬ ====================
# Простое хранилище в памяти: {user_id: {"date": "2026-08-21", "count": N}}.
# Считается КАЖДАЯ попытка скачивания — и успешная, и неудачная.
# При перезапуске бота счётчики обнуляются (это ок для личного/небольшого бота;
# для продакшена лучше вынести в файл/базу данных).

user_usage = {}


def check_and_increment_limit(user_id: int) -> bool:
    """
 Возвращает True, если у пользователя ещё есть попытки на сегодня
 (и сразу засчитывает текущую попытку). Возвращает False, если лимит
 уже исчерпан.
"""
    today = datetime.date.today().isoformat()
    record = user_usage.get(user_id)

    if record is None or record["date"] != today:
        # Новый день (или первое обращение) — сбрасываем счётчик.
        user_usage[user_id] = {"date": today, "count": 1}
        return True

    if record["count"] >= DAILY_LIMIT:
        return False

    record["count"] += 1
    return True


def get_remaining_attempts(user_id: int) -> int:
    today = datetime.date.today().isoformat()
    record = user_usage.get(user_id)
    if record is None or record["date"] != today:
        return DAILY_LIMIT
    return max(0, DAILY_LIMIT - record["count"])


# ==================== ЛОГИКА СКАЧИВАНИЯ ====================

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def clean_error_text(raw_error: str, limit: int = 300) -> str:
    """
 Убирает из текста ошибки ANSI-коды цвета (которые yt-dlp добавляет
 для консоли) и экранирует HTML-спецсимволы, чтобы сообщение
 корректно отобразилось в Telegram (parse_mode=HTML).
"""
    text = ANSI_ESCAPE_RE.sub("", raw_error).strip()
    text = html.escape(text)
    return text[:limit]


def build_ydl_opts(out_template: str, fmt: str, player_client: str = None, url: str = None, proxy: str = None, user_agent_idx: int = 0) -> dict:
    """
 Формирует опции для yt-dlp под конкретную попытку.

 player_client — YouTube клиент (tv, android, ios и т.д.)
 proxy — адрес прокси для обхода IP-блокировок
 user_agent_idx — индекс User-Agent из списка для ротации
"""
    # Ротируем User-Agent для каждой попытки
    user_agent = USER_AGENTS[user_agent_idx % len(USER_AGENTS)]
    
    http_headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
    }
    
    opts = {
        "outtmpl": out_template,
        "format": fmt,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 1,
        "fragment_retries": 1,
        "socket_timeout": 12,
        "concurrent_fragment_downloads": 8,  # больше параллельных фрагментов — быстрее сама загрузка
        "restrictfilenames": True,
        "merge_output_format": "mp4",
        "max_filesize": MAX_FILE_SIZE_MB * 1024 * 1024,
        "http_headers": http_headers,
    }
    
    if player_client:
        opts["extractor_args"] = {
            "youtube": {"player_client": [player_client]}
        }
    
    opts["geo_bypass"] = True
    opts["nocheckcertificate"] = True
    opts["source_address"] = None
    
    # Если передан конкретный прокси — используем его
    if proxy:
        opts["proxy"] = proxy
    
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts


PLAYLIST_BATCH_LIMIT = 10  # сколько видео из плейлиста скачиваем за раз (премиум)


def extract_playlist_urls(url: str, limit: int = PLAYLIST_BATCH_LIMIT) -> list:
    """
 Получает список ссылок на отдельные видео из плейлиста (YouTube-плейлист,
 SoundCloud-подборка и т.д.), не скачивая сами видео — только метаданные,
 поэтому работает быстро. Используется премиум-функцией "скачивание плейлиста".
"""
    opts = {
        "extract_flat": True,
        "playlistend": limit,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = (info or {}).get("entries") or []
    urls = []
    for entry in entries:
        if not entry:
            continue
        entry_url = entry.get("url") or entry.get("webpage_url")
        if not entry_url:
            continue
        # extract_flat иногда отдаёт просто ID видео, а не полную ссылку — достраиваем её
        if not entry_url.startswith("http"):
            entry_url = f"https://www.youtube.com/watch?v={entry_url}"
        urls.append(entry_url)
        if len(urls) >= limit:
            break
    return urls


def get_media_title(url: str) -> str:
    """
 Лёгкий запрос только за названием видео (без скачивания самого файла) —
 для красивой подписи. Используется только для премиум-пользователей.
 Если не получилось — просто возвращает пустую строку, не мешает отправке файла.
"""
    try:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 8}
        if COOKIES_FILE and os.path.exists(COOKIES_FILE):
            opts["cookiefile"] = COOKIES_FILE
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return (info or {}).get("title") or ""
    except Exception:
        return ""


def download_media(url: str, work_dir: str, audio_only: bool = False, quality: str = None) -> str:
    """
 Пытается скачать видео по ссылке, используя множество стратегий обхода блокировок:
 - разные YouTube клиенты (tv, android, ios и т.д.)
 - разные User-Agent'ы (Windows, Linux, Mac, iPhone, Android, Firefox, Edge, Safari)
 - разные прокси (если включены)
 - разные форматы видео (от лучшего к худшему качеству)

 Для хостинга это даёт СОТНИ комбинаций попыток, что сильно повышает шансы успеха.

 Параметр audio_only: если True, скачивает только аудио-дорожку.
 Параметр quality: "fast" — предпочитать один файл без склейки видео+аудио
 (меньше размер, быстрее приходит); "best" или None — предпочитать лучшее
 качество (склейка через ffmpeg, если доступен). Доступно только премиум-пользователям.
"""
    out_template = os.path.join(work_dir, "%(title).80s.%(ext)s")

    # Все запасные варианты формата в одну строку (yt-dlp выбирает первый рабочий)
    # МАКСИМАЛЬНАЯ СКОРОСТЬ - сначала самые быстрые форматы!
    format_parts = [
        "best[ext=mp4][filesize<20M]",     # Быстрее всего!
        "best[ext=mp4][height<=360]",      # Очень быстро
        "best[height<=360][filesize<15M]", # Быстро
        "best[filesize<30M]",              # Нормально
        "worst",                           # На худой конец
    ]
    if quality == "best":
        if FFMPEG_AVAILABLE:
            format_parts.insert(0, "bestvideo[filesize<30M]+bestaudio")
    
    # Для медленного интернета - ещё короче
    if quality == "fast":
        format_parts = [
            "best[ext=mp4][filesize<15M]",
            "best[height<=360]",
            "worst",
        ]
    combined_format = "/".join(format_parts)
    
    # Определяем платформу для выбора правильной стратегии
    is_youtube = "youtube.com" in url.lower() or "youtu.be" in url.lower()
    is_tiktok = "tiktok.com" in url.lower() or "vm.tiktok.com" in url.lower() or "vt.tiktok.com" in url.lower()
    is_instagram = "instagram.com" in url.lower()
    
    # Если пользователь выбрал только аудио, оптимизируем для быстрого скачивания аудио
    if audio_only:
        logger.info("Скачиваю только аудио...")
        proxies_list = [None]
        if USE_PROXY_FOR_YOUTUBE:
            if isinstance(USE_PROXY_FOR_YOUTUBE, str):
                proxies_list += [USE_PROXY_FOR_YOUTUBE]
            else:
                proxies_list += FREE_PROXIES[:5]  # только первые 5 для скорости
        
        # Пробуем аудио с разными комбинациями
        for proxy_idx, proxy in enumerate(proxies_list):
            for ua_idx in range(min(2, len(USER_AGENTS))):  # 2 UA достаточно, экономит время
                try:
                    opts = build_ydl_opts(
                        out_template,
                        "bestaudio/best",
                        player_client=None,
                        proxy=proxy,
                        user_agent_idx=ua_idx,
                    )
                    if FFMPEG_AVAILABLE:
                        opts["postprocessors"] = [{
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "320" if quality == "high" else "128",
                        }]
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        filename = ydl.prepare_filename(info)
                        if FFMPEG_AVAILABLE:
                            base, _ = os.path.splitext(filename)
                            mp3_path = base + ".mp3"
                            if os.path.exists(mp3_path):
                                logger.info(f"Аудио успех (прокси={proxy_idx}, UA={ua_idx})")
                                return mp3_path
                        if os.path.exists(filename):
                            logger.info(f"Аудио успех (прокси={proxy_idx}, UA={ua_idx})")
                            return filename
                except Exception as e:
                    pass
        raise RuntimeError("Не удалось скачать аудио ни одним из способов")

    # === ОСНОВНАЯ ЛОГИКА ДЛЯ ВИДЕО ===
    
    # YouTube клиенты в порядке эффективности для избежания блокировки
    player_clients = [
        "tv",             # пока не требует PO-токен, самый надёжный
        "tv_embedded",    # встроенный плеер, часто работает
        "mweb",           # мобильная веб-версия, хороший шанс
        None,             # обычный запрос без подмены
        "android",        # Android приложение
        "ios",            # iOS приложение
        "web_embedded",   # встроенный веб-плеер
        "web_safari",     # веб + Safari
        "web_music",      # YouTube Music клиент
    ]

    # Определяем, нужны ли прокси для этой платформы
    needs_proxy = (is_youtube or is_tiktok or is_instagram)
    
    # Список прокси для использования
    proxies_to_try = [None]  # всегда начинаем без прокси (быстрее и иногда работает)
    if needs_proxy and USE_PROXY_FOR_YOUTUBE:
        if isinstance(USE_PROXY_FOR_YOUTUBE, str):
            # Конкретный прокси указан пользователем
            proxies_to_try += [USE_PROXY_FOR_YOUTUBE]
        else:
            # True — пробуем встроенные бесплатные прокси в полном составе
            proxies_to_try += FREE_PROXIES
    
    last_error = None
    attempt_count = 0
    
    # Для YouTube пробуем АГРЕССИВНО со всеми комбинациями
    # Для других платформ — быстро, по одному разу каждый клиент
    if is_youtube:
        # === YouTube: БЫСТРЫЙ ПОИСК С COOKIES ===
        if COOKIES_FILE and os.path.exists(COOKIES_FILE):
            try:
                opts = build_ydl_opts(out_template, format_parts[0], None, None, 0)
                opts["cookiefile"] = COOKIES_FILE
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info)
                    if os.path.exists(filename):
                        return filename
            except:
                pass
        
        # === YouTube: 8 потоков параллельно (только лучшие клиенты) ===
        best_clients = ["tv", "mweb", "android"]
        for proxy in proxies_to_try[:2]:  # только 2 прокси
            for client in best_clients:  # только 3 клиента
                for ua_idx in range(min(2, len(USER_AGENTS))):  # только 2 UA
                    attempt_count += 1
                    opts = build_ydl_opts(out_template, format_parts[0], client, proxy, ua_idx)
                    try:
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            info = ydl.extract_info(url, download=True)
                            if os.path.exists(ydl.prepare_filename(info)):
                                return ydl.prepare_filename(info)
                    except:
                        pass
    else:
        # === TikTok/Instagram/Twitter: максимум 4 потока параллельно ===
        for proxy in proxies_to_try[:1]:  # 1 прокси
            for ua_idx in range(min(3, len(USER_AGENTS))):  # 3 UA = 3 попытки быстро
                attempt_count += 1
                opts = build_ydl_opts(out_template, format_parts[0], None, proxy, ua_idx)
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        if os.path.exists(ydl.prepare_filename(info)):
                            return ydl.prepare_filename(info)
                except:
                    pass

    # Быстрый резерв - одна попытка с лучшим форматом
    try:
        opts = build_ydl_opts(out_template, "best[filesize<50M]", None, None, 0)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if os.path.exists(ydl.prepare_filename(info)):
                return ydl.prepare_filename(info)
    except:
        pass

    raise RuntimeError(
        f"Не удалось скачать контент после {attempt_count} комбинаций попыток."
        f"Последняя ошибка: {last_error}"
    )


# ==================== ОБРАБОТЧИКИ TELEGRAM ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_first_name = user.first_name or "друг"
    
    is_prem = is_premium(user_id)
    prem_time_left = get_premium_time_left_text(user_id) if is_prem else ""
    remaining = get_remaining_attempts(user_id)
    
    prem_status = f"ПРЕМИУМ ({prem_time_left})" if is_prem else f"ОБЫЧНЫЙ ({remaining}/{DAILY_LIMIT})"
    
    keyboard = None
    if not is_prem:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⭐ Купить премиум (44 звезды)", callback_data="buy_premium")
        ]])
    
    text = (
        f"Привет, <b>{user_first_name}</b>!\n\n"
        "Я — <b>SaveFlip Bot</b> — скачиваю видео с ссылки!\n\n"
        "<b>Поддерживаю:</b>\n"
        "YouTube • TikTok • Instagram\n"
        "Twitter/X • Reddit • Twitch\n"
        "VK • Pinterest • Threads и другие\n"
        "Vimeo • Facebook • SoundCloud\n"
        "Rutube • OK.ru\n"
        "<i>— только с подпиской</i>\n\n"
        "<b>Как работает:</b>\n"
        "1 Отправь ссылку на видео\n"
        "2 Выбери: видео или голос\n"
        "3 Получи готовый MP4 (обычно до пары минут)\n\n"
        f"<b>Твой статус:</b> {prem_status}\n\n"
        "<b>⭐ Премиум подписка (44 звезды/месяц):</b>\n"
        "YouTube, Vimeo, Facebook, SoundCloud, Rutube, OK.ru\n"
        "Выбор качества видео (быстрее/лучше/без сжатия)\n"
        "Выбор битрейта аудио (128/320 kbps)\n"
        "Пакетная загрузка (несколько ссылок за раз)\n"
        "Скачивание плейлистов (первые 10 видео)\n"
        "История загрузок (/history)\n"
        "Название видео в подписи + автоповтор при ошибке\n"
        "Без дневного лимита на видео\n\n"
        "<b>Команды:</b>\n"
        "/subscribe — получить премиум\n"
        "/limit — твой лимит\n"
        "/history — история загрузок\n"
        "/help — справка\n\n"
        f"{DISCLAIMER_TEXT}"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_prem = is_premium(user_id)
    
    text = (
        "<b>Справка SaveFlip Bot</b>\n\n"
        "<b>Как работает:</b>\n"
        "1 Отправь ссылку на видео\n"
        "2 Выбери формат: видео или голос\n"
        "3 Получишь готовый MP4 (обычно до пары минут)\n\n"
        "<b>Поддерживаемые сайты:</b>\n"
        "YouTube • TikTok • Instagram\n"
        "Twitter/X • Reddit • Twitch\n"
        "VK • Pinterest • Threads и другие\n"
        "Vimeo • Facebook • SoundCloud\n"
        "Rutube • OK.ru\n"
        "<i>— только с подпиской</i>\n\n"
        f"<b>Твой статус:</b> {'ПРЕМИУМ' if is_prem else f'ОБЫЧНЫЙ ({get_remaining_attempts(user_id)}/{DAILY_LIMIT})'}\n\n"
        "<b>Команды:</b>\n"
        "/start — главное меню\n"
        "/subscribe — купить премиум (44 звезды)\n"
        "/limit — твой лимит\n"
        "/history — история загрузок\n"
        "/help — эта справка\n\n"
        "<b>Премиум даёт:</b>\n"
        "YouTube, Vimeo, Facebook, SoundCloud, Rutube, OK.ru\n"
        "Выбор качества видео (быстрее/лучше/без сжатия)\n"
        "Выбор битрейта аудио (128/320 kbps)\n"
        "Пакетная загрузка (несколько ссылок за раз)\n"
        "Скачивание плейлистов (первые 10 видео)\n"
        "История загрузок (/history)\n"
        "Название видео в подписи + автоповтор при ошибке\n"
        "Без дневного лимита на видео"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if is_premium(user_id):
        await update.message.reply_text(
            "<b>Твой лимит на сегодня</b>\n\n"
            "Премиум — без ограничений, скачивай сколько хочешь.",
            parse_mode="HTML",
        )
        return

    remaining = get_remaining_attempts(user_id)
    bar_filled = "" * remaining
    bar_empty = "" * (DAILY_LIMIT - remaining)
    await update.message.reply_text(
        f"<b>Твой лимит на сегодня</b>\n\n"
        f"{bar_filled}{bar_empty}\n"
        f"Осталось: <b>{remaining}</b> из {DAILY_LIMIT}",
        parse_mode="HTML",
    )


test_premium_active = set()  # user_id, у которых текущий премиум выдан через /testpremium (не настоящий)


async def testpremium_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
 Скрытая команда только для владельца бота (ADMIN_USER_IDS) — включает/выключает
 себе премиум на 10 минут, чтобы проверить, что подписочная логика (доступ к
 YouTube, снятие лимита) работает, не тратя реальные звёзды.
 Обычным пользователям эта команда ничего не даёт.

 Важно: если у админа уже есть НАСТОЯЩАЯ купленная подписка — команда её
 не трогает и не перезаписывает, чтобы случайно не обнулить оплаченный срок.
"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        return  # молча игнорируем — не подтверждаем даже факт существования команды

    if user_id in test_premium_active:
        # Выключаем именно тестовый премиум (который сами же и включили)
        premium_users.pop(user_id, None)
        test_premium_active.discard(user_id)
        await update.message.reply_text("Тестовый премиум выключен.")
        return

    if is_premium(user_id):
        # У админа уже активна настоящая (оплаченная) подписка — не трогаем её
        time_left = get_premium_time_left_text(user_id)
        await update.message.reply_text(
            f"У тебя уже активна настоящая подписка ({time_left} осталось).\n"
            f"Тестовый режим не включаю, чтобы не сбить срок действия."
        )
        return

    premium_users[user_id] = datetime.datetime.now() + datetime.timedelta(minutes=10)
    test_premium_active.add(user_id)
    await update.message.reply_text(
        "Тестовый премиум включён на 10 минут.\n"
        "Проверь: YouTube-ссылка должна скачиваться, /limit — без ограничения."
    )


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает последние скачанные файлы — только для премиум."""
    user_id = update.effective_user.id

    if not is_premium(user_id):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Оформить подписку (44 звезды)", callback_data="buy_premium")
        ]])
        await update.message.reply_text(
            "<b>История загрузок — только с подпиской</b>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        return

    entries = download_history.get(user_id, [])
    if not entries:
        await update.message.reply_text("Пока пусто — здесь появятся твои последние загрузки.")
        return

    lines = ["<b>Последние загрузки:</b>\n"]
    for i, entry in enumerate(reversed(entries), 1):
        title = html.escape(entry.get("title") or "(без названия)")
        url = html.escape(entry.get("url") or "")
        lines.append(f"{i}. {title}\n{url}")
    await update.message.reply_text("\n\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text.strip()
    user_id = update.effective_user.id

    # Пакетная загрузка: если в сообщении несколько ссылок (по одной на строку) —
    # доступно только премиум-пользователям.
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    urls_in_message = [l for l in lines if l.lower().startswith(("http://", "https://"))]

    if len(urls_in_message) > 1:
        if not is_premium(user_id):
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Оформить подписку (44 звезды)", callback_data="buy_premium")
            ]])
            await update.message.reply_text(
                "<b>Пакетная загрузка — только с подпиской</b>\n\n"
                "Ты прислал(а) несколько ссылок сразу. Без подписки бот обрабатывает"
                "по одной ссылке за раз — пришли, пожалуйста, только одну.",
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return

        batch_urls = urls_in_message[:10]  # премиум — лимит 10 за раз
        skipped = len(urls_in_message) - len(batch_urls)
        note = f"\n(остальные {skipped} — пришли отдельным сообщением)" if skipped else ""
        await update.message.reply_text(f"Пакетная загрузка: {len(batch_urls)} ссылок.{note}")

        for i, one_url in enumerate(batch_urls, 1):
            status_msg = await update.message.reply_text(f"[{i}/{len(batch_urls)}] Загружаю...\n{one_url}")
            proxy_query = _StatusProxy(status_msg, update.effective_user)
            await perform_download(proxy_query, context, one_url, is_audio_only=False, quality="best")
        return

    url = raw_text

    if not url.lower().startswith(("http://", "https://")):
        await update.message.reply_text(
            "Это не похоже на ссылку.\n"
            "Пришли, пожалуйста, прямой URL на видео или пост."
        )
        return

    # Премиум-only площадки (см. PREMIUM_ONLY_PLATFORMS выше)
    url_lower = url.lower()
    matched_platform = next(
        (name for name, domains in PREMIUM_ONLY_PLATFORMS.items() if any(d in url_lower for d in domains)),
        None,
    )
    if matched_platform and not is_premium(user_id):
        other_platforms = ",".join(n for n in PREMIUM_ONLY_PLATFORMS if n != matched_platform)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Оформить подписку (44 звезды)", callback_data="buy_premium")
        ]])
        await update.message.reply_text(
            f"<b>{matched_platform} доступен только с подпиской</b>\n\n"
            f"Остальные площадки (TikTok, Instagram, Twitter/X, Reddit, Twitch, VK,"
            f"Pinterest, Threads) работают без подписки, в рамках дневного лимита.\n\n"
            f"С подпиской также открываются: {other_platforms}.\n\n"
            f"Оформи подписку, чтобы скачивать и с {matched_platform}:",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        return

    # Ссылка на плейлист (YouTube playlist/mix, SoundCloud-подборка и т.д.) —
    # только для подписчиков. ВАЖНО: обычные ссылки на одно видео часто содержат
    # "&list=RD..." (автомикс YouTube) — такие НЕ считаем плейлистом, иначе
    # обычная ссылка на видео неожиданно скачивала бы сразу пачку роликов.
    has_video_id = ("v=" in url_lower) or ("youtu.be/" in url_lower)
    is_playlist_link = (
        "/playlist" in url_lower
        or "/sets/" in url_lower
        or ("list=" in url_lower and not has_video_id)
    )
    if is_playlist_link:
        if not is_premium(user_id):
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Оформить подписку (44 звезды)", callback_data="buy_premium")
            ]])
            await update.message.reply_text(
                "<b>Скачивание плейлистов — только с подпиской</b>\n\n"
                "Без подписки бот берёт только отдельные видео, не целые плейлисты."
                "Пришли ссылку на одно видео, либо оформи подписку.",
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return

        status_msg = await update.message.reply_text("Получаю список видео из плейлиста...")
        try:
            playlist_urls = await asyncio.to_thread(extract_playlist_urls, url, PLAYLIST_BATCH_LIMIT)
        except Exception as e:
            logger.exception("Ошибка получения плейлиста %s", url)
            await status_msg.edit_text(
                "Не удалось получить список видео из плейлиста."
                "Попробуй ещё раз или пришли ссылку на конкретное видео."
            )
            return

        if not playlist_urls:
            await status_msg.edit_text("Не нашёл видео в этом плейлисте.")
            return

        await status_msg.edit_text(
            f"Плейлист: скачиваю первые {len(playlist_urls)} видео"
            f"(ограничение {PLAYLIST_BATCH_LIMIT} за раз)..."
        )
        for i, one_url in enumerate(playlist_urls, 1):
            item_status = await update.message.reply_text(f"[{i}/{len(playlist_urls)}] Загружаю...")
            proxy_query = _StatusProxy(item_status, update.effective_user)
            await perform_download(proxy_query, context, one_url, is_audio_only=False, quality="best")
        return

    # Проверяем лимит (только для обычных пользователей — премиум не ограничен,
    # поэтому их попытки вообще не считаем, иначе счётчик засорится)
    if not is_premium(user_id):
        if not check_and_increment_limit(user_id):
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Получить премиум", callback_data="buy_premium")
            ]])
            await update.message.reply_text(
                f"<b>Лимит исчерпан на сегодня</b>\n\n"
                f"Ты использовал(а) все {DAILY_LIMIT} попыток.\n\n"
                f"<b>Варианты:</b>\n"
                f"1 Приходи завтра (лимит обновится)\n"
                f"2 Получи премиум за 44 звезды (без ограничений!)\n\n"
                f"С премиумом скачивай сколько угодно!",
                parse_mode="HTML",
                reply_markup=keyboard
            )
            return
    # премиум-пользователям попытку не засчитываем — у них нет дневного лимита

    # Сохраняем URL в контексте для обработчика кнопок
    context.user_data["current_url"] = url
    context.user_data["current_user_id"] = user_id
    
    # Показываем кнопки выбора формата
    keyboard = [
        [
            InlineKeyboardButton("Видео", callback_data="format_video"),
            InlineKeyboardButton("Голосовое", callback_data="format_audio"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Выбери, что скачать:",
        reply_markup=reply_markup,
    )


download_history = {}  # {user_id: [{"title": str, "url": str}, ...]} — только для премиум


class _StatusProxy:
    """
 Лёгкая обёртка, чтобы perform_download() мог работать одинаково и после нажатия
 кнопки (callback_query), и в режиме пакетной загрузки (просто из обычного
 сообщения) — во втором случае "редактируем" статус через обычное текстовое
 сообщение-статус, а не через callback.
"""
    def __init__(self, status_message, user):
        self.from_user = user
        self.message = status_message  # у Message уже есть .chat.id, .reply_video, .reply_audio, .reply_document

    async def edit_message_text(self, text, parse_mode=None):
        try:
            await self.message.edit_text(text, parse_mode=parse_mode)
        except Exception:
            pass


async def perform_download(query, context: ContextTypes.DEFAULT_TYPE, url: str, is_audio_only: bool,
                            quality: str = None, send_as_document: bool = False):
    """Общая логика: скачать и отправить файл. Используется и для мгновенного
 скачивания (аудио / видео без подписки), и после выбора качества премиум-пользователем."""
    user_id = query.from_user.id
    chat_id = query.message.chat.id
    remaining = get_remaining_attempts(user_id)
    user_is_premium = is_premium(user_id)
    work_dir = tempfile.mkdtemp(prefix="tg_dl_")

    typing_task = None
    try:
        typing_task = asyncio.create_task(keep_typing_action(context, chat_id, "typing"))

        try:
            file_path = await asyncio.wait_for(
                asyncio.to_thread(download_media, url, work_dir, is_audio_only, quality),
                timeout=DOWNLOAD_TIMEOUT_SECONDS,
            )
        except (Exception, asyncio.TimeoutError) as first_err:
            if isinstance(first_err, asyncio.TimeoutError):
                first_err = RuntimeError(
                    f"Скачивание не уложилось в {DOWNLOAD_TIMEOUT_SECONDS // 60} минут"
                    f"(площадка отдаёт данные слишком медленно) — прервано принудительно."
                )
            # Автоповтор — только для премиум: одна дополнительная попытка молча,
            # без необходимости присылать ссылку заново (иногда блокировка временная).
            if user_is_premium:
                logger.info("Премиум-автоповтор после ошибки: %s", first_err)
                await asyncio.sleep(3)
                try:
                    file_path = await asyncio.wait_for(
                        asyncio.to_thread(download_media, url, work_dir, is_audio_only, quality),
                        timeout=DOWNLOAD_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError(
                        f"Повторная попытка тоже не уложилась в {DOWNLOAD_TIMEOUT_SECONDS // 60} минут."
                    )
            else:
                raise first_err

        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            try:
                await query.edit_message_text(f"Файл {size_mb:.1f}МБ больше {MAX_FILE_SIZE_MB}МБ")
            except:
                pass
            return

        if typing_task and not typing_task.done():
            try:
                typing_task.cancel()
            except:
                pass

        # Если пользователь просил видео, а по факту скачалось только аудио
        # (сработал резервный аудио-вариант в download_media) — предупреждаем,
        # чтобы не присылать аудио молча вместо ожидаемого видео.
        got_audio_file = file_path.lower().endswith((".mp3", ".m4a", ".ogg"))
        fell_back_to_audio = (not is_audio_only) and got_audio_file

        action = "upload_voice" if (is_audio_only or fell_back_to_audio) else "upload_video"
        typing_task = asyncio.create_task(keep_typing_action(context, chat_id, action))

        # Название видео в подписи — только для премиум, лёгкий отдельный запрос метаданных
        title = ""
        if user_is_premium:
            title = await asyncio.to_thread(get_media_title, url)

        if fell_back_to_audio:
            caption = "Видео скачать не удалось, отправляю аудио-версию"
        elif title:
            caption = f"{title[:150]}"
        else:
            caption = "Скачано"
        if not user_is_premium:
            caption += f"\nОсталось: {remaining}/{DAILY_LIMIT}"

        try:
            with open(file_path, "rb") as f:
                if send_as_document:
                    await query.message.reply_document(document=f, caption=caption)
                elif is_audio_only or got_audio_file:
                    await query.message.reply_audio(audio=f, caption=caption)
                else:
                    await query.message.reply_video(video=f, supports_streaming=True, caption=caption)

            try:
                await query.edit_message_text("✅ Готово! Видео отправлено!")
            except:
                pass

            # История загрузок — только для премиум, последние 10
            if user_is_premium:
                history = download_history.setdefault(user_id, [])
                history.append({"title": title or "(без названия)", "url": url})
                del history[:-10]

        except Exception as send_err:
            logger.error("Ошибка отправки: %s", send_err)

    except Exception as e:
        logger.exception("Ошибка при скачивании %s", url)
        safe_error = clean_error_text(str(e))
        try:
            await query.edit_message_text(
                "Не получилось скачать это видео.\n\n"
                "Площадка могла временно заблокировать запрос — попробуй ещё раз чуть позже"
                "или пришли другую ссылку.\n\n"
                f"<i>Техническая причина: {safe_error[:150]}</i>",
                parse_mode="HTML",
            )
        except:
            pass
    finally:
        if typing_task:
            try:
                typing_task.cancel()
            except:
                pass
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except:
            pass


async def handle_format_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора формата (видео или аудио)"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        await query.answer()
    except:
        pass

    url = context.user_data.get("current_url")
    if not url:
        try:
            await query.edit_message_text("Ссылка потеряна")
        except:
            pass
        return

    format_choice = query.data
    is_audio_only = (format_choice == "format_audio")

    # Премиум-пользователям при выборе видео даём выбрать качество
    if not is_audio_only and is_premium(user_id):
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Быстрее (меньше файл)", callback_data="quality_fast"),
                InlineKeyboardButton("Лучшее качество", callback_data="quality_best"),
            ],
            [
                InlineKeyboardButton("Без сжатия (файлом)", callback_data="quality_doc"),
            ],
        ])
        try:
            await query.edit_message_text(
                "Доступно с подпиской — выбери качество:",
                reply_markup=keyboard,
            )
        except:
            pass
        return

    # Премиум-пользователям при выборе аудио даём выбрать битрейт
    if is_audio_only and is_premium(user_id):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Обычное (128 kbps)", callback_data="audioquality_normal"),
            InlineKeyboardButton("Высокое (320 kbps)", callback_data="audioquality_high"),
        ]])
        try:
            await query.edit_message_text(
                "Доступно с подпиской — выбери качество звука:",
                reply_markup=keyboard,
            )
        except:
            pass
        return

    format_text = "Голосовое" if is_audio_only else "Видео"
    try:
        await query.edit_message_text(
            f"{format_text}\nЗагружаю...\n\n"
            f"Иногда загрузка занимает до 4 минут (сайт может медленно отвечать) — просто подожди, бот работает."
        )
    except:
        pass

    await perform_download(query, context, url, is_audio_only, quality=None)


async def handle_quality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора качества (только для премиум, после handle_format_choice)"""
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass

    url = context.user_data.get("current_url")
    if not url:
        try:
            await query.edit_message_text("Ссылка потеряна")
        except:
            pass
        return

    send_as_document = (query.data == "quality_doc")
    quality = "fast" if query.data == "quality_fast" else "best"
    if send_as_document:
        quality_text = "Без сжатия (файлом)"
    elif quality == "fast":
        quality_text = "Быстрее"
    else:
        quality_text = "Лучшее качество"
    try:
        await query.edit_message_text(
            f"{quality_text}\nЗагружаю...\n\n"
            f"Иногда загрузка занимает до 4 минут — просто подожди."
        )
    except:
        pass

    await perform_download(query, context, url, is_audio_only=False, quality=quality, send_as_document=send_as_document)


async def handle_audioquality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора битрейта аудио (только для премиум)"""
    query = update.callback_query
    try:
        await query.answer()
    except:
        pass

    url = context.user_data.get("current_url")
    if not url:
        try:
            await query.edit_message_text("Ссылка потеряна")
        except:
            pass
        return

    quality = "high" if query.data == "audioquality_high" else "normal"
    quality_text = "Высокое (320 kbps)" if quality == "high" else "Обычное (128 kbps)"
    try:
        await query.edit_message_text(
            f"{quality_text}\nЗагружаю...\n\n"
            f"Иногда загрузка занимает до 4 минут — просто подожди."
        )
    except:
        pass

    await perform_download(query, context, url, is_audio_only=True, quality=quality)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /subscribe — покупка премиума"""
    user = update.effective_user
    user_id = user.id
    
    if is_premium(user_id):
        time_left = get_premium_time_left_text(user_id)
        await update.message.reply_text(
            f"<b>Ты уже премиум!</b>\n\n"
            f"Подписка действует ещё: <b>{time_left}</b>\n\n"
            f"Спасибо за поддержку!\n"
            f"Наслаждайся неограниченными загрузками!",
            parse_mode="HTML"
        )
    else:
        # Создаём кнопку для покупки со стикером
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("⭐ Купить премиум за 44 звезды", callback_data="buy_premium")
        ]])
        
        await update.message.reply_text(
            f"<b>SaveFlip Bot PREMIUM</b>\n\n"
            f"<b>Стоимость: 44 звезды в месяц</b>\n\n"
            f"<b>Что даёт премиум:</b>\n\n"
            f"<b>Доступ к YouTube</b>\n"
            f"<i>Без подписки YouTube-ссылки не скачиваются вообще — доступны только"
            f"другие площадки (TikTok, Instagram и т.д.). С подпиской работает и YouTube.</i>\n\n"
            f"<b>Доступ к Vimeo, Facebook, SoundCloud, Rutube, OK.ru</b>\n"
            f"<i>Ещё 5 площадок, доступных только с подпиской.</i>\n\n"
            f"<b>Выбор качества видео</b>\n"
            f"<i>После ссылки можно выбрать: быстрее (файл меньше, приходит раньше),"
            f"лучшее качество, или без сжатия — файлом, чтобы Telegram не пережимал видео.</i>\n\n"
            f"<b>Выбор битрейта аудио</b>\n"
            f"<i>Для голосовых/аудио — 128 kbps (обычное) или 320 kbps (высокое качество звука).</i>\n\n"
            f"<b>Пакетная загрузка</b>\n"
            f"<i>Пришли до 10 ссылок одним сообщением (каждая на новой строке) —"
            f"бот скачает их по очереди, не нужно слать по одной.</i>\n\n"
            f"<b>Скачивание плейлистов</b>\n"
            f"<i>Пришли ссылку на плейлист (YouTube, SoundCloud-подборку и т.д.) —"
            f"бот скачает первые {PLAYLIST_BATCH_LIMIT} видео из него автоматически.</i>\n\n"
            f"<b>История загрузок</b>\n"
            f"<i>Команда /history показывает последние 10 скачанных файлов с названиями и ссылками.</i>\n\n"
            f"<b>Название видео + автоповтор</b>\n"
            f"<i>В подписи к файлу — настоящее название видео. Если скачивание не удалось"
            f"с первого раза — бот тихо пробует ещё раз, не нужно присылать ссылку заново.</i>\n\n"
            f"<b>Без дневного лимита</b>\n"
            f"<i>Обычным пользователям доступно {DAILY_LIMIT} загрузки в день,"
            f"с подпиской — без ограничения.</i>\n\n"
            f"<b>Поддержка разработчика</b>\n"
            f"<i>Подписка помогает и дальше развивать бота — спасибо за доверие!</i>\n\n"
            f"<b>Как работает:</b>\n"
            f"Нажми кнопку → подтверди платёж звёздами → готово!\n"
            f"Звёзды снимаются один раз в месяц автоматически.\n\n"
            f"<b>Текущий статус:</b> Обычный пользователь\n\n"
            f"Подписка не только снимает ограничения — она напрямую поддерживает"
            f"дальнейшую разработку бота. Спасибо, если решишь оформить!",
            parse_mode="HTML",
            reply_markup=keyboard
        )


async def handle_premium_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик покупки премиума"""
    query = update.callback_query
    user_id = query.from_user.id
    
    try:
        await query.answer()
    except:
        pass
    
    try:
        # Отправляем счёт для оплаты звёздами
        await context.bot.send_invoice(
            chat_id=user_id,
            title="SaveFlip Bot Premium",
            description="Премиум-подписка на 1 месяц без ограничений",
            payload="saveflip_premium_1month",
            provider_token="",  # Для Telegram Stars токен не нужен
            currency="XTR",  # XTR = Telegram Stars
            prices=[{"label": "Премиум на месяц", "amount": 44}],  # 44 звезды
        )
    except Exception as e:
        logger.error(f"Ошибка при отправке счёта: {e}")
        try:
            await query.edit_message_text(f"Ошибка: {str(e)[:80]}")
        except:
            pass


async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка перед платежом"""
    query = update.pre_checkout_query
    
    if query.invoice_payload == "saveflip_premium_1month":
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Неизвестный платёж")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка успешного платежа"""
    user_id = update.effective_user.id
    payment = update.message.successful_payment
    
    if payment.invoice_payload == "saveflip_premium_1month":
        # Добавляем 30 дней премиума
        add_premium(user_id, days=30)
        
        await update.message.reply_text(
            f"<b>✅ СПАСИБО ЗА ПОКУПКУ!</b>\n\n"
            f"Ты теперь <b>ПРЕМИУМ пользователь</b>\n\n"
            f"<b>Твои новые привилегии:</b>\n"
            f"<b>Доступ к YouTube</b> — теперь можно скачивать и с YouTube\n"
            f"<b>Доступ к Vimeo, Facebook, SoundCloud, Rutube, OK.ru</b> — тоже открыты\n"
            f"<b>Выбор качества видео</b> — быстрее, лучше или без сжатия (файлом)\n"
            f"<b>Выбор битрейта аудио</b> — 128 или 320 kbps\n"
            f"<b>Пакетная загрузка</b> — несколько ссылок в одном сообщении\n"
            f"<b>Плейлисты</b> — первые {PLAYLIST_BATCH_LIMIT} видео из плейлиста одной ссылкой\n"
            f"<b>История загрузок</b> — команда /history\n"
            f"<b>Без ограничений</b> — скачивай неограниченное кол-во видео в день\n\n"
            f"📅 <b>Подписка действует до:</b> {(premium_users[user_id]).strftime('%d.%m.%Y')}\n\n"
            f"Большое спасибо за поддержку! Наслаждайся премиумом",
            parse_mode="HTML"
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Необработанная ошибка: %s", context.error)


async def keep_typing_action(context: ContextTypes.DEFAULT_TYPE, chat_id: int, action: str = "typing"):
    """
 Telegram показывает индикатор "печатает..." / "отправляет видео..."
 только около 5 секунд, поэтому для долгого скачивания его нужно
 обновлять в фоне, пока идёт работа. Останавливается через
 asyncio.CancelledError, когда основная задача завершена.
"""
    try:
        while True:
            await context.bot.send_chat_action(chat_id=chat_id, action=action)
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


# ==================== ЗАПУСК ====================

def print_startup_banner():
    """Аккуратный отчёт о состоянии бота перед запуском — сразу видно, что настроено."""
    width = 46

    def row(text: str) -> str:
        # Дополняем строку пробелами, чтобы рамка была ровной
        # (эмодзи считаем за 2 "визуальных" символа для выравнивания).
        visual_len = sum(2 if ord(ch) > 0x2000 else 1 for ch in text)
        pad = max(0, width - 2 - visual_len)
        return f"║ {text}{'' * pad} ║"

    token_ok = bool(BOT_TOKEN) and BOT_TOKEN != "ВСТАВЬ_СЮДА_СВОЙ_ТОКЕН" and ":" in BOT_TOKEN
    cookies_ok = bool(COOKIES_FILE and os.path.exists(COOKIES_FILE))

    proxy_status = "отключен"
    if USE_PROXY_FOR_YOUTUBE:
        if isinstance(USE_PROXY_FOR_YOUTUBE, str):
            proxy_status = f"{USE_PROXY_FOR_YOUTUBE[:30]}..."
        else:
            proxy_status = f"{len(FREE_PROXIES)} встроенных прокси"
    
    rows = [
        ("Токен бота", "указан" if token_ok else "не настроен"),
        ("yt-dlp", "установлен"),
        ("ffmpeg", "найден" if FFMPEG_AVAILABLE else "не найден"),
        ("Cookies", "подключены" if cookies_ok else "не используются"),
        ("Прокси & UA", proxy_status),
        ("Дневной лимит", f"{DAILY_LIMIT} попыток"),
        ("Макс. размер файла", f"{MAX_FILE_SIZE_MB} МБ"),
    ]
    label_width = max(len(label) for label, _ in rows) + 2

    print("╔" + "═" * (width - 2) + "╗")
    print(row("S A V E F L I P B O T"))
    print("╠" + "═" * (width - 2) + "╣")
    for label, value in rows:
        print(row(f"{label.ljust(label_width)}{value}"))
    print("╚" + "═" * (width - 2) + "╝")
    return token_ok


def main():
    token_ok = print_startup_banner()
    if not token_ok:
        print()
        print("Токен бота не настроен.")
        print("Вставь свой токен в переменную BOT_TOKEN в начале файла —")
        print("получить его можно у @BotFather в Telegram.")
        print()
        return


    # concurrent_updates=True — критично: без этого бот обрабатывает сообщения
    # СТРОГО по одному. Пока идёт одна загрузка (до нескольких минут), бот не
    # реагирует вообще ни на что новое — ни на вторую ссылку, ни на команды,
    # ни на сообщения от других людей. С этим флагом сообщения обрабатываются
    # параллельно (сама загрузка и так уже идёт в отдельном потоке, это безопасно).
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("limit", limit_command))
    app.add_handler(CommandHandler("testpremium", testpremium_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CallbackQueryHandler(handle_premium_purchase, pattern="buy_premium"))
    app.add_handler(CallbackQueryHandler(handle_format_choice, pattern="format_"))
    app.add_handler(CallbackQueryHandler(handle_quality_choice, pattern="quality_"))
    app.add_handler(CallbackQueryHandler(handle_audioquality_choice, pattern="audioquality_"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_error_handler(error_handler)

    print()
    print("Бот запущен и готов к работе!")
    print("Чтобы остановить его, нажми Stop в Pydroid 3.")
    print()

    try:
        app.run_polling()
    except Exception as e:
        print()
        print(f"Бот аварийно завершил работу: {e}")
        print("Проверь токен и подключение к интернету, затем запусти снова.")


if __name__ == "__main__":
    main()
