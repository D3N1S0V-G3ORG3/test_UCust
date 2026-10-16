# File: skills/marketing_frameworks.py
"""
Marketing Frameworks, JTBD, Value Ladder & Behavioral Economics Engine for UCust.AI.
Усиливает маркетинговые навыки платформы без дообучения нейросети за счет:
1. 7 классических формул копирайтинга (AIDA, PAS, BAB, 4P, StoryBrand, Hook-Story-Offer, FAB).
2. Лестницы узнавания Бена Ханта (5 ступеней прогрева: Unaware -> Most Aware).
3. 5 Психологических триггеров Чалдини (Social Proof, Scarcity, Authority, Reciprocity, Risk Reversal).
4. JTBD (Jobs-to-be-Done) Движка — трансформация свойств продукта в функциональную, эмоциональную и социальную ценность.
5. Лестницы ценности Рассела Брансона (Value Ladder: Lead Magnet -> Tripwire -> Core Offer -> Profit Maximizer).
6. Модели поведения Фогга для CTA (BJ Fogg Behavior Model: B = MAP) — устранение трения и микро-конверсии.
"""

from __future__ import annotations

import random
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple


class HuntStage(str, Enum):
    STAGE_1_UNAWARE = "unaware"                  # Холодные: не знают о проблеме (разрушение мифов, парадоксы)
    STAGE_2_PROBLEM_AWARE = "problem_aware"      # Осознание боли: чувствуют проблему, ищут причины
    STAGE_3_SOLUTION_AWARE = "solution_aware"    # Поиск решений: сравнивают методы и подходы
    STAGE_4_PRODUCT_AWARE = "product_aware"      # Выбор компании: кейсы, отзывы, экспертность бренда
    STAGE_5_MOST_AWARE = "most_aware"            # Горячие: готовы купить, нужен оффер и дедлайн


class MarketingFramework(str, Enum):
    AIDA = "AIDA"                  # Attention -> Interest -> Desire -> Action
    PAS = "PAS"                    # Problem -> Agitation -> Solution
    BAB = "BAB"                    # Before -> After -> Bridge
    FOUR_P = "4P"                  # Picture -> Promise -> Prove -> Push
    STORYBRAND = "StoryBrand"      # Hero -> Problem -> Guide -> Plan -> CTA -> Success
    HOOK_STORY_OFFER = "HSO"       # Hook -> Story -> Offer (Reels / Shorts)
    FAB = "FAB"                    # Feature -> Advantage -> Benefit


class PsychologicalTrigger(str, Enum):
    # Психологические модели Чарли Мангера (Mental Models of Misjudgment):
    REWARD_SUPER_RESPONSE = "reward_super_response"  # Сверхреакция на вознаграждение (кешбэк, баллы, мгновенная выгода)
    SOCIAL_PROOF = "social_proof"                    # Социальное доказательство (отзывы, бестселлеры, рейтинг 4.9, выбор большинства)
    PAVLOVIAN_ASSOCIATION = "pavlovian_association"  # Павловский эффект ассоциаций (статус, эстетика, приятный образ, эмоция)
    DEPRIVAL_FOMO = "deprival_fomo"                  # Эффект дефицита и боязнь потери (Deprival Super-Reaction, осталось 2 шт)
    SCARCITY_FOMO = "scarcity_fomo"                  # Алиас для Scarcity
    AUTHORITY = "authority"                          # Авторитет (сертификаты, технологии, экспертность, признание)
    RECIPROCITY = "reciprocity"                      # Взаимный обмен (бесплатная польза, расчет, подарок до покупки)
    RISK_REVERSAL = "risk_reversal"                  # Снятие риска (гарантия возврата, договор, тест-драйв)
    LOLLAPALOOZA = "lollapalooza"                    # Эффект Лоллапалуза (синергия 3-4 триггеров одновременно)


class ValueLadderTier(str, Enum):
    LEAD_MAGNET = "lead_magnet"            # 0 ₽: Бесплатный чек-лист, гайд, расчет сметы, аудит
    TRIPWIRE = "tripwire"                  # Недорогой пробник (300-900 ₽): снятие первого финансового барьера
    CORE_OFFER = "core_offer"              # Основной продукт / услуга: флагман компании
    PROFIT_MAXIMIZER = "profit_maximizer"  # VIP / Апсейл: абонемент, годовая гарантия, расширенный пакет


class NicheCluster(str, Enum):
    B2B_INDUSTRIAL = "b2b_industrial"          # B2B, IT, SaaS, Логистика, Оборудование, Производство
    EDTECH_EDUCATION = "edtech_education"      # EdTech, Курсы, Инфобизнес, Обучение, Менторство
    LOCAL_SERVICES_SMB = "local_services_smb"  # Малый бизнес, Общепит, Бьюти, СТО, Детейлинг, Ритейл
    FREELANCE_EXPERTS = "freelance_experts"    # Фрилансеры, Маркетологи, Психологи, Коучи, Эксперты
    LIFESTYLE_CONSUMER = "lifestyle_consumer"  # Общий B2C / Лайфстайл


# ============================================================================
# NICHE CONSTRAINTS DICTIONARY (КОНТЕКСТНАЯ МАРШРУТИЗАЦИЯ И ОГРАНИЧЕНИЯ)
# ============================================================================

