# File: ai/services/channel_formatters.py
"""
ChannelFormattersFactory: Unified Multi-Platform Post Formatting and Sanitization Engine.
Consolidates Telegram (Bot API 7.2+), VKontakte, Odnoklassniki, and Max Messenger formatting rules into a single DRY module.
"""

from __future__ import annotations

import re
import html
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Union
from pydantic import BaseModel, Field

try:
    from skills.expandable_blockquote import ExpandableBlockquoteFormatter
except ImportError:
    try:
        from ai.skills.expandable_blockquote import ExpandableBlockquoteFormatter
    except ImportError:
        ExpandableBlockquoteFormatter = None


class TargetChannelEnum(str, Enum):
    TELEGRAM = "tg"
    VK = "vk"
    OK = "ok"
    MAX = "max"

    @classmethod
    def normalize(cls, val: Any) -> "TargetChannelEnum":
        if isinstance(val, TargetChannelEnum):
            return val
        s = str(val).lower().strip()
        if any(k in s for k in ["tg", "telegram", "телег", "тг"]):
            return cls.TELEGRAM
        if any(k in s for k in ["vk", "vkontakte", "вк", "вконтакте"]):
            return cls.VK
        if any(k in s for k in ["ok", "odnoklassniki", "ок", "однокласс"]):
            return cls.OK
        if any(k in s for k in ["max", "мессенджер", "макс"]):
            return cls.MAX
        return cls.TELEGRAM


class FormattedPostResult(BaseModel):
    """Единый результат платформенного форматирования."""
    channel: TargetChannelEnum
    post_text: str
    caption_text: Optional[str] = None
    extended_text: Optional[str] = None
    first_comment: Optional[str] = None
    snippet_url: Optional[str] = None
    push_preview: Optional[str] = None
    sms_fallback: Optional[str] = None
    reply_markup: Optional[Dict[str, Any]] = None
    char_count: int = 0
    is_valid: bool = True
    warnings: List[str] = Field(default_factory=list)


class SharedSanitizerCore:
    """Общие утилиты нормализации типографики и очистки тегов."""

    @staticmethod
    def clean_typography(text: str) -> str:
        """Нормализация русской типографики: кавычки-ёлочки, длинные тире, неразрывные пробелы."""
        if not text:
            return ""
        res = text
        # Замена дефисов между словами на длинное тире
        res = re.sub(r'(\s)[-–](\s)', r'\1—\2', res)
        # Кавычки лапки/прямые на ёлочки «»
        res = re.sub(r'(?:\"|&quot;)([^\"\n]+?)(?:\"|&quot;)', r'«\1»', res)
        # Удаление дублирующихся пробелов
        res = re.sub(r'[ \t]+', ' ', res)
        return res

    @staticmethod
    def strip_all_tags(text: str) -> str:
        """Полное удаление любых HTML тегов с декодированием сущностей."""
        if not text:
            return ""
        clean = re.sub(r'<[^>]+>', '', text)
        return html.unescape(clean).strip()

    @staticmethod
    def remove_empty_lines_overflow(text: str) -> str:
        """Ограничивает серии пустых строк максимум двумя переносами."""
        if not text:
            return ""
        return re.sub(r'\n{3,}', '\n\n', text).strip()


