# -*- coding: utf-8 -*-
"""
модуль: telegram_rich_formatter.py
Комплексное обогащение и форматирование постов для Telegram (Bot API 7.2+):
1. <code>ПРОМОКОД</code> — копирование в 1 клик для промокодов и телефонов
2. <s>Старая цена</s> Новая цена — зачеркивание старой цены при скидках
3. <tg-spoiler>Секрет/Бонус</tg-spoiler> — спойлеры для интриги и викторин
4. <blockquote expandable>...</blockquote> — сворачиваемые прайсы и правила
5. Inline-кнопки (reply_markup) — сайт, карта (2GIS/Яндекс), запись, менеджер
6. Link preview options — управление положением и размером превью ссылок
"""

from __future__ import annotations
import re
try:
    from ai.skills.expandable_blockquote import ExpandableBlockquoteFormatter
except ImportError:
    try:
        from skills.expandable_blockquote import ExpandableBlockquoteFormatter
    except ImportError:
        from .expandable_blockquote import ExpandableBlockquoteFormatter


class TelegramRichPostFormatter:
    """
    Продвинутый процессор обогащения постов под возможности Telegram:
    преобразует текст в интерактивный маркетинговый креатив с кнопками,
    кликабельными промокодами, спойлерами и сворачиваемыми блоками.
    """

    @classmethod
    def format_clickable_promocodes(cls, text: str, promo_code: Optional[str] = None) -> str:
        """
        Оборачивает промокоды и телефонные номера в <code>,
        чтобы в Telegram пользователь мог скопировать их в буфер обмена одним кликом.
        """
        if not text:
            return ""

        result = text

        # 1. Если явно передан промокод — оборачиваем его точное вхождение
        if promo_code and promo_code.strip():
            code_clean = promo_code.strip()
            # Если еще не обернут в <code>
            if f"<code>{code_clean}</code>" not in result and f"`{code_clean}`" not in result:
                pattern = re.compile(rf"(?<!<code>)(?<!`)\b({re.escape(code_clean)})\b(?!</code>)(?!`)", re.IGNORECASE)
                result = pattern.sub(r"<code>\1</code>", result)

        # 2. Авто-поиск промокодов по ключевым словам: «промокод: CODE», «промокоду CODE»
        promo_keyword_pattern = re.compile(
            r"(промокод[уа]?\s*[:\-—]?\s*)(?:«|\"|\b)([A-Z0-9А-Я_]{4,20})(?:»|\"|\b)",
            re.IGNORECASE
        )
        def _wrap_promo(match):
            prefix = match.group(1)
            code = match.group(2)
            return f"{prefix}<code>{code}</code>"

        result = promo_keyword_pattern.sub(_wrap_promo, result)

        # 3. Авто-поиск телефонных номеров: +7 (XXX) XXX-XX-XX или 8 (XXX) XXX-XX-XX
        phone_pattern = re.compile(
            r"(?<!<code>)(?<!`)(?:(?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2})(?!</code>)(?!`)"
        )
        result = phone_pattern.sub(r"<code>\g<0></code>", result)

        return result

    @classmethod
    def format_strikethrough_prices(cls, text: str) -> str:
        """
        Находит паттерны старых и новых цен (скидок) и форматирует:
        «вместо 3500 ₽ всего 2490 ₽» -> «<s>3 500 ₽</s> <b>2 490 ₽</b>»
        «было 2000 руб, стало 1500 руб» -> «<s>2 000 руб</s> <b>1 500 руб</b>»
        """
        if not text:
            return ""

        patterns = [
            # «вместо 3500 ₽ всего 2490 ₽»
            (
                r"(?:вместо|старая цена:?)\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))\s*(?:всего|новая цена:?|теперь)?\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))",
                r"<s>\1</s> <b>\2</b>"
            ),
            # «было 3500 ₽ — стало 2490 ₽»
            (
                r"(?:было:?)\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))\s*(?:[—\-,]\s*(?:стало:?))?\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))",
                r"<s>\1</s> <b>\2</b>"
            ),
            # «3500 ₽ -> 2490 ₽»
            (
                r"(\d[\d\s]*(?:₽|руб|rub|\$|€))\s*(?:->|→|=>)\s*(\d[\d\s]*(?:₽|руб|rub|\$|€))",
                r"<s>\1</s> <b>\2</b>"
            )
        ]

        result = text
        for pat, repl in patterns:
            result = re.sub(pat, repl, result, flags=re.IGNORECASE)

        return result

    @classmethod
    def format_spoilers(cls, text: str, spoiler_keywords: Optional[List[str]] = None) -> str:
        """
        Оборачивает секретные ответы, интриги или скрытые бонусы в <tg-spoiler>.
        Синтаксис: <tg-spoiler>текст</tg-spoiler>
        """
        if not text:
            return ""

        result = text
        # 1. Если пользователь ввел ||текст|| (стандартный маркдаун-спойлер) -> превращаем в <tg-spoiler>
        result = re.sub(r"\|\|(.*?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", result)

        # 2. Авто-поиск фраз: «секретный бонус: ...», «правильный ответ: ...»
        spoiler_triggers = [
            r"(секретный\s+бонус\s*[:\-—]?\s*)([^\n\.]+)",
            r"(правильный\s+ответ\s*[:\-—]?\s*)([^\n\.]+)",
            r"(сюрприз\s+внутри\s*[:\-—]?\s*)([^\n\.]+)"
        ]
        for trig in spoiler_triggers:
            result = re.sub(trig, r"\1<tg-spoiler>\2</tg-spoiler>", result, flags=re.IGNORECASE)

        return result

    @classmethod
    def sanitize_telegram_html(cls, text: str, promo_code: Optional[str] = None) -> str:
        """
        Преобразует текст в 100% валидный Telegram HTML:
        - Преобразует Markdown **bold** в <b>bold</b>
        - Преобразует Markdown *italic* в <i>italic</i>
        - Преобразует Markdown `code` в <code>code</code>
        - Убирает плейсхолдеры в квадратных скобках ([ссылка на сайт или директ] и т.д.)
        - Устраняет галлюцинированные промокоды (PAS2023, PROMO2023), если задан целевой promo_code
        - Обеспечивает валидность тегов для Telegram Bot API
        """
        if not text:
            return ""

        res = text

        # 1. Замена плейсхолдеров в квадратных скобках
        placeholder_patterns = [
            r"\[ссылка\s+на\s+сайт[^\]]*\]",
            r"\[ссылка[^\]]*\]",
            r"\[директ[^\]]*\]",
            r"\[контакты[^\]]*\]",
            r"\[телефон[^\]]*\]",
            r"\[адрес[^\]]*\]"
        ]
        for p_pat in placeholder_patterns:
            res = re.sub(p_pat, "👉 по ссылке в шапке профиля или кнопке ниже", res, flags=re.IGNORECASE)

        # 2. Если задан настоящий промокод — вычищаем галлюцинированные промокоды (PAS2023, PROMO...)
        if promo_code:
            hallucinated_promo_pattern = re.compile(
                r"\b(PAS|PROMO|SALE|DISCOUNT|EASTER|SPRING)\d{2,4}\b(?!\s*<\/(?:code)>)",
                re.IGNORECASE
            )
            def _clean_hallucinated(m):
                matched = m.group(0)
                if matched.upper() != promo_code.upper():
                    return promo_code.upper()
                return matched
            res = hallucinated_promo_pattern.sub(_clean_hallucinated, res)

        # 3. Преобразование Markdown в Telegram HTML
        # **жирный** -> <b>жирный</b>
        res = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", res)
        # *курсив* -> <i>курсив</i> (но не трогаем пункты списков в начале строки)
        res = re.sub(r"(?<!\n)(?<!^)\*([^\*\n]+?)\*", r"<i>\1</i>", res)
        # `код` -> <code>код</code>
        res = re.sub(r"`([^`\n]+?)`", r"<code>\1</code>", res)

        # 4. Устранение возможных дубликатов тегов
        res = res.replace("<b><b>", "<b>").replace("</b></b>", "</b>")
        res = res.replace("<code><code>", "<code>").replace("</code></code>", "</code>")

        # 5. Защита от эмодзи внутри тегов форматирования (<s>, <code>, <b>)
        res = cls.sanitize_tag_emojis(res)

        # 6. Типографика (длинные тире и кавычки-елочки вне HTML-тегов)
        res = cls.sanitize_typography(res)

        # 7. Санитизация blockquote от разрывов двойными переносами
        res = cls.sanitize_blockquotes(res)

        # 8. Принудительное форсирование «воздуха» и разметки
        res = cls.enforce_telegram_air(res)

        return res.strip()

    @classmethod
    def sanitize_blockquotes(cls, text: str) -> str:
        """
        Гарантирует целостность тегов <blockquote> / <blockquote expandable>:
        схлопывает любые двойные переносы (\\n\\n+) внутри цитаты в одинарный перенос (\\n),
        чтобы парсер Telegram не разбивал цитату на несколько отдельных блоков.
        """
        def _clean_bq(m):
            tag_open = m.group(1)
            content = m.group(2)
            tag_close = m.group(3)
            # Внутри цитаты заменяем множественные переносы на одинарный
            cleaned_content = re.sub(r'\n{2,}', '\n', content.strip())
            return f"{tag_open}{cleaned_content}{tag_close}"

        return re.sub(r'(<blockquote[^>]*>)([\s\S]*?)(</blockquote>)', _clean_bq, text, flags=re.IGNORECASE)

    @classmethod
    def sanitize_typography(cls, text: str) -> str:
        """
        Применяет правила качественной русской типографики вне HTML-тегов:
        - Заменяет дефисы и короткие тире с пробелами (" - ", " – ") на длинное тире (" — ")
        - Заменяет прямые машинные кавычки ("...") на русские кавычки-ёлочки («...»)
        - Гарантирует целостность HTML-тегов, ссылок и атрибутов.
        """
        if not text:
            return ""

        # Разбиваем текст на токены (HTML теги и обычный текст)
        tokens = re.split(r'(<[^>]+>)', text)
        for i, token in enumerate(tokens):
            if not token.startswith('<'):
                # 1. Замена дефисов между словами на длинное тире
                token = re.sub(r'(\s)[-–](\s)', r'\1—\2', token)
                # 2. Замена прямых парных кавычек на елочки
                token = re.sub(r'"([^"\n<>]+?)"', r'«\1»', token)
                tokens[i] = token

        return "".join(tokens)

    @classmethod
    def sanitize_tag_emojis(cls, text: str) -> str:
        """
        Предотвращает ошибки Telegram Bot API 'Bad Request: can't parse entities',
        вынося эмодзи из тегов <s>, <code>, <b> наружу.
        Например: <s>1 450 ₽ 📉</s> -> <s>1 450 ₽</s> 📉
                 <code>🏷️ SALE</code> -> 🏷️ <code>SALE</code>
        """
        if not text:
            return ""

        emoji_class = r'[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50\ufe0f]'

        def _clean_tag(m):
            tag_name = m.group(1)
            content = m.group(2)

            # Вынос ведущих эмодзи
            prefix_emoji = ""
            m_pre = re.match(r'^(\s*(?:' + emoji_class + r'+\s*)+)', content)
            if m_pre:
                prefix_emoji = m_pre.group(1).strip() + " "
                content = content[m_pre.end():]

            # Вынос замыкающих эмодзи
            suffix_emoji = ""
            m_suf = re.search(r'(\s*(?:' + emoji_class + r'+\s*)+)$', content)
            if m_suf:
                suffix_emoji = " " + m_suf.group(1).strip()
                content = content[:m_suf.start()]

            return f"{prefix_emoji}<{tag_name}>{content.strip()}</{tag_name}>{suffix_emoji}"

        res = re.sub(r'<(s|code|b)>(.*?)</\1>', _clean_tag, text, flags=re.DOTALL)
        res = re.sub(r'[ \t]{2,}', ' ', res)
        return res

    @classmethod
    def enforce_telegram_air(cls, text: str) -> str:
        """
        Гарантирует идеальную визуальную архитектуру и «воздух» (пустые строки между блоками):
        1. Каждый маркер списка (▫️, 🔹, •) — строго с новой строки.
        2. Пустая строка перед началом списка буллетов.
        3. Одинарный перенос между элементами одного списка.
        4. Пустая строка после окончания списка буллетов.
        5. Пустая строка перед и после <blockquote>.
        6. Пустая строка перед блоком цены 🏷️ и подарков 🎁.
        7. Пустая строка перед интерактивом <i>Листайте...</i>.
        8. Пустая строка перед CTA (👉 / <a href=).
        9. Пустая строка перед блоком хештегов (#...).
        10. Нормализация тройных переносов в ровно двойной (\n\n).
        """
        if not text:
            return ""

        res = text.strip()
        res = res.replace("\r\n", "\n").replace("\r", "\n")

        # 1. Если маркер списка (▫️, 🔹, •) прилип к концу предыдущего текста на той же строке -> переносим на новую строку (\n)
        res = re.sub(r'([^\n])\s*([▫🔹•]\ufe0f?)\s+', r'\1\n\2 ', res)

        # 2. Гарантируем пустую строку (\n\n) перед первым элементом списка
        res = re.sub(r'([^\n▫🔹•\s])\n+([▫🔹•]\ufe0f?\s+)', r'\1\n\n\2', res)

        # 3. Маркеры внутри одного списка идут с одинарным переносом (\n)
        res = re.sub(r'([▫🔹•]\ufe0f?[^\n]+)\n+([▫🔹•]\ufe0f?\s+)', r'\1\n\2', res)

        # 4. Гарантируем пустую строку (\n\n) после последнего элемента списка (перед любым не-буллетом)
        res = re.sub(r'([▫🔹•]\ufe0f?[^\n]+)\n+([^▫🔹•\n\s])', r'\1\n\n\2', res)

        # 5. Гарантируем пустую строку (\n\n) перед и после цитаты
        res = re.sub(r'([^\n\s])\n+(<blockquote)', r'\1\n\n\2', res)
        res = re.sub(r'(</blockquote>)\n+([^\n\s])', r'\1\n\n\2', res)

        # 6. Гарантируем пустую строку (\n\n) перед блоком цены
        res = re.sub(r'([^\n\s])\n+(🏷\ufe0f?|<b>Цена:?</b>|Цена:)', r'\1\n\n\2', res)

        # 7. Оборачивание бонуса/подарка в <tg-spoiler>, если он еще не обернут
        if "<tg-spoiler>" not in res and ("🎁" in res or "Подарок" in res):
            res = re.sub(r'(🎁\ufe0f?\s*(?:Подарок|Секретный\s*подарок)[^:\n]*:\s*)(?!<tg-spoiler>)([^<\n\.]+[\.]?)', r'\1<tg-spoiler>\2</tg-spoiler>', res, flags=re.IGNORECASE)

        # 8. Гарантируем пустую строку (\n\n) перед интерактивом / курсивным призывом
        res = re.sub(r'([^\n\s])\n+(<i>(?:Листайте|Свайпайте|Сделайте))', r'\1\n\n\2', res, flags=re.IGNORECASE)

        # 9. Гарантируем пустую строку (\n\n) перед CTA ссылкой
        res = re.sub(r'([^\n\s])\n+(👉|\[Забронировать|\[Оформить|<a\s+href)', r'\1\n\n\2', res)

        # 10. Гарантируем пустую строку (\n\n) перед хештегами (подвал)
        res = re.sub(r'([^\n\s])\n+(#[A-Za-zА-Яа-я0-9_]+)', r'\1\n\n\2', res)

        # 11. Нормализация тройных переносов (не более 1 пустой строки подряд)
        res = re.sub(r'\n{3,}', '\n\n', res)

        return res.strip()

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
        """
        Генерирует умную сетку интерактивных Inline-кнопок (reply_markup) для Telegram:
        - Кнопка 1: Главный CTA (Записаться онлайн / Меню / Заказать)
        - Кнопка 2: Наш сайт / Telegram-канал
        - Кнопка 3: Маршрут на карте (2GIS / Яндекс Карты)
        - Кнопка 4: Связаться с менеджером
        """
        if custom_buttons:
            return {"inline_keyboard": custom_buttons}

        keyboard: List[List[Dict[str, str]]] = []
        contacts = contacts or {}
        social_links = social_links or {}

        # 1. Основной сайт или витрина
        web = website_url or social_links.get("website") or contacts.get("website")
        
        # 2. Ссылки на карты (2GIS / Яндекс)
        map_url = social_links.get("2gis") or social_links.get("yandex_maps") or contacts.get("map_url")
        if not map_url and contacts.get("address"):
            clean_addr = contacts['address'].replace(" ", "+")
            map_url = f"https://yandex.ru/maps/?text={clean_addr}"

        # 3. Телефон или связь в Telegram
        tg_contact = social_links.get("telegram") or social_links.get("tg_manager") or contacts.get("telegram")
        phone = contacts.get("phone")

        row1: List[Dict[str, str]] = []
        if web and str(web).startswith("http"):
            label = "🛍️ Оформить заказ" if cta_type in ["ecommerce", "delivery"] else "🌐 Перейти на сайт"
            row1.append({"text": label, "url": str(web)})
        elif tg_contact and str(tg_contact).startswith("http"):
            row1.append({"text": "💬 Написать нам", "url": str(tg_contact)})

        if row1:
            keyboard.append(row1)

        row2: List[Dict[str, str]] = []
        if map_url and str(map_url).startswith("http"):
            row2.append({"text": "📍 Как добраться (Карта)", "url": str(map_url)})

        if tg_contact and str(tg_contact).startswith("http") and not any(b.get("url") == tg_contact for b in row1):
            row2.append({"text": "📲 Записаться", "url": str(tg_contact)})
        elif phone:
            clean_phone = re.sub(r"[^\d+]", "", str(phone))
            if clean_phone.startswith("+") or clean_phone.isdigit():
                row2.append({"text": f"📞 Позвонить", "url": f"tel:{clean_phone}"})

        if row2:
            keyboard.append(row2)

        # Если кнопок не набралось — даем базовую кнопку бренда
        if not keyboard and company_name:
            keyboard.append([{"text": f"✨ Узнать больше о {company_name}", "url": "https://t.me/UcustAi"}])

        return {"inline_keyboard": keyboard}

    @classmethod
    def build_rich_telegram_post(
        cls,
        text: str,
        company_name: str = "",
        niche: str = "",
        promo_code: Optional[str] = None,
        website_url: Optional[str] = None,
        contacts: Optional[Dict[str, Any]] = None,
        social_links: Optional[Dict[str, Any]] = None,
        enable_expandable_blockquote: bool = True,
        enable_clickable_promo: bool = True,
        enable_strikethrough: bool = True,
        enable_spoilers: bool = True,
        enable_buttons: bool = True,
        cta_type: str = "general"
    ) -> Dict[str, Any]:
        """
        Полный сквозной пайплайн форматирования поста для Telegram:
        Возвращает:
        - clean_text: чистый текст
        - html_text: Telegram HTML (<code>, <s>, <tg-spoiler>, <blockquote expandable>)
        - markdown_v2_text: Telegram MarkdownV2 (`, ~, ||, **>)
        - reply_markup: Telegram Inline Keyboard
        - link_preview_options: настройки превью
        - expandable_blocks: список свернутых секций
        """
        if not text:
            return {
                "clean_text": "",
                "html_text": "",
                "markdown_v2_text": "",
                "reply_markup": None,
                "expandable_blocks": []
            }

        # 1. Чистый текст без служебных мета-тегов
        clean_text = ExpandableBlockquoteFormatter.strip_expandable_blockquote(text)

        # 2. Форматирование HTML
        html_text = clean_text

        # 2.1 Сворачиваемые цитаты (Expandable Blockquotes)
        expandable_blocks = []
        if enable_expandable_blockquote:
            html_text, _ = ExpandableBlockquoteFormatter.auto_wrap_sections(html_text, mode="html")
            expandable_blocks = ExpandableBlockquoteFormatter.extract_blocks(html_text)

        # 2.2 Промокоды и телефоны в <code> (копирование в 1 клик)
        if enable_clickable_promo:
            html_text = cls.format_clickable_promocodes(html_text, promo_code=promo_code)

        # 2.3 Зачеркнутые старые цены <s>
        if enable_strikethrough:
            html_text = cls.format_strikethrough_prices(html_text)

        # 2.4 Спойлеры <tg-spoiler>
        if enable_spoilers:
            html_text = cls.format_spoilers(html_text)

        # 3. Форматирование MarkdownV2
        md_text = clean_text
        if enable_expandable_blockquote:
            md_text, _ = ExpandableBlockquoteFormatter.auto_wrap_sections(md_text, mode="markdown_v2")

        # 4. Генерация Inline-кнопок
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

        # 5. Link Preview Options
        link_preview_options = {
            "is_disabled": False,
            "prefer_small_media": True,
            "show_above_text": False
        }

        return {
            "clean_text": clean_text,
            "html_text": html_text,
            "markdown_v2_text": md_text,
            "reply_markup": reply_markup,
            "link_preview_options": link_preview_options,
            "expandable_blocks": expandable_blocks,
            "features_applied": {
                "clickable_promo": enable_clickable_promo and "<code>" in html_text,
                "strikethrough_prices": enable_strikethrough and "<s>" in html_text,
                "spoilers": enable_spoilers and "<tg-spoiler>" in html_text,
                "expandable_blockquote": bool(expandable_blocks),
                "inline_buttons": bool(reply_markup and reply_markup.get("inline_keyboard"))
            }
        }

    COLLAGE_KEYWORDS = [
        "коллаж", "коллажем", "склейка", "склей", "сетка 2x2", "сеткой", "плиткой",
        "grid", "collage", "в один кадр", "объедини фото", "сделай коллаж"
    ]

    @classmethod
    def is_collage_requested(cls, prompt: str = "", user_data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Проверяет, запросил ли пользователь создание коллажа ЯВНО в промпте, подсказках или настройках.
        По умолчанию: False (всегда используется Единый пост-альбом sendMediaGroup).
        """
        if user_data:
            if user_data.get("as_collage") is True or user_data.get("format") in ["collage", "коллаж", "grid"]:
                return True
            hints = str(user_data.get("hints", "")) + " " + str(user_data.get("instructions", "")) + " " + str(user_data.get("prompt_hint", ""))
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
    def build_2x2_collage(cls, image_paths: List[str], output_path: str, gap: int = 8) -> Optional[str]:
        """
        Объединяет до 4 изображений в красивый симметричный коллаж 2x2.
        """
        valid_paths = [p for p in image_paths if isinstance(p, str) and os.path.exists(p)]
        if not valid_paths:
            return None
        if len(valid_paths) == 1:
            return valid_paths[0]

        try:
            from PIL import Image
            imgs = [Image.open(p).convert("RGB") for p in valid_paths[:4]]
            target_w, target_h = 600, 600
            resized = []
            for img in imgs:
                min_dim = min(img.width, img.height)
                left = (img.width - min_dim) // 2
                top = (img.height - min_dim) // 2
                cropped = img.crop((left, top, left + min_dim, top + min_dim))
                resized.append(cropped.resize((target_w, target_h), Image.Resampling.LANCZOS))

            # Если 2 фото: горизонтальная склейка
            if len(resized) == 2:
                col_w = target_w * 2 + gap
                col_h = target_h
                collage = Image.new("RGB", (col_w, col_h), (24, 24, 27))
                collage.paste(resized[0], (0, 0))
                collage.paste(resized[1], (target_w + gap, 0))
            # Если 3 или 4 фото: сетка 2x2
            else:
                col_w = target_w * 2 + gap
                col_h = target_h * 2 + gap
                collage = Image.new("RGB", (col_w, col_h), (24, 24, 27))
                collage.paste(resized[0], (0, 0))
                collage.paste(resized[1], (target_w + gap, 0))
                collage.paste(resized[2], (0, target_h + gap))
                if len(resized) == 4:
                    collage.paste(resized[3], (target_w + gap, target_h + gap))

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            collage.save(output_path, "JPEG", quality=95)
            return output_path
        except Exception as e:
            print(f"[TelegramRichPostFormatter] ⚠️ Ошибка сборки коллажа: {e}")
            return valid_paths[0]
