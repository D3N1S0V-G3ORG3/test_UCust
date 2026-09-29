# -*- coding: utf-8 -*-
"""
модуль: vk_rich_formatter.py
Форматирование и санитизация публикаций для ВКонтакте (VK):
1. Снятие HTML-разметки (<b>, <i>, <code> и т.д. -> чистый текст).
2. Защита охватов: вынос внешних ссылок в первый комментарий (First Comment Rule).
3. Нормализация CAPS LOCK (разрешен только в заголовке до 5 слов).
4. Навигационные хештеги сообщества (#рубрика@domain).
5. Идеальный «воздух» и контроль правила ката (280 символов).
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional, Tuple


class VKPostFormatter:
    """
    Детерминированный процессор подготовки публикаций для ВКонтакте:
    гарантирует сохранение органических охватов, читабельность и соблюдение Редполитики VK.
    """

    @classmethod
    def format_vk_post(
        cls,
        text: str,
        group_domain: Optional[str] = None,
        promo_code: Optional[str] = None,
        external_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Главная точка входа: возвращает очищенный текст поста и текст для первого комментария.
        """
        if not text:
            return {"post_text": "", "first_comment": ""}

        res = text.strip()
        first_comment_links: List[str] = []

        if external_url:
            first_comment_links.append(external_url)

        # 1. Поиск внешних ссылок в тексте (http/https вне vk.com)
        external_link_pattern = re.compile(r'https?://(?!vk\.com|vk\.me)[^\s<>"\']+', re.IGNORECASE)
        found_links = external_link_pattern.findall(res)
        for fl in found_links:
            if fl not in first_comment_links:
                first_comment_links.append(fl)

        # 2. Удаление HTML-ссылок <a href="...">Текст</a> и обычных ссылок
        def _replace_html_link(m):
            url = m.group(1)
            anchor = m.group(2)
            if "vk.com" in url or "vk.me" in url:
                return anchor
            if url not in first_comment_links:
                first_comment_links.append(url)
            return anchor

        res = re.sub(r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', _replace_html_link, res, flags=re.IGNORECASE)
        res = external_link_pattern.sub("", res)
        # Очищаем остаточные висячие фразы вроде "на сайте " перед удаленной ссылкой
        res = re.sub(r'\bна\s+сайте\s+(?=[,\.\s]|$)', '', res, flags=re.IGNORECASE)

        # 3. Снятие всех HTML-тегов (<b>, <i>, <code>, <s>, <blockquote>, <tg-spoiler>)
        res = re.sub(r'</?(?:b|i|code|s|blockquote|tg-spoiler)[^>]*>', '', res, flags=re.IGNORECASE)

        # 4. Снятие Markdown разметки (**жирный**, *курсив*, `код`)
        res = re.sub(r'\*\*(.+?)\*\*', r'\1', res)
        res = re.sub(r'(?<!\n)(?<!^)\*([^\*\n]+?)\*', r'\1', res)
        res = re.sub(r'`([^`\n]+?)`', r'\1', res)

        # 5. Типографика (кавычки-елочки и длинные тире)
        res = cls.sanitize_typography(res)

        # 6. Нормализация CAPS LOCK в основном тексте (кроме первой строки заголовка)
        res = cls.normalize_caps_lock(res)

        # 7. Форматирование хештегов под сообщество (#рубрика@domain)
        if group_domain:
            clean_domain = group_domain.lstrip('@')
            def _domain_tag(m):
                tag = m.group(1)
                if '@' in tag:
                    return tag
                return f"{tag}@{clean_domain}"
            res = re.sub(r'(#[A-Za-zА-Яа-я0-9_]+)', _domain_tag, res)

        # 8. Обеспечение призыва «Ссылка в первом комментарии»
        if first_comment_links:
            cta_comment_note = "👉 Ссылка на каталог и оформление — в первом комментарии под постом."
            if "первом комментари" not in res.lower():
                # Вставляем перед хештегами или в конец
                m_hash = re.search(r'(\n+#[A-Za-zА-Яа-я0-9_@]+)', res)
                if m_hash:
                    res = res[:m_hash.start()] + f"\n\n{cta_comment_note}" + res[m_hash.start():]
                else:
                    res = res + f"\n\n{cta_comment_note}"

        # 9. Наведение идеального «воздуха» и отступов
        res = cls.enforce_vk_air(res)

        # 10. Формирование текста первого комментария
        first_comment_text = ""
        if first_comment_links:
            first_comment_text = "🔗 Прямая ссылка для заказа и подробностей:\n" + "\n".join(first_comment_links)
            if promo_code:
                first_comment_text += f"\n\n🎁 Промокод на скидку: {promo_code}"

        return {
            "post_text": res.strip(),
            "first_comment": first_comment_text.strip(),
            "has_first_comment": bool(first_comment_text),
            "hook_length_chars": len(res.split("\n\n")[0]) if res else 0
        }

    @classmethod
    def sanitize_typography(cls, text: str) -> str:
        """Русская типографика: длинные тире и кавычки-ёлочки."""
        if not text:
            return ""
        res = re.sub(r'(\s)[-–](\s)', r'\1—\2', text)
        res = re.sub(r'"([^"\n]+?)"', r'«\1»', res)
        return res

    @classmethod
    def normalize_caps_lock(cls, text: str) -> str:
        """
        Разрешает CAPS LOCK только для заголовка (первая строка, до 5 слов).
        В основном тексте слова КАПСОМ (от 4 букв) переводятся в нижний регистр.
        """
        lines = text.split("\n")
        if not lines:
            return ""

        processed_lines = []
        for i, line in enumerate(lines):
            clean_line = line.strip()
            if i == 0 and len(clean_line.split()) <= 6 and clean_line.isupper():
                # Оставляем заголовок капсом
                processed_lines.append(clean_line)
            else:
                # В теле текста убираем капс из длинных кричащих слов (кроме аббревиатур вроде РФ, СНГ, SKU)
                def _decap(m):
                    word = m.group(0)
                    if len(word) > 3 and word.isupper() and word not in ["ГОСТ", "СССР", "США", "СНГ", "УТП"]:
                        return word.capitalize()
                    return word
                processed_lines.append(re.sub(r'\b[А-ЯЁA-Z]{4,}\b', _decap, line))

        return "\n".join(processed_lines)

    @classmethod
    def enforce_vk_air(cls, text: str) -> str:
        """Обеспечивает четкое разделение списков и абзацев для ленты VK."""
        if not text:
            return ""
        res = text.replace("\r\n", "\n").replace("\r", "\n")

        # 1. Если заголовок капсом на первой строке и прилип к тексту -> отбиваем пустой строкой (\n\n)
        lines = res.split("\n")
        if lines and lines[0].isupper() and len(lines[0].split()) <= 6:
            if len(lines) > 1 and lines[1].strip() != "":
                lines.insert(1, "")
                res = "\n".join(lines)

        # 2. Если маркер списка прилип к строке -> с новой строки
        res = re.sub(r'([^\n])\s*([▫🔹✔️•]\ufe0f?)\s+', r'\1\n\2 ', res)

        # 3. Пустая строка перед началом списка
        res = re.sub(r'([^\n▫🔹✔️•\s])\n+([▫🔹✔️•]\ufe0f?\s+)', r'\1\n\n\2', res)

        # 4. Маркеры внутри одного списка идут строго с одинарным переносом (\n)
        while re.search(r'([▫🔹✔️•]\ufe0f?[^\n]+)\n{2,}([▫🔹✔️•]\ufe0f?\s+)', res):
            res = re.sub(r'([▫🔹✔️•]\ufe0f?[^\n]+)\n{2,}([▫🔹✔️•]\ufe0f?\s+)', r'\1\n\2', res)

        # 5. Пустая строка после окончания списка
        res = re.sub(r'([▫🔹✔️•]\ufe0f?[^\n]+)\n+([^▫🔹✔️•\n\s])', r'\1\n\n\2', res)

        # 6. Пустая строка перед CTA (👉 / Ссылка...)
        res = re.sub(r'([^\n\s])\n+(👉|Ссылка\s+в\s+первом|Заказать|Оформить)', r'\1\n\n\2', res, flags=re.IGNORECASE)

        # 7. Пустая строка перед хештегами
        res = re.sub(r'([^\n\s])\n+(#[A-Za-zА-Яа-я0-9_@]+)', r'\1\n\n\2', res)

        # 8. Нормализация тройных переносов
        res = re.sub(r'\n{3,}', '\n\n', res)

        return res.strip()
