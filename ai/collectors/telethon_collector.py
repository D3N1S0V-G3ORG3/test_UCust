"""
Telethon Collector — реальный парсер Telegram-каналов.

Читает API-ключи из переменных окружения (.env):
  TELETHON_API_ID    — числовой App api_id с my.telegram.org
  TELETHON_API_HASH  — строковый App api_hash с my.telegram.org
  TELETHON_SESSION   — имя файла сессии (по умолчанию: ucust_session)

При первом запуске попросит ввести номер телефона и код из Telegram.
После авторизации сессия сохраняется в файл .session и больше не спрашивается.
"""

from __future__ import annotations

import sys
import os
import re
import html
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
import httpx

from schemas.models import CollectorDataSchema

def _log(msg: str):
    """Безопасный вывод сообщений без падения на cp1251 консолях."""
    try:
        print(msg)
    except Exception:
        try:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            print(msg.encode(enc, errors="replace").decode(enc, errors="replace"))
        except Exception:
            pass

def _get_credentials() -> tuple[str, str, str]:
    api_id = os.getenv("TELETHON_API_ID", "").strip()
    api_hash = os.getenv("TELETHON_API_HASH", "").strip()
    session = os.getenv("TELETHON_SESSION", "ucust_session").strip()
    return api_id, api_hash, session

def _is_configured() -> bool:
    api_id, api_hash, _ = _get_credentials()
    return bool(api_id and api_hash and api_id.isdigit())

# Обратная совместимость для модульных проверок
_API_ID = os.getenv("TELETHON_API_ID", "").strip()
_API_HASH = os.getenv("TELETHON_API_HASH", "").strip()
_SESSION = os.getenv("TELETHON_SESSION", "ucust_session").strip()
_IS_CONFIGURED = _is_configured()


def _get_proxy_config() -> Optional[dict]:
    """
    Формирует конфигурацию прокси для Telethon из .env (SOCKS5 / HTTP / MTProto).
    Поддерживает как TELETHON_PROXY_URL, так и раздельные параметры.
    """
    proxy_url = os.getenv("TELETHON_PROXY_URL", "").strip()
    proxy_type_env = os.getenv("TELETHON_PROXY_TYPE", "").strip().lower()
    proxy_host = os.getenv("TELETHON_PROXY_HOST", "").strip()
    proxy_port = os.getenv("TELETHON_PROXY_PORT", "").strip()
    proxy_user = os.getenv("TELETHON_PROXY_USER", "").strip() or None
    proxy_pass = os.getenv("TELETHON_PROXY_PASSWORD", "").strip() or None

    if proxy_url:
        import urllib.parse
        parsed = urllib.parse.urlparse(proxy_url)
        proxy_type_env = parsed.scheme.lower()
        proxy_host = parsed.hostname or ""
        proxy_port = str(parsed.port or 1080)
        proxy_user = parsed.username
        proxy_pass = parsed.password

    if not proxy_host or not proxy_port or not proxy_port.isdigit():
        return None

    # Определение типа прокси (1=SOCKS4, 2=SOCKS5, 3=HTTP)
    ptype = 2 if "socks5" in proxy_type_env else (1 if "socks4" in proxy_type_env else 3)
    
    proxy_dict = {
        'proxy_type': ptype,
        'addr': proxy_host,
        'port': int(proxy_port),
        'username': proxy_user,
        'password': proxy_pass,
        'rdns': True
    }
    _log(f"[TelethonCollector] 🛡️ Использование прокси: {proxy_type_env or 'socks5'}://{proxy_host}:{proxy_port}")
    return proxy_dict


def _mock_payload(channel: str, limit: int) -> dict:
    """Возвращает фиктивные данные с анализом комментариев аудитории."""
    mock_comments = [
        {"id": 101, "author": "Алексей", "text": "А сколько времени уходит на запуск системы в реальный бизнес?", "likes": 4},
        {"id": 102, "author": "Елена", "text": "Работает ли это для сложных ниш и B2B услуг?", "likes": 7},
        {"id": 103, "author": "Михаил", "text": "Главное чтобы тексты были без шаблонной воды и отсекались клише.", "likes": 12},
    ]
    return {
        "channel": channel,
        "limit": limit,
        "fetched_at": datetime.utcnow().isoformat(),
        "mode": "mock",
        "messages": [
            {
                "id": i,
                "text": f"[MOCK] Пост {i} из {channel}. Опыт внедрения мульти-агентных систем для автоматизации контента.",
                "views": 100 + i * 25,
                "comments_count": len(mock_comments),
                "comments": mock_comments,
                "top_objections_from_comments": [
                    "Сроки запуска и окупаемость",
                    "Применимость для сложных ниш",
                    "Защита от шаблонных текстов"
                ]
            }
            for i in range(1, limit + 1)
        ],
    }