class TelegramFormatter:
    """Форматтер для Telegram: поддержка HTML 7.2+, умное деление подписи фото (1024) и текста (4096)."""

    ALLOWED_TAGS = {"b", "strong", "i", "em", "code", "pre", "a", "s", "strike", "del", "u", "blockquote", "tg-spoiler", "tg-emoji"}

    COLLAGE_KEYWORDS = [
        "коллаж", "коллажем", "склейка", "склей", "сетка 2x2", "сеткой", "плиткой",
        "grid", "collage", "в один кадр", "объедини фото", "сделай коллаж"
    ]

    @classmethod
    def format_clickable_promocodes(cls, text: str, promo_code: Optional[str] = None) -> str:
        if not text:
            return ""
        result = text
        if promo_code and promo_code.strip():
            code_clean = promo_code.strip()
            if f"<code>{code_clean}</code>" not in result and f"`{code_clean}`" not in result:
                pattern = re.compile(rf"(?<!<code>)(?<!`)\b({re.escape(code_clean)})\b(?!</code>)(?!`)", re.IGNORECASE)
                result = pattern.sub(r"<code>\1</code>", result)

        promo_keyword_pattern = re.compile(
            r"(промокод[уа]?\s*[:\-—]?\s*)(?:«|\"|\b)([A-Z0-9А-Я_]{4,20})(?:»|\"|\b)",
            re.IGNORECASE
        )
        result = promo_keyword_pattern.sub(lambda m: f"{m.group(1)}<code>{m.group(2)}</code>", result)

        phone_pattern = re.compile(
            r"(?<!<code>)(?<!`)(?:(?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2})(?!</code>)(?!`)"
        )
        result = phone_pattern.sub(r"<code>\g<0></code>", result)
        return result

    @classmethod
    def format_strikethrough_prices(cls, text: str) -> str:
        if not text:
            return ""
        patterns = [
            (r"(?:вместо|старая цена:?)\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))\s*(?:всего|новая цена:?|теперь)?\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))", r"<s>\1</s> <b>\2</b>"),
            (r"(?:было:?)\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))\s*(?:[—\-,]\s*(?:стало:?))?\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))", r"<s>\1</s> <b>\2</b>"),
            (r"(\d[\d\s]*(?:₽|руб|rub|\$|€))\s*(?:->|→|=>)\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))", r"<s>\1</s> <b>\2</b>"),
        ]
        res = text
        for pat, repl in patterns:
            res = re.sub(pat, repl, res, flags=re.IGNORECASE)
        return res

    @classmethod
    def format_spoilers(cls, text: str, spoiler_keywords: Optional[List[str]] = None) -> str:
        if not text:
            return ""
        res = re.sub(r"\|\|(.*?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", text)
        triggers = [
            r"(секретный\s+бонус\s*[:\-—]?\s*)([^\n\.]+)",
            r"(правильный\s+ответ\s*[:\-—]?\s*)([^\n\.]+)",
            r"(сюрприз\s+внутри\s*[:\-—]?\s*)([^\n\.]+)",
        ]
        for trig in triggers:
            res = re.sub(trig, r"\1<tg-spoiler>\2</tg-spoiler>", res, flags=re.IGNORECASE)
        return res

    @classmethod
    def sanitize_telegram_html(cls, text: str, promo_code: Optional[str] = None) -> str:
        if not text:
            return ""
        res = text
        # Замена плейсхолдеров
        placeholder_patterns = [
            r"\[ссылка\s+на\s+сайт[^\]]*\]", r"\[ссылка[^\]]*\]", r"\[директ[^\]]*\]",
            r"\[контакты[^\]]*\]", r"\[телефон[^\]]*\]", r"\[адрес[^\]]*\]"
        ]
        for p_pat in placeholder_patterns:
            res = re.sub(p_pat, "👉 по ссылке в шапке профиля или кнопке ниже", res, flags=re.IGNORECASE)

        # Markdown -> Telegram HTML
        res = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", res)
        res = re.sub(r"(?<!\n)(?<!^)\*([^\*\n]+?)\*", r"<i>\1</i>", res)
        res = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", res)

        # Типографика
        res = SharedSanitizerCore.clean_typography(res)

        # Санитизация тегов
        def _filter_tag(match):
            tag_full = match.group(0)
            tag_name = match.group(1).lower()
            if tag_name.startswith("/"):
                tag_name = tag_name[1:]
            if tag_name in cls.ALLOWED_TAGS:
                return tag_full
            return ""

        res = re.sub(r'<(/?[a-zA-Z0-9\-_]+)(?:\s+[^>]*)?>', _filter_tag, res)
        return SharedSanitizerCore.remove_empty_lines_overflow(res)

    @classmethod
    def split_caption_and_body(cls, text: str, max_caption_len: int = 1000) -> Tuple[str, str]:
        clean = cls.sanitize_telegram_html(text)
        if len(clean) <= max_caption_len:
            return clean, ""

        paragraphs = [p.strip() for p in clean.split("\n\n") if p.strip()]
        if len(paragraphs) <= 1:
            return clean[:max_caption_len], clean[max_caption_len:]

        caption_parts: List[str] = []
        body_parts: List[str] = []
        cur_len = 0

        for p in paragraphs:
            p_len = len(p) + 2
            if cur_len + p_len <= max_caption_len and not body_parts:
                caption_parts.append(p)
                cur_len += p_len
            else:
                body_parts.append(p)

        return "\n\n".join(caption_parts), "\n\n".join(body_parts)

    @classmethod
    def generate_inline_keyboard(
        cls,
        company_name: str = "",
        website_url: Optional[str] = None,
        contacts: Optional[Dict[str, Any]] = None,
        social_links: Optional[Dict[str, Any]] = None,
        cta_type: str = "general",
        promo_code: Optional[str] = None,
        custom_buttons: Optional[List[List[Dict[str, str]]]] = None
    ) -> Dict[str, Any]:
        if custom_buttons:
            return {"inline_keyboard": custom_buttons}

        keyboard: List[List[Dict[str, str]]] = []
        contacts = contacts or {}
        social_links = social_links or {}

        web = website_url or social_links.get("website") or contacts.get("website")
        map_url = social_links.get("2gis") or social_links.get("yandex_maps") or contacts.get("map_url")
        if not map_url and contacts.get("address"):
            clean_addr = contacts['address'].replace(" ", "+")
            map_url = f"https://yandex.ru/maps/?text={clean_addr}"

        tg_contact = social_links.get("telegram") or social_links.get("tg_manager") or contacts.get("telegram")

        row1: List[Dict[str, str]] = []
        if web and str(web).startswith("http"):
            label = "🛍️ Оформить заказ" if cta_type in ["ecommerce", "delivery"] else "🌐 Перейти на сайт"
            row1.append({"text": label, "url": str(web)})
        if row1:
            keyboard.append(row1)

        row2: List[Dict[str, str]] = []
        if map_url and str(map_url).startswith("http"):
            row2.append({"text": "📍 Мы на карте", "url": str(map_url)})
        if tg_contact and str(tg_contact).startswith("http"):
            row2.append({"text": "💬 Написать менеджеру", "url": str(tg_contact)})
        if row2:
            keyboard.append(row2)

        return {"inline_keyboard": keyboard} if keyboard else {}

    @classmethod
    def format_telegram_post(
        cls,
        text: str,
        company_name: str = "",
        website_url: Optional[str] = None,
        contacts: Optional[Dict[str, Any]] = None,
        social_links: Optional[Dict[str, Any]] = None,
        promo_code: Optional[str] = None,
        cta_type: str = "general",
        enable_clickable_promo: bool = True,
        enable_strikethrough: bool = True,
        enable_spoilers: bool = True,
        enable_expandable_blockquote: bool = True,
        enable_buttons: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        html_text = cls.sanitize_telegram_html(text, promo_code=promo_code)
        if enable_clickable_promo:
            html_text = cls.format_clickable_promocodes(html_text, promo_code=promo_code)
        if enable_strikethrough:
            html_text = cls.format_strikethrough_prices(html_text)
        if enable_spoilers:
            html_text = cls.format_spoilers(html_text)

        reply_markup = None
        if enable_buttons:
            reply_markup = cls.generate_inline_keyboard(
                company_name=company_name,
                website_url=website_url,
                contacts=contacts,
                social_links=social_links,
                cta_type=cta_type,
                promo_code=promo_code
            )

        return {
            "clean_text": SharedSanitizerCore.strip_all_tags(html_text),
            "html_text": html_text,
            "markdown_v2_text": SharedSanitizerCore.strip_all_tags(html_text),
            "reply_markup": reply_markup,
            "expandable_blocks": [],
        }

    build_rich_telegram_post = format_telegram_post

    @classmethod
    def is_collage_requested(cls, prompt: str = "", user_data: Optional[Dict[str, Any]] = None) -> bool:
        if user_data:
            if user_data.get("as_collage") is True or user_data.get("format") in ["collage", "коллаж", "grid"]:
                return True
            hints = str(user_data.get("hints", "")) + " " + str(user_data.get("instructions", ""))
            hints_lower = hints.lower()
            for kw in cls.COLLAGE_KEYWORDS:
                if kw in hints_lower:
                    return True
        if prompt:
            prompt_lower = prompt.lower()
            for kw in cls.COLLAGE_KEYWORDS:
                if kw in prompt_lower:
                    return True
        return False

    @classmethod
    def format_post(cls, text: str, has_media: bool = False, **kwargs) -> FormattedPostResult:
        res_dict = cls.format_telegram_post(text, **kwargs)
        html_text = res_dict["html_text"]
        caption, extended = cls.split_caption_and_body(html_text) if has_media else ("", "")
        return FormattedPostResult(
            channel=TargetChannelEnum.TELEGRAM,
            post_text=html_text,
            caption_text=caption if has_media else None,
            extended_text=extended if (has_media and extended) else None,
            reply_markup=res_dict.get("reply_markup"),
            char_count=len(html_text),
            is_valid=len(html_text) <= 4096,
        )


class VKFormatter:
    """Форматтер для ВКонтакте: защита органических охватов (First Comment Rule), срез 280 символов до ката."""

    @classmethod
    def format_vk_post(
        cls,
        text: str,
        group_domain: Optional[str] = None,
        promo_code: Optional[str] = None,
        external_url: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        payload = cls.format_vk_post_payload(
            text, group_domain=group_domain, promo_code=promo_code, external_url=external_url, **kwargs
        )
        return payload

    @classmethod
    def format_vk_post_payload(
        cls,
        text: str,
        group_domain: Optional[str] = None,
        promo_code: Optional[str] = None,
        external_url: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        if not text:
            return {"post_text": "", "first_comment": ""}

        res = SharedSanitizerCore.clean_typography(text)
        first_comment_links: List[str] = []
        if external_url:
            first_comment_links.append(external_url)

        external_link_pattern = re.compile(r'https?://(?!vk\.com|vk\.me)[^\s<>"\']+', re.IGNORECASE)
        for fl in external_link_pattern.findall(res):
            if fl not in first_comment_links:
                first_comment_links.append(fl)

        def _replace_html_link(m):
            url = m.group(1)
            anchor = m.group(2)
            if "vk.com" in url or "vk.me" in url:
                return anchor
            if url not in first_comment_links:
                first_comment_links.append(url)
            return anchor

        res = re.sub(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', _replace_html_link, res, flags=re.IGNORECASE)
        clean_text = SharedSanitizerCore.strip_all_tags(res)
        clean_text = external_link_pattern.sub('', clean_text).strip()
        clean_text = SharedSanitizerCore.remove_empty_lines_overflow(clean_text)

        first_comment = ""
        if first_comment_links:
            first_comment = "🔗 Ссылка для перехода: " + " | ".join(first_comment_links)

        return {
            "post_text": clean_text,
            "first_comment": first_comment
        }

    @classmethod
    def format_post(cls, text: str, has_media: bool = False, **kwargs) -> FormattedPostResult:
        res = cls.format_vk_post_payload(text, **kwargs)
        clean_text = res["post_text"]
        first_comment = res["first_comment"]
        return FormattedPostResult(
            channel=TargetChannelEnum.VK,
            post_text=clean_text,
            first_comment=first_comment if first_comment else None,
            char_count=len(clean_text),
            is_valid=len(clean_text) <= 15000,
        )


class OKFormatter:
    """Форматтер для Одноклассников: удаление HTML, чистый воздух, одиночный сниппет ссылки."""

    @classmethod
    def format_ok_post(cls, text: str, promo_code: Optional[str] = None, **kwargs) -> str:
        payload = cls.format_ok_post_payload(text, promo_code=promo_code, **kwargs)
        return payload["post_text"]

    @classmethod
    def format_ok_post_payload(cls, text: str, promo_code: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        if not text:
            return {"post_text": "", "snippet_url": None, "attachment_links": []}

        res = SharedSanitizerCore.clean_typography(text)
        attachment_links: List[str] = []

        # 1. Ссылки из HTML <a href="...">
        def _extract_a_link(m):
            url = m.group(1)
            anchor = m.group(2)
            if url not in attachment_links:
                attachment_links.append(url)
            return anchor

        res = re.sub(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', _extract_a_link, res, flags=re.IGNORECASE)

        # 2. Ссылки из Markdown [Текст](URL)
        def _extract_md_link(m):
            anchor = m.group(1)
            url = m.group(2)
            if url not in attachment_links:
                attachment_links.append(url)
            return anchor

        res = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', _extract_md_link, res)

        # 3. Извлечение сырых URL
        raw_urls = re.findall(r'https?://[^\s<>"\']+', res)
        for u in raw_urls:
            if u not in attachment_links:
                attachment_links.append(u)
        res = re.sub(r'https?://[^\s<>"\']+', '', res).strip()

        # 4. Снятие тегов и маркдауна
        clean_text = SharedSanitizerCore.strip_all_tags(res)
        clean_text = re.sub(r'\*\*(.+?)\*\*', r'\1', clean_text)
        clean_text = re.sub(r'`([^`\n]+?)`', r'\1', clean_text)

        # 5. Социальный CTA
        if "класс" not in clean_text.lower():
            clean_text += "\n\nСтавьте «Класс» 👍, чтобы не потерять пост, и делитесь им с друзьями!"

        clean_text = SharedSanitizerCore.remove_empty_lines_overflow(clean_text)

        return {
            "post_text": clean_text,
            "snippet_url": attachment_links[0] if attachment_links else None,
            "attachment_links": attachment_links
        }

    @classmethod
    def format_post(cls, text: str, has_media: bool = False, **kwargs) -> FormattedPostResult:
        payload = cls.format_ok_post_payload(text, **kwargs)
        clean_text = payload["post_text"]
        return FormattedPostResult(
            channel=TargetChannelEnum.OK,
            post_text=clean_text,
            snippet_url=payload.get("snippet_url"),
            char_count=len(clean_text),
            is_valid=len(clean_text) <= 10000,
        )


class MaxMessengerFormatter:
    """Форматтер для Max Messenger: Push-превью (до 70 символов), лимит 400 симв., Markdown, изолированный CTA."""

    @classmethod
    def format_max_message(cls, text: str, cta_url: Optional[str] = None, cta_title: str = "Открыть", **kwargs) -> Dict[str, Any]:
        if not text:
            return {"message_text": "", "push_preview": "", "char_count": 0}

        res = text.strip()
        filler_greetings = [
            r"^(?:Здравствуйте|Добрый\s+(?:день|вечер|утро)|Приветствуем|Привет)[,\s]*(?:уважаемый\s+(?:клиент|покупатель|гость))?[!.,\s]*",
            r"^(?:Уважаемый\s+(?:клиент|покупатель|гость))[!.,\s]*",
            r"^(?:Рады\s+сообщить|Спешим\s+поделиться|Обратите\s+внимание)[!.,\s]*"
        ]
        for fg in filler_greetings:
            res = re.sub(fg, "", res, flags=re.IGNORECASE).strip()

        res = SharedSanitizerCore.clean_typography(res)
        res = re.sub(r'<b>(.+?)</b>', r'**\1**', res)
        res = re.sub(r'<code>(.+?)</code>', r'`\1`', res)
        res = re.sub(r'</?(?:i|s|blockquote|tg-spoiler)[^>]*>', '', res)

        cta_link_text = ""
        link_match = re.search(r'(?:👉\s*)?\[([^\]]+)\]\(([^\)]+)\)', res)
        if link_match:
            cta_link_text = f"👉 [{link_match.group(1)}]({link_match.group(2)})"
            res = res[:link_match.start()].rstrip("👉 \t\n")
        elif cta_url:
            cta_link_text = f"👉 [{cta_title}]({cta_url})"

        res = re.sub(r'https?://[^\s]+', '', res).strip()
        if cta_link_text:
            res = f"{res}\n\n{cta_link_text}"

        res = SharedSanitizerCore.remove_empty_lines_overflow(res)
        first_line = res.split("\n")[0]
        push_preview = re.sub(r'[\*`#]', '', first_line).strip()
        if len(push_preview) > 70:
            push_preview = push_preview[:67] + "..."

        sms_text = cls.strip_markdown_for_sms(res.strip())

        return {
            "message_text": res.strip(),
            "sms_fallback_text": sms_text,
            "push_preview": push_preview,
            "char_count": len(res.strip()),
            "is_within_limit": len(res.strip()) <= 400
        }

    @classmethod
    def strip_markdown_for_sms(cls, text: str) -> str:
        if not text:
            return ""
        res = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\1: \2', text)
        return re.sub(r'[\*`_#]', '', res).strip()

    @classmethod
    def format_post(cls, text: str, has_media: bool = False, **kwargs) -> FormattedPostResult:
        res = cls.format_max_message(text, **kwargs)
        return FormattedPostResult(
            channel=TargetChannelEnum.MAX,
            post_text=res["message_text"],
            push_preview=res.get("push_preview"),
            sms_fallback=res.get("sms_fallback_text"),
            char_count=res.get("char_count", 0),
            is_valid=res.get("is_within_limit", True),
        )


class ChannelFormattersFactory:
    """Единая фабрика платформенного форматирования контента."""

    _FORMATTERS = {
        TargetChannelEnum.TELEGRAM: TelegramFormatter,
        TargetChannelEnum.VK: VKFormatter,
        TargetChannelEnum.OK: OKFormatter,
        TargetChannelEnum.MAX: MaxMessengerFormatter,
    }

    @classmethod
    def get_formatter(cls, channel: TargetChannelEnum | str):
        norm_channel = TargetChannelEnum.normalize(channel)
        return cls._FORMATTERS.get(norm_channel, TelegramFormatter)

    @classmethod
    def format(
        cls,
        text: str,
        target_channel: TargetChannelEnum | str,
        has_media: bool = False,
        **kwargs
    ) -> FormattedPostResult:
        norm_channel = TargetChannelEnum.normalize(target_channel)
        formatter_cls = cls.get_formatter(norm_channel)
        return formatter_cls.format_post(text=text, has_media=has_media, **kwargs)


# Совместимые классы-алиасы для легаси-кода
TelegramRichPostFormatter = TelegramFormatter
VKPostFormatter = VKFormatter
OKPostFormatter = OKFormatter
