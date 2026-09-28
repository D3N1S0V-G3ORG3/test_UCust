"""
File: ai/skills/content_generation_engine.py
Главный движок генерации контента для социальных сетей (UCust AI Core Generation Engine).
Связывает Clean RAG (pgvector), дедупликацию, Saiga LLM и ComfyUI Lazy Rendering.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from prompts.telegram_generation_prompt import TELEGRAM_EXPERT_PROMPT
from skills.rag_retriever_skill import CleanRAGRetrieverSkill
from skills.audit_deduplication_agent import AuditDeduplicationAgent
from skills.fact_checking_critic import FactCheckingCritic
from skills.geo_entity_resolver import GeoEntityResolver, SKUCard
from skills.autonomous_research_grounder import FactSheet
from core.lazy_rendering_controller import (
    PostDraft, PostLifecycleStatus, ContentFormat, ImageGenerationSpec, SubscriptionTier, IndustryArchetype, ShotIntent
)

logger = logging.getLogger("ContentGenerationEngine")


class ContentGenerationEngine:
    """
    Сквозной конвейер генерации постов:
    1. Семантический аудит и защита от повторов (Pre-Mortem Audit, threshold=0.82).
    2. Извлечение фактов из RAG с автоматическим Grounding-фоллбэком при UNKNOWN_ENTITY.
    3. Мгновенная 1-клик привязка FactSheet к выбранному SKU (Disambiguation Chips).
    4. Генерация текста в Saiga LLM с поддержкой разметки Telegram 7.2+ и Closed-Domain Grounding.
    5. Факт-чекинг критик и автокоррекция галлюцинаций (FactCheckingCritic).
    6. Сборка спецификации для отложенного рендера ComfyUI (0 GPU cost на этапе черновика).
    """

    def __init__(self, dev_mode: bool = True):
        self.dev_mode = dev_mode
        self.audit_agent = AuditDeduplicationAgent(custom_threshold=0.82)
        try:
            from core.llm_provider import SaigaLLMSkill
        except ImportError:
            try:
                from skills.saiga_llm import SaigaLLMSkill
            except ImportError:
                SaigaLLMSkill = None

        if SaigaLLMSkill:
            self.llm = SaigaLLMSkill()
        else:
            self.llm = None

    async def generate_post(
        self,
        project_id: str,
        topic: str,
        profile: Optional[Dict[str, Any]] = None,
        recent_posts: Optional[List[str]] = None,
        aspect_ratio: str = "1:1",
        target_channel: Optional[str] = None,
        sku_id: Optional[str] = None
    ) -> PostDraft:
        """
        Генерирует готовый пост в статусе DRAFT_TEXT с поддержкой мгновенной привязки SKU.
        """
        logger.info(f"✍️ [ContentGenerationEngine] Генерация поста для project_id='{project_id}', тема='{topic[:50]}', sku_id='{sku_id}'")
        profile = profile or {}
        about = profile.get("about", {})
        goals = profile.get("goals", {})
        
        company_name = about.get("name") or profile.get("company_name") or project_id
        niche = about.get("niche") or profile.get("niche") or "Бизнес и услуги"
        positioning = about.get("positioning") or profile.get("positioning") or f"Качественные решения от {company_name}"
        tov_list = goals.get("tone_of_voice") or profile.get("tone") or ["Экспертный", "Лаконичный", "Уверенный"]
        tov = ", ".join(tov_list) if isinstance(tov_list, list) else str(tov_list)
        content_goal = goals.get("content_goals", ["Вовлечение и продажа"])[0] if goals.get("content_goals") else "Вовлечение и продажи"

        # 1. Семантическая дедупликация (Pre-Mortem Audit)
        is_duplicate = False
        actual_topic = topic
        if recent_posts:
            verdict = self.audit_agent.evaluate_uniqueness(
                proposed_topic_or_text=topic,
                recent_channel_posts=recent_posts,
                topic_category=niche
            )
            if verdict.is_duplicate:
                is_duplicate = True
                actual_topic = verdict.suggested_shifted_angle or topic
                logger.info(f"🔄 [Deduplication] Обнаружен повтор темы. Смещение угла: '{actual_topic}'")

        # 2. Интерактивные чипы точного поиска SKU (Disambiguation Chips)
        resolved_chips = GeoEntityResolver.resolve_disambiguation_chips(actual_topic)
        selected_sku: Optional[SKUCard] = None

        if sku_id and resolved_chips:
            for chip in resolved_chips:
                if chip.sku_id == sku_id:
                    selected_sku = chip
                    break

        if selected_sku:
            # Мгновенная привязка FactSheet из верифицированной карточки SKU (0 сек задержки)
            fact_sheet = FactSheet(
                product_name=selected_sku.full_title,
                category=selected_sku.line_name,
                key_specs=selected_sku.key_specs,
                target_audience=selected_sku.hair_type,
                unverified_claims=selected_sku.unverified_claims,
                sources=["PIM Retail Database (magnitcosmetic.ru / goldapple.ru)"],
                color_marker=selected_sku.color_marker,
                is_verified=True
            )
            rag_facts = selected_sku.key_specs
            rag_context = "\n".join([f"- {spec}" for spec in selected_sku.key_specs])
            actual_topic = selected_sku.full_title
        else:
            # 2.1. Извлечение фактов: RAG + Автономный ресёрч при неизвестных сущностях
            rag_facts, fact_sheet = await CleanRAGRetrieverSkill.retrieve_with_grounding_fallback(
                project_id=project_id,
                query=actual_topic,
                niche=niche,
                top_k=3
            )
            if rag_facts:
                rag_context = "\n".join([f"- {fact}" for fact in rag_facts])
            else:
                rag_context = f"- {company_name}: специализируется на сфере '{niche}', ключевое УТП: {positioning}."

        # 3. Сборка системного и пользовательского промпта для Telegram 7.2+
        system_msg = TELEGRAM_EXPERT_PROMPT.format(
            tone_of_voice=tov,
            positioning=positioning,
            content_goal=content_goal,
            rag_context=rag_context
        )

        if fact_sheet and fact_sheet.is_grounded:
            system_msg += (
                f"\n\nСТАНДАРТ ЖЕСТКОГО ФАКТИЧЕСКОГО ЯКОРЕНИЯ:\n"
                f"{fact_sheet.to_prompt_block()}\n"
                "Правило: не выдумывай несуществующие цифры и технологии, отсутствующие в списке выше."
            )

        user_msg = f"Напиши публикацию для Telegram-канала компании '{company_name}' на тему: {actual_topic}"

        # 4. LLM Инференс
        post_text = ""
        if self.llm:
            try:
                if hasattr(self.llm, "generate_chat"):
                    messages = [
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": user_msg}
                    ]
                    post_text = self.llm.generate_chat(messages=messages, max_tokens=800)
                elif hasattr(self.llm, "generate_post"):
                    post_text = self.llm.generate_post(topic=actual_topic, niche=niche, company_name=company_name)
            except Exception as llm_err:
                logger.error(f"⚠️ Ошибка LLM инференса: {llm_err}")

        # Детерминированный фоллбэк при недоступности локальных весов
        if not post_text:
            post_text = (
                f"☕ <b>{actual_topic}</b> — ключевые стандарты и детали от {company_name}.\n\n"
                f"<blockquote expandable>\n"
                f"{rag_context}\n"
                f"</blockquote>\n\n"
                f"Каждый день мы совершенствуем процессы, чтобы вы получали безупречный результат.\n\n"
                f"👉 Подробнее по ссылке в описании профиля или напишите нам в личные сообщения."
            )

        # 4.1. Арбитражная проверка фактов и автокоррекция (FactCheckingCritic)
        critic_report = FactCheckingCritic.validate_and_autocorrect(
            text=post_text,
            fact_sheet=fact_sheet
        )
        post_text = critic_report.sanitized_text

        # 5. Двухфакторная матрица эстетики (Tenant Aesthetic ∩ Product Color) и классификация ShotIntent
        topic_lower = actual_topic.lower()
        tenant_aesthetic = (profile.get("aesthetic") or about.get("style") or "scandi_eco").lower()
        
        # Определение композиционного намерения кадра (ShotIntent)
        if any(w in topic_lower for w in ["в руках", "держит", "мастер наносит", "рука", "руки", "пальцы", "holding", "in hands"]):
            shot_intent = ShotIntent.IN_HANDS
        elif any(w in topic_lower for w in ["клиент", "модель", "девушка", "укладка", "прическа", "в кресле", "процесс"]):
            shot_intent = ShotIntent.LIFESTYLE_MODEL
        elif any(w in topic_lower for w in ["pov", "от первого лица", "вид от первого"]):
            shot_intent = ShotIntent.POV_USER
        else:
            shot_intent = ShotIntent.PRODUCT_ONLY

        # Двухфакторная палитра окружения
        color_marker = getattr(fact_sheet, "color_marker", "") if fact_sheet else ""
        if "loft" in tenant_aesthetic or "барбер" in niche.lower() or "dark" in tenant_aesthetic:
            surf_desc = "dark matte polished concrete or blackened industrial steel table"
            env_desc = "moody brutalist loft salon interior, exposed brick, dark slate surfaces"
            light_desc = "dramatic directional rim lighting with cool 4500K key light and deep atmospheric room shadows"
        elif "glam" in tenant_aesthetic or "luxury" in tenant_aesthetic or "премиум" in niche.lower():
            surf_desc = "white polished Calacatta marble countertop with subtle gold brass trim"
            env_desc = "luxurious modern beauty atelier, warm circular mirror glow, golden reflections"
            light_desc = "warm focused spotlight 3200K, soft ambient fill, elegant specular highlights"
        else:  # Default: scandi_eco / modern minimal
            surf_desc = "minimalist light Scandinavian oak vanity surface"
            env_desc = "airy sunlit modern salon interior with soft round mirrors and fresh botanical greenery in creamy bokeh"
            light_desc = "natural diffused morning window daylight 5000K, clean organic contact shadows"

        if shot_intent == ShotIntent.IN_HANDS:
            subject_action = f"female hairstylist hands in clean professional manicure holding the {actual_topic[:40]}"
        elif shot_intent == ShotIntent.LIFESTYLE_MODEL:
            subject_action = f"satisfied beauty salon client with styled glossy hair, {actual_topic[:40]} sitting on vanity"
        else:
            subject_action = f"commercial tabletop product shot of {actual_topic[:40]}"

        visual_prompt = (
            f"A commercial photograph of {subject_action}, resting on {surf_desc}. "
            f"Set in {env_desc}. Illuminated by {light_desc}. "
            f"Shot on 85mm f/1.8 prime lens, shallow depth of field, tactile micro-textures, authentic reflections, zero CGI."
        )

        dim_map = {
            "1:1": (1024, 1024),
            "4:5": (1080, 1350),
            "9:16": (1080, 1920),
            "16:9": (1920, 1080)
        }
        w, h = dim_map.get(aspect_ratio, (1024, 1024))

        image_spec = ImageGenerationSpec(
            prompt=visual_prompt,
            aspect_ratio=aspect_ratio,
            width=w,
            height=h,
            shot_intent=shot_intent,
            use_controlnet=False
        )

        # 6. Формирование PostDraft в статусе DRAFT_TEXT
        post_id = f"post_{uuid.uuid4().hex[:10]}"
        post_draft = PostDraft(
            post_id=post_id,
            brand_id=project_id,
            target_date=datetime.utcnow(),
            format=ContentFormat.SINGLE_SHOT,
            status=PostLifecycleStatus.DRAFT_TEXT,
            text_content=post_text,
            image_specs=[image_spec],
            rendered_image_urls=[],
            vram_cost_mb=0,
            selected_sku=selected_sku.model_dump() if selected_sku else None,
            disambiguation_chips=[c.model_dump() for c in resolved_chips]
        )

        return post_draft