async def _fetch_channel_web_preview_async(channel: str, limit: int = 10) -> Optional[dict]:
    """
    Быстрый и надежный парсинг публичного Telegram-канала через официальный Web Preview (t.me/s/channel).
    Не требует авторизации по номеру телефона, SMS или MTProto-сессии.
    """
    clean_channel = re.sub(r'^(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?', '', channel.strip())
    clean_channel = clean_channel.lstrip('@').strip('/')

    if not clean_channel:
        return None

    url = f"https://t.me/s/{clean_channel}"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as http_client:
            resp = await http_client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                }
            )
            if resp.status_code != 200:
                _log(f"[TelethonCollector] ⚠️ Web-Preview {url} вернул статус {resp.status_code}.")
                return None
            page_html = resp.text
    except Exception as http_err:
        _log(f"[TelethonCollector] ⚠️ Ошибка запроса Web-Preview {url}: {http_err}")
        return None

    raw_blocks = re.split(r'(?=<div[^>]+data-post="[^"]+")', page_html)
    messages_data = []

    for blk in raw_blocks:
        m_id = re.search(r'data-post="([^"]+)"', blk)
        if not m_id:
            continue
        post_id_str = m_id.group(1)

        text_match = re.search(r'<div class="[^"]*tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', blk, re.DOTALL)
        msg_text = ""
        if text_match:
            raw_t = text_match.group(1)
            raw_t = re.sub(r'<br\s*/?>', '\n', raw_t)
            raw_t = re.sub(r'<[^>]+>', '', raw_t)
            msg_text = html.unescape(raw_t).strip()

        date_match = re.search(r'<time datetime="([^"]+)"', blk)
        date_str = date_match.group(1) if date_match else None

        views_match = re.search(r'<span class="tgme_widget_message_views">([^<]+)</span>', blk)
        views_str = views_match.group(1).strip() if views_match else "0"
        views = 0
        try:
            if "K" in views_str or "k" in views_str:
                views = int(float(re.sub(r'[^\d.,]', '', views_str).replace(',', '.')) * 1000)
            elif "M" in views_str or "m" in views_str:
                views = int(float(re.sub(r'[^\d.,]', '', views_str).replace(',', '.')) * 1000000)
            else:
                views = int(re.sub(r'\D', '', views_str) or 0)
        except Exception:
            views = 0

        photo_match = re.search(r"background-image:url\('([^']+)'\)", blk)
        photo_url = photo_match.group(1) if photo_match else None

        post_num = int(post_id_str.split("/")[-1]) if "/" in post_id_str and post_id_str.split("/")[-1].isdigit() else len(messages_data) + 1

        if msg_text or photo_url:
            messages_data.append({
                "id": post_num,
                "text": msg_text,
                "date": date_str,
                "views": views,
                "forwards": 0,
                "comments_count": 0,
                "comments": [],
                "media_type": "photo" if photo_url else None,
                "photo_url": photo_url,
                "media_path": None,
                "is_forwarded": "tgme_widget_message_forwarded_from" in blk,
            })

    if not messages_data:
        return None

    messages_data.reverse()
    selected = messages_data[:limit]
    _log(f"[TelethonCollector] 🌐 Успешно собрано {len(selected)} реальных постов из Web-Preview @{clean_channel}.")
    return {
        "channel": f"@{clean_channel}",
        "limit": limit,
        "fetched_at": datetime.utcnow().isoformat(),
        "mode": "real_web_preview",
        "messages": selected,
    }


async def _fetch_channel_async(channel: str, limit: int) -> dict:
    """Асинхронно забирает посты и комментарии из Telegram-канала через Telethon с авто-переходом на Web-Preview."""
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

    api_id, api_hash, session = _get_credentials()
    proxy = _get_proxy_config()
    client = TelegramClient(session, int(api_id), api_hash, proxy=proxy)

    messages_data = []
    try:
        try:
            await asyncio.wait_for(client.connect(), timeout=5.0)
        except Exception as conn_err:
            err_desc = str(conn_err) or type(conn_err).__name__
            _log(f"[TelethonCollector] ⚠️ Не удалось подключиться к Telegram MTProto ({err_desc}). Переключение на Web-Preview...")
            web_data = await _fetch_channel_web_preview_async(channel, limit)
            if web_data and web_data.get("messages"):
                return web_data
            return _mock_payload(channel, limit)

        if not await client.is_user_authorized():
            _log(f"[TelethonCollector] ℹ️ Сессия '{session}' не авторизована. Переключение на Web-Preview для {channel}...")
            web_data = await _fetch_channel_web_preview_async(channel, limit)
            if web_data and web_data.get("messages"):
                return web_data
            return _mock_payload(channel, limit)
            
        async for message in client.iter_messages(channel, limit=limit):
            # Пропускаем рекламные сообщения (forwarded + без текста)
            if message.fwd_from and not message.text:
                continue
            media_type = None
            media_path = None
            if message.media:
                if isinstance(message.media, MessageMediaPhoto):
                    media_type = "photo"
                    try:
                        if not os.path.exists("temp_media"):
                            os.makedirs("temp_media")
                        filepath = await client.download_media(message, file="temp_media/")
                        media_path = filepath
                    except Exception as e:
                        _log(f"Failed to download photo: {e}")
                elif isinstance(message.media, MessageMediaDocument):
                    media_type = "document"

            # Сбор комментариев / ответов под постом
            comments = []
            comments_count = 0
            if getattr(message, "replies", None):
                comments_count = getattr(message.replies, "replies", 0) or 0
                if comments_count > 0:
                    try:
                        async for reply in client.iter_messages(channel, reply_to=message.id, limit=5):
                            if reply.text:
                                comments.append({
                                    "id": reply.id,
                                    "text": reply.text,
                                    "date": reply.date.isoformat() if reply.date else None,
                                    "sender_id": reply.sender_id
                                })
                    except Exception:
                        pass

            messages_data.append({
                "id": message.id,
                "text": message.text or "",
                "date": message.date.isoformat() if message.date else None,
                "views": getattr(message, "views", 0) or 0,
                "forwards": getattr(message, "forwards", 0) or 0,
                "comments_count": comments_count,
                "comments": comments,
                "media_type": media_type,
                "media_path": media_path,
                "is_forwarded": message.fwd_from is not None,
            })

    except Exception as fetch_err:
        _log(f"[TelethonCollector] ⚠️ Ошибка при парсинге Telethon: {fetch_err}. Переключение на Web-Preview...")
        web_data = await _fetch_channel_web_preview_async(channel, limit)
        if web_data and web_data.get("messages"):
            return web_data
        return _mock_payload(channel, limit)
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    return {
        "channel": channel,
        "limit": limit,
        "fetched_at": datetime.utcnow().isoformat(),
        "mode": "real",
        "messages": messages_data,
    }