NICHE_CONSTRAINTS: Dict[NicheCluster, Dict[str, Any]] = {
    NicheCluster.B2B_INDUSTRIAL: {
        "cluster_name": "B2B-сектор и Промышленность (IT, Логистика, Оборудование)",
        "keywords": [
            "it", "saas", "b2b", "логистик", "оборудован", "промышленност", "производств",
            "консалтинг", "бухгалтер", "юриспруденц", "склад", "инжиниринг", "транспорт",
            "автоматизац", "сервер", "безопасност", "поставка", "опт", "интеграци"
        ],
        "style_doctrine": "Сухой скальпель. Лаконичность, инженерная точность, фактура. Никаких превосходных прилагательных и детских аналогий.",
        "emoji_rule": "Эмодзи отключены либо используются строго нейтральные геометрические маркеры (🔹, ▪️) — не более 1-2 на пост.",
        "sensory_rule": "ПРАВИЛО ROI И МЕТРИК: Сенсорика превращается в точные цифры, SLA и окупаемость. Вместо «удобный сервис» пиши «экономит 14 часов бухгалтера в месяц», «снижение простоя оборудования на 28%», «доставка за 48 часов по договору».",
        "munger_focus": "Снятие рисков (Doubt-Avoidance & Authority): B2B покупает безопасность. Обязательно опирайся на гарантии по договору, сертификаты, фиксированные сметы и реальные кейсы.",
        "priority_trigger": PsychologicalTrigger.RISK_REVERSAL,
        "cliches_to_kill": [
            "динамично развивающаяся", "команда профессионалов", "индивидуальный подход",
            "лучшее качество", "волшебный", "бомбический", "надежный партнер", "широкий спектр"
        ],
        "critic_actionable_rule": "Если Мангер видит воду и общие фразы вроде «надежный партнер», он требует: «Убери воду. Напиши точные цифры: экономию в рублях/часах, SLA, размер автопарка или среднее время обработки заявки»."
    },
    NicheCluster.EDTECH_EDUCATION: {
        "cluster_name": "EdTech, Инфобизнес и Образование",
        "keywords": [
            "образован", "курс", "edtech", "школ", "инфобизнес", "обучен", "вебинар",
            "марафон", "ментор", "английск", "программирован", "дизайн", "професси",
            "репетитор", "мастер-класс", "стажировк", "вебинар"
        ],
        "style_doctrine": "Разговорный, эмпатичный, динамичный. Фокус на Pain Amplification (амплификация скрытой боли) и трансформации статуса «до/после».",
        "emoji_rule": "Функциональные смысловые акценты (🧠, 📊, ⚡️, 🎯) — 2-3 на пост для управления вниманием.",
        "hook_rule": "ХУК В СКРЫТЫЙ СТРАХ: Бей прямо в барьер или стереотип аудитории. Никаких «Хотите освоить IT?». Пиши: «В 2026 году джуниор-разработчику без реального портфолио отказывают в 94% случаев».",
        "sensory_rule": "ТРАНСФОРМАЦИЯ НАВЫКА: Показывай осязаемые артефакты (строчки чистого кода, принятый оффер, дипломный проект в портфолио, первая зарплата).",
        "munger_focus": "Взаимный обмен (Reciprocation): Текст ОБЯЗАН давать безусловную бесплатную пользу (пошаговый алгоритм, разбор частой ошибки, готовый шаблон) строго ДО перехода к продаже курса.",
        "priority_trigger": PsychologicalTrigger.RECIPROCITY,
        "cliches_to_kill": [
            "уникальная методика", "успешный успех", "легкий заработок", "курс изменит вашу жизнь",
            "гарантированный доход", "без усилий"
        ],
        "critic_actionable_rule": "Критик следит, чтобы польза и инсайт шли ПЕРЕД продажей. Запрещены обещания легких денег без прозрачной учебной программы."
    },
    NicheCluster.LOCAL_SERVICES_SMB: {
        "cluster_name": "Малый бизнес и Локальные услуги (Общепит, Бьюти, СТО, Ритейл)",
        "keywords": [
            "пекарн", "кофейн", "общепит", "ресторан", "бьют", "салон красот", "барбершоп",
            "сто", "автосервис", "детейлинг", "клининг", "мебель", "цвет", "фитнес",
            "стоматолог", "кафе", "кулич", "выпечк", "маникюр", "шиномонтаж", "мойка", "ремонт"
        ],
        "style_doctrine": "Гиперлокальный, плотный, сочный, кинематографичный. Атмосфера соседского доверия и мгновенного импульса.",
        "emoji_rule": "Аппетитные и предметные иконки (☕️, 🥐, ✂️, 🚗, ✨) — до 2-3 штук как структурные якоря.",
        "sensory_rule": "ФИЗИЧЕСКАЯ СЕНСОРИКА: Клиент должен «почувствовать» хруст корочки, запах смолотого кофе, матовый блеск полированного кузова или легкость в плечах после массажа.",
        "munger_focus": "Эффект Lollapalooza (Социальное доказательство + Дефицит окон/порций): Импульсивное решение на стыке доверия соседей и ограниченного запаса («осталось 3 порции / 2 свободных окна на вечер»).",
        "priority_trigger": PsychologicalTrigger.LOLLAPALOOZA,
        "cta_rule": "ИМПЕРАТИВНЫЙ ЛОКАЛЬНЫЙ СТА: Вместо унылого «Ждем вас в салоне» пиши «Забери последнее окно на сложную покраску сегодня в 19:30. Ссылка для брони ниже».",
        "cliches_to_kill": [
            "с любовью для вас", "уютная атмосфера", "приятные цены", "широкий ассортимент",
            "высокое качество", "самое лучшее"
        ],
        "critic_actionable_rule": "Критик бракует абстрактные восторги и требует осязаемых деталей: рецептуру, температуру, остаток мест, время выдержки теста или номер оттенка."
    },
    NicheCluster.FREELANCE_EXPERTS: {
        "cluster_name": "Фрилансеры и Помогающие практики (Эксперты, Маркетологи, Коучи)",
        "keywords": [
            "маркетолог", "психолог", "коуч", "таргетолог", "копирайтер", "фриланс",
            "самопиар", "консультант", "нутрициолог", "астролог", "таролог", "эксперт",
            "менторств", "smm", "стратег", "продюсер", "личный бренд", "юрист", "частный"
        ],
        "style_doctrine": "Сторителлинг от первого лица («Я-позиция», бесшовно переходящая в «Вы-результат»). Живой человеческий диалог без высокомерия.",
        "emoji_rule": "Минималистичные акценты (💡, ⚡️, 📌) — 1-2 на пост.",
        "rhythm_rule": "РВАНЫЙ РИТМ ИЛЬЯХОВА: Обязательное чередование коротких предложений-ударов и развернутых мыслей для эффекта живого разговора тет-а-тет.",
        "sensory_rule": "РЕЗУЛЬТАТ ВМЕСТО ПРОЦЕССА: Не описывай часы работы или сложный алгоритм — покажи конечное состояние клиента (спокойный сон, уверенность на переговорах, рост выручки в 2 раза).",
        "munger_focus": "Павловские ассоциации (Pavlovian Association): Связывай работу с экспертом с чувством защищенности, легкости и признания.",
        "priority_trigger": PsychologicalTrigger.PAVLOVIAN_ASSOCIATION,
        "cliches_to_kill": [
            "помогу выйти на новый уровень", "раскрою ваш потенциал", "проработка установок",
            "индивидуальная сессия", "лучший специалист"
        ],
        "critic_actionable_rule": "Критик следит, чтобы эксперт не хвалил себя, а раскрывал решение конкретной боли через личный кейс или факап с понятным выводом."
    }
}


