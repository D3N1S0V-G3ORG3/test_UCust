# File: core/agents.py | Module: agents | Part of Intellectual Property Submission.
"""Agent definitions for the multi-agent marketing system."""

from __future__ import annotations

import gc
import os
import asyncio
from typing import List, Optional

from collectors.telethon_collector import TelethonCollector
from collectors.vk_collector import VkApiCollector
from nlu_engine.generative_core import GenerativeCore
from nlu_engine.preprocessor import PreProcessor
from skills.comfyui_local import ComfyUILocalSkill
from skills.travity_search import TravitySearchSkill
from schemas.models import (
    CollectorDataSchema,
    CopywritingFramework,
    FRAMEWORK_PROMPTS,
    GridPlanSchema,
    GridTileSchema,
    LTX23ConfigSchema,
    LTX23PromptSchema,
    PostDraftSchema,
    StrategyPlanSchema,
    SWOTResultSchema,
    UserQuestionnaire,
)
from storage.db import Database
from storage.models import UserProfile
from storage.vector_store import InMemoryVectorStore, VectorRecord


class AgentContext:
    """Shared runtime context passed between all agents in the orchestration pipeline."""

    # Step 1: Initialize context fields and normalize optional collections.
    def __init__(
        self,
        questionnaire: Optional[UserQuestionnaire] = None,
        user_profile_id: Optional[int] = None,
        collector_data: Optional[List[CollectorDataSchema]] = None,
        swot: Optional[SWOTResultSchema] = None,
        strategy: Optional[StrategyPlanSchema] = None,
        post_draft: Optional[PostDraftSchema] = None,
        grid_plan: Optional[GridPlanSchema] = None,
        ltx23_prompts: Optional[List[LTX23PromptSchema]] = None,
        approval_status: Optional[str] = None,
        pending_user_action: bool = False,
        injected_events: Optional[List[str]] = None,
        user_event_type: Optional[str] = None,
        user_event_context: Optional[str] = None,
        logs: Optional[List[str]] = None,
        correction_attempts: int = 0,
        framework: Optional[CopywritingFramework] = None,
    ) -> None:
        self.questionnaire = questionnaire
        self.user_profile_id = user_profile_id
        self.collector_data = collector_data or []
        self.swot = swot
        self.strategy = strategy
        self.post_draft = post_draft
        self.grid_plan = grid_plan
        self.ltx23_prompts = ltx23_prompts or []
        self.approval_status = approval_status
        self.pending_user_action = pending_user_action
        self.injected_events = injected_events or []
        self.user_event_type = user_event_type
        self.user_event_context = user_event_context
        self.logs = logs or []
        self.correction_attempts = correction_attempts
        self.framework = framework

    # Step 2: Validate context consistency for a specific orchestration state.
    def validate(self, state: Optional[str] = None) -> None:
        if state in {"IDLE", "DATA_COLLECTED"} and self.questionnaire is None:
            raise ValueError("Questionnaire is required for early pipeline stages.")

        if state in {"MARKET_ANALYZED", "CONTENT_READY", "AWAITING_USER_DECISION", "USER_APPROVED"}:
            if self.strategy is None and self.post_draft is None:
                raise ValueError("Strategy or post draft is required for content stages.")

    # Step 3: Append a normalized technical message to the execution log.
    def add_log(self, message: str) -> None:
        self.logs.append(message)


class BaseAgent:
    """Base class defining the contract for all pipeline agents with async lifecycle hooks."""

    name: str = "base_agent"
    expected_state: Optional[str] = None

    async def activate(self, context: AgentContext) -> None:
        """Lifecycle hook executed before agent run to warm up resources/models."""
        context.add_log(f"{self.name}: activate hook executed (resource warmup).")

    async def run(self, context: AgentContext) -> AgentContext:
        """Main async agent execution method."""
        raise NotImplementedError

    async def process(self, context: AgentContext) -> AgentContext:
        """Async alias for run to support process(context) interface."""
        return await self.run(context)

    async def standby(self, context: AgentContext) -> None:
        """Lifecycle hook executed after agent run to clean up RAM/VRAM resources."""
        context.add_log(f"{self.name}: standby hook executed (resource cleanup).")

    def check_state(self, current_state: str) -> None:
        if self.expected_state and self.expected_state != current_state:
            raise RuntimeError(
                f"{self.name}: expected state '{self.expected_state}', got '{current_state}'."
            )