def _run_async_safely(coro, timeout: float = 30.0):
    """
    Безопасно выполняет асинхронную корутину в синхронном контексте,
    учитывая любые состояния event loop (работающий loop, закрытый loop, отсутствие loop).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=timeout)

    return asyncio.run(coro)


class TelethonCollector:
    """
    Коллектор постов из Telegram-каналов через Telethon с отказоустойчивым Web-Preview фолбэком.

    Поддерживает 3 уровня устойчивости:
    1. Авторизованный Telethon MTProto клиент (богатые метаданные и комментарии).
    2. Публичный Web-Preview парсер (t.me/s/channel) — 100% реальные посты без необходимости авторизации по SMS.
    3. Синтетический Mock-режим — только при отсутствии интернет-доступа или закрытом приватном канале.
    """

    def collect(self, channel: str, limit: int = 10) -> CollectorDataSchema:
        """
        Синхронная обёртка для вызова из нересинхронного кода.

        :param channel: username канала (например @durov или https://t.me/durov)
        :param limit: максимальное количество постов
        :return: CollectorDataSchema с собранными данными
        """
        if not _is_configured():
            _log("[TelethonCollector] ℹ️ TELETHON_API_ID/HASH не заданы в .env — запуск публичного Web-Preview парсинга...")
            try:
                payload = _run_async_safely(_fetch_channel_web_preview_async(channel, limit), timeout=15.0)
            except Exception as e:
                _log(f"[TelethonCollector] ⚠️ Ошибка Web-Preview: {e}")
                payload = None
            if not payload or not payload.get("messages"):
                payload = _mock_payload(channel, limit)
        else:
            try:
                payload = _run_async_safely(_fetch_channel_async(channel, limit), timeout=60.0)
                _log(
                    f"[TelethonCollector] Собрано {len(payload.get('messages', []))} "
                    f"постов из {channel}."
                )
            except Exception as exc:
                _log(f"[TelethonCollector] Ошибка парсинга: {exc}. Переключение на Web-Preview...")
                try:
                    payload = _run_async_safely(_fetch_channel_web_preview_async(channel, limit), timeout=15.0)
                except Exception:
                    payload = None
                if not payload or not payload.get("messages"):
                    payload = _mock_payload(channel, limit)

        return CollectorDataSchema(source="telethon", payload=payload)

    async def collect_async(self, channel: str, limit: int = 10) -> CollectorDataSchema:
        """
        Нативный async-метод для вызова из async-контекста (onboarding_pipeline и т.д.).

        :param channel: username канала
        :param limit: максимальное количество постов
        :return: CollectorDataSchema
        """
        if not _is_configured():
            _log("[TelethonCollector] ℹ️ TELETHON_API_ID/HASH не заданы — запуск публичного Web-Preview парсинга...")
            web_data = await _fetch_channel_web_preview_async(channel, limit)
            if web_data and web_data.get("messages"):
                payload = web_data
            else:
                payload = _mock_payload(channel, limit)
        else:
            try:
                payload = await _fetch_channel_async(channel, limit)
                _log(
                    f"[TelethonCollector] Собрано {len(payload['messages'])} "
                    f"постов из {channel}."
                )
            except Exception as exc:
                _log(f"[TelethonCollector] Ошибка: {exc}. Переключение на Web-Preview...")
                web_data = await _fetch_channel_web_preview_async(channel, limit)
                if web_data and web_data.get("messages"):
                    payload = web_data
                else:
                    payload = _mock_payload(channel, limit)

        return CollectorDataSchema(source="telethon", payload=payload)