class NicheClusterResolver:
    """Резолвер кластеров ниш для контекстной маршрутизации."""

    @classmethod
    def resolve_cluster(cls, niche: str) -> Tuple[NicheCluster, Dict[str, Any]]:
        niche_lower = (niche or "").lower().strip()
        for cluster_enum, spec in NICHE_CONSTRAINTS.items():
            keywords = spec.get("keywords", [])
            if any(kw in niche_lower for kw in keywords):
                return cluster_enum, spec
        return NicheCluster.LOCAL_SERVICES_SMB, NICHE_CONSTRAINTS[NicheCluster.LOCAL_SERVICES_SMB]



# ============================================================================
# 1. JTBD (JOBS-TO-BE-DONE) ENGINE
# ============================================================================

class JTBDTransformer:
    """
    Преобразует сухие технические характеристики продукта в 3 измерения JTBD:
    1. Functional Job (Функциональная задача): какую практическую работу выполняет продукт.
    2. Emotional Job (Эмоциональная задача): какое чувство спокойствия / радости дарит клиенту.
    3. Social Job (Социальная задача): как клиента воспринимают окружающие (семья, друзья, коллеги).
    """

    NICHE_JTBD_PATTERNS = {
        "мебель": {
            "functional": "Надежная мебель точных размеров, которая выдерживает ежедневные нагрузки без скрипов и деформаций.",
            "emotional": "Ощущение уюта, тепла и спокойствия дома после тяжелого рабочего дня.",
            "social": "Гордость перед гостями за стильный интерьер и статус эстета с идеальным вкусом."
        },
        "стоматология": {
            "functional": "Безболезненное лечение зубов и восстановление жевательной функции с гарантией долговечности.",
            "emotional": "Избавление от страха зубной боли и абсолютная уверенность при общении.",
            "social": "Широкая, открытая и статусная улыбка, привлекающая людей и повышающая авторитет."
        },
        "автосервис": {
            "functional": "Точная диагностика и ремонт неисправностей с первого раза по прозрачной смете.",
            "emotional": "Уверенность в безопасности автомобиля в дальних поездках с семьей без риска внезапной поломки.",
            "social": "Репутация практичного водителя, у которого автомобиль всегда в идеальном техническом состоянии."
        },
        "кофейня": {
            "functional": "Быстрое получение свежесваренного кофе из отборных зерен со стабильным вкусом.",
            "emotional": "Утренний заряд энергии и 15 минут удовольствия наедине со своими мыслями.",
            "social": "Принадлежность к сообществу ценителей качественного specialty-кофе и стильного городского лайфстайла."
        },
        "it": {
            "functional": "Автоматизация рутинных процессов, безотказная работа инфраструктуры и сокращение издержек.",
            "emotional": "Спокойствие за сохранность данных и отсутствие авралов в выходные дни.",
            "social": "Имидж инновационной компании, опережающей конкурентов на технологическом уровне."
        }
    }

    @classmethod
    def transform_feature(cls, niche: str, raw_feature: str = "") -> Dict[str, str]:
        """Преобразует характеристику в JTBD-триаду."""
        niche_key = "it"
        for key in cls.NICHE_JTBD_PATTERNS:
            if key in niche.lower():
                niche_key = key
                break
        
        base_jtbd = cls.NICHE_JTBD_PATTERNS.get(niche_key, cls.NICHE_JTBD_PATTERNS["it"])
        
        feature_text = raw_feature if raw_feature else "высокие стандарты качества"
        return {
            "raw_feature": feature_text,
            "functional_job": base_jtbd["functional"],
            "emotional_job": base_jtbd["emotional"],
            "social_job": base_jtbd["social"],
            "jtbd_summary_prompt": (
                f"Клиент нанимает продукт не ради свойства «{feature_text}», а ради:\n"
                f"• Функционально: {base_jtbd['functional']}\n"
                f"• Эмоционально: {base_jtbd['emotional']}\n"
                f"• Социально: {base_jtbd['social']}"
            )
        }