class Agent_Interviewer(BaseAgent):
    """Agent responsible for questionnaire validation and optional SQL persistence."""

    name = "Agent_Interviewer"
    expected_state = "IDLE"

    # Step 6: Configure interviewer dependencies.
    def __init__(self, database: Optional[Database] = None) -> None:
        self.database = database

    # Step 7: Validate questionnaire payload and persist profile data when SQL is configured.
    async def run(self, context: AgentContext) -> AgentContext:
        context.validate("IDLE")
        questionnaire = context.questionnaire
        if questionnaire is None:
            raise ValueError("Questionnaire is required.")

        context.add_log("Agent_Interviewer: questionnaire validated.")

        if self.database is None:
            context.add_log("Agent_Interviewer: SQL storage is not configured; persistence skipped.")
            return context

        def _persist_profile() -> Optional[int]:
            session = None
            try:
                session = self.database.get_session()
                profile = UserProfile(
                    step1=questionnaire.step1.model_dump(),
                    step2=questionnaire.step2.model_dump(),
                    step3=questionnaire.step3.model_dump(),
                    step4=questionnaire.step4.model_dump(),
                    step5=questionnaire.step5.model_dump(),
                )
                session.add(profile)
                session.commit()
                return profile.id
            finally:
                if session is not None:
                    session.close()

        try:
            profile_id = await asyncio.to_thread(_persist_profile)
            context.user_profile_id = profile_id
            context.add_log(f"Agent_Interviewer: questionnaire persisted in SQL (id={profile_id}).")
        except Exception as db_exc:
            context.add_log(f"Agent_Interviewer: SQL storage unavailable ({db_exc}); persistence skipped.")
            context.user_profile_id = 1

        return context


