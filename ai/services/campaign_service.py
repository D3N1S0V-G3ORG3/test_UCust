"""
File: ai/services/campaign_service.py
Модуль оркестрации RAG, генерации контента (текст, визуал, опросы, контент-планы)
и контроля качества (OTK, Charlie Munger Critic, Fact-Checking).
Часть мультиагентной системы UCust AI (Фаза P1).
"""

from __future__ import annotations

import os
import time
import uuid
import asyncio
import logging
from typing import Any, Dict, List, Optional

from schemas.pipeline_state import PipelineState, ContentFormatEnum
from rag.models import Document

logger = logging.getLogger("CampaignService")


class CampaignService:
    """
    Сервис генерации контента и OTK аудита качества:
    - Контекстная RAG-маршрутизация и Pre-Flight оценка плотности данных (DRS)
    - Синтез маркетинговой структуры (Воронка Ханта, JTBD, психологические триггеры)
    - Генерация постов через локальную / облачную LLM (Saiga NeMo / OpenRouter)
    - Генерация инфоповодов, контент-планов и интерактивных опросов/квизов
    - Рендер визуала через ComfyUI GPU пайплайн (Realism 2.0 / LTX)
    - Аудит качества и самоисправление черновиков (Charlie Munger Critic 2.0 + Fact-Checking)
    """

    def __init__(
        self,
        rag_pipeline: Optional[Any] = None,
        db_session: Optional[Any] = None,
        redis_cache: Optional[Any] = None,
    ) -> None:
        self.rag = rag_pipeline
        self.db = db_session
        self.redis_cache = redis_cache

    async def generate_campaign(
        self,
        state: PipelineState,
        user_data: Optional[Dict[str, Any]] = None,
    ) -> PipelineState:
        """
        Главный конвейер генерации кампании (End-to-End Pipeline State):
        Принимает PipelineState с заполненным брендовым контекстом, генерирует контент,
        проводит аудит качества и возвращает обновленный state.
        """
        data = user_data or {}
        t_start = time.time()

        company_name = state.company_name or data.get("company_name", "UCust")
        niche = state.niche or data.get("niche", "бизнес")
        topic = state.topic or data.get("topic") or data.get("prompt") or "Новые возможности"
        tone = state.tone_of_voice or data.get("tone", "Естественный и живой")
        target_format = state.target_format

        # 1. Формат и опрос/квиз
        if target_format in {ContentFormatEnum.POLL, ContentFormatEnum.QUIZ}:
            poll_res = await self.generate_poll(
                topic=topic,
                company_name=company_name,
                niche=niche,
                is_quiz=(target_format == ContentFormatEnum.QUIZ),
            )
            raw_poll = poll_res.get("poll", poll_res)
            if hasattr(raw_poll, "model_dump"):
                poll_payload = raw_poll.model_dump()
            elif hasattr(raw_poll, "dict"):
                poll_payload = raw_poll.dict()
            elif isinstance(raw_poll, dict):
                poll_payload = raw_poll
            else:
                poll_payload = {"question": str(raw_poll)}

            state.poll_payload = poll_payload
            state.draft_text = poll_payload.get("intro_text") or poll_payload.get("question") or ""
            state.critic_score = 1.0
            state.fact_check_passed = True
            state.telemetry["generation_duration"] = round(time.time() - t_start, 2)
            return state

        # 2. Вызов полного процесса генерации поста (текст + визуал + OTK)
        post_input = {
            **data,
            "company_name": company_name,
            "niche": niche,
            "city": state.city or data.get("city", "Москва"),
            "prompt": topic,
            "tone": tone,
            "target_format": target_format.value,
            "attachments": state.attachments,
            "user_id": state.user_id,
        }
        res = await self.generate_post(post_input, session_id=state.session_id)

        # 3. Синхронизация полей PipelineState
        state.city = res.get("city") or post_input["city"]
        state.local_news_context = res.get("local_news_context", [])
        state.human_constraints = res.get("human_constraints", [])
        state.draft_text = res.get("clean_user_post_text") or res.get("post_text", "")
        if res.get("image_url") or res.get("photo_url"):
            photo_url = res.get("image_url") or res.get("photo_url")
            state.photo_paths = [photo_url]
        state.visual_prompt = res.get("photo_prompt", "")

        critic_data = res.get("critic_review") or {}
        state.critic_score = float(critic_data.get("score", 1.0))
        state.critic_flaws = critic_data.get("fatal_flaws") or critic_data.get("flaws", [])
        state.fact_check_passed = bool(critic_data.get("passed", True))

        state.telemetry["pipeline_duration"] = res.get("telemetry", {}).get("total_duration", round(time.time() - t_start, 2))
        return state

    async def generate_post(
        self,
        user_data: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Полноценный генеративный пайплайн для поста (соответствует API UnifiedOrchestrator).
        """
        t_pipeline_start = time.time()
        session_id = session_id or str(uuid.uuid4())

        company_name = user_data.get("company_name") or "UCust"
        niche = user_data.get("niche") or "бизнес"
        city = user_data.get("city") or "Москва"
        prompt = user_data.get("prompt") or user_data.get("topic") or "Новинки и возможности"
        tone = user_data.get("tone") or "Естественный и живой"
        offer = user_data.get("offer") or ""
        format_type = user_data.get("format_type") or user_data.get("target_format") or "post"

        aspect_ratio = user_data.get("aspect_ratio", "1:1")
        if not user_data.get("aspect_ratio"):
            fmt_lower = str(format_type).lower()
            if any(k in fmt_lower for k in ["story", "stories", "reels", "shorts", "клип", "истори"]):
                aspect_ratio = "9:16"
            elif any(k in fmt_lower for k in ["cover", "article", "youtube", "banner", "обложк", "стать"]):
                aspect_ratio = "16:9"

        # 1. Pre-Flight Context Router
        from skills.context_router import ContextRouterSkill
        router = ContextRouterSkill()
        routing_directive = router.route_task(
            topic=prompt,
            company_name=company_name,
            niche=niche,
            user_data=user_data,
        )
        tenant_id = routing_directive.tenant_id

        # 2. RAG-поиск с изоляцией тенанта
        rag_fact_context = None
        data_richness_score = 0.20
        proven_hooks_list: List[Dict[str, Any]] = []
        negative_constraints_list: List[Dict[str, Any]] = []

        if user_data.get("proven_hooks"):
            proven_hooks_list.extend(user_data["proven_hooks"])
        if user_data.get("negative_constraints"):
            negative_constraints_list.extend(user_data["negative_constraints"])

        if self.rag:
            try:
                from skills.data_richness_engine import DataRichnessEngine

                rag_query_text = f"{prompt} {niche} {company_name} {offer}"
                rag_ctx = await self.rag.query_async(rag_query_text, tenant_id=tenant_id)
                if rag_ctx and (rag_ctx.has_sufficient_context or rag_ctx.formatted_context):
                    rag_fact_context = rag_ctx.formatted_context
                    drs_assessment = DataRichnessEngine.evaluate_text(rag_fact_context, company_name=company_name)
                    data_richness_score = drs_assessment.total_score / 100.0

                # Динамическое извлечение инсайтов Continuous Learning из чанков RAG
                if rag_ctx and rag_ctx.chunks:
                    for chk in rag_ctx.chunks:
                        m = getattr(chk, "metadata", {}) or {}
                        m_type = m.get("type")
                        if m_type == "proven_hook":
                            proven_hooks_list.append({
                                "hook": m.get("hook") or chk.text,
                                "target_format": m.get("target_format"),
                                "score": m.get("score"),
                            })
                        elif m_type == "negative_constraint":
                            negative_constraints_list.append({
                                "failed_hook": m.get("failed_hook") or chk.text,
                                "penalty": m.get("penalty", 0.40),
                                "reason": m.get("reason", "Исторически неэффективный паттерн с низким ER"),
                            })
            except Exception as r_err:
                logger.warning(f"[CampaignService] Ошибка RAG query: {r_err}")

        # 3. Маркетинговые директивы (Воронка Ханта, Триггеры, JTBD)
        from skills.marketing_frameworks import (
            MarketingFrameworkDirector, HuntStage, MarketingFramework, PsychologicalTrigger
        )
        raw_stage = user_data.get("hunt_stage") or user_data.get("stage")
        hunt_stage_enum = HuntStage(raw_stage) if raw_stage in [s.value for s in HuntStage] else HuntStage.STAGE_2_PROBLEM_AWARE
        stage_strategy = MarketingFrameworkDirector.HUNT_STAGE_STRATEGIES[hunt_stage_enum]

        raw_fw = user_data.get("framework")
        framework_enum = MarketingFramework(raw_fw) if raw_fw in [f.value for f in MarketingFramework] else stage_strategy["framework"]

        raw_trigger = user_data.get("trigger")
        trigger_enum = PsychologicalTrigger(raw_trigger) if raw_trigger in [t.value for t in PsychologicalTrigger] else stage_strategy["trigger"]

        marketing_bundle = MarketingFrameworkDirector.construct_marketing_prompt(
            company_name=company_name,
            niche=niche,
            topic=prompt,
            framework=framework_enum,
            hunt_stage=hunt_stage_enum,
            trigger=trigger_enum,
            pain_points=user_data.get("pain_points") or [f"неэффективность и переплаты в нише {niche}"],
            raw_feature=prompt,
        )

        # 4. Cinematography Director (Арт-директор визуала)
        from skills.photo_generator import CinematographyDirector
        variation_index = int(user_data.get("variation_index", 0))
        brand_colors_input = user_data.get("brand_colors")

        cinematic_concept = CinematographyDirector.compose_cinematic_prompt(
            topic=prompt,
            niche=niche,
            brand_colors=brand_colors_input,
            variation_index=variation_index,
            routing=routing_directive,
            brand_props=user_data.get("brand_props") or user_data.get("visual_anchors"),
            brand_profile=user_data.get("brand_profile"),
        )
        visual_scene_context_for_saiga = (
            f"Ключевой визуальный сюжет фотосессии: {cinematic_concept.get('prompt', '')[:250]}. "
            f"Опирайся на этот визуал, чтобы текст поста гармонировал с кадром."
        )

        # 4.5. JIT Hyper-Local Context Grounding (Graceful degradation with Circuit Breaker & Strict 2.0s SLA)
        from skills.local_context_grounder import LocalContextGrounder
        grounder = LocalContextGrounder(io_timeout=1.2, total_sla_timeout=2.0)
        local_grounding = await grounder.ground_context(
            city=city,
            niche=niche,
            company_name=company_name
        )
        local_news_context = user_data.get("local_news_context") or local_grounding.local_news_context
        human_constraints = user_data.get("human_constraints") or local_grounding.human_constraints

        # 5. Параллельные генеративные задачи: Текст + Фото
        from skills.saiga_llm import SaigaLLMSkill
        saiga = SaigaLLMSkill()
        should_gen_image = user_data.get("generate_image", True)

        async def _generate_text_task():
            t_t_start = time.time()
            gen_res = saiga.generate_smm_post(
                topic=prompt,
                company_name=company_name,
                niche=niche,
                city=city,
                tone=tone,
                format_type=format_type,
                visual_context=visual_scene_context_for_saiga,
                rag_context=rag_fact_context,
                marketing_directive=marketing_bundle,
                routing=routing_directive,
                proven_hooks=proven_hooks_list,
                local_news_context=local_news_context,
                human_constraints=human_constraints,
            )
            p_text = gen_res.get("post_text", "")

            # OTK Проверка (Charlie Munger Critic 2.0 с штрафами за неэффективные паттерны)
            from skills.critic_munger import CriticMungerSkill
            critic = CriticMungerSkill(strictness=0.80)
            critic_res = critic.review_content(
                p_text,
                topic=prompt,
                target_audience=niche,
                routing=routing_directive,
                niche=niche,
                negative_constraints=negative_constraints_list,
            )

            if not critic_res.get("passed"):
                # 1 итерация самоисправления
                p_text = saiga.self_heal_text(p_text, critic_res.get("actionable_feedback", ""), routing=routing_directive)
                critic_res = critic.review_content(
                    p_text,
                    topic=prompt,
                    target_audience=niche,
                    routing=routing_directive,
                    niche=niche,
                    negative_constraints=negative_constraints_list,
                )

            return {
                "gen_result": gen_res,
                "post_text": p_text,
                "critic_res": critic_res,
                "duration": round(time.time() - t_t_start, 2),
            }

        async def _generate_photo_task():
            if not should_gen_image:
                return None
            from skills.photo_generator import PhotoGeneratorSkill
            photo_skill = PhotoGeneratorSkill()
            t_p_start = time.time()
            photo_res = await photo_skill.generate_photo(
                topic=prompt,
                niche=niche,
                aspect_ratio=aspect_ratio,
                company_name=company_name,
                brand_colors=brand_colors_input,
                attachments=user_data.get("attachments"),
                variation_index=variation_index,
                routing=routing_directive,
            )
            return {
                "image_url": photo_res.get("url"),
                "photo_prompt": photo_res.get("prompt", ""),
                "photo_res": photo_res,
                "duration": round(time.time() - t_p_start, 2),
            }

        text_result, photo_result = await asyncio.gather(_generate_text_task(), _generate_photo_task())

        gen_result = text_result["gen_result"]
        post_text = text_result["post_text"]
        critic_res = text_result["critic_res"]

        # Сохранение фото-промпта в RAG (если было фото)
        if photo_result and photo_result.get("photo_prompt") and self.rag:
            try:
                p_doc = Document(
                    doc_id=f"visual_prompt_{uuid.uuid4().hex[:8]}",
                    text=f"Промпт ComfyUI для {company_name}: {photo_result['photo_prompt']}",
                    metadata={"category": "photo_generation_history", "company_name": company_name},
                )
                await self.rag.ingest_documents_async([p_doc])
            except Exception as p_rag_e:
                logger.debug(f"[CampaignService] Заметка RAG photo prompt: {p_rag_e}")

        # Очистка служебных хэштегов из текста для пользователя
        clean_user_post_text = "\n".join([
            line for line in post_text.strip().splitlines()
            if not line.strip().startswith("#") and not line.strip().startswith("🏷️ Хэштеги")
        ]).strip()

        # Финальная санитарная обработка (удаление каркасов PAS/AIDA, нормализация брендов, буллетов и CTA)
        clean_user_post_text = SaigaLLMSkill._sanitize_llm_post(clean_user_post_text, company_name=company_name, niche=niche)

        # Форматирование для Telegram (Rich Post Formatter)
        from skills.telegram_rich_formatter import TelegramRichPostFormatter
        rich_tg = TelegramRichPostFormatter.build_rich_telegram_post(
            text=clean_user_post_text,
            company_name=company_name,
            niche=niche,
            promo_code=user_data.get("promo_code") or gen_result.get("promo_code"),
            website_url=user_data.get("target_action_link") or user_data.get("website_url"),
        )

        total_duration = round(time.time() - t_pipeline_start, 2)
        return {
            "status": "success",
            "task_type": "generate_post",
            "session_id": session_id,
            "company_name": company_name,
            "niche": niche,
            "post_text": clean_user_post_text,
            "clean_user_post_text": clean_user_post_text,
            "html_text": rich_tg["html_text"],
            "markdown_v2_text": rich_tg["markdown_v2_text"],
            "image_url": photo_result.get("image_url") if photo_result else None,
            "photo_prompt": photo_result.get("photo_prompt", "") if photo_result else "",
            "critic_review": critic_res,
            "routing": routing_directive.dict() if hasattr(routing_directive, "dict") else {},
            "city": city,
            "local_news_context": local_news_context,
            "human_constraints": human_constraints,
            "local_grounding": local_grounding.dict() if hasattr(local_grounding, "dict") else {},
            "telemetry": {
                "total_duration": total_duration,
                "text_duration": text_result["duration"],
                "photo_duration": photo_result.get("duration", 0.0) if photo_result else 0.0,
            },
        }

    async def plan_content(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """Генерация стратегического контент-плана."""
        from skills.content_strategy_engine import ContentStrategyEngine

        strat_engine = ContentStrategyEngine()
        company_name = user_data.get("company_name", "UCust")
        niche = user_data.get("niche", "IT Automation")
        city = user_data.get("city", "Москва")
        country = user_data.get("country", "Россия")

        rag_insights = None
        if self.rag:
            try:
                rag_query_res = await self.rag.query_async(f"боли страхи возражения {company_name} {niche} {city}")
                if rag_query_res and rag_query_res.chunks:
                    rag_insights = {
                        "pain_points": [c.text[:80] for c in rag_query_res.chunks],
                        "context": rag_query_res.formatted_context,
                    }
            except Exception as e:
                logger.warning(f"[CampaignService] RAG plan insights error: {e}")

        plan = strat_engine.generate_30day_content_plan(
            company_name=company_name,
            niche=niche,
            city=city,
            country=country,
            rag_insights=rag_insights,
            user_data=user_data,
        )
        return {
            "status": "success",
            "task_type": "plan_content",
            "company_name": company_name,
            "niche": niche,
            "content_plan": plan,
        }

    async def generate_poll(
        self,
        topic: str,
        company_name: str = "UCust",
        niche: str = "бизнес",
        is_quiz: bool = False,
    ) -> Dict[str, Any]:
        """Генерация вовлекающего опроса или квиза."""
        from skills.poll_generator import PollGeneratorSkill

        skill = PollGeneratorSkill()
        poll_res = skill.generate_poll(
            topic=topic,
            company_name=company_name,
            niche=niche,
            is_quiz=is_quiz,
        )
        return {
            "status": "success",
            "task_type": "generate_poll",
            "poll": poll_res,
        }

    async def review_content(
        self,
        text: str,
        topic: str = "",
        target_audience: str = "",
        niche: str = "",
    ) -> Dict[str, Any]:
        """Автономная OTK проверка контента через CriticMungerSkill."""
        from skills.critic_munger import CriticMungerSkill

        critic = CriticMungerSkill(strictness=0.80)
        res = critic.review_content(text=text, topic=topic, target_audience=target_audience, niche=niche)
        return {
            "status": "success",
            "task_type": "critic_review",
            "critic_review": res,
            "passed": res.get("passed", False),
            "score": res.get("score", 0.0),
        }

    async def get_ideas(
        self,
        niche: str,
        count: int = 5,
        company_name: str = "",
        country: str = "россия",
        days_ahead: int = 21,
        task_type: str = "get_idea_bank",
    ) -> Dict[str, Any]:
        """Генерация идей и плейсхолдеров из SmartIdeaBank."""
        from skills.smart_idea_bank import SmartIdeaBank

        bank = SmartIdeaBank()
        ideas = bank.suggest_top_ideas(
            niche=niche,
            limit=count,
            company_name=company_name,
            country=country,
            days_ahead=days_ahead,
        )
        placeholders = bank.get_dynamic_placeholders(
            niche=niche,
            company_name=company_name,
            limit=count,
        )
        return {
            "status": "success",
            "task_type": task_type,
            "niche": niche,
            "company_name": company_name,
            "ideas_count": len(ideas),
            "ideas": ideas,
            "placeholders": [p.dict() for p in placeholders],
        }