# ============================================================================
# 2. VALUE LADDER ARCHITECT (ЛЕСТНИЦА ЦЕННОСТИ)
# ============================================================================

class ValueLadderArchitect:
    """
    Формирует 4-уровневую продуктовую воронку по Расселу Брансону для любой ниши бизнеса.
    """

    VALUE_LADDER_BLUEPRINTS = {
        "мебель": {
            ValueLadderTier.LEAD_MAGNET: "Бесплатный 3D-дизайн проект с расчетом сметы за 15 минут (0 ₽)",
            ValueLadderTier.TRIPWIRE: "Набор образцов премиального шпона и защитного масла на дом (490 ₽)",
            ValueLadderTier.CORE_OFFER: "Изготовление обеденного стола / кухни из массива дуба под ключ",
            ValueLadderTier.PROFIT_MAXIMIZER: "VIP-пакет «Интерьер под ключ» с 5-летней гарантией и ежегодным сервисным уходом"
        },
        "стоматология": {
            ValueLadderTier.LEAD_MAGNET: "Чек-лист правильного ухода за эмалью + Онлайн-консультация ортодонта (0 ₽)",
            ValueLadderTier.TRIPWIRE: "Компьютерная 3D-томография челюсти со скидкой 70% (990 ₽)",
            ValueLadderTier.CORE_OFFER: "Комплексная имплантация / Установка керамических виниров E-Max",
            ValueLadderTier.PROFIT_MAXIMIZER: "Годовой абонемент семейного стоматологического обслуживания VIP"
        },
        "автосервис": {
            ValueLadderTier.LEAD_MAGNET: "Чек-лист подготовки автомобиля к сезону + Инспекция по 40 параметрам (0 ₽)",
            ValueLadderTier.TRIPWIRE: "Компьютерная диагностика двигателя и сброс ошибок (450 ₽)",
            ValueLadderTier.CORE_OFFER: "Комплексное ТО (масла, фильтры, колодки) с гарантией на запчасти",
            ValueLadderTier.PROFIT_MAXIMIZER: "Годовая программа поддержки на дорогах 24/7 и сезонное хранение шин"
        },
        "default": {
            ValueLadderTier.LEAD_MAGNET: "Бесплатный PDF-гайд / экспресс-аудит от эксперта за 0 ₽",
            ValueLadderTier.TRIPWIRE: "Пробная мини-консультация / тестовый образец с 80% скидкой",
            ValueLadderTier.CORE_OFFER: "Основной флагманский продукт / услуга под ключ",
            ValueLadderTier.PROFIT_MAXIMIZER: "Премиальный VIP-пакет с максимальным сопровождением и расширенной гарантией"
        }
    }

    @classmethod
    def get_ladder_for_niche(cls, niche: str) -> Dict[ValueLadderTier, str]:
        """Возвращает продуктовую лестницу ценности для ниши."""
        for key in cls.VALUE_LADDER_BLUEPRINTS:
            if key != "default" and key in niche.lower():
                return cls.VALUE_LADDER_BLUEPRINTS[key]
        return cls.VALUE_LADDER_BLUEPRINTS["default"]


# ============================================================================
# 3. FOGG BEHAVIOR MODEL (B = MAP) FOR ZERO-FRICTION CTA
# ============================================================================

class FoggCTAGenerator:
    """
    Генератор призывов к действию по Модели поведения Фогга (B = Motivation x Ability x Prompt).
    Исключает высокое трение («позвоните по телефону») и генерирует микро-конверсии с нулевым барьером.
    """

    CTA_PRESETS = {
        "direct_keyword": [
            "👉 Напишите слово «{keyword}» в сообщения сообщества — бот мгновенно пришлет каталог с ценами за 5 секунд!",
            "📩 Отправьте «+» в комментарии, и мы вышлем персональный расчет стоимости прямо в личные сообщения.",
            "💬 Напишите «{keyword}» в директ, чтобы зафиксировать спеццену и получить подарок к заказу."
        ],
        "one_click_quiz": [
            "🎯 Пройдите тест из 3 вопросов по ссылке в шапке профиля и узнайте точную стоимость за 30 секунд!",
            "⚡ Ответьте на 2 вопроса в закрепленном опросе — заберите персональный промокод на скидку."
        ],
        "instant_reciprocity": [
            "🎁 Заберите бесплатную PDF-шпаргалку с разбором ошибок прямо сейчас — ссылка в шапке профиля!",
            "📥 Напишите «ГАЙД» в личные сообщения — пришлем экспертный чек-лист без спама и звонков."
        ]
    }

    @classmethod
    def get_default_keyword_for_niche(cls, niche: str) -> str:
        """Подбирает органичный и релевантный ключевик для Fogg CTA в зависимости от сферы бизнеса."""
        niche_l = (niche or "").lower()
        if any(w in niche_l for w in ["кофе", "coffee", "кафе", "общепит", "ресторан", "пекарн", "еда", "бургер", "бар", "напит", "f&b"]):
            return "МЕНЮ"
        elif any(w in niche_l for w in ["мебель", "ремонт", "интерьер", "строитель", "стройка", "кухн", "шкаф"]):
            return "РАСЧЕТ"
        elif any(w in niche_l for w in ["авто", "сто", "детейлинг", "сервис", "шиномонтаж", "гонк", "автоспорт", "rds"]):
            return "ЗАПИСЬ"
        elif any(w in niche_l for w in ["бьюти", "салон", "маникюр", "парикмахер", "барбер", "клиник", "spa", "спа", "космет"]):
            return "ВИЗИТ"
        elif any(w in niche_l for w in ["курс", "школ", "обучен", "вебинар", "edtech", "репетитор", "урок"]):
            return "ГАЙД"
        elif any(w in niche_l for w in ["фитнес", "спорт", "тренировк", "зал", "йог"]):
            return "ТРЕНИРОВКА"
        elif any(w in niche_l for w in ["недвижим", "риелтор", "квартир", "аренд"]):
            return "КАТАЛОГ"
        elif any(w in niche_l for w in ["одежд", "обувь", "шоурум", "бутик", "магазин"]):
            return "ПРИМЕРКА"
        return "ПОДРОБНЕЕ"

    @classmethod
    def generate_low_friction_cta(
        cls,
        action_type: str = "direct_keyword",
        keyword: Optional[str] = None,
        company_name: str = "",
        niche: str = ""
    ) -> str:
        """Генерирует призыв к действию с минимальным порогом входа."""
        presets = cls.CTA_PRESETS.get(action_type, cls.CTA_PRESETS["direct_keyword"])
        template = random.choice(presets)
        kw = keyword or cls.get_default_keyword_for_niche(niche)
        return template.format(keyword=kw, company_name=company_name)


