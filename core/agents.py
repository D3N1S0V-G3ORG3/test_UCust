# File: core/agents.py | Module: agents | Part of Intellectual Property Submission.
"""Agent definitions for the multi-agent marketing system."""

from __future__ import annotations

import os
from typing import List, Optional

from collectors.telethon_collector import TelethonCollector
from collectors.vk_collector import VkApiCollector
from nlu_engine.generative_core import GenerativeCore
from nlu_engine.preprocessor import PreProcessor
from schemas.models import (
    CollectorDataSchema,
    GridPlanSchema,
    GridTileSchema,
    KandinskyPromptSchema,
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
        kandinsky_prompts: Optional[List[KandinskyPromptSchema]] = None,
        approval_status: Optional[str] = None,
        pending_user_action: bool = False,
        injected_events: Optional[List[str]] = None,
        user_event_type: Optional[str] = None,
        user_event_context: Optional[str] = None,
        logs: Optional[List[str]] = None,
    ) -> None:
        self.questionnaire = questionnaire
        self.user_profile_id = user_profile_id
        self.collector_data = collector_data or []
        self.swot = swot
        self.strategy = strategy
        self.post_draft = post_draft
        self.grid_plan = grid_plan
        self.kandinsky_prompts = kandinsky_prompts or []
        self.approval_status = approval_status
        self.pending_user_action = pending_user_action
        self.injected_events = injected_events or []
        self.user_event_type = user_event_type
        self.user_event_context = user_event_context
        self.logs = logs or []

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
    """Base class defining the contract for all pipeline agents."""

    name: str = "base_agent"
    expected_state: Optional[str] = None

    # Step 4: Execute a single agent stage and return an updated context.
    def run(self, context: AgentContext) -> AgentContext:
        raise NotImplementedError

    # Step 5: Validate that the incoming state matches the agent precondition.
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
    def run(self, context: AgentContext) -> AgentContext:
        context.validate("IDLE")
        questionnaire = context.questionnaire
        if questionnaire is None:
            raise ValueError("Questionnaire is required.")

        context.add_log("Agent_Interviewer: questionnaire validated.")

        if self.database is None:
            context.add_log("Agent_Interviewer: SQL storage is not configured; persistence skipped.")
            return context

        session = self.database.get_session()
        try:
            profile = UserProfile(
                step1=questionnaire.step1.model_dump(),
                step2=questionnaire.step2.model_dump(),
                step3=questionnaire.step3.model_dump(),
                step4=questionnaire.step4.model_dump(),
                step5=questionnaire.step5.model_dump(),
            )
            session.add(profile)
            session.commit()
            context.user_profile_id = profile.id
            context.add_log(f"Agent_Interviewer: questionnaire persisted in SQL (id={profile.id}).")
        finally:
            session.close()

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
        telethon_channel: Optional[str] = None,
        vk_group_id: Optional[str] = None,
    ) -> None:
        self.telethon_collector = telethon_collector or TelethonCollector()
        self.vk_collector = vk_collector or VkApiCollector()
        self.preprocessor = preprocessor or PreProcessor()
        self.generative_core = generative_core or GenerativeCore()
        self.telethon_channel = telethon_channel or os.getenv("UCUST_TELETHON_CHANNEL", "@default_channel")
        self.vk_group_id = vk_group_id or os.getenv("UCUST_VK_GROUP_ID", "default_group")

    # Step 9: Collect parser data, apply preprocessing, and generate SWOT and strategy artifacts.
    def run(self, context: AgentContext) -> AgentContext:
        context.validate("DATA_COLLECTED")

        telethon_data = self.telethon_collector.collect(self.telethon_channel)
        vk_data = self.vk_collector.collect(self.vk_group_id)
        context.collector_data.extend([telethon_data, vk_data])
        context.add_log("Agent_Analyst: parser data collected.")

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

        context.strategy = self.generative_core.process_request(context.swot.summary)
        context.add_log("Agent_Analyst: strategy generated.")
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


class Agent_Copywriter(BaseAgent):
    """Agent that generates and adapts post drafts with uniqueness controls."""

    name = "Agent_Copywriter"
    expected_state = "MARKET_ANALYZED"

    # Step 11: Configure copywriter dependencies.
    def __init__(self, vector_store: Optional[InMemoryVectorStore] = None) -> None:
        self.vector_store = vector_store or InMemoryVectorStore()

    # Step 12: Produce the baseline post draft and calculate uniqueness indicators.
    def run(self, context: AgentContext) -> AgentContext:
        strategy_text = context.strategy.strategy if context.strategy else "baseline strategy"
        draft_text = f"Post based on strategy: {strategy_text}"

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
        )
        context.add_log("Agent_Copywriter: draft created.")
        return context

    # Step 13: Apply a user event override and update text plus uniqueness metrics.
    def process_user_event(
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


class Agent_Visual_Director(BaseAgent):
    """Agent responsible for visual planning and prompt generation."""

    name = "Agent_Visual_Director"
    expected_state = "CONTENT_READY"

    # Step 17: Build content tiles and image-generation prompts.
    def run(self, context: AgentContext) -> AgentContext:
        if context.post_draft is None:
            raise ValueError("Post draft is required before visual planning.")

        tiles = [
            GridTileSchema(tile_id=1, title="Expertise", description="Post highlighting core capabilities"),
            GridTileSchema(tile_id=2, title="Case Study", description="Client success narrative"),
            GridTileSchema(tile_id=3, title="Insight", description="Market observation for the target niche"),
        ]
        context.grid_plan = GridPlanSchema(tiles=tiles)
        context.add_log("Agent_Visual_Director: content grid generated.")

        context.kandinsky_prompts = [
            KandinskyPromptSchema(
                prompt_text=f"Visual for tile '{tile.title}': {tile.description}",
                style="minimalist corporate",
                aspect_ratio="1:1",
            )
            for tile in tiles
        ]
        context.add_log("Agent_Visual_Director: image prompts generated.")
        return context


__all__ = [
    "AgentContext",
    "BaseAgent",
    "Agent_Interviewer",
    "Agent_Analyst",
    "Agent_Copywriter",
    "Agent_Visual_Director",
]
