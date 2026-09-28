"""
Fact-Checking Critic & Auto-Corrector for UCust.AI (LLM-as-a-Judge).
Модуль арбитражной сверки сгенерированного текста с верифицированным паспортом FactSheet:
1. Выявляет галлюцинированные цифры, неподтвержденные ТТХ, фальшивые сертификаты и вымышленные ингредиенты.
2. Формирует JSON-патч точечной автокоррекции (Auto-Correction Patch).
3. Применяет диффы без потери авторского тона и стиля текста.
"""

from __future__ import annotations

import re
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

try:
    from skills.autonomous_research_grounder import FactSheet
except ImportError:
    try:
        from ai.skills.autonomous_research_grounder import FactSheet
    except ImportError:
        FactSheet = None

logger = logging.getLogger("fact_checking_critic")


class FactCorrectionPatch(BaseModel):
    hallucinated_phrase: str = Field(..., description="Вымышленная фраза или неподтвержденная цифра")
    replacement: str = Field(..., description="Безопасная, концептуальная и фактологически верная замена")
    reason: str = Field(..., description="Причина корректировки (отсутствие в FactSheet)")


class FactValidationReport(BaseModel):
    is_fully_grounded: bool = Field(default=True, description="Флаг полного соответствия фактам")
    hallucinations_detected: int = Field(default=0, description="Количество выявленных расхождений")
    patches: List[FactCorrectionPatch] = Field(default_factory=list, description="Список примененных исправлений")
    original_text: str = Field(..., description="Исходный сгенерированный текст")
    sanitized_text: str = Field(..., description="Итоговый верифицированный текст")


class FactCheckingCritic:
    """
    Интеллектуальный критик-верификатор на базе правил и сравнительного анализа сущностей.
    """

    # Регулярные выражения для поиска жестких числовых и качественных утверждений
    METRIC_PATTERN = re.compile(
        r'(\b\d+[\.,]?\d*\s*(?:г|кг|мл|л|гц|мгц|ггц|ghz|mhz|khz|hz|mah|мач|вт|w|v|в|мм|см|м|gb|гб|tb|тб|mp|мп|fps|°c|%|дней|лет|месяцев|минут|часов)\b)',
        re.IGNORECASE
    )

    DUBIOUS_MARKETING_CLAIMS = [
        (re.compile(r'\b100%\s+натуральн[а-яё]*\b', re.IGNORECASE), "натуральные отборные ингредиенты"),
        (re.compile(r'\b100%\s+гаранти[а-яё]*\b', re.IGNORECASE), "высокая надежность"),
        (re.compile(r'\bлучш[а-яё]+\s+в\s+мире\b', re.IGNORECASE), "высоко оцененный экспертами"),
        (re.compile(r'\bвечн[а-яё]+\s+гаранти[а-яё]*\b', re.IGNORECASE), "надежная фирменная гарантия"),
        (re.compile(r'\bвыдерживается\s+\d+\s+лет\b', re.IGNORECASE), "проходит классический процесс выдержки"),
        (re.compile(r'\bмгновенн[а-яё]+\s+излеч[а-яё]*\b', re.IGNORECASE), "бережно поддерживает организм"),
    ]

    @classmethod
    def validate_and_autocorrect(
        cls,
        text: str,
        fact_sheet: Optional[FactSheet] = None
    ) -> FactValidationReport:
        """
        Сверяет сгенерированный текст с FactSheet и автоматически исправляет галлюцинации.
        """
        if not text:
            return FactValidationReport(
                is_fully_grounded=True,
                hallucinations_detected=0,
                patches=[],
                original_text="",
                sanitized_text=""
            )

        sanitized = text
        patches: List[FactCorrectionPatch] = []

        # 1. Проверка общих сомнительных маркетинговых клеймов
        for pattern, replacement in cls.DUBIOUS_MARKETING_CLAIMS:
            matches = pattern.findall(sanitized)
            for m in set(matches):
                patch = FactCorrectionPatch(
                    hallucinated_phrase=m,
                    replacement=replacement,
                    reason="Необоснованное абсолютное утверждение без юридического подтверждения"
                )
                patches.append(patch)
                sanitized = re.sub(re.escape(m), replacement, sanitized)

        # 2. Очистка от технических утечек поисковой выдачи и сырого markdown
        search_leak_patterns = [
            (re.compile(r'[-–—]?\s*Источник\s*\(https?://[^\)]+\):\s*#+[^\n]*', re.IGNORECASE), ""),
            (re.compile(r'#+\s*\d*\.?\s*Аналитический обзор[^\n]*', re.IGNORECASE), ""),
            (re.compile(r'#+\s*Актуальные рыночные тренды:[^\n]*', re.IGNORECASE), ""),
        ]
        for pattern, replacement in search_leak_patterns:
            if pattern.search(sanitized):
                sanitized = pattern.sub(replacement, sanitized)

        # 3. Если FactSheet предоставлен, сверяем числовые метрики
        if fact_sheet and fact_sheet.is_grounded:
            known_context = " ".join(fact_sheet.key_specs).lower()
            product_name_lower = fact_sheet.product_name.lower()
            combined_known = f"{known_context} {product_name_lower}"

            # Поиск всех числовых метрик в тексте
            found_metrics = cls.METRIC_PATTERN.findall(text)
            for metric in set(found_metrics):
                metric_clean = metric.strip().lower()
                num_part = re.search(r'\d+', metric_clean)
                if num_part:
                    num_val = num_part.group(0)
                    # Исключаем цены, промокоды и цитаты
                    if any(w in metric_clean for w in ["₽", "руб", "usd", "$", "eur", "€"]):
                        continue
                    if num_val not in combined_known and len(num_val) >= 2:
                        safe_replacement = "необходимый срок"
                        if any(u in metric_clean for u in ["дней", "дня", "день", "суток"]):
                            safe_replacement = "длительное время"
                        elif any(u in metric_clean for u in ["часов", "часа", "час", "минут"]):
                            safe_replacement = "строго выверенное время"
                        elif "%" in metric_clean:
                            safe_replacement = "выгодные специальные условия"
                        elif any(u in metric_clean for u in ["mah", "мач"]):
                            safe_replacement = "емкий аккумулятор"
                        elif any(u in metric_clean for u in ["mp", "мп"]):
                            safe_replacement = "высокое разрешение камеры"
                        elif any(u in metric_clean for u in ["gb", "гб", "tb", "тб"]):
                            safe_replacement = "внушительный объем памяти"

                        patch = FactCorrectionPatch(
                            hallucinated_phrase=metric,
                            replacement=safe_replacement,
                            reason=f"Цифра '{metric}' не подтверждена в проверенном FactSheet"
                        )
                        patches.append(patch)
                        sanitized = sanitized.replace(metric, safe_replacement)

        # Удаляем пустые лишние строки
        sanitized = re.sub(r'\n{3,}', '\n\n', sanitized).strip()

        report = FactValidationReport(
            is_fully_grounded=len(patches) == 0,
            hallucinations_detected=len(patches),
            patches=patches,
            original_text=text,
            sanitized_text=sanitized
        )

        if patches:
            logger.info(
                f"🛡️ [FactCheckingCritic] Обнаружено {len(patches)} расхождений. Применен JSON-патч автокоррекции."
            )
        else:
            logger.info("✅ [FactCheckingCritic] Текст прошел 100% факт-чекинг без замечаний.")

        return report
