# -*- coding: utf-8 -*-
"""
модуль: max_messenger_formatter.py
Форматирование и санитизация прямых push-уведомлений и сообщений для Max Messenger:
1. Контроль первого Push-экрана (первые 50–70 символов — оффер/суть).
2. Вычищение приветственного «мусора» («Добрый день, уважаемый клиент...»).
3. Строгий лимит длины сообщения (до 300–400 символов).
4. Единый целевой CTA (Single Action) с двойной изоляцией (\n\n) от мисскликов.
5. Поддержка Markdown (**жирный**, `код`).
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional


class MaxMessengerFormatter:
    """
    Детерминированный процессор для push- и direct-сообщений Max Messenger:
    гарантирует максимальный CTR открытий с заблокированного экрана и отсутствие мисскликов.
    """

    @classmethod
    def format_max_message(
        cls,
        text: str,
        cta_url: Optional[str] = None,
        cta_title: str = "Открыть"
    ) -> Dict[str, Any]:
        if not text:
            return {"message_text": "", "push_preview": "", "char_count": 0}

        res = text.strip()

        # 1. Вычищаем пустые шаблонные приветствия (включая составные)
        filler_greetings = [
            r"^(?:Здравствуйте|Добрый\s+(?:день|вечер|утро)|Приветствуем|Привет)[,\s]*(?:уважаемый\s+(?:клиент|покупатель|гость))?[!.,\s]*",
            r"^(?:Уважаемый\s+(?:клиент|покупатель|гость))[!.,\s]*",
            r"^(?:Рады\s+сообщить|Спешим\s+поделиться|Обратите\s+внимание)[!.,\s]*"
        ]
        for fg in filler_greetings:
            res = re.sub(fg, "", res, flags=re.IGNORECASE).strip()

        # 2. Нормализация типографики
        res = re.sub(r'(\s)[-–](\s)', r'\1—\2', res)
        res = re.sub(r'"([^"\n]+?)"', r'«\1»', res)

        # 3. Преобразование HTML в Markdown
        res = re.sub(r'<b>(.+?)</b>', r'**\1**', res)
        res = re.sub(r'<code>(.+?)</code>', r'`\1`', res)
        res = re.sub(r'</?(?:i|s|blockquote|tg-spoiler)[^>]*>', '', res)

        # 4. Обработка ссылок: если в тексте несколько ссылок, оставляем только одну главную
        # Изолируем CTA в самом низу
        cta_link_text = ""
        link_match = re.search(r'(?:👉\s*)?\[([^\]]+)\]\(([^\)]+)\)', res)
        if link_match:
            cta_link_text = f"👉 [{link_match.group(1)}]({link_match.group(2)})"
            res = res[:link_match.start()].rstrip("👉 \t\n")
        elif cta_url:
            cta_link_text = f"👉 [{cta_title}]({cta_url})"

        # Удаляем любые оставшиеся сырые URL из тела сообщения
        res = re.sub(r'https?://[^\s]+', '', res).strip()

        # 5. Сборка сообщения с гарантированной изоляцией CTA (\n\n)
        if cta_link_text:
            res = f"{res}\n\n{cta_link_text}"

        # 6. Расчет Push-превью (первая строка / первые 65 символов)
        first_line = res.split("\n")[0]
        push_preview = re.sub(r'[\*`#]', '', first_line).strip()
        if len(push_preview) > 70:
            push_preview = push_preview[:67] + "..."

        # 7. Генерация чистого SMS-фоллбэка (если получатель оффлайн)
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
        """
        Преобразует Markdown-сообщение в чистый SMS-текст для GSM-доставки при оффлайн-получателе:
        - Преобразует [Текст](https://...) в "Текст: https://..."
        - Снимает **жирный**, `код`, _курсив_
        - Сохраняет читабельность в стандартных SMS-клиентах без поддержки разметки
        """
        if not text:
            return ""

        res = text.strip()

        # 1. Ссылки Markdown [Текст](URL) -> Текст: URL
        res = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\1: \2', res)

        # 2. Снятие Markdown форматирования (**жирный**, `код`, _курсив_)
        res = re.sub(r'\*\*(.+?)\*\*', r'\1', res)
        res = re.sub(r'`([^`]+?)`', r'\1', res)
        res = re.sub(r'_(.+?)_', r'\1', res)

        # 3. Нормализация пробелов и переносов
        res = re.sub(r'[ \t]{2,}', ' ', res)
        return res.strip()
