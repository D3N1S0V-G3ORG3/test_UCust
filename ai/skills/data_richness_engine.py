# File: skills/data_richness_engine.py
"""
Data Richness Score (DRS) & Pre-Flight Entity Slot Extraction Engine for UCust.AI.
Переносит контроль качества на этап инжеста (всасывания) данных:
1. Оценивает коммерческую плотность брифа (DRS: 0-100 баллов) по 5 критическим слотам сущностей:
   - Product_Features (30 баллов): материалы, характеристики, габариты, SKU
   - Pricing_Model (20 баллов): точные цены, скидки, валюты, тарифы, рассрочка
   - Terms_Guarantees (15 баллов): сроки доставки/монтажа, гарантия, возврат
   - Pain_Points (20 баллов): конкретные проблемы и боли ЦА
   - Social_Proofs (15 баллов): кейсы, отзывы, цифры, стаж работы
2. Трехуровневая маршрутизация (Threshold Routing):
   - Green (DRS >= 80): Полная воронка Ханта (TOFU/MOFU/BOFU) с жесткими офферами.
   - Yellow (DRS 50-79): Адаптивная воронка (отключение неподтвержденных фреймворков вроде Risk Reversal).
   - Red (DRS < 50): Критическая нехватка фактуры -> Запуск Reverse Interrogation Bot (микро-опросник).
3. Защита от синдрома «Мнимой полноты» (False Fullness):
   - Полное игнорирование объема текста (word count) — оценка строго по найденным коммерческим сущностям.
"""

from __future__ import annotations

import re
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("data_richness_engine")


class DRSTier(str, Enum):
    GREEN = "green"    # DRS >= 80: Полная готовность
    YELLOW = "yellow"  # DRS 50-79: Частичная фактура
    RED = "red"        # DRS < 50: Критическая нехватка


@dataclass
class SlotResult:
    slot_name: str
    weight: int
    score: int
    is_filled: bool
    extracted_items: List[str] = field(default_factory=list)
    missing_aspects: List[str] = field(default_factory=list)


@dataclass
class DRSAssessment:
    total_score: int
    tier: DRSTier
    slots: Dict[str, SlotResult]
    allowed_frameworks: List[str]
    disabled_frameworks: List[str]
    missing_slots_summary: List[str]
    reverse_interrogation_questions: List[str]
    recommendation: str