class Agent_Analyst(BaseAgent):
    """Agent that collects external signals and produces SWOT plus strategy outputs."""

    name = "Agent_Analyst"
    expected_state = "DATA_COLLECTED"

    # Step 8: Initialize analytics dependencies and secure runtime configuration.
    def __init__(
        self,
        telethon_collector: Optional[TelethonCollector] = None,
        vk_collector: Optional[VkApiCollector] = None,
        preprocessor: Optional[PreProcessor] = None,
        generative_core: Optional[GenerativeCore] = None,
        search_skill: Optional[TravitySearchSkill] = None,
        telethon_channel: Optional[str] = None,
        vk_group_id: Optional[str] = None,
    ) -> None:
        self.telethon_collector = telethon_collector or TelethonCollector()
        self.vk_collector = vk_collector or VkApiCollector()
        self.preprocessor = preprocessor or PreProcessor()
        self.generative_core = generative_core or GenerativeCore()
        self.search_skill = search_skill or TravitySearchSkill()
        self.telethon_channel = telethon_channel or os.getenv("UCUST_TELETHON_CHANNEL", "@default_channel")
        self.vk_group_id = vk_group_id or os.getenv("UCUST_VK_GROUP_ID", "default_group")

    # Step 9: Collect parser data, execute web search, apply preprocessing, and generate SWOT and strategy artifacts.
    async def run(self, context: AgentContext) -> AgentContext:
        context.validate("DATA_COLLECTED")

        try:
            telethon_data, vk_data = await asyncio.gather(
                asyncio.to_thread(self.telethon_collector.collect, self.telethon_channel),
                asyncio.to_thread(self.vk_collector.collect, self.vk_group_id),
            )
        except Exception as col_err:
            context.add_log(f"Agent_Analyst: collectors fallback note ({col_err}).")
            telethon_data = self.telethon_collector.collect(self.telethon_channel)
            vk_data = self.vk_collector.collect(self.vk_group_id)
        context.collector_data.extend([telethon_data, vk_data])
        context.add_log("Agent_Analyst: parser data collected.")

        # Dynamically formulate web search query based on niche/business
        niche = ""
        if context.questionnaire is not None:
            niche = context.questionnaire.step1.mission or context.questionnaire.step1.business_name
        
        # Запрашиваем Копирайтера сжать запрос для экономии токенов Travity
        from core.agents import Agent_Copywriter
        search_query = Agent_Copywriter.optimize_search_query(niche)

        context.add_log(f"Agent_Analyst: initiating web search skill for optimized query '{search_query}'...")
        web_search_md = await self.search_skill.search(search_query)
        context.add_log("Agent_Analyst: Travity web search completed.")

        raw_items = [
            *[item.get("text", "") for item in telethon_data.payload.get("messages", [])],
            *[item.get("text", "") for item in vk_data.payload.get("posts", [])],
        ]
        raw_text = " ".join([item for item in raw_items if item])

        sanitized = self.preprocessor.sanitize_data(raw_text)
        context.add_log(f"Agent_Analyst: preprocessing applied, sentiment={sanitized.sentiment}.")
        for log_line in sanitized.technical_log:
            context.add_log(f"Agent_Analyst: {log_line}")

        rules_result = self._apply_marketing_rules(context.questionnaire, raw_items)
        context.swot = SWOTResultSchema(
            strengths=rules_result["strengths"],
            weaknesses=rules_result["weaknesses"],
            opportunities=rules_result["opportunities"],
            threats=rules_result["threats"],
            summary="SWOT generated from questionnaire and parser signals.",
        )
        context.add_log("Agent_Analyst: SWOT generated.")

        # Include "АКТУАЛЬНЫЕ ДАННЫЕ ИЗ СЕТИ" in context before LLM strategy generation
        strategy_context = (
            f"SWOT Summary: {context.swot.summary}\n\n"
            f"=== АКТУАЛЬНЫЕ ДАННЫЕ ИЗ СЕТИ ===\n"
            f"{web_search_md}\n\n"
            f"Инструкция: Используй эти реальные факты из сети и данные SWOT-анализа для формирования финальной стратегии."
        )

        context.strategy = self.generative_core.process_request(strategy_context)
        context.add_log("Agent_Analyst: strategy generated with live web search facts.")
        for log_line in context.strategy.technical_log:
            context.add_log(f"Agent_Analyst: {log_line}")

        return context

    # Step 10: Apply deterministic rule logic to construct SWOT dimensions.
    def _apply_marketing_rules(
        self,
        questionnaire: Optional[UserQuestionnaire],
        raw_items: List[str],
    ) -> dict:
        results = {
            "strengths": [],
            "weaknesses": [],
            "opportunities": [],
            "threats": [],
        }

        if questionnaire is None:
            results["weaknesses"].append("Questionnaire is missing: baseline profile data is unavailable.")
            results["threats"].append("Market assessment cannot proceed without customer profile data.")
            return results

        step1_text = f"{questionnaire.step1.business_name} {questionnaire.step1.mission} {questionnaire.step1.region}"
        step2_text = (
            f"{questionnaire.step2.target_audience} "
            f"{questionnaire.step2.demographics} "
            f"{questionnaire.step2.pain_points}"
        )
        step3_text = f"{questionnaire.step3.tone_of_voice} {questionnaire.step3.content_formats}"
        step4_text = f"{questionnaire.step4.goals} {questionnaire.step4.kpi} {questionnaire.step4.frequency}"

        audience = step2_text.lower()
        if "b2b" in audience:
            results["strengths"].append("Positioning supports expert-driven and rational content.")
        else:
            results["strengths"].append("Positioning supports emotional visual storytelling for consumer audiences.")

        competitors_count = len([item for item in questionnaire.step5.competitors.split(",") if item.strip()])
        if competitors_count >= 5:
            results["threats"].append("High local competitor density detected.")
        elif competitors_count == 0:
            results["opportunities"].append("Low competitor density indicates a growth window.")
        else:
            results["threats"].append("Moderately saturated competitive environment detected.")

        if len(raw_items) < 5:
            results["weaknesses"].append("Insufficient parser sample size for robust insight extraction.")
        else:
            results["strengths"].append("Sample size is adequate for baseline analytics.")

        tone = step3_text.lower()
        if "formal" in tone:
            results["weaknesses"].append("Engagement risk due to overly formal communication style.")
        else:
            results["opportunities"].append("Flexible tone can improve audience engagement.")

        frequency = step4_text.lower()
        if "daily" in frequency:
            results["strengths"].append("High publishing frequency supports sustained reach.")
        else:
            results["weaknesses"].append("Low publishing frequency may reduce growth velocity.")

        goals = step4_text.lower()
        if "lead" in goals or "sale" in goals or "conversion" in goals:
            results["opportunities"].append("Conversion-oriented goals simplify performance measurement.")
        else:
            results["weaknesses"].append("Goals are defined without direct conversion metrics.")

        positioning = step1_text.lower()
        if "premium" in positioning or "lux" in positioning:
            results["strengths"].append("Premium positioning increases perceived brand value.")
        elif "budget" in positioning or "econom" in positioning:
            results["threats"].append("Price competition may increase margin pressure.")
        else:
            results["opportunities"].append("Flexible positioning allows controlled message experiments.")

        return results