# ============================================================================
# 4. MASTER MARKETING FRAMEWORK DIRECTOR (FACADE)
# ============================================================================

class MarketingFrameworkDirector:
    """
    Главный арт-директор маркетинга UCust.AI:
    Объединяет Копирайтинг (7 формул) + Прогрев Ханта (5 ступеней) + Триггеры Чалдини + JTBD + Value Ladder + Fogg CTA.
    """

    FRAMEWORK_DESCRIPTIONS = {
        MarketingFramework.AIDA: {
            "name": "AIDA (Attention, Interest, Desire, Action)",
            "goal": "Классическая универсальная продающая структура для промо и анонсов",
            "blocks": ["1. Взрывной заголовок (Внимание)", "2. Любопытный факт или инсайт (Интерес)", "3. Образ выгоды и результат (Желание)", "4. Низкофрикционный CTA (Действие)"]
        },
        MarketingFramework.PAS: {
            "name": "PAS (Problem, Agitation, Solution)",
            "goal": "Пробитие баннерной слепоты через реальную боль клиента и ее нагнетание",
            "blocks": ["1. Обозначение острой проблемы (Боль)", "2. Что будет, если не решать проблему (Усиление боли)", "3. Решение от нашего бренда (Выход)"]
        },
        MarketingFramework.BAB: {
            "name": "BAB (Before, After, Bridge)",
            "goal": "Наглядная демонстрация трансформации клиента (до / после / инструмент)",
            "blocks": ["1. Как было плохо/сложно ДО обращения (Before)", "2. Как стало идеально и легко ПОСЛЕ (After)", "3. Как продукт бренда стал этим мостом (Bridge)"]
        },
        MarketingFramework.FOUR_P: {
            "name": "4P (Picture, Promise, Prove, Push)",
            "goal": "Эмоциональное погружение с твердыми доказательствами и дедлайном",
            "blocks": ["1. Яркая визуальная картинка мечты (Picture)", "2. Четкое обещание результата (Promise)", "3. Факты, цифры и отзывы (Prove)", "4. Дедлайн и жесткий призыв (Push)"]
        },
        MarketingFramework.STORYBRAND: {
            "name": "StoryBrand (7-Part Framework)",
            "goal": "Превращение клиента в главного Героя, а бренда — в мудрого Проводника",
            "blocks": ["1. Цель Героя-клиента", "2. Препятствие/Проблема", "3. Проводник (Наш бренд)", "4. Понятный план из 3 шагов", "5. Призыв к действию и образ триумфа"]
        },
        MarketingFramework.HOOK_STORY_OFFER: {
            "name": "Hook-Story-Offer (Reels / Shorts / Клипы)",
            "goal": "Удержание внимания в первые 3 секунды с переходом в историю и оффер",
            "blocks": ["1. 3-секундный хук-стоппер", "2. Короткая динамичная история / закулисье", "3. Финальный оффер с ограничением по времени"]
        },
        MarketingFramework.FAB: {
            "name": "FAB (Feature, Advantage, Benefit)",
            "goal": "Перевод технических характеристик продукта на язык личной выгоды покупателя",
            "blocks": ["1. Характеристика (Что сделано)", "2. Преимущество (Почему лучше аналогов)", "3. Выгода клиента (Сколько сэкономит / как облегчит жизнь)"]
        }
    }

    HUNT_STAGE_STRATEGIES = {
        HuntStage.STAGE_1_UNAWARE: {
            "framework": MarketingFramework.BAB,
            "trigger": PsychologicalTrigger.RECIPROCITY,
            "value_tier": ValueLadderTier.LEAD_MAGNET,
            "hook_formula": "«90% людей даже не подозревают, почему...»",
            "vibe": "Разрушение мифов, вовлечение, легкий юмор, лайфстайл"
        },
        HuntStage.STAGE_2_PROBLEM_AWARE: {
            "framework": MarketingFramework.PAS,
            "trigger": PsychologicalTrigger.AUTHORITY,
            "value_tier": ValueLadderTier.LEAD_MAGNET,
            "hook_formula": "«Почему попытка сэкономить на... оборачивается переплатой в 2 раза?»",
            "vibe": "Боль, дискомфорт, вскрытие скрытых рисков, экспертный совет"
        },
        HuntStage.STAGE_3_SOLUTION_AWARE: {
            "framework": MarketingFramework.FAB,
            "trigger": PsychologicalTrigger.RISK_REVERSAL,
            "value_tier": ValueLadderTier.TRIPWIRE,
            "hook_formula": "«Сравнение в лоб: Подход А против Подхода Б — что выгоднее на дистанции 3 лет?»",
            "vibe": "Объективное сравнение, технические нюансы, снятие страхов"
        },
        HuntStage.STAGE_4_PRODUCT_AWARE: {
            "framework": MarketingFramework.STORYBRAND,
            "trigger": PsychologicalTrigger.SOCIAL_PROOF,
            "value_tier": ValueLadderTier.CORE_OFFER,
            "hook_formula": "«Кейс: как мы решили задачу клиента X за Y дней без единой переделки»",
            "vibe": "Закулисье, честные отзывы, процесс производства, твердые пруфы"
        },
        HuntStage.STAGE_5_MOST_AWARE: {
            "framework": MarketingFramework.AIDA,
            "trigger": PsychologicalTrigger.SCARCITY_FOMO,
            "value_tier": ValueLadderTier.CORE_OFFER,
            "hook_formula": "«Только до [День недели]: заберите [Бонус] при заказе...»",
            "vibe": "Горячий оффер, четкий дедлайн, ограничение по слотам, моментальный CTA"
        }
    }

    TRIGGER_TEMPLATES = {
        PsychologicalTrigger.REWARD_SUPER_RESPONSE: (
            "💰 Сверхреакция на вознаграждение (Reward Super-Response): Начислим {cashback}% кешбэка "
            "и подарочный бонус прямо на карту при первом заказе."
        ),
        PsychologicalTrigger.SOCIAL_PROOF: (
            "⭐ Социальное доказательство (Social Proof): Более {client_count} довольных клиентов уже выбрали нас. "
            "Средний рейтинг на картах — {rating} из 5.0."
        ),
        PsychologicalTrigger.PAVLOVIAN_ASSOCIATION: (
            "✨ Павловский эффект ассоциаций (Pavlovian Association): Безупречная эстетика, статус и комфорт. "
            "Почувствуйте уверенность в каждом прикосновении и восхищенные взгляды."
        ),
        PsychologicalTrigger.DEPRIVAL_FOMO: (
            "⏳ Эффект дефицита и боязнь потери (Deprival Super-Reaction): Спецпредложение действует строго до 23:59. "
            "В наличии осталось всего {slots_count} единицы / свободных слота."
        ),
        PsychologicalTrigger.SCARCITY_FOMO: (
            "⏳ Ограничение и дефицит: Спецпредложение действует строго до конца недели. "
            "Осталось всего {slots_count} свободных слота на замер/консультацию."
        ),
        PsychologicalTrigger.AUTHORITY: (
            "🏛️ Экспертность и технологии: Официальный контроль качества, профессиональное оборудование "
            "и команда сертифицированных специалистов с опытом от 7 лет."
        ),
        PsychologicalTrigger.RECIPROCITY: (
            "🎁 Принцип взаимности: Мы подготовили бесплатный расчет сметы и экспертную консультацию для вас — "
            "никаких скрытых условий и навязывания."
        ),
        PsychologicalTrigger.RISK_REVERSAL: (
            "🛡️ Полное снятие рисков: Работаем строго по договору с фиксированной ценой "
            "и официальной гарантией качества."
        ),
        PsychologicalTrigger.LOLLAPALOOZA: (
            "🔥 Эффект Lollapalooza (Синергия 4 триггеров): "
            "1. Выбор {client_count} клиентов (Социальное доказательство). "
            "2. Осталось всего {slots_count} места со скидкой (Дефицит). "
            "3. Кешбэк {cashback}% и подарок к заказу (Вознаграждение). "
            "4. Гарантия результата по договору (Снятие рисков)."
        )
    }

    @classmethod
    def construct_marketing_prompt(
        cls,
        company_name: str,
        niche: str,
        topic: str,
        framework: MarketingFramework = MarketingFramework.AIDA,
        hunt_stage: HuntStage = HuntStage.STAGE_2_PROBLEM_AWARE,
        trigger: Optional[PsychologicalTrigger] = None,
        pain_points: Optional[List[str]] = None,
        contacts: Optional[Dict[str, Any]] = None,
        raw_feature: str = ""
    ) -> Dict[str, Any]:
        """
        Формирует комплексную маркетинговую директиву для Saiga LLM с интеграцией:
        - Выбранного фреймворка копирайтинга
        - Ступени прогрева Бена Ханта
        - JTBD трансформации
        - Продуктовой воронки Value Ladder
        - Fogg Model Low-Friction CTA
        """
        # 1. Разрешение кластера ниши для контекстной маршрутизации
        cluster_enum, cluster_spec = NicheClusterResolver.resolve_cluster(niche)
        effective_trigger = trigger or cluster_spec.get("priority_trigger", PsychologicalTrigger.SOCIAL_PROOF)

        fw_info = cls.FRAMEWORK_DESCRIPTIONS.get(framework, cls.FRAMEWORK_DESCRIPTIONS[MarketingFramework.AIDA])
        stage_strategy = cls.HUNT_STAGE_STRATEGIES.get(hunt_stage, cls.HUNT_STAGE_STRATEGIES[HuntStage.STAGE_2_PROBLEM_AWARE])
        trigger_text = cls.TRIGGER_TEMPLATES.get(effective_trigger, "").format(client_count="1 200+", rating="4.9", slots_count="3", cashback="15")
        
        # 2. JTBD трансформация
        jtbd = JTBDTransformer.transform_feature(niche, raw_feature)
        
        # 3. Value Ladder уровень
        value_ladder = ValueLadderArchitect.get_ladder_for_niche(niche)
        tier = stage_strategy.get("value_tier", ValueLadderTier.CORE_OFFER)
        tier_offer = value_ladder.get(tier, "Основное предложение")

        # 4. Fogg Low-Friction CTA
        default_kw = FoggCTAGenerator.get_default_keyword_for_niche(niche)
        low_friction_cta = FoggCTAGenerator.generate_low_friction_cta(
            action_type="direct_keyword",
            keyword=default_kw,
            company_name=company_name,
            niche=niche
        )

        pains_str = ", ".join(pain_points) if pain_points else "страх переплаты и сомнения в качестве"

        cluster_rules = (
            f"\n8. КОНТЕКСТНЫЕ ОГРАНИЧЕНИЯ КЛАСТЕРА [{cluster_spec['cluster_name'].upper()}]:\n"
            f"   • Стиль: {cluster_spec['style_doctrine']}\n"
            f"   • Сенсорика/ROI: {cluster_spec['sensory_rule']}\n"
            f"   • Эмодзи: {cluster_spec['emoji_rule']}\n"
            f"   • Мангер-фокус: {cluster_spec['munger_focus']}\n"
            f"   • Запрещенные штампы кластера: {', '.join(cluster_spec['cliches_to_kill'])}\n"
        )
        if "hook_rule" in cluster_spec:
            cluster_rules += f"   • Правило хука: {cluster_spec['hook_rule']}\n"
        if "cta_rule" in cluster_spec:
            cluster_rules += f"   • Правило CTA: {cluster_spec['cta_rule']}\n"
        if "rhythm_rule" in cluster_spec:
            cluster_rules += f"   • Правило ритма: {cluster_spec['rhythm_rule']}\n"

        prompt_instructions = (
            f"=== СТРОГАЯ МАРКЕТИНГОВАЯ ДИРЕКТИВА ДЛЯ ТЕКСТА ===\n"
            f"1. Структура текста: Формула {fw_info['name']}.\n"
            f"   Обязательные смысловые блоки:\n" + "\n".join(f"   • {b}" for b in fw_info['blocks']) + "\n"
            f"   КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать в тексте служебные названия шагов и заголовков блоков ('Проблема:', 'Агонизация:', 'Решение:', 'Боль:', 'Усиление:', 'Картина:', 'Обещание:', 'Характеристика:', 'Выгода:')! Пост должен читаться как связная, цельная история без технических маркеров формулы.\n"
            f"2. Психологическая ступень воронки Ханта: {hunt_stage.value.upper()} ({stage_strategy['vibe']}).\n"
            f"3. JTBD-фокус (Jobs-to-be-Done):\n"
            f"   {jtbd['jtbd_summary_prompt']}\n"
            f"4. Продуктовый уровень (Value Ladder): [{tier.value.upper()}] -> Оффер: {tier_offer}.\n"
            f"5. Обязательный психологический триггер:\n"
            f"   {trigger_text}\n"
            f"6. Низкофрикционный призыв к действию (Fogg Model B=MAP):\n"
            f"   {low_friction_cta}\n"
            f"7. Тональность: Живая, без абстракций и шаблонных фраз («В современном мире», «Не упустите шанс»).\n"
            f"{cluster_rules}"
        )

        return {
            "niche_cluster": cluster_enum.value,
            "cluster_spec": cluster_spec,
            "framework": framework.value,
            "hunt_stage": hunt_stage.value,
            "psychological_trigger": effective_trigger.value,
            "value_ladder_tier": tier.value,
            "jtbd": jtbd,
            "fogg_cta": low_friction_cta,
            "trigger_prompt": trigger_text,
            "full_marketing_prompt": prompt_instructions,
            "critic_actionable_rule": cluster_spec.get("critic_actionable_rule", "")
        }


    @classmethod
    def generate_post_with_framework(
        cls,
        company_name: str,
        niche: str,
        topic: str,
        framework: MarketingFramework = MarketingFramework.PAS,
        hunt_stage: HuntStage = HuntStage.STAGE_2_PROBLEM_AWARE,
        trigger: PsychologicalTrigger = PsychologicalTrigger.SOCIAL_PROOF,
        pain_points: Optional[List[str]] = None,
        contacts: Optional[Dict[str, Any]] = None,
        raw_feature: str = ""
    ) -> Dict[str, Any]:
        """
        Генерирует готовый эталонный пост, строго следующий выбранному фреймворку,
        с JTBD-акцентом, продуктовой ступенью и низкофрикционным призывом по модели Фогга.
        """
        f_info = cls.FRAMEWORK_DESCRIPTIONS[framework]
        t_template = cls.TRIGGER_TEMPLATES.get(trigger, "")
        t_text = t_template.format(client_count="1 200+", rating="4.9", slots_count="3", cashback="15")
        jtbd = JTBDTransformer.transform_feature(niche, raw_feature)
        fogg_cta = FoggCTAGenerator.generate_low_friction_cta(
            action_type="direct_keyword",
            company_name=company_name,
            niche=niche
        )

        lead = ""
        body = ""

        # 1. AIDA
        if framework == MarketingFramework.AIDA:
            lead = f"🔥 «{topic}» — как получить максимум результата в {niche}?"
            body = (
                f"8 из 10 клиентов сталкиваются с тем, что результат не оправдывает ожиданий из-за скрытых компромиссов в качестве.\n\n"
                f"В «{company_name}» мы смотрим на задачу иначе: {jtbd['functional_job']} Вы получаете {jtbd['emotional_job']}\n\n"
                f"{t_text}"
            )

        # 2. PAS (Боль -> Усиление -> Решение без служебных маркеров)
        elif framework == MarketingFramework.PAS:
            lead = f"⚠️ Почему 90% попыток сэкономить на услугах в сфере {niche} заканчиваются переплатой в 2 раза?"
            body = (
                f"Вы заказываете услугу, надеясь на быстрый результат, но в итоге сталкиваетесь со скрытыми переделками и сорванными сроками.\n\n"
                f"Чем дольше откладывать решение, тем выше итоговые затраты и потерянные нервы.\n\n"
                f"С «{company_name}» вы получаете надежный результат: {jtbd['functional_job']} и {jtbd['emotional_job']}. {t_text}"
            )

        # 3. BAB (Before -> After -> Bridge)
        elif framework == MarketingFramework.BAB:
            lead = f"🔄 До и После: реальная трансформация с «{company_name}»"
            body = (
                f"Раньше: долгий поиск надежных исполнителей, сомнения в качестве и постоянный стресс из-за дедлайнов.\n\n"
                f"Сейчас: {jtbd['emotional_job']} и {jtbd['social_job']}\n\n"
                f"Наш авторский подход и строгий контроль качества помогли закрыть эту задачу под ключ. {t_text}"
            )

        # 4. 4P (Picture -> Promise -> Prove -> Push)
        elif framework == MarketingFramework.FOUR_P:
            lead = f"✨ Представьте: ваш проект в сфере {niche} реализован безупречно с первого раза"
            body = (
                f"Вы получаете {jtbd['emotional_job']}.\n\n"
                f"Мы в «{company_name}» гарантируем: {jtbd['functional_job']}\n\n"
                f"{t_text}\n\n"
                f"Специальные условия действуют только до конца недели!"
            )

        # 5. StoryBrand (Клиент - Герой, Бренд - Проводник)
        elif framework == MarketingFramework.STORYBRAND:
            lead = f"📖 История одного решения: как преодолеть главное препятствие в {niche}"
            body = (
                f"Каждый наш клиент стремится к идеальному результату, но на пути часто встают недобросовестные подрядчики и раздутые сметы.\n\n"
                f"Команда «{company_name}» выступает вашим надежным проводником. Наш план предельно прост:\n"
                f"1. Бесплатный аудит и расчет\n"
                f"2. Заключение прозрачного договора\n"
                f"3. {jtbd['functional_job']}\n\n"
                f"{t_text}"
            )

        # 6. Hook-Story-Offer (Reels/Shorts)
        elif framework == MarketingFramework.HOOK_STORY_OFFER:
            lead = f"⚡ Перестаньте делать это, если хотите идеальный результат в {niche}!"
            body = (
                f"Вчера на объекте команда «{company_name}» столкнулась с классической ошибкой: клиент доверился обещаниям на словах и потерял 3 недели.\n\n"
                f"Мы исправили ситуацию за 2 дня благодаря отлаженным технологиям: {jtbd['functional_job']}\n\n"
                f"{t_text}"
            )

        # 7. FAB (Feature -> Advantage -> Benefit)
        else:
            lead = f"💎 В чем секрет качества «{company_name}»? Разбор на пальцах"
            body = (
                f"Мы используем только оригинальные сертифицированные материалы и технологии.\n\n"
                f"Благодаря этому: {jtbd['functional_job']}\n\n"
                f"В итоге вы получаете: {jtbd['emotional_job']} и {jtbd['social_job']}\n\n"
                f"{t_text}"
            )

        full_post = f"{lead}\n\n{body}\n\n{fogg_cta}"

        # Генерация профессиональных поисковых тегов конкурентов
        from skills.competitor_hashtags import NicheCompetitorHashtagEngine
        city_val = contacts.get("city", "") if contacts and isinstance(contacts, dict) else ""
        dynamic_hashtags = NicheCompetitorHashtagEngine.get_competitor_hashtags(
            niche=niche,
            topic=topic,
            city=city_val,
            company_name=company_name
        )

        # Строгая защита от утечек названий моделей и очистка формул
        from skills.tech_sanitizer import TechSanitizer
        sanitized_post = TechSanitizer.sanitize_text(full_post)
        try:
            from skills.saiga_llm import SaigaLLMSkill
            sanitized_post = SaigaLLMSkill._sanitize_llm_post(sanitized_post, company_name=company_name, niche=niche)
        except Exception:
            pass

        return {
            "status": "success",
            "company_name": company_name,
            "niche": niche,
            "topic": topic,
            "framework": framework.value,
            "framework_name": f_info["name"],
            "hunt_stage": hunt_stage.value,
            "psychological_trigger": trigger.value,
            "jtbd": jtbd,
            "fogg_cta": fogg_cta,
            "post_text": sanitized_post,
            "hashtags": dynamic_hashtags
        }