class DataRichnessEngine:
    """
    Интеллектуальный шлюз оценки плотности коммерческих сущностей в брифе.
    """

    # 1. Регулярные выражения и сигнатуры для детекции 5 коммерческих слотов
    PATTERNS = {
        "pricing_model": [
            r"\b\d+[\s\xa0]*(?:руб(?:л[ейя])?|₽|usd|\$|eur|€|тыс(?:яч)?\.?\s*руб)\b",
            r"\b(?:цена|стоимость|тариф|прайс|скидк[аеиу]|акци[яией]|рассрочк[аеи]|от\s+\d+)\b",
            r"\b(?:бесплатно|предоплат[ае]|взнос|пакет|подписк[аеи])\b"
        ],
        "terms_guarantees": [
            r"\b(?:гаранти[яией]|срок[а-я]*(?:\s+[а-я]+)?\s+(?:доставк[иа]|изготовлен[ия]|монтаж[а-я]*|работ[а-я]*|отгрузк[иа]|поставк[иа]|исполнен[ия]))\b",
            r"\b\d+[\s\xa0]*(?:рабоч[а-я]*|календарн[а-я]*|банковск[а-я]*)?[\s\xa0]*(?:дн(?:ей|я)|час(?:ов|а)?|недел[ьи]|месяц(?:ев|а)?|лет|года)\b",
            r"\b(?:возврат[а-я]*|обмен[а-я]*|доставк[а-я]*\s+по|выезд\s+мастера|монтаж\s+за|отгрузк[а-я]*|поставк[а-я]*)\b"
        ],
        "product_features": [
            r"\b(?:материал[а-я]*|состав|габарит[а-я]*|размер[а-я]*|модель|объем|вес|мощность)\b",
            r"\b(?:массив\s+дуба|сталь|керамик[а-я]*|натуральн[а-я]*|хлопок|кожа|алюминий|ткань|дерево)\b",
            r"\b(?:интерфейс|модул[ьи]|автоматизаци[яи]|алгоритм[а-я]*|платформ[а-я]*|интеграци[яи])\b",
            r"\b\d+[\s\xa0]*(?:мм|см|м|кг|г|л|мл|вт|квт|гб|mb|gb|fps|v|вольт)\b"
        ],
        "pain_points": [
            r"\b(?:проблем[а-я]*|бол[ьи]|переплат[а-я]*|устал[а-я]*|рутин[а-я]*|ошибк[а-я]*|слив\s+бюджета)\b",
            r"\b(?:нехватк[а-я]|срыв\s+дедлайн[а-я]*|человеческий\s+фактор|трат[а-я]*\s+времени|галлюцинаци[а-я]*)\b",
            r"\b(?:страх|риск[а-я]*|сложно|непонятн[а-я]*|долго|дорого|некачественн[а-я]*)\b"
        ],
        "social_proofs": [
            r"\b(?:отзыв[а-я]*|клиент[а-я]*|кейсы?|портфолио|на\s+рынке\s+с\s+\d+|опыт\s+\d+)\b",
            r"\b(?:более\s+\d+|свыше\s+\d+|\d+\+?\s+клиент[а-я]*|\d+\+?\s+проектов|рейтинг\s+[45][\.,]\d)\b",
            r"\b(?:сертификат[а-я]*|наград[а-я]*|диплом[а-я]*|патент[а-я]*|лицензи[яи])\b"
        ]
    }

    @classmethod
    def evaluate_text(cls, raw_text: str, company_name: str = "Клиент") -> DRSAssessment:
        """
        Оценивает коммерческую плотность текста (DRS) без учета длины (анти-мнимость).
        """
        if not raw_text or len(raw_text.strip()) < 10:
            return cls._build_zero_assessment(company_name)

        text_lower = raw_text.lower()
        
        # 1. Оценка слотов
        # Слот 1: Product Features (30 баллов)
        feat_matches = cls._find_matches("product_features", text_lower)
        feat_score = 30 if len(feat_matches) >= 3 else (15 if len(feat_matches) >= 1 else 0)
        slot_features = SlotResult(
            slot_name="product_features",
            weight=30,
            score=feat_score,
            is_filled=feat_score >= 15,
            extracted_items=feat_matches[:5],
            missing_aspects=["материалы", "габариты", "спецификации"] if feat_score == 0 else []
        )

        # Слот 2: Pricing Model (20 баллов)
        price_matches = cls._find_matches("pricing_model", text_lower)
        price_score = 20 if len(price_matches) >= 2 else (10 if len(price_matches) >= 1 else 0)
        slot_pricing = SlotResult(
            slot_name="pricing_model",
            weight=20,
            score=price_score,
            is_filled=price_score >= 10,
            extracted_items=price_matches[:4],
            missing_aspects=["точные цены", "условия рассрочки / тарифы"] if price_score == 0 else []
        )

        # Слот 3: Terms & Guarantees (15 баллов)
        terms_matches = cls._find_matches("terms_guarantees", text_lower)
        terms_score = 15 if len(terms_matches) >= 2 else (8 if len(terms_matches) >= 1 else 0)
        slot_terms = SlotResult(
            slot_name="terms_guarantees",
            weight=15,
            score=terms_score,
            is_filled=terms_score >= 8,
            extracted_items=terms_matches[:4],
            missing_aspects=["сроки доставки/монтажа", "гарантийные обязательства"] if terms_score == 0 else []
        )

        # Слот 4: Pain Points (20 баллов)
        pain_matches = cls._find_matches("pain_points", text_lower)
        pain_score = 20 if len(pain_matches) >= 2 else (10 if len(pain_matches) >= 1 else 0)
        slot_pain = SlotResult(
            slot_name="pain_points",
            weight=20,
            score=pain_score,
            is_filled=pain_score >= 10,
            extracted_items=pain_matches[:4],
            missing_aspects=["конкретные боли и проблемы клиентов"] if pain_score == 0 else []
        )

        # Слот 5: Social Proofs (15 баллов)
        proof_matches = cls._find_matches("social_proofs", text_lower)
        proof_score = 15 if len(proof_matches) >= 2 else (8 if len(proof_matches) >= 1 else 0)
        slot_proofs = SlotResult(
            slot_name="social_proofs",
            weight=15,
            score=proof_score,
            is_filled=proof_score >= 8,
            extracted_items=proof_matches[:4],
            missing_aspects=["цифры кейсов", "число довольных клиентов", "опыт на рынке"] if proof_score == 0 else []
        )

        # 2. Итоговый расчет
        total_score = feat_score + price_score + terms_score + pain_score + proof_score
        total_score = min(100, max(0, total_score))

        slots_dict = {
            "product_features": slot_features,
            "pricing_model": slot_pricing,
            "terms_guarantees": slot_terms,
            "pain_points": slot_pain,
            "social_proofs": slot_proofs
        }

        # 3. Маршрутизация и фильтрация фреймворков
        allowed_fw = ["BAB", "Hook-Story-Offer", "StoryBrand"]
        disabled_fw = []

        if total_score >= 80:
            tier = DRSTier.GREEN
            allowed_fw.extend(["AIDA", "4P", "PAS", "FAB"])
            recommendation = "Идеальная фактура. Запущена полноценная 5-ступенчатая воронка Ханта."
        elif total_score >= 50:
            tier = DRSTier.YELLOW
            allowed_fw.extend(["PAS", "FAB"])
            if not slot_terms.is_filled or not slot_pricing.is_filled:
                disabled_fw.append("Risk_Reversal (Отключен: нет точных гарантий/цен)")
                disabled_fw.append("Hard_Offer_AIDA (Отключен: нет твердых условий)")
            recommendation = "Фактура средняя. Отключены агрессивные гарантии во избежание галлюцинаций."
        else:
            tier = DRSTier.RED
            disabled_fw.extend(["AIDA", "4P", "FAB", "Risk_Reversal"])
            recommendation = "Критическая нехватка данных. Запущен режим Process Storytelling и реверсивный опросник."

        # 4. Формирование вопросов для Reverse Interrogation Bot
        missing_summary = []
        questions = []
        
        if not slot_pricing.is_filled:
            missing_summary.append("Цены и тарифы")
            questions.append(f"В материалах нет точных цен. Напишите базовую стоимость для «{company_name}» (например: 'от 5 000 ₽' или 'тариф Старт 15 000 ₽'):")
            
        if not slot_terms.is_filled:
            missing_summary.append("Сроки и гарантии")
            questions.append(f"Укажите реальный срок выполнения/доставки для «{company_name}» (например: '3 рабочих дня', 'гарантия 12 месяцев'):")

        if not slot_features.is_filled:
            missing_summary.append("Спецификации и материалы")
            questions.append(f"Опишите 2-3 ключевых свойства вашего продукта (материалы, технологии, форматы):")

        if not slot_proofs.is_filled:
            missing_summary.append("Социальные пруфы")
            questions.append(f"Сколько лет вы работаете на рынке или сколько клиентов уже воспользовались продуктом «{company_name}»?")

        return DRSAssessment(
            total_score=total_score,
            tier=tier,
            slots=slots_dict,
            allowed_frameworks=allowed_fw,
            disabled_frameworks=disabled_fw,
            missing_slots_summary=missing_summary,
            reverse_interrogation_questions=questions[:3],
            recommendation=recommendation
        )

    @classmethod
    def _find_matches(cls, category: str, text: str) -> List[str]:
        patterns = cls.PATTERNS.get(category, [])
        found = []
        for p in patterns:
            for m in re.finditer(p, text):
                match_str = m.group(0).strip()
                if match_str and match_str not in found:
                    found.append(match_str)
        return found

    @classmethod
    def _build_zero_assessment(cls, company_name: str) -> DRSAssessment:
        return DRSAssessment(
            total_score=0,
            tier=DRSTier.RED,
            slots={},
            allowed_frameworks=["BAB", "Hook-Story-Offer"],
            disabled_frameworks=["AIDA", "4P", "PAS", "FAB", "Risk_Reversal"],
            missing_slots_summary=["Все коммерческие слоты пусты"],
            reverse_interrogation_questions=[
                f"Загрузите прайс-лист или кратко опишите продукт компании «{company_name}»:",
                f"Укажите цены и сроки оказания услуг для «{company_name}»:"
            ],
            recommendation="Критическая нехватка данных: бриф пуст."
        )


__all__ = ["DataRichnessEngine", "DRSAssessment", "DRSTier", "SlotResult"]