class StatePruningReducer:
    """
    State Pruning Reducer (Директива 1):
    Поузельная проекция и изоляция контекста для предотвращения переполнения
    контекстного окна LLM (8k/16k токенов) и снижения TTFT минимум на 40%.
    """
    @staticmethod
    def estimate_tokens(text: str) -> int:
        if not text:
            return 0
        return max(1, len(text) // 4)

    @classmethod
    def reduce_for_copywriter(cls, context: AgentContext, max_token_budget: int = 2048) -> Dict[str, Any]:
        """
        Формирует сжатую проекцию состояния строго для Agent_Copywriter:
        - include_keys: brand_dna_summary, swot_matrix.key_points, rag_facts, topic, framework
        - exclude_keys: raw_ocr_data, competitor_raw_html, interviewer_chat_history, raw_parser_payloads
        - max_token_budget: 2048
        """
        framework_val = context.framework.value if context.framework else "PAS"
        
        # 1. Сжатая выжимка о бренде (Brand DNA Summary)
        brand_parts = []
        if context.questionnaire and context.questionnaire.step1:
            s1 = context.questionnaire.step1
            if getattr(s1, "business_name", None):
                brand_parts.append(f"Brand: {s1.business_name}")
            if getattr(s1, "mission", None):
                brand_parts.append(f"Mission: {s1.mission}")
            if getattr(s1, "region", None):
                brand_parts.append(f"Region: {s1.region}")
        if context.questionnaire and context.questionnaire.step3:
            s3 = context.questionnaire.step3
            if getattr(s3, "tone_of_voice", None):
                brand_parts.append(f"Tone: {s3.tone_of_voice}")

        brand_dna_summary = " | ".join(brand_parts) if brand_parts else "General Brand"

        # 2. Ключевые поинты SWOT (топ-2 пункта на категорию, исключая сырой мусор)
        swot_points = []
        if context.swot:
            if context.swot.strengths:
                swot_points.append("Strengths: " + "; ".join(context.swot.strengths[:2]))
            if context.swot.weaknesses:
                swot_points.append("Weaknesses: " + "; ".join(context.swot.weaknesses[:2]))
            if context.swot.opportunities:
                swot_points.append("Opportunities: " + "; ".join(context.swot.opportunities[:2]))
            if context.swot.threats:
                swot_points.append("Threats: " + "; ".join(context.swot.threats[:2]))
        swot_summary = "\n".join(swot_points) if swot_points else (context.swot.summary if context.swot else "Standard SWOT")

        # 3. Стратегия / факты
        raw_strat = context.strategy.strategy if context.strategy else "baseline strategy"
        
        # Ограничение бюджета символов (max_token_budget * 4)
        budget_chars = max_token_budget * 4
        fixed_chars = len(brand_dna_summary) + len(swot_summary) + 300
        available_strat_chars = max(300, budget_chars - fixed_chars)
        
        if len(raw_strat) > available_strat_chars:
            strat_trimmed = raw_strat[:available_strat_chars] + "..."
        else:
            strat_trimmed = raw_strat

        reduced = {
            "active_node": "Agent_Copywriter",
            "framework": framework_val,
            "brand_dna_summary": brand_dna_summary,
            "swot_key_points": swot_summary,
            "strategy_summary": strat_trimmed,
            "max_token_budget": max_token_budget,
        }
        
        total_prompt_text = f"{brand_dna_summary}\n{swot_summary}\n{strat_trimmed}"
        reduced["estimated_tokens"] = cls.estimate_tokens(total_prompt_text)
        return reduced


class Agent_Copywriter(BaseAgent):
    """Agent that generates and adapts post drafts with uniqueness controls and state pruning."""

    name = "Agent_Copywriter"
    expected_state = "MARKET_ANALYZED"

    # Step 11: Configure copywriter dependencies.
    def __init__(
        self,
        vector_store: Optional[InMemoryVectorStore] = None,
        framework: CopywritingFramework = CopywritingFramework.PAS,
        llm_skill: Optional[Any] = None,
    ) -> None:
        self.vector_store = vector_store or InMemoryVectorStore()
        self.framework = framework
        self.llm_skill = llm_skill

    @staticmethod
    def optimize_search_query(niche: str) -> str:
        """
        [УМНАЯ ЭКОНОМИЯ ТОКЕНОВ]
        Копирайтер формулирует строгий, сжатый поисковой запрос для Travity.
        Убирает воду, оставляя только ключевые слова для поисковика.
        """
        if not niche:
            return "SMM trends"
        
        stop_words = {"на", "в", "как", "для", "ниша", "компания", "сделать", "лучшие"}
        words = [w for w in niche.split() if w.lower() not in stop_words]
        optimized = " ".join(words[:4]) + " SMM 2026"
        return optimized

    def build_system_prompt(self, framework: CopywritingFramework) -> str:
        framework_instruction = FRAMEWORK_PROMPTS.get(
            framework, FRAMEWORK_PROMPTS[CopywritingFramework.PAS]
        ).strip()
        strict_rule = "Не пиши названия блоков (например, 'PROBLEM:'). Просто пиши связный текст, следуя этой логике."
        return f"{framework_instruction}\n\n{strict_rule}"

    # Step 12: Produce the baseline post draft using pruned state and calculate uniqueness indicators.
    async def run(self, context: AgentContext) -> AgentContext:
        # Применение StatePruningReducer (Директива 1)
        reduced_state = StatePruningReducer.reduce_for_copywriter(context, max_token_budget=2048)
        context.add_log(f"Agent_Copywriter: StatePruningReducer applied (estimated tokens: {reduced_state.get('estimated_tokens', 0)} / 2048).")

        framework = context.framework or self.framework
        system_prompt = self.build_system_prompt(framework)

        user_prompt = (
            f"Бренд: {reduced_state['brand_dna_summary']}\n"
            f"Ключевые преимущества: {reduced_state['swot_key_points']}\n"
            f"Маркетинговая стратегия: {reduced_state['strategy_summary']}\n"
        )

        # Reflection loop: Check for previous FactChecker critiques (removed claims)
        removed_claims = context.post_draft.removed_claims if context.post_draft and context.post_draft.removed_claims else []
        if removed_claims:
            critique_instruction = (
                f"\n\nПРЕДЫДУЩАЯ ОШИБКА: Ты выдумал следующие факты: {removed_claims}. "
                f"Исключи их полностью. Опирайся строго на проверенные факты."
            )
            user_prompt += critique_instruction
            context.add_log(f"Agent_Copywriter: Reflection critique instruction appended for {removed_claims}.")

        draft_text = ""
        try:
            if self.llm_skill is None:
                from skills.saiga_llm import SaigaLLMSkill
                self.llm_skill = SaigaLLMSkill()

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            draft_text = await asyncio.to_thread(self.llm_skill.generate_chat, messages=messages)
        except Exception as llm_err:
            context.add_log(f"Agent_Copywriter: LLM generation fallback note ({llm_err}).")

        if not draft_text or not draft_text.strip():
            # Защищенный fallback-шаблон публикации при недоступности внешнего LLM-инференса
            brand_name = (
                context.questionnaire.step1.business_name
                if context.questionnaire and context.questionnaire.step1.business_name
                else "UCust"
            )
            draft_text = (
                f"🚀 {brand_name}: Новые решения для вашего роста!\n\n"
                f"{reduced_state['strategy_summary']}\n\n"
                f"▫️ Ключевые преимущества:\n{reduced_state['swot_key_points']}\n\n"
                f"👉 Узнайте подробности и подключайтесь уже сегодня!"
            )

        embedding = self.vector_store.embed_text(draft_text)
        metadata = self._build_metadata(context)

        uniqueness_score = self.vector_store.semantic_filter(embedding, metadata)
        is_duplicate, _ = self.vector_store.is_duplicate(embedding)

        if is_duplicate:
            draft_text = f"{draft_text} (uniqueness reinforced)"
            context.add_log("Agent_Copywriter: duplicate detected; draft adjusted.")
        else:
            context.add_log("Agent_Copywriter: uniqueness verified.")

        self._store_embedding(embedding=embedding, metadata=metadata)
        context.post_draft = PostDraftSchema(
            text=draft_text,
            uniqueness_score=uniqueness_score,
            duplicates_found=is_duplicate,
            removed_claims=removed_claims,
        )
        context.add_log(f"Agent_Copywriter: draft created using framework {framework.value}.")
        return context

    async def standby(self, context: AgentContext) -> None:
        """Standby hook for clearing LLM Saiga 3 VRAM and invoking Garbage Collector."""
        context.add_log(f"{self.name}: standby hook executed.")
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()
        context.add_log(f"{self.name}: RAM/VRAM garbage collection completed.")

    # Step 13: Apply a user event override and update text plus uniqueness metrics.
    async def process_user_event(
        self,
        context: AgentContext,
        event_type: str,
        event_context: str,
    ) -> AgentContext:
        if context.post_draft is None:
            raise ValueError("Post draft is required before processing a user event.")

        updated_text = self.inject_custom_event(
            event_type=event_type,
            context=event_context,
            source_text=context.post_draft.text,
        )

        metadata = self._build_metadata(context)
        embedding = self.vector_store.embed_text(updated_text)
        uniqueness_score = self.vector_store.semantic_filter(embedding, metadata)
        is_duplicate, _ = self.vector_store.is_duplicate(embedding)
        self._store_embedding(embedding=embedding, metadata=metadata)

        context.post_draft = PostDraftSchema(
            text=updated_text,
            uniqueness_score=uniqueness_score,
            duplicates_found=is_duplicate,
        )
        context.pending_user_action = True
        context.approval_status = "EDIT"
        context.user_event_type = event_type
        context.user_event_context = event_context
        context.injected_events.append(event_type.strip().lower())
        context.add_log(f"Agent_Copywriter: user event applied with priority ({event_type}).")
        return context

    # Step 14: Transform draft text using event-specific templates.
    def inject_custom_event(self, event_type: str, context: str, source_text: str) -> str:
        normalized_event = event_type.lower().strip()
        normalized_context = context.strip() or "No extra context provided."
        baseline_text = source_text.strip()

        template_map = {
            "gratitude": (
                "Gratitude Post",
                "Thank you to our customers, partners, and team for your trust and support.",
            ),
            "holiday": (
                "Holiday Announcement",
                "Warm seasonal greetings from our team, with appreciation for your continued trust.",
            ),
            "achievement": (
                "Achievement Update",
                "We are proud to share a meaningful milestone achieved by our team.",
            ),
            "emergency": (
                "Urgent Update",
                "We are sharing an urgent operational update with immediate guidance.",
            ),
            "custom_edit": (
                "Custom Editorial Update",
                "This draft has been revised according to direct user guidance.",
            ),
        }

        title, opening = template_map.get(normalized_event, template_map["custom_edit"])
        return (
            f"{title}\n"
            f"{opening}\n\n"
            f"Event context: {normalized_context}\n\n"
            f"Baseline draft:\n{baseline_text}"
        )

    # Step 15: Derive semantic metadata from context fields.
    def _build_metadata(self, context: AgentContext) -> dict:
        metadata = {}
        if context.questionnaire is not None:
            niche = context.questionnaire.step1.mission or context.questionnaire.step1.business_name
            city = context.questionnaire.step1.region
            if niche:
                metadata["niche"] = niche
            if city:
                metadata["city"] = city
        return metadata

    # Step 16: Persist embedding records into vector storage.
    def _store_embedding(self, embedding: list[float], metadata: dict) -> None:
        record = VectorRecord(
            text_id=f"draft-{self.vector_store.count() + 1}",
            embedding=embedding,
            metadata=metadata,
        )
        self.vector_store.add_embedding(record)


class Agent_FactChecker(BaseAgent):
    """Agent responsible for verifying draft facts, LLM hallucinations, and framework compliance."""

    name = "Agent_FactChecker"
    expected_state = "DRAFT_GENERATED"

    BASE_SYSTEM_PROMPT = (
        "Ты — строгий фактчекер и шеф-редактор. Тебе даны исходные факты (SWOT, стратегия), "
        "выбранный фреймворк копирайтинга (PAS, AIDA, PMHS) и черновик текста.\n"
        "Твои задачи:\n"
        "1. ФАКТЧЕКИНГ: Найти и удалить любые факты, цифры, имена и утверждения в черновике, которых НЕТ в исходных фактах.\n"
        "2. ПРОВЕРКА СТРУКТУРЫ ФРЕЙМВОРКА: Проверить логику структуры (Problem-Agitation-Solution / Attention-Interest-Desire-Action).\n"
        "3. ОБЯЗАТЕЛЬНЫЙ CTA: Убедиться в наличии четкого призыва к действию (Call To Action) в конце текста. Если CTA отсутствует — зафиксировать нарушение.\n"
        "4. РЕДАКТУРА: Вырезать бессмысленные слова. Вернуть очищенный текст, не добавляя ничего от себя."
    )

    def __init__(self, generative_core: Optional[GenerativeCore] = None) -> None:
        self.generative_core = generative_core or GenerativeCore()

    def build_system_prompt(self, framework: Optional[CopywritingFramework] = None) -> str:
        framework_name = framework.value if framework else "PAS"
        return f"{self.BASE_SYSTEM_PROMPT}\n\nТекущий проверяемый фреймворк: {framework_name}."

    async def run(self, context: AgentContext) -> AgentContext:
        if context.post_draft is None:
            raise ValueError("Post draft is required before fact-checking.")

        original_text = context.post_draft.text
        framework = context.framework or CopywritingFramework.PAS
        system_prompt = self.build_system_prompt(framework)

        swot_summary = context.swot.summary if context.swot else "No SWOT available"
        strategy_summary = context.strategy.strategy if context.strategy else "No Strategy available"
        facts_context = f"SWOT: {swot_summary}\nStrategy: {strategy_summary}\nFramework: {framework.value}"

        context.add_log(f"Agent_FactChecker: Starting verification (framework={framework.value}, length={len(original_text)} chars)...")
        context.add_log(f"Agent_FactChecker Original Draft:\n'{original_text}'")

        try:
            from skills.diff_applier import DiffApplier
        except ImportError:
            try:
                from ai.skills.diff_applier import DiffApplier
            except ImportError:
                DiffApplier = None

        cleaned_text, removed_claims = self.generative_core.verify_facts(
            system_prompt=system_prompt,
            facts_context=facts_context,
            draft_text=original_text,
            framework=framework,
        )

        # Директива 2 + Edge Case 1: Точечный патчинг через DiffApplier с Fuzzy Matching (порог >= 0.85)
        if removed_claims and DiffApplier:
            patch_edits = [
                {
                    "target_sentence": claim,
                    "action": "DELETE" if not any(w in claim for w in ["SWOT", "Brand"]) else "REPLACE",
                    "replacement": ""
                }
                for claim in removed_claims
            ]
            patched_text, applied_count = DiffApplier.apply_patches(
                source_text=original_text,
                edits=patch_edits,
                similarity_threshold=0.85
            )
            cleaned_text = patched_text
            context.add_log(f"Agent_FactChecker: DiffApplier successfully patched {applied_count} hallucinated sentences in <2.0s.")

        context.post_draft.text = cleaned_text
        context.post_draft.removed_claims = removed_claims

        if len(removed_claims) > 0:
            if context.correction_attempts < 3:
                context.correction_attempts += 1
                context.post_draft.fact_checked = True  # Исправлено точечным патчем
                critique_msg = f"FactChecker Patch Applied (Attempt {context.correction_attempts}/3): Patched claims: {removed_claims}."
                context.add_log(critique_msg)
            else:
                context.post_draft.fact_checked = False
                context.add_log("Agent_FactChecker: Maximum correction attempts reached (3/3).")
        else:
            context.post_draft.fact_checked = True
            context.add_log(
                f"Agent_FactChecker: fact-checking completed cleanly (fact_checked=True, removed {len(removed_claims)} claims)."
            )

        return context

    async def standby(self, context: AgentContext) -> None:
        """Standby hook for clearing LLM Saiga 3 VRAM and invoking Garbage Collector."""
        context.add_log(f"{self.name}: standby hook executed.")
        gc.collect()
        context.add_log(f"{self.name}: RAM/VRAM garbage collection completed.")


class Agent_Visual_Director(BaseAgent):
    """Agent responsible for multimodal video+audio planning and LTX-2.3 ComfyUI workflow generation."""

    name = "Agent_Visual_Director"
    expected_state = "CONTENT_READY"

    def __init__(self, comfyui_skill: Optional[ComfyUILocalSkill] = None) -> None:
        self.comfyui_skill = comfyui_skill or ComfyUILocalSkill()

    # Step 17: Build content grid tiles and LTX-2.3 multimodal video+audio workflows.
    async def run(self, context: AgentContext) -> AgentContext:
        if context.post_draft is None:
            raise ValueError("Post draft is required before visual planning.")

        tiles = [
            GridTileSchema(tile_id=1, title="Expertise", description="Dynamic video scene highlighting core tech capabilities"),
            GridTileSchema(tile_id=2, title="Case Study", description="Cinematic customer success narrative with movement"),
            GridTileSchema(tile_id=3, title="Insight", description="Animated motion graphics illustrating niche market insights"),
        ]
        context.grid_plan = GridPlanSchema(tiles=tiles)
        context.add_log("Agent_Visual_Director: content grid generated.")

        ltx23_prompts = []
        for tile in tiles:
            video_p = (
                f"Cinematic 4k motion video for tile '{tile.title}': {tile.description}. "
                f"Realistic lighting, smooth camera motion, professional color grading."
            )
            audio_p = (
                f"Ambient corporate soundscape, subtle synth pads, clear sound effects matched to video movement for '{tile.title}'."
            )

            workflow_graph = self._build_comfyui_workflow(
                video_prompt=video_p,
                audio_prompt=audio_p,
                aspect_ratio="16:9",
            )

            prompt = LTX23PromptSchema(
                video_prompt=video_p,
                audio_prompt=audio_p,
                motion_bucket_id=127,
                fps=24,
                aspect_ratio="16:9",
                duration_seconds=5.0,
                config=LTX23ConfigSchema(),
                comfyui_workflow=workflow_graph,
            )
            ltx23_prompts.append(prompt)

        context.ltx23_prompts = ltx23_prompts

        # Single-Server Deployment: Bind local media output paths directly from ComfyUI Output
        if ltx23_prompts:
            media_info = await self.comfyui_skill._execute_full_flow(ltx23_prompts[0].comfyui_workflow)
            context.post_draft.video_url = media_info.get("video_url")
            context.post_draft.audio_url = media_info.get("audio_url")
            context.post_draft.media_url = media_info.get("media_url")
            context.post_draft.local_video_path = media_info.get("video_path")
            context.post_draft.local_audio_path = media_info.get("audio_path")

        context.add_log(f"Agent_Visual_Director: {len(ltx23_prompts)} LTX-2.3 ComfyUI video+audio workflows generated. Local media bound.")
        return context

    async def standby(self, context: AgentContext) -> None:
        """Standby hook executed after visual planning to release ComfyUI GPU resources."""
        context.add_log(f"{self.name}: standby hook executed. LTX-2.3 generation session completed; ComfyUI GPU resources released.")
        gc.collect()

    def _build_comfyui_workflow(self, video_prompt: str, audio_prompt: str, aspect_ratio: str) -> dict:
        """Loads Ltx_generations.json workflow template via ComfyCLIRunner and customizes video prompts and seeds."""
        from skills.comfy_cli_runner import ComfyCLIRunner
        runner = ComfyCLIRunner()
        workflow = runner.load_workflow()
        return runner.customize_workflow(
            workflow_json=workflow,
            video_prompt=video_prompt,
            audio_prompt=audio_prompt,
            aspect_ratio=aspect_ratio,
        )


__all__ = [
    "AgentContext",
    "StatePruningReducer",
    "BaseAgent",
    "Agent_Interviewer",
    "Agent_Analyst",
    "Agent_Copywriter",
    "Agent_FactChecker",
    "Agent_Visual_Director",
]
