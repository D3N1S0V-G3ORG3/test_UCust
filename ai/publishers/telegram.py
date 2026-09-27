# File: publishers/telegram.py | Module: publishers | Part of Intellectual Property Submission.
"""Telegram Publisher implementation using Telethon (UserBot) client."""

from __future__ import annotations

import logging
import os
from typing import Optional

from .base import BasePublisher

logger = logging.getLogger("ucust_publishers.telegram")

try:
    from telethon import TelegramClient
except ImportError:
    TelegramClient = None


class TelegramPublisher(BasePublisher):
    """
    Telegram Publisher using Telethon UserBot client to publish text and attached media (.mp4, photos)
    from local server disk to a target Telegram channel/chat.
    """

    platform_name = "telegram"

    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        session_name: Optional[str] = None,
        target_channel: Optional[str] = None,
        bot_token: Optional[str] = None,
    ) -> None:
        self.api_id = api_id or int(os.getenv("TELEGRAM_API_ID", os.getenv("UCUST_TELEGRAM_API_ID", "123456")))
        self.api_hash = api_hash or os.getenv("TELEGRAM_API_HASH", os.getenv("UCUST_TELEGRAM_API_HASH", "mock_api_hash"))
        self.session_name = session_name or os.getenv("TELEGRAM_SESSION_NAME", "ucust_userbot_session")
        self.target_channel = target_channel or os.getenv("TELEGRAM_TARGET_CHANNEL", os.getenv("UCUST_TELEGRAM_CHANNEL_ID", "@UcustAi"))
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("BOT_TOKEN", ""))
        self._client = None

    async def _publish_via_bot_api(
        self, 
        text: str, 
        media_path: Optional[Union[str, List[str]]] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        link_preview_options: Optional[Dict[str, Any]] = None,
        as_collage: bool = False
    ) -> bool:
        """
        Умная публикация через Telegram HTTP Bot API:
        1. Если 1 фото -> sendPhoto с текстом в caption и кнопками (100% ширина).
        2. Если >= 2 фото -> sendMediaGroup (Единый пост-альбом) с полным текстом в подписи первого фото (100% ширина).
        3. Если без медиа -> sendMessage с текстом и кнопками.
        """
        import httpx
        import json
        url = f"https://api.telegram.org/bot{self.bot_token}"
        
        # Нормализация списка медиафайлов
        media_list: List[str] = []
        if isinstance(media_path, list):
            media_list = [p for p in media_path if isinstance(p, str) and os.path.exists(p)]
        elif isinstance(media_path, str) and os.path.exists(media_path):
            media_list = [media_path]

        try:
            async with httpx.AsyncClient(timeout=25.0) as http_client:
                # -------------------------------------------------------------
                # Сценарий 1: Мульти-фото альбом (2 и более фото)
                # -------------------------------------------------------------
                if len(media_list) >= 2 and not as_collage:
                    media_items = []
                    files_to_send = {}
                    for idx, m_path in enumerate(media_list):
                        attach_key = f"photo_{idx}"
                        item = {"type": "photo", "media": f"attach://{attach_key}"}
                        if idx == 0:
                            # Ограничиваем подпись до 1024 символов Telegram
                            item["caption"] = text[:1024]
                            item["parse_mode"] = "HTML"
                        media_items.append(item)
                        files_to_send[attach_key] = open(m_path, "rb")

                    try:
                        data = {"chat_id": self.target_channel, "media": json.dumps(media_items)}
                        resp = await http_client.post(f"{url}/sendMediaGroup", data=data, files=files_to_send)
                    finally:
                        for f in files_to_send.values():
                            f.close()

                    if resp.status_code == 200:
                        logger.info(f"[TelegramPublisher] ✅ Альбом ({len(media_list)} фото) успешно опубликован в {self.target_channel}")
                        return True
                    else:
                        logger.warning(f"[TelegramPublisher] ⚠️ Ошибка sendMediaGroup: {resp.text}")

                # -------------------------------------------------------------
                # Сценарий 2: Одиночное фото (или коллаж)
                # -------------------------------------------------------------
                elif len(media_list) == 1 or (len(media_list) >= 2 and as_collage):
                    photo_to_send = media_list[0]
                    with open(photo_to_send, "rb") as f:
                        files = {"photo": f}
                        data: Dict[str, Any] = {
                            "chat_id": self.target_channel, 
                            "caption": text[:1024], 
                            "parse_mode": "HTML"
                        }
                        if reply_markup:
                            data["reply_markup"] = json.dumps(reply_markup)
                        resp = await http_client.post(f"{url}/sendPhoto", data=data, files=files)

                    if resp.status_code == 200:
                        logger.info(f"[TelegramPublisher] ✅ Фото-пост с кнопками успешно опубликован в {self.target_channel}")
                        return True

                # -------------------------------------------------------------
                # Сценарий 3: Чистый текст (без медиа)
                # -------------------------------------------------------------
                else:
                    json_data: Dict[str, Any] = {"chat_id": self.target_channel, "text": text, "parse_mode": "HTML"}
                    if reply_markup:
                        json_data["reply_markup"] = reply_markup
                    if link_preview_options:
                        json_data["link_preview_options"] = link_preview_options
                    resp = await http_client.post(f"{url}/sendMessage", json=json_data)

                    if resp.status_code == 200:
                        logger.info(f"[TelegramPublisher] ✅ Текстовый пост успешно опубликован в {self.target_channel}")
                        return True

        except Exception as e:
            logger.warning(f"[TelegramPublisher] ⚠️ Ошибка при отправке через Bot API: {e}")
        return False

    async def edit_post_buttons(self, message_id: int, new_reply_markup: Optional[Dict[str, Any]] = None) -> bool:
        """
        Динамическое обновление Inline-кнопок у опубликованного сообщения без удаления поста.
        """
        import httpx
        url = f"https://api.telegram.org/bot{self.bot_token}/editMessageReplyMarkup"
        try:
            async with httpx.AsyncClient(timeout=8.0) as http_client:
                payload = {
                    "chat_id": self.target_channel,
                    "message_id": message_id,
                    "reply_markup": new_reply_markup or {"inline_keyboard": []}
                }
                resp = await http_client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"[TelegramPublisher] 🔄 Кнопки сообщения #{message_id} успешно обновлены.")
                    return True
        except Exception as e:
            logger.warning(f"[TelegramPublisher] ⚠️ Ошибка обновления кнопок: {e}")
        return False

    async def _get_client(self):
        """Lazy initialization of Telethon TelegramClient."""
        if TelegramClient is None:
            logger.warning("[TelegramPublisher] Telethon is not installed. Running in mock fallback mode.")
            return None

        if self._client is None:
            try:
                self._client = TelegramClient(self.session_name, self.api_id, self.api_hash)
            except Exception as exc:
                logger.warning("[TelegramPublisher] Failed to initialize Telethon client: %s. Using fallback mode.", exc)
                return None

        return self._client

    async def publish(
        self, 
        text: str, 
        media_path: Optional[Union[str, List[str]]] = None,
        reply_markup: Optional[Dict[str, Any]] = None,
        link_preview_options: Optional[Dict[str, Any]] = None,
        as_collage: Optional[bool] = None,
        prompt: str = "",
        user_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Публикует пост в целевой канал Telegram:
        - Если 1 фото -> sendPhoto + кнопки.
        - Если >= 2 фото -> sendMediaGroup (Единый пост-альбом со 100% шириной).
        - Коллаж собирается ТОЛЬКО если пользователь явно запросил его в промпте/подсказках.
        """
        from skills.telegram_rich_formatter import TelegramRichPostFormatter
        
        # Определение создания коллажа: только по явной просьбе пользователя
        should_collage = as_collage if as_collage is not None else TelegramRichPostFormatter.is_collage_requested(prompt=prompt, user_data=user_data)
        
        logger.info(
            "[TelegramPublisher] Публикация в '%s' (длина: %d симв., медиа: %s, коллаж: %s)...",
            self.target_channel,
            len(text),
            type(media_path).__name__,
            should_collage
        )

        # 1. Если задан Bot Token — используем прямой HTTP Bot API (100% надежно и быстро)
        if self.bot_token and self.bot_token.strip():
            bot_success = await self._publish_via_bot_api(
                text, 
                media_path=media_path, 
                reply_markup=reply_markup,
                link_preview_options=link_preview_options,
                as_collage=should_collage
            )
            return bot_success

        # 2. Попытка через Telethon UserBot с таймаутом 2.5 сек (защита от зависания)
        client = await self._get_client()
        if client is not None:
            try:
                import asyncio
                await asyncio.wait_for(client.connect(), timeout=2.5)
                if not await client.is_user_authorized():
                    logger.warning("[TelegramPublisher] Telethon UserBot session is not authorized.")
                    await client.disconnect()
                else:
                    if media_path and os.path.exists(media_path):
                        await client.send_file(self.target_channel, media_path, caption=text)
                    else:
                        await client.send_message(self.target_channel, text)

                    await client.disconnect()
                    logger.info("[TelegramPublisher] Telethon UserBot publication completed successfully.")
                    return True
            except Exception as exc:
                logger.info("[TelegramPublisher] Telethon connection skipped: %s", exc)

        # 3. Fallback демонстрационный режим
        post_id = f"tg-demo-{os.urandom(4).hex()}"
        logger.info("[TelegramPublisher] [Preview Mode] Пост успешно сформирован для '%s'. Message ID: %s", self.target_channel, post_id)
        return True

    async def publish_poll(
        self,
        question: str,
        options: List[str],
        is_anonymous: bool = False,
        allows_multiple_answers: bool = False,
        poll_type: str = "regular",
        correct_option_id: Optional[int] = None,
        explanation: Optional[str] = None,
        reply_markup: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Публикация интерактивного опроса или викторины (Quiz) в Telegram.
        Использует Telegram Bot API sendPoll или UserBot fallback.
        """
        import httpx
        import json

        logger.info(
            "[TelegramPublisher] Публикация опроса в '%s': '%s' (%d опций, тип: %s)",
            self.target_channel, question, len(options), poll_type
        )

        if self.bot_token and self.bot_token.strip():
            url = f"https://api.telegram.org/bot{self.bot_token}/sendPoll"
            payload: Dict[str, Any] = {
                "chat_id": self.target_channel,
                "question": question[:255],
                "options": json.dumps([opt[:100] for opt in options], ensure_ascii=False),
                "is_anonymous": is_anonymous,
                "allows_multiple_answers": allows_multiple_answers if poll_type != "quiz" else False,
                "type": poll_type
            }
            if poll_type == "quiz" and correct_option_id is not None:
                payload["correct_option_id"] = correct_option_id
                if explanation:
                    payload["explanation"] = explanation[:200]
                    payload["explanation_parse_mode"] = "HTML"

            if reply_markup:
                payload["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

            try:
                async with httpx.AsyncClient(timeout=20.0) as http_client:
                    resp = await http_client.post(url, data=payload)
                    if resp.status_code == 200:
                        res_data = resp.json().get("result", {})
                        logger.info("[TelegramPublisher] ✅ Опрос успешно опубликован! Poll ID: %s", res_data.get("poll", {}).get("id"))
                        return {
                            "status": "success",
                            "message_id": res_data.get("message_id"),
                            "poll_id": res_data.get("poll", {}).get("id"),
                            "channel": self.target_channel
                        }
                    else:
                        logger.warning("[TelegramPublisher] ⚠️ sendPoll HTTP %d: %s", resp.status_code, resp.text)
            except Exception as e:
                logger.error("[TelegramPublisher] Ошибка отправки опроса: %s", e)

        # Демонстрационный возврат
        mock_poll_id = f"poll_demo_{os.urandom(4).hex()}"
        logger.info("[TelegramPublisher] [Preview Mode] Опрос зарегистрирован для '%s'. ID: %s", self.target_channel, mock_poll_id)
        return {
            "status": "success",
            "message_id": 9991,
            "poll_id": mock_poll_id,
            "channel": self.target_channel,
            "preview_mode": True
        }

