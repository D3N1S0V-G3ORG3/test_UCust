"""
File: ai/skills/poll_generator.py
Interactive Social Poll & Quiz Generation Skill for UCust AI (Telegram & VK).

Поддерживает:
1. Вовлекающие опросы (TOFU) — легкие вопросы, споры, сбор мнений.
2. Квалифицирующие опросы (MOFU) — выявление болей, потребностей, предпочтений ЦА.
3. Конверсионные опросы (BOFU) — выбор тарифа, любимого продукта, готовность к заказу.
4. Экспертные Викторины (Quiz) — проверка знаний подписчиков с правильным ответом и пояснением.
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import logging
import uuid
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("ucust_ai.poll_generator")


class PollOption(BaseModel):
    id: int
    text: str = Field(..., max_length=100, description="Текст варианта ответа (макс. 100 символов)")
    is_correct: Optional[bool] = None


class GeneratedPoll(BaseModel):
    id: str = Field(default_factory=lambda: f"poll_{uuid.uuid4().hex[:8]}")
    topic: str
    question: str = Field(..., max_length=255, description="Вопрос опроса (макс. 255 символов для Telegram/VK)")
    options: List[str] = Field(..., min_items=2, max_items=10, description="От 2 до 10 вариантов ответов")
    poll_type: str = Field("regular", description="regular | quiz")
    is_anonymous: bool = Field(False, description="Анонимный опрос или публичный")
    allows_multiple_answers: bool = Field(False, description="Разрешен ли выбор нескольких вариантов")
    correct_option_id: Optional[int] = Field(None, description="Индекс правильного ответа (для викторин 0-based)")
    explanation: Optional[str] = Field(None, max_length=200, description="Пояснение к правильному ответу для викторин")
    funnel_stage: str = Field("TOFU", description="TOFU | MOFU | BOFU")
    niche: str = "Бизнес"
    company_name: str = ""
    accompanying_text: str = Field("", description="Подводка/текст поста перед опросом")
    suggested_call_to_action: str = ""


class PollGenerateRequest(BaseModel):
    topic: str = Field(..., description="Тема опроса или инфоповод")
    niche: str = Field("Бизнес", description="Ниша / сфера деятельности")
    company_name: str = Field("", description="Название компании / бренда")
    goal: str = Field("engagement", description="engagement (TOFU) | qualification (MOFU) | decision (BOFU) | knowledge_check (Quiz)")
    is_quiz: bool = Field(False, description="Сгенерировать викторину с правильным ответом")
    options_count: int = Field(4, ge=2, le=10, description="Желаемое количество вариантов")
    is_anonymous: bool = Field(False, description="Анонимный опрос")
    allows_multiple_answers: bool = Field(False, description="Разрешить выбор нескольких вариантов")


class PollGeneratorSkill:
    """
    Генератор профессиональных интерактивных опросов и квизов для Telegram и VK.
    """

    def __init__(self, llm_engine=None):
        self.llm = llm_engine

    def generate_poll(
        self,
        topic: str,
        niche: str = "Бизнес",
        company_name: str = "UCust",
        goal: str = "engagement",
        is_quiz: bool = False,
        options_count: int = 4,
        is_anonymous: bool = False,
        allows_multiple_answers: bool = False
    ) -> GeneratedPoll:
        """
        Генерирует готовый опрос на основе параметров ниши и целей воронки.
        """
        comp = company_name or "наш бренд"
        niche_lower = niche.lower()
        topic_clean = topic.strip()

        # 1. Если запрошена викторина (Quiz)
        if is_quiz or goal == "knowledge_check":
            return self._generate_quiz_poll(
                topic=topic_clean,
                niche=niche,
                company_name=comp,
                options_count=options_count
            )

        # 2. Опросы по этапам воронки (приоритет прямому goal)
        if goal == "decision" or (goal != "engagement" and any(w in topic_clean.lower() for w in ["выбор тарифа", "спецпредложен", "скидк", "купить", "заказать"])):
            return self._generate_bofu_poll(
                topic=topic_clean,
                niche=niche,
                company_name=comp,
                options_count=options_count,
                is_anonymous=is_anonymous,
                allows_multiple_answers=allows_multiple_answers
            )
        elif goal == "qualification" or (goal != "engagement" and any(w in topic_clean.lower() for w in ["боль", "проблем", "сложност", "барьер"])):
            return self._generate_mofu_poll(
                topic=topic_clean,
                niche=niche,
                company_name=comp,
                options_count=options_count,
                is_anonymous=is_anonymous,
                allows_multiple_answers=True if goal == "qualification" else allows_multiple_answers
            )
        else:
            return self._generate_tofu_poll(
                topic=topic_clean,
                niche=niche,
                company_name=comp,
                options_count=options_count,
                is_anonymous=is_anonymous,
                allows_multiple_answers=allows_multiple_answers
            )


    def _generate_tofu_poll(
        self,
        topic: str,
        niche: str,
        company_name: str,
        options_count: int = 4,
        is_anonymous: bool = False,
        allows_multiple_answers: bool = False
    ) -> GeneratedPoll:
        """TOFU (Вовлечение / Мнения / Юмор / Лайфстайл)"""
        niche_l = niche.lower()
        
        if any(k in niche_l for k in ["кофе", "кафе", "ресторан", "еда", "food"]):
            question = f"☕ С чего начинается ваше идеальное утро?"
            options = [
                "Плотный фильтр-кофе или американо",
                "Нежный капучино / латте с пенкой",
                "Освежающий флэт уайт на альтернативном молоке",
                "Матча / зеленый чай для мягкой бодрости",
                "Главное — свежая выпечка, а напиток вторичен 🥐"
            ][:options_count]
            intro = f"В {company_name} уверены: правильное утро задает тон всему дню! Давайте сверим вкусы нашей кофейной семьи."
        elif any(k in niche_l for k in ["it", "разработ", "софт", "saas", "ai", "технолог"]):
            question = f"💻 Главный источник продуктивности на удаленке / в офисе?"
            options = [
                "Шумоподавляющие наушники + lo-fi плейлист 🎧",
                "Помидорный таймер и блокировка соцсетей",
                "Бесконечный запас кофе и четкий таск-трекер",
                "Работа ночью, когда никто не отвлекает в Slack",
                "Парное программирование и созвоны"
            ][:options_count]
            intro = f"Команда {company_name} провела опрос среди инженеров. А как вы спасаетесь от прокрастинации в спринтах?"
        else:
            question = f"📊 Какое качество в сфере «{niche}» для вас на 1 месте?"
            options = [
                "Скорость и соблюдение дедлайнов",
                "Безупречное качество без компромиссов",
                "Прозрачные и понятные цены",
                "Внимательное и человечное отношение",
                "Инновационные решения и современные технологии"
            ][:options_count]
            intro = f"Нам важно знать, что ценит аудитория {company_name}. Поделитесь вашим мнением в опросе ниже 👇"

        return GeneratedPoll(
            topic=topic,
            question=question,
            options=options,
            poll_type="regular",
            is_anonymous=is_anonymous,
            allows_multiple_answers=allows_multiple_answers,
            funnel_stage="TOFU",
            niche=niche,
            company_name=company_name,
            accompanying_text=intro,
            suggested_call_to_action="Голосуйте и делитесь в комментариях, почему выбрали именно этот вариант!"
        )

    def _generate_mofu_poll(
        self,
        topic: str,
        niche: str,
        company_name: str,
        options_count: int = 4,
        is_anonymous: bool = False,
        allows_multiple_answers: bool = True
    ) -> GeneratedPoll:
        """MOFU (Квалификация / Выявление болей / Экспертный разбор)"""
        niche_l = niche.lower()

        if any(k in niche_l for k in ["кофе", "кафе", "ресторан", "еда"]):
            question = f"🤔 С какой главной проблемой вы сталкиваетесь при выборе кофе?"
            options = [
                "Слишком горький / жженый вкус в обычных магазинах",
                "Непонятно, как правильно заваривать дома",
                "Сложно подобрать зерно под свой вкус",
                "Быстро выдыхается после вскрытия пачки"
            ][:options_count]
            intro = f"Мы в {company_name} готовим практический гид по домашнему завариванию. Что разобрать в первую очередь?"
        elif any(k in niche_l for k in ["it", "разработ", "софт", "saas", "ai"]):
            question = f"⚠️ Какое узкое место сильнее всего тормозит ваши релизы?"
            options = [
                "Долгие ручные тесты и регресс перед деплоем",
                "Постоянно меняющиеся требования и техдолг",
                "Нехватка квалифицированных мидл/сеньор кадров",
                "Сложности с архитектурой и микросервисами"
            ][:options_count]
            intro = f"Эксперты {company_name} разбирают реальные кейсы оптимизации процессов разработки. Отметьте ваши главные блокеры."
        else:
            question = f"🎯 Что вызывает больше всего сложностей при заказе услуг в «{niche}»?"
            options = [
                "Сложно найти надежных исполнителей с гарантией",
                "Непрозрачный расчет финальной стоимости",
                "Срывы сроков и плохая коммуникация",
                "Отсутствие пост-поддержки и гарантии"
            ][:options_count]
            intro = f"Честный опрос от {company_name}: с какими барьерами вы чаще всего сталкиваетесь в нашей нише?"

        return GeneratedPoll(
            topic=topic,
            question=question,
            options=options,
            poll_type="regular",
            is_anonymous=is_anonymous,
            allows_multiple_answers=allows_multiple_answers,
            funnel_stage="MOFU",
            niche=niche,
            company_name=company_name,
            accompanying_text=intro,
            suggested_call_to_action="Выберите до 2 вариантов. В следующем посте разберем решение самой частой проблемы!"
        )

    def _generate_bofu_poll(
        self,
        topic: str,
        niche: str,
        company_name: str,
        options_count: int = 4,
        is_anonymous: bool = False,
        allows_multiple_answers: bool = False
    ) -> GeneratedPoll:
        """BOFU (Решение о покупке / Спецпредложение / Выбор продукта)"""
        niche_l = niche.lower()

        if any(k in niche_l for k in ["кофе", "кафе", "ресторан", "еда"]):
            question = f"🎁 Какой спецпродукт от {company_name} включить в акцию недели со скидкой 20%?"
            options = [
                "Дрип-пакеты Эфиопия Иргачефф (10 шт)",
                "Килограммовая пачка авторского эспрессо-бленда",
                "Набор спешелти фильтр-кофе для V60",
                "Дегустационный сет микролотов свежей обжарки"
            ][:options_count]
            intro = f"Пятничный интерактив от {company_name}! Вы сами выбираете, на какую позицию мы откроем промокод на выходные."
        else:
            question = f"🚀 Какой формат сотрудничества с {company_name} для вас наиболее удобен?"
            options = [
                "Быстрый экспресс-аудит текущего решения (бесплатно)",
                "Комплексный проект 'под ключ' с персональным менеджером",
                "Тестовый период / пилотный запуск со скидкой",
                "Консультация с ведущим экспертом направления"
            ][:options_count]
            intro = f"Формируем спецпредложения на следующий месяц в {company_name}. Помогите нам сделать условия максимально выгодными для вас."

        return GeneratedPoll(
            topic=topic,
            question=question,
            options=options,
            poll_type="regular",
            is_anonymous=is_anonymous,
            allows_multiple_answers=allows_multiple_answers,
            funnel_stage="BOFU",
            niche=niche,
            company_name=company_name,
            accompanying_text=intro,
            suggested_call_to_action="Голосуйте! Лидер опроса станет основой специального предложения для подписчиков."
        )

    def _generate_quiz_poll(
        self,
        topic: str,
        niche: str,
        company_name: str,
        options_count: int = 4
    ) -> GeneratedPoll:
        """Quiz / Викторина с проверкой знаний подписчиков и объяснением"""
        niche_l = niche.lower()

        if any(k in niche_l for k in ["кофе", "кафе", "ресторан", "еда"]):
            question = f"🧠 Кофейный квиз: какая идеальная температура воды для заваривания светлой обжарки?"
            options = [
                "100°C (крутой кипяток)",
                "91°C – 94°C",
                "75°C – 80°C",
                "Температура не имеет значения"
            ][:options_count]
            correct_id = 1
            explanation = "Кипяток (100°C) пережигает деликатные масла светлой обжарки. Оптимум — 91-94°C для баланса сладости и кислотности."
            intro = f"Проверьте свою кофейную эрудицию вместе с {company_name}! Выберите правильный вариант ответа ниже 🤓"
        elif any(k in niche_l for k in ["it", "разработ", "софт", "saas", "ai"]):
            question = f"🧠 IT-квиз: какой HTTP-код означает, что запрос принят в асинхронную обработку, но еще не завершен?"
            options = [
                "200 OK",
                "202 Accepted",
                "204 No Content",
                "304 Not Modified"
            ][:options_count]
            correct_id = 1
            explanation = "HTTP 202 Accepted указывает, что запрос принят на обработку, но результат будет готов позже (например, в очереди Celery)."
            intro = f"Пятничный блиц-квиз для разработчиков от команды {company_name}! Знаете правильный ответ?"
        else:
            question = f"🧠 Проверка знаний: какой ключевой фактор сильнее всего влияет на результат в «{niche}»?"
            options = [
                "Случайность и удача",
                "Четкая системная методология и контроль качества",
                "Только размер первоначального бюджета",
                "Громкая реклама без доработки продукта"
            ][:options_count]
            correct_id = 1
            explanation = "Системный подход и стандарты контроля качества обеспечивают повторяемый результат независимо от внешних факторов."
            intro = f"Небольшая интеллектуальная викторина от {company_name}! Давайте проверим интуицию."

        return GeneratedPoll(
            topic=topic,
            question=question,
            options=options,
            poll_type="quiz",
            is_anonymous=False,
            allows_multiple_answers=False,
            correct_option_id=correct_id,
            explanation=explanation,
            funnel_stage="TOFU",
            niche=niche,
            company_name=company_name,
            accompanying_text=intro,
            suggested_call_to_action="Выберите вариант и сразу увидите правильный ответ с объяснением эксперта!"
        )
