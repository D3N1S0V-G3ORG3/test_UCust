# File: skills/critic_munger.py
"""
Agent Critic Charlie Munger 2.0: Professional Marketing, Lexicon & Semantic Bleed Audit Engine.
"""

from __future__ import annotations
import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import re
from typing import Dict, Any, List, Optional
from skills.context_router import RoutingDirective, QuadrantEnum, FunnelLockEnum

try:
    from skills.marketing_frameworks import NicheClusterResolver, NicheCluster, NICHE_CONSTRAINTS
except ImportError:
    from ai.skills.marketing_frameworks import NicheClusterResolver, NicheCluster, NICHE_CONSTRAINTS


class CriticMungerSkill:
    STOP_CLICHES = [
        'динамично развивающаяся', 'команда профессионалов', 'индивидуальный подход',
        'лучшее качество', 'доступным ценам', 'широкий спектр', 'не упустите',
        'высокий уровень', 'лидеры рынка', 'уникальное предложение', 'встречайте наше',
        'встречайте наш', 'это не просто', 'крушить барьеры', 'руинах обыденности',
        'сверхъестественн', 'выстрел в мир', 'держись крепче'
    ]

    QUADRANT_STOP_WORDS = {
        QuadrantEnum.B2C_LIFESTYLE: [
            r"оптимиз\w*", r"\bkpi\b", r"\broi\b", r"документооборот\w*",
            r"сокращени\w+ издержек", r"бюджет\w*", r"внедр\w+",
            r"сертификат\w+ и справк\w+ вдвое быстр\w+", r"\bcac\b", r"конверси\w+ в продаж"
        ],
        QuadrantEnum.B2C_ECOM: [
            r"\bkpi\b", r"\broi\b", r"документооборот\w*", r"b2b", r"enterprise"
        ],
        QuadrantEnum.B2B_TECH: [
            r"волшебн\w+", r"сказочн\w+", r"супер-пупер", r"бомбическ\w+"
        ]
    }

    def __init__(self, strictness: float = 0.75):
        self.strictness = strictness

    def review_content(
        self,
        text: str,
        topic: str = '',
        target_audience: str = '',
        routing: Optional[RoutingDirective] = None,
        niche: str = '',
        negative_constraints: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:

        if not text or len(text.strip()) < 20:
            return {
                'passed': False, 'score': 0.2, 'verdict': 'REJECT',
                'criticism': 'Текст пустой или слишком короткий.',
                'actionable_feedback': 'Напишите полноценный текст с хуком и оффером.',
                'fatal_flaws': ['Текст не несет пользы.']
            }

        fatal_flaws: List[str] = []
        cautions: List[str] = []
        audit_breakdown: Dict[str, bool] = {}
        score = 1.0
        text_clean = text.strip()
        text_lower = text_clean.lower()
        lines = [line.strip() for line in text_clean.splitlines() if line.strip()]
        # -1. SUBSTANCE DEPTH & ANTI-ECHO GATEKEEPER
        if len(text_clean) < 100 or len(lines) < 3:
            score -= 0.40
            fatal_flaws.append("Thin Content: Текст слишком поверхностный (<100 символов) или содержит менее 3 смысловых строк.")
            audit_breakdown['substance_depth'] = False
        else:
            audit_breakdown['substance_depth'] = True

        if topic and len(topic.strip()) > 10:
            topic_clean = topic.strip().lower()
            if text_lower == topic_clean or (len(text_clean) < len(topic.strip()) * 1.5 and topic_clean in text_lower):
                score -= 0.45
                fatal_flaws.append("Echo of Brief: Текст является тривиальным эхо-повтором темы брифа без добавленной пользы.")
                audit_breakdown['anti_echo'] = False
            else:
                audit_breakdown['anti_echo'] = True
        else:
            audit_breakdown['anti_echo'] = True

        # 0. 4-QUADRANT LEXICON GATEKEEPER (Regex Filter, <1 ms)
        forbidden_patterns = []
        if routing and routing.critic_directive.forbidden_regex:
            forbidden_patterns.extend(routing.critic_directive.forbidden_regex)
        elif routing and routing.quadrant in self.QUADRANT_STOP_WORDS:
            forbidden_patterns.extend(self.QUADRANT_STOP_WORDS[routing.quadrant])

        found_forbidden = []
        for pat in forbidden_patterns:
            matches = re.findall(pat, text_lower)
            if matches:
                found_forbidden.extend(matches)

        if found_forbidden:
            score -= 0.35
            unique_found = list(set(found_forbidden))[:3]
            fatal_flaws.append(f"Tone & Lexicon Violation: Обнаружен недопустимый B2B-жаргон {unique_found}.")
            audit_breakdown['lexicon_gatekeeper'] = False
        else:
            audit_breakdown['lexicon_gatekeeper'] = True

        # 0.1 SEMANTIC BLEED & OXYMORON CHECK (Универсальная проверка сущностей)
        has_absurd_b2b_blend = False
        
        # 1. Религия / Церковь
        if any(w in (topic + " " + text_lower) for w in ["церков", "храм", "собор", "богослужен", "религи"]):
            if any(w in text_lower for w in ["документ", "бюджет", "инноваци", "kpi", "roi", "сократили время", "сократить бюджет", "справк", "сертификат"]):
                has_absurd_b2b_blend = True
                
        # 2. Домашние питомцы / Котики
        if any(w in (topic + " " + text_lower) for w in ["кот", "кошк", "собак", "питом"]):
            if any(w in text_lower for w in ["оптимиз", "расход", "kpi", "roi", "бюджет", "снижение расходов", "индивидуальный план в течение первых"]):
                has_absurd_b2b_blend = True

        # 3. Еда / Ресторан / Кофе
        if any(w in (topic + " " + text_lower) for w in ["ресторан", "кофе", "раф", "ужин", "авторская кухня", "блюдо", "кулинар", "гастроном", "десерт", "выпечк"]):
            if any(w in text_lower for w in ["документооборот", "интеграция erp", "бухгалтерский аудит"]):
                has_absurd_b2b_blend = True

        if has_absurd_b2b_blend:
            score -= 0.40
            fatal_flaws.append("Semantic Bleed: Обнаружен оксюморон (натягивание B2B SaaS метрик на бытовую/религиозную тему).")
            audit_breakdown['semantic_bleed'] = False
        else:
            audit_breakdown['semantic_bleed'] = True

        # 1. ТЕСТ НА «ГЛАВНУЮ ЗАДАЧУ» (THE ONE THING)
        is_tofu = routing and routing.text_directive.funnel_lock == FunnelLockEnum.TOFU_UNAWARE
        cta_keywords = ['напишите', 'переходите', 'ссылк', 'жмите', 'пишите', 'забирайте', 'промокод', 'оставляйте', 'заказывайте', 'делитесь', 'комментари', 'личные сообщения', 'лс', 'заглядывайте', 'хорошего дня', 'с праздником', 'приходите', 'поздравля']
        found_ctas = [k for k in cta_keywords if k in text_lower]
        
        if not found_ctas and not is_tofu:
            score -= 0.15
            fatal_flaws.append('Нет понятного Call to Action (The One Thing не определен).')
            audit_breakdown['the_one_thing'] = False
        else:
            audit_breakdown['the_one_thing'] = True

        # 2. ОЦЕНКА ПО ФОРМУЛЕ «СКОЛЬЗКОЙ ДОРОЖКИ»
        first_line = lines[0] if lines else ""
        if len(first_line) < 10:
            score -= 0.10
            cautions.append('Слишком короткий заголовок.')
            audit_breakdown['slippery_slope'] = False
        elif any(w in first_line.lower() for w in ['привет', 'здравствуйте', 'всем привет', 'встречайте']):
            score -= 0.15
            fatal_flaws.append('Скучный зачин («Привет»/«Встречайте») ломает скользкую дорожку.')
            audit_breakdown['slippery_slope'] = False
        else:
            audit_breakdown['slippery_slope'] = True

        # 3. ТЕСТ НА «И ЧЁ?» (WIIFM)
        benefit_markers = ['эконом', 'гаранти', 'быстр', 'надежн', 'удобн', 'защит', 'легк', 'выгод', 'решени', 'помож', 'без ', 'сократ', 'вкус', 'атмосфер', 'уют', 'наслажд', 'радост', 'настроен', 'светл', 'покой', 'мир', 'вдохновен']
        has_benefit = any(b in text_lower for b in benefit_markers)
        
        if not has_benefit and not is_tofu:
            score -= 0.15
            cautions.append('Тест «И чё?»: мало оцифрованной или эмоциональной пользы.')
            audit_breakdown['wiifm_benefit'] = False
        else:
            audit_breakdown['wiifm_benefit'] = True

        # 4. ТЕСТ НА «УЗНАВАЕМОСТЬ БРЕНДА» (TONE OF VOICE)
        found_cliches = [c for c in self.STOP_CLICHES if c in text_lower]
        if found_cliches:
            score -= 0.15 * len(found_cliches)
            fatal_flaws.append(f'Нарушение Tone of Voice: обнаружены штампы {found_cliches}.')
            audit_breakdown['brand_voice'] = False
        else:
            audit_breakdown['brand_voice'] = True

        # 5. ВИЗУАЛЬНЫЙ СКАН
        paragraphs = [p.strip() for p in text_clean.split("\n\n") if p.strip()]
        has_good_paragraphs = len(paragraphs) >= 2 and all(len(p.splitlines()) <= 5 for p in paragraphs)
        if not has_good_paragraphs and len(text_clean) > 250:
            score -= 0.10
            cautions.append('Визуальный скан: слишком плотный текст, разбейте на абзацы по 3-4 строки.')
            audit_breakdown['visual_scan_rhythm'] = False
        else:
            audit_breakdown['visual_scan_rhythm'] = True

        # 6. СООТВЕТСТВИЕ КОНТЕКСТУ ПЛОЩАДКИ
        emoji_count = len(re.findall(r'[\U00010000-\U0010ffff]', text_clean))
        if emoji_count > 6:
            score -= 0.10
            cautions.append(f'Перебор с эмодзи ({emoji_count} шт.) — оставьте 2-3.')
            audit_breakdown['platform_nativity'] = False
        else:
            audit_breakdown['platform_nativity'] = True

        # 7. MUNGER PSYCHOLOGICAL INDEX (MPI) & LOLLAPALOOZA SYNERGY
        detected_psychological_triggers = []
        if re.search(r'скидк\w+|кешбэк\w*|бонус\w*|промокод\w*|подарок\w*|бесплатн\w+|выгод\w+', text_lower):
            detected_psychological_triggers.append('reward_super_response')
        if re.search(r'отзыв\w*|клиент\w*|выбира\w+|рейтинг\w*|бестселлер\w*|\d+\s*довольных|звезд\w*|рекоменд\w+', text_lower):
            detected_psychological_triggers.append('social_proof')
        if re.search(r'эстетик\w*|статус\w*|уверенност\w*|наслажд\w*|уют\w*|стил\w+|вдохнов\w*|чувств\w*|атмосфер\w*', text_lower):
            detected_psychological_triggers.append('pavlovian_association')
        if re.search(r'остал\w+|только до|до конца недели|до \d+:\d+|ограничен\w+|последн\w+|всего \d+|дефицит\w*', text_lower):
            detected_psychological_triggers.append('deprival_fomo')
        if re.search(r'гаранти\w*|договор\w*|сертификат\w*|официальн\w*|возврат\w*|тест-драйв\w*', text_lower):
            detected_psychological_triggers.append('risk_reversal_authority')

        is_lollapalooza = len(detected_psychological_triggers) >= 3
        if is_lollapalooza:
            score = min(1.0, score + 0.10)
            audit_breakdown['lollapalooza_synergy'] = True
        else:
            audit_breakdown['lollapalooza_synergy'] = False

        # 8. CONTEXT-AWARE NICHE CLUSTER AUDIT
        cluster_enum, cluster_spec = NicheClusterResolver.resolve_cluster(niche or target_audience or topic)
        
        # B2B & Industrial: Требование точных цифр, SLA и окупаемости (Zero-Water)
        if cluster_enum == NicheCluster.B2B_INDUSTRIAL:
            has_digits = bool(re.search(r'\d+', text_clean))
            if not has_digits:
                score -= 0.25
                fatal_flaws.append("B2B Zero-Metrics: Текст не содержит точных цифр, метрик окупаемости (ROI), часов экономии или SLA.")
                audit_breakdown['b2b_metrics'] = False
            else:
                audit_breakdown['b2b_metrics'] = True

        # EdTech & Education: Требование бесплатной пользы / разбора ошибки перед продажей
        elif cluster_enum == NicheCluster.EDTECH_EDUCATION:
            has_value = any(w in text_lower for w in ["ошибк", "разбор", "шаблон", "правил", "совет", "лайфхак", "чек-лист", "алгоритм", "гайд", "практик"])
            if not has_value:
                score -= 0.20
                cautions.append("EdTech Reciprocity: Текст переходит к продаже курса без предварительной ценности или разбора ошибки.")
                audit_breakdown['edtech_reciprocity'] = False
            else:
                audit_breakdown['edtech_reciprocity'] = True

        # Local SMB: Сенсорика и четкий локальный дефицит
        elif cluster_enum == NicheCluster.LOCAL_SERVICES_SMB:
            has_sensory = any(w in text_lower for w in ["вкус", "хруст", "запах", "блеск", "аромат", "свеж", "мякиш", "корочк", "температур", "оттенок", "мастер"])
            if not has_sensory:
                score -= 0.15
                cautions.append("SMB Sensory Gap: Недостаточно тактильных и сенсорных дескрипторов продукта/услуги.")
                audit_breakdown['smb_sensory'] = False
            else:
                audit_breakdown['smb_sensory'] = True

        # Freelance Experts: Продажа конечного состояния вместо процесса
        elif cluster_enum == NicheCluster.FREELANCE_EXPERTS:
            has_outcome = any(w in text_lower for w in ["спокойн", "уверенност", "выручк", "доход", "сон", "свобод", "результат", "клиент"])
            if not has_outcome:
                score -= 0.15
                cautions.append("Freelance Outcome Gap: Описан процесс работы, а не конечное желанное состояние клиента.")
                audit_breakdown['freelance_outcome'] = False
            else:
                audit_breakdown['freelance_outcome'] = True

        # 9. WHINE GATEKEEPER (Анти-Нытье в Grounded Storytelling)
        # Отсекает уныние, жалобы и позицию жертвы без преодоления и пользы для клиента
        whine_markers = [
            "жалуемся", "жаловаться", "как всё плохо", "как все плохо",
            "руки опускаются", "дороги не чистят", "клиентов мало",
            "почему так тяжело", "несправедливо", "нет сил",
            "все бесит", "всё бесит", "все надоело", "всё надоело",
            "устали до смерти", "тяжелая доля", "тяжёлая доля",
            "никто не ценит", "мы устали", "одни проблемы"
        ]
        resolution_markers = [
            "справились", "успели", "для вас", "для гостей", "горячий", "готово", "ждем", "ждём",
            "решили", "преодолели", "качество", "свежий", "смогли", "победили",
            "рады", "результат", "зато", "сделали", "не зря", "получилось",
            "встречаем", "доставили", "работаем для", "ради вас", "ради вашего"
        ]
        found_whine = [w for w in whine_markers if w in text_lower]
        has_resolution = any(r in text_lower for r in resolution_markers)

        if found_whine and not has_resolution:
            score -= 0.25
            fatal_flaws.append(
                f"Whine Gatekeeper: Обнаружены жалобы и уныние ({found_whine}) без решения проблемы и ценности для клиента."
            )
            audit_breakdown['whine_gatekeeper'] = False
        else:
            audit_breakdown['whine_gatekeeper'] = True

        # 10. FEEDBACK LOOP NEGATIVE CONSTRAINTS (Continuous Learning Gatekeeper)
        if negative_constraints:
            for constraint in negative_constraints:
                failed_hook = constraint.get("failed_hook") or constraint.get("pattern") or constraint.get("text") or ""
                penalty = float(constraint.get("critic_penalty") or constraint.get("penalty") or 0.40)
                reason = constraint.get("reason") or "Провальный исторический паттерн с аномально низким ER."

                is_match = False
                if failed_hook and len(failed_hook.strip()) > 10:
                    hook_lower = failed_hook.strip().lower()
                    key_words = [w for w in re.findall(r'\b[а-яёa-z]{4,}\b', hook_lower) if len(w) > 3]
                    if len(key_words) >= 2:
                        matched_words = sum(1 for kw in key_words if kw in text_lower)
                        match_ratio = matched_words / float(len(key_words))
                        if match_ratio >= 0.50:  # 50% ключевых смысловых слов совпало
                            is_match = True
                    elif hook_lower in text_lower:
                        is_match = True

                if is_match:
                    fatal_flaws.append(
                        f"Feedback Negative Constraint: Обнаружен исторически неэффективный паттерн ('{failed_hook[:60]}...'). {reason}"
                    )
                    audit_breakdown['feedback_constraint'] = False
                    # Принудительное математическое пенализирование: final_score = score * penalty
                    score = score * penalty
                    cautions.append(
                        f"Запрещено использовать неэффективный паттерн: '{failed_hook[:60]}...' (штраф обратной связи -{int((1.0 - penalty) * 100)}%). Смените структуру хука."
                    )

        score = max(0.1, min(1.0, round(score, 2)))
        passed = score >= self.strictness

        if passed:
            verdict = 'APPROVED'
            synergy_msg = " [🔥 LOLLAPALOOZA SYNERGY ACTIVE]" if is_lollapalooza else ""
            criticism = f'Текст полностью прошел аудит качества для кластера [{cluster_spec["cluster_name"]}]: сильный хук, чистота лексики, фактурные детали и выдержанный ритм.{synergy_msg}'
            actionable_feedback = 'Готово к публикации.'
        else:
            verdict = 'REVISE_NEEDED'
            reasons = fatal_flaws + cautions
            criticism = f'Текст требует доработки ({cluster_spec["cluster_name"]}): {reasons[:2]}'
            feedback_parts = []
            
            # Добавление специализированного правила критики кластера
            if cluster_spec.get("critic_actionable_rule"):
                feedback_parts.append(cluster_spec["critic_actionable_rule"])
                
            if not audit_breakdown.get('whine_gatekeeper', True):
                feedback_parts.append('Устраните уныние и жалобы. Трудности должны подаваться исключительно как преодоленное препятствие ради безупречного качества для гостя.')

            if not audit_breakdown.get('feedback_constraint', True):
                feedback_parts.append('ПРИНУДИТЕЛЬНЫЙ ОТСЕВ: черновик повторяет исторически провальный паттерн аудитории. Полностью перепишите лид-зацеп.')
                
            if not audit_breakdown.get('lexicon_gatekeeper', True):
                feedback_parts.append('Удалите несоответствующий B2B-жаргон (KPI, ROI, оптимизация бюджета) из лайфстайл-поста.')
            if not audit_breakdown.get('semantic_bleed', True):
                feedback_parts.append('Устраните оксюморон: не продавайте софт и оптимизацию в посте про питомцев/еду/религию.')
            if not audit_breakdown.get('brand_voice', True):
                feedback_parts.append(f'Удалите штампы: {found_cliches}.')
            if not is_lollapalooza and len(detected_psychological_triggers) < 2:
                feedback_parts.append('Усильте конверсию: добавьте хотя бы 2 триггера Мангера (например, Скидка + Ограничение по времени или Отзывы).')
            actionable_feedback = ' '.join(feedback_parts) if feedback_parts else 'Улучшите структуру и естественность текста.'

        return {
            'passed': passed,
            'score': score,
            'verdict': verdict,
            'niche_cluster': cluster_enum.value,
            'cluster_name': cluster_spec["cluster_name"],
            'criticism': criticism,
            'actionable_feedback': actionable_feedback,
            'fatal_flaws': fatal_flaws,
            'cautions': cautions,
            'audit_breakdown': audit_breakdown,
            'munger_psychology': {
                'detected_triggers': detected_psychological_triggers,
                'triggers_count': len(detected_psychological_triggers),
                'is_lollapalooza': is_lollapalooza
            }
        }

