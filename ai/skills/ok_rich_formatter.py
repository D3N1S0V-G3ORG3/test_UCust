# -*- coding: utf-8 -*-
"""
модуль: ok_rich_formatter.py
Форматирование и санитизация публикаций для Одноклассников (ОК.ru):
1. Снятие всех HTML-тегов.
2. Максимум «воздуха»: отбивка пустой строкой (\n\n) после каждого смыслового предложения.
3. Эмоциональные маркеры (🌻, ☕, 🎁, ❤️, 👍, 📌) строго по границам предложений.
4. Автоматическая интеграция социального CTA («Класс» 👍 / Поделиться).
5. Идеальная русская типографика (кавычки-ёлочки и длинные тире).
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional


class OKPostFormatter:
    """
    Детерминированный процессор подготовки публикаций для Одноклассников:
    обеспечивает высокую читабельность для возрастной и семейной аудитории,
    максимум визуального пространства и стимулирование социального шеринга.
    """

    @classmethod
    def format_ok_post(
        cls,
        text: str,
        promo_code: Optional[str] = None
    ) -> str:
        payload = cls.format_ok_post_payload(text, promo_code)
        return payload["post_text"]

    @classmethod
    def format_ok_post_payload(
        cls,
        text: str,
        promo_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Возвращает структурированный пейлоад для OK API:
        - post_text: чистый текст без ссылочного шума
        - snippet_url: ссылка для автоматического сниппета ОК (attachments -> link)
        - attachment_links: список всех найденных ссылок
        """
        if not text:
            return {"post_text": "", "snippet_url": None, "attachment_links": []}

        res = text.strip()
        attachment_links: List[str] = []

        # 1. Извлечение ссылок из <a href="...">
        def _extract_a_link(m):
            url = m.group(1)
            anchor = m.group(2)
            if url not in attachment_links:
                attachment_links.append(url)
            return anchor

        res = re.sub(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', _extract_a_link, res, flags=re.IGNORECASE)

        # 2. Извлечение ссылок из Markdown [Текст](URL)
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
        # Удаляем длинные сырые URL из текста (ОК подтянет их сниппетом)
        res = re.sub(r'https?://[^\s<>"\']+', '', res).strip()

        # 4. Снятие всех HTML-тегов
        res = re.sub(r'</?(?:b|i|code|s|blockquote|tg-spoiler|a)[^>]*>', '', res, flags=re.IGNORECASE)

        # 5. Снятие Markdown разметки
        res = re.sub(r'\*\*(.+?)\*\*', r'\1', res)
        res = re.sub(r'(?<!\n)(?<!^)\*([^\*\n]+?)\*', r'\1', res)
        res = re.sub(r'`([^`\n]+?)`', r'\1', res)

        # 6. Русская типографика (кавычки-елочки и тире)
        res = cls.sanitize_typography(res)

        # 7. Проверка и интеграция обязательного социального CTA (Класс 👍)
        if "класс" not in res.lower():
            res += "\n\nСтавьте «Класс» 👍, чтобы не потерять пост, и делитесь им с друзьями!"

        # 8. Принудительное наведение максимума «воздуха» (одна мысль — отдельная строка)
        res = cls.enforce_ok_air(res)

        return {
            "post_text": res.strip(),
            "snippet_url": attachment_links[0] if attachment_links else None,
            "attachment_links": attachment_links,
            "has_snippet": bool(attachment_links)
        }

    @classmethod
    def sanitize_typography(cls, text: str) -> str:
        if not text:
            return ""
        res = re.sub(r'(\s)[-–](\s)', r'\1—\2', text)
        res = re.sub(r'"([^"\n]+?)"', r'«\1»', res)
        return res

    @classmethod
    def enforce_ok_air(cls, text: str) -> str:
        """
        В ОК сплошные абзацы не читаются. Разделяем смысловые предложения двойным переносом (\n\n).
        """
        if not text:
            return ""

        res = text.replace("\r\n", "\n").replace("\r", "\n")

        # 1. Если точка/восклицательный/вопросительный знак разделяют предложения в одном абзаце — делаем перенос
        # Защищаем общепринятые сокращения: ул., д., г., руб., коп., тел., просп., пер., корп., стр.
        def _split_sentence(m):
            word = m.group(1)
            next_char = m.group(2)
            clean_word = word.rstrip('.!?').lower()
            if clean_word in ["ул", "г", "д", "руб", "коп", "тел", "просп", "пер", "корп", "стр"]:
                return f"{word} {next_char}"
            return f"{word}\n\n{next_char}"

        res = re.sub(r'([а-яёa-z0-9»\)]+[.!?])\s+([А-ЯЁA-Z«▫🔹📌🌻☕🎁❤️👍])', _split_sentence, res)

        # 2. Переносы перед маркерами
        res = re.sub(r'([^\n])\s*([▫🔹📌🌻☕🎁❤️👍🏷✔️•]\ufe0f?)\s+', r'\1\n\n\2 ', res)

        # 3. Нормализация тройных переносов
        res = re.sub(r'\n{3,}', '\n\n', res)

        return res.strip()
