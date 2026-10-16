"""
File: ai/core/orchestrator.py
Архитектурный фасад мультиагентной системы UCust AI (Pipeline Orchestrator Facade).
Декомпозирован на доменные сервисы: BrandService, CampaignService, PublishingService (Фаза P1).
"""

from __future__ import annotations

import os
import sys
import re
import uuid
import json
import time
import hashlib
import asyncio
import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

logger = logging.getLogger("PipelineOrchestratorFacade")


from storage.models import UserProfile, OrchestratorTrace, PublicationHistory, ProjectMetadata, ContentTask
from schemas.pipeline_state import PipelineState, ContentFormatEnum
from services.brand_service import BrandService
from services.campaign_service import CampaignService
from services.publishing_service import PublishingService
from rag.models import Document


class SecurityGuard:
    """
    Модуль безопасности. Защищает от Prompt Injection, джейлбрейков,
    утечек коммерческой тайны и персональных данных (DLP).
    """

    FORBIDDEN_KEYWORDS = [
        "select *", "drop table", "ignore previous instructions", "забудь все",
        "dump database", "выведи базу", "покажи все профили", "пароли",
        "system prompt", "ты теперь", "print db", "ignore above"
    ]

    HARMFUL_AND_OFFENSIVE_TERMS = [
        "гитлер", "нацизм", "фашизм", "расизм", "экстремизм", "терроризм",
        "свастик", "геноцид", "наркотик", "порно", "инцест", "самоубийств"
    ]

    TONE_STOPWORDS = [
        "безумно", "потрясающе", "волшебный", "сказочный",
        "крушить барьеры", "руинах обыденности", "сверхъестественн",
        "пушка", "бомба", "выстрел в мир", "держись крепче"
    ]

    PROTECTED_IP_TERMS = [
        "ltx", "ltx-video", "ltxv", "saiga", "moondream", "comfyui", "safetensors",
        "lora", "clip", "latent", "cfg", "emptyllatent", "checkpoint", "vlm",
        "gemma", "sdxl", "flux", "unipc", "karras", "sampler", "vae", "controlnet",
        "qwen", "qwen_image", "qwen_2.5_vl", "famegrid", "realskinfix", "auraflow",
        "clownshark", "emptysd3latent", "unetloader", "cliploader", "vaedecodetiled"
    ]

    @classmethod
    def sanitize_public_text(cls, text: str) -> str:
        """Защита коммерческой тайны: маскирует упоминания внутренних весов и нод."""
        if not text:
            return ""
        clean = text
        for term in cls.PROTECTED_IP_TERMS:
            pattern = re.compile(rf'\b{re.escape(term)}\b', re.IGNORECASE)
            clean = pattern.sub("UCust AI Engine", clean)
        return clean

    @classmethod
    def check_user_input(cls, user_text: str) -> bool:
        """Проверяет ввод пользователя на попытки взлома, инъекций и токсичный контент."""
        if not user_text:
            return True

        try:
            from skills.political_legal_guard import PoliticalAndLegalGuard
            is_safe, reason = PoliticalAndLegalGuard.validate_content(user_text)
            if not is_safe:
                print(f"[SecurityGuard] 🚨 ОТКЛОНЕНО СИСТЕМОЙ БЕЗОПАСНОСТИ: {reason}!")
                return False
        except Exception:
            pass

        text_lower = user_text.lower()
        for kw in cls.FORBIDDEN_KEYWORDS:
            if kw in text_lower:
                print(f"[SecurityGuard] 🚨 ОБНАРУЖЕНА ПОПЫТКА ВЗЛОМА: '{kw}'!")
                return False

        for hw in cls.HARMFUL_AND_OFFENSIVE_TERMS:
            if hw in text_lower:
                print(f"[SecurityGuard] 🚨 ОБНАРУЖЕН ЗАПРЕЩЕННЫЙ КОНТЕНТ: '{hw}'!")
                return False
        return True

    @classmethod
    def validate_content_tone_of_voice(
        cls,
        content_text: str,
        custom_forbidden_words: Optional[List[str]] = None,
    ) -> tuple[bool, Optional[str]]:
        """Tone-of-Voice Gatekeeper: отсекает стоп-слова и нарушение редполитики."""
        if not content_text:
            return True, None

        content_lower = content_text.lower()
        for word in cls.TONE_STOPWORDS:
            if word in content_lower:
                return False, f"Нарушение гайдлайнов качества: обнаружено запрещенное выражение '{word}'"

        if custom_forbidden_words:
            for c_word in custom_forbidden_words:
                if c_word and c_word.lower() in content_lower:
                    return False, f"Нарушение редполитики бренда: запрещено использовать слово '{c_word}'"

        return True, None

    @classmethod
    def sanitize_graph_data(cls, raw_data: List[Dict]) -> List[Dict]:
        """Очищает данные перед отправкой на фронтенд для отрисовки графиков."""
        return [{"metric_name": item.get("niche", "Unknown"), "value": item.get("count", 0)} for item in raw_data]


class PipelineOrchestratorFacade:
    """
    Тонкий фасад конвейера мультиагентной системы (Pipeline State Machine).
    Координирует работу специализированных доменных сервисов:
    - BrandService (сбор данных, парсеры, Brand DNA)
    - CampaignService (RAG, генерация контента, OTK валидация)
    - PublishingService (адаптация под платформы, доставка, трекинг)
    """

    def __init__(
        self,
        db_session: Optional[Any] = None,
        vector_store: Optional[Any] = None,
        redis_cache: Optional[Any] = None,
        rag_pipeline: Optional[Any] = None,
    ) -> None:
        from storage.pgvector_store import PGVectorStore
        from core.redis_cache import RedisCacheManager
        from rag.pipeline import CleanRAGPipeline

        self.db = db_session
        self.vector_store = vector_store or (PGVectorStore(self.db) if self.db else None)
        self.redis_cache = redis_cache or RedisCacheManager()
        self.rag = rag_pipeline or CleanRAGPipeline(min_confidence_threshold=0.55)

        # Dependency Injection доменных сервисов
        self.brand_service = BrandService(self.db, self.redis_cache, self.rag)
        self.campaign_service = CampaignService(self.rag, self.db, self.redis_cache)
        self.publishing_service = PublishingService(self.db, self.redis_cache, self.rag)

        # Фоновый контроль файловой ретенции (Non-blocking worker)
        def _run_media_retention_cleanup():
            try:
                from storage.media_retention import MediaRetentionManager
                cleaner = MediaRetentionManager()
                cleaner.cleanup_expired_files(
                    retention_days=int(os.getenv("MEDIA_RETENTION_DAYS", "30")),
                    temp_cache_retention_hours=float(os.getenv("TEMP_CACHE_RETENTION_HOURS", "5.0")),
                    archive_generations=os.getenv("MEDIA_AUTO_ARCHIVE", "true").lower() == "true",
                )
            except Exception:
                pass

        threading.Thread(target=_run_media_retention_cleanup, daemon=True, name="MediaRetentionWorker").start()

        # Инициализация внутреннего календаря
        try:
            from core.internal_calendar import InternalCalendarEngine
            InternalCalendarEngine.get_instance().refresh()
        except Exception:
            try:
                from ai.core.internal_calendar import InternalCalendarEngine
                InternalCalendarEngine.get_instance().refresh()
            except Exception:
                pass

    def _hash_payload(self, payload: Any) -> str:
        payload_str = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload_str.encode('utf-8')).hexdigest()

    def _log_trace(self, session_id: str, agent_name: str, action: str, payload: Any):
        """Неблокирующая фиксация трейса сессии в БД и Redis через пул потоков."""
        payload_hash = self._hash_payload(payload)

        def _persist_trace_sync():
            if self.db:
                try:
                    trace = OrchestratorTrace(
                        session_id=session_id,
                        agent_name=agent_name,
                        action=action,
                        payload_hash=payload_hash,
                        payload=payload if isinstance(payload, dict) else {"data": payload}
                    )
                    self.db.add(trace)
                    self.db.commit()
                except Exception as e:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass
                    print(f"[PipelineFacade] ⚠️ Ошибка сохранения трейса в БД: {e}")

            try:
                self.redis_cache.set_cached_result(action, payload_hash, payload)
            except Exception as r_err:
                print(f"[PipelineFacade] ⚠️ Ошибка сохранения трейса в Redis: {r_err}")

        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _persist_trace_sync)
        except RuntimeError:
            _persist_trace_sync()

    async def _emit_event(
        self,
        session_id: str,
        event_type: str,
        stage: str,
        progress_pct: int,
        message: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Безопасная публикация события этапа конвейера в распределенную шину SSE."""
        if not session_id:
            return
        try:
            try:
                from api.streaming import global_event_bus, PipelineEvent
            except ImportError:
                from ai.api.streaming import global_event_bus, PipelineEvent
            event = PipelineEvent(
                event_type=event_type,
                session_id=session_id,
                stage=stage,
                progress_pct=progress_pct,
                message=message,
                payload=payload or {},
            )
            await global_event_bus.publish_event(event)
        except Exception as e:
            logger.debug(f"[PipelineFacade] Не удалось опубликовать SSE событие: {e}")

    async def execute_pipeline(
        self,
        state: PipelineState,
        user_data: Optional[Dict[str, Any]] = None,
        auto_publish: bool = False,
    ) -> PipelineState:
        """
        Сквозной конвейер состояний Pipeline State Graph.
        Включает расчет метрик телеметрии (длительность этапов, токены, расчет стоимости $),
        трансляцию этапов в реальном времени через Server-Sent Events (SSE)
        и структурированное JSON-логирование для ELK / Grafana Loki.
        """
        start_time = time.time()
        try:
            # 1. Этап Brand DNA (извлечение ДНК бренда и контекста)
            await self._emit_event(
                state.session_id,
                "step_started",
                "brand_dna",
                10,
                "Извлечение ДНК бренда, парсинг профиля и анализ артефактов...",
            )
            state = await self.brand_service.process_brand(state, user_data=user_data)
            await self._emit_event(
                state.session_id,
                "step_completed",
                "brand_dna",
                30,
                "ДНК бренда успешно обработан и зафиксирован",
                {"brand_dna": state.brand_dna},
            )

            # 2. Этап RAG & Campaign Service (генерация черновика и визуала)
            await self._emit_event(
                state.session_id,
                "step_started",
                "content_draft",
                40,
                "Синтез структуры контента, RAG-маршрутизация и инференс Saiga LLM...",
            )
            state = await self.campaign_service.generate_campaign(state, user_data=user_data)
            await self._emit_event(
                state.session_id,
                "step_completed",
                "content_draft",
                75,
                "Черновик контента и визуал успешно сформированы",
                {
                    "critic_score": state.critic_score,
                    "fact_check_passed": state.fact_check_passed,
                },
            )

            # 3. Этап OTK контроля качества (Charlie Munger Critic)
            await self._emit_event(
                state.session_id,
                "step_started",
                "critic_review",
                80,
                "Аудит качества контента и проверка фактов (Charlie Munger Critic)...",
            )
            await self._emit_event(
                state.session_id,
                "step_completed",
                "critic_review",
                90,
                f"OTK аудит качества завершен (оценка: {state.critic_score})",
            )

            if auto_publish:
                # 4. Этап публикации
                await self._emit_event(
                    state.session_id,
                    "step_started",
                    "publishing",
                    92,
                    "Автоматическая публикация в подключенные каналы...",
                )
                state = await self.publishing_service.publish(state, user_data=user_data)
                await self._emit_event(
                    state.session_id,
                    "step_completed",
                    "publishing",
                    98,
                    "Контент успешно опубликован",
                    {
                        "is_published": state.is_published,
                        "published_urls": state.published_urls,
                    },
                )

            await self._emit_event(
                state.session_id,
                "pipeline_finished",
                "publishing" if auto_publish else "critic_review",
                100,
                "Мультиагентный конвейер успешно завершен",
                {
                    "critic_score": state.critic_score,
                    "draft_length": len(state.draft_text or ""),
                },
            )

            duration = time.time() - start_time
            state.telemetry["total_pipeline_duration"] = round(duration, 3)

            # Оценка потребления токенов и стоимости инференса ($0.000002 / token)
            prompt_chars = len(str(user_data or {})) + len(state.topic or "") + len(state.rag_facts or []) * 50
            completion_chars = len(state.draft_text or "")
            prompt_tokens = max(1, prompt_chars // 3)

            completion_tokens = max(1, completion_chars // 3)
            total_tokens = prompt_tokens + completion_tokens
            cost_usd = round(total_tokens * 0.000002, 6)

            token_data = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
            state.telemetry["token_consumption"] = token_data
            state.telemetry["cost_usd"] = cost_usd

            # Structured JSON Log (ELK / Grafana Loki compatible)
            structured_log = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "logger": "PipelineOrchestratorFacade",
                "level": "INFO",
                "event": "pipeline_execution_completed",
                "session_id": state.session_id,
                "tenant_id": state.tenant_id,
                "company_name": state.company_name,
                "status": "success",
                "timings": state.telemetry.get("timings", {}),
                "total_duration_sec": round(duration, 3),
                "token_consumption": token_data,
                "cost_estimation_usd": cost_usd,
                "critic_score": state.critic_score,
                "is_published": state.is_published,
            }
            logger.info(json.dumps(structured_log, ensure_ascii=False))

            try:
                from core.observability import ObservabilityManager
                ObservabilityManager.record_task_duration("pipeline_execution", duration, status="success")
            except Exception:
                pass

            return state

        except Exception as exc:
            duration = time.time() - start_time
            await self._emit_event(
                state.session_id if state else "unknown",
                "pipeline_error",
                "error",
                0,
                f"Ошибка выполнения конвейера: {exc}",
                {"error": str(exc)},
            )
            err_log = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "logger": "PipelineOrchestratorFacade",
                "level": "ERROR",
                "event": "pipeline_execution_failed",
                "session_id": state.session_id if state else "unknown",
                "tenant_id": state.tenant_id if state else "unknown",
                "error": str(exc),
                "status": "error",
                "duration_sec": round(duration, 3),
            }
            logger.error(json.dumps(err_log, ensure_ascii=False))
            try:
                from core.observability import ObservabilityManager
                ObservabilityManager.record_task_duration("pipeline_execution", duration, status="error")
            except Exception:
                pass
            raise exc


    async def execute_task(self, task_type: str, user_data: dict, session_id: Optional[str] = None) -> dict:
        """
        Универсальный обработчик задач (точка входа для API и воркеров).
        Делегирует исполнение доменным сервисам на основе типизированного контракта.
        """
        task_start_time = time.time()
        session_id = session_id or str(uuid.uuid4())
        print(f"\n[PipelineFacade] ⚖️ Новая задача '{task_type}', сессия: {session_id}")


        # 1. Проверка безопасности (Security Layer)
        raw_input = user_data.get("raw_social_input", "")
        if not SecurityGuard.check_user_input(raw_input):
            return {"status": "error", "message": "Security Violation: запрос отклонен."}

        # Нормализация вложений
        attachments = user_data.get("attachments") or user_data.get("photos") or []
        if isinstance(attachments, dict):
            attachments = [attachments]
        if not attachments and user_data.get("image_url"):
            attachments = [{"url": user_data.get("image_url")}]
        if not attachments and user_data.get("dataUrl"):
            attachments = [{"dataUrl": user_data.get("dataUrl")}]

        raw_format = str(user_data.get("target_format") or user_data.get("format_type") or "post").lower()
        format_map = {
            "poll": ContentFormatEnum.POLL,
            "quiz": ContentFormatEnum.QUIZ,
            "carousel": ContentFormatEnum.CAROUSEL,
            "storytelling": ContentFormatEnum.STORYTELLING,
            "puzzle": ContentFormatEnum.PUZZLE,
            "swipe_puzzle": ContentFormatEnum.SWIPE_PUZZLE,
            "cryptex": ContentFormatEnum.CRYPTEX,
        }
        target_format_enum = format_map.get(raw_format, ContentFormatEnum.POST)

        # Конструирование сквозного состояния PipelineState
        state = PipelineState(
            session_id=session_id,
            tenant_id=user_data.get("tenant_id") or user_data.get("project_id") or "default_tenant",
            user_id=user_data.get("user_id") or "default_user",
            company_name=user_data.get("company_name") or user_data.get("name") or "",
            niche=user_data.get("niche") or user_data.get("field") or "бизнес",
            topic=user_data.get("topic") or user_data.get("prompt") or "",
            tone_of_voice=user_data.get("tone") or "Экспертный, лаконичный, живой",
            target_format=target_format_enum,
            attachments=attachments,
            raw_notes=user_data.get("raw_notes"),
            telegram_channel=user_data.get("channel"),
            website_url=user_data.get("website") or user_data.get("url"),
        )

        try:
            # --- 1. BRAND SERVICE (Сбор и Анализ) ---
            if task_type in {"quick_vision", "analyze_attachments", "analyze_photo", "vision"}:
                vqa_res = await self.brand_service.analyze_attachments(
                    attachments=attachments,
                    topic=state.topic,
                    company_name=state.company_name or "UCust",
                )
                self._log_trace(session_id, "BrandService", "AttachmentsAnalyzed", {"count": vqa_res.get("count", 0)})
                return {"status": "success", "task_type": task_type, "vision_analysis": vqa_res, "structured_matrix": vqa_res.get("structured_matrix")}

            if task_type in {"analyze_documents", "extract_documents", "parse_documents", "ingest_client_files"}:
                doc_paths = user_data.get("documents") or user_data.get("files") or user_data.get("document_paths") or user_data.get("file_paths") or []
                if isinstance(doc_paths, str):
                    doc_paths = [doc_paths]
                res = await self.brand_service.extract_documents(doc_paths, state.company_name, state.niche)
                self._log_trace(session_id, "BrandService", "DocumentsParsed", {"count": res.get("extracted_count", 0)})
                return res

            if task_type in {"parse_telegram", "collect_telegram", "telegram"}:
                ch = user_data.get("channel") or user_data.get("url") or user_data.get("target") or "@UcustAi"
                res = await self.brand_service.collect_telegram(ch, limit=int(user_data.get("limit", 10)), include_media_vqa=user_data.get("include_media_vqa", True), company_name=state.company_name)
                self._log_trace(session_id, "BrandService", "TelegramParsed", {"channel": ch})
                return res

            if task_type in {"parse_vk", "collect_vk", "vk"}:
                gid = user_data.get("group_id") or user_data.get("url") or user_data.get("target") or "ucust_ai"
                res = await self.brand_service.collect_vk(gid, limit=int(user_data.get("limit", 10)))
                self._log_trace(session_id, "BrandService", "VKParsed", {"group_id": gid})
                return res

            if task_type in {"parse_geo", "collect_geo", "maps", "2gis", "yandex"}:
                target = user_data.get("url") or user_data.get("organization_id") or user_data.get("target") or ""
                res = await self.brand_service.collect_geo(target, limit=int(user_data.get("limit", 10)), provider=user_data.get("provider"))
                self._log_trace(session_id, "BrandService", "GeoParsed", {"target": target})
                return res

            if task_type in {"parse_website", "collect_website", "website"}:
                url = user_data.get("url") or user_data.get("target") or ""
                if not url:
                    return {"status": "error", "message": "Параметр 'url' обязателен для задачи parse_website."}
                res = await self.brand_service.collect_website(url)
                self._log_trace(session_id, "BrandService", "WebsiteParsed", {"url": url})
                return res

            if task_type in {"quick_scan", "scan_sources", "fast_onboarding"}:
                u = user_data.get("url") or user_data.get("website") or ""
                ch = user_data.get("channel") or user_data.get("telegram") or ""
                if not u and user_data.get("urls") and isinstance(user_data["urls"], list):
                    for item in user_data["urls"]:
                        if not isinstance(item, str):
                            continue
                        if ("t.me" in item or "telegram" in item) and not ch:
                            ch = item
                        elif not u:
                            u = item

                res = await self.brand_service.scan_sources(u, ch, state.company_name)
                self._log_trace(session_id, "BrandService", "SourcesScanned", {"url": u, "channel": ch})
                return res

            if task_type in {"onboard_brand", "brand_dna", "onboarding_agent", "onboarding", "onboard_user", "analyze_brand", "interviewer"}:
                state = await self.brand_service.process_brand(state, user_data=user_data)
                self._log_trace(session_id, "BrandService", "BrandDNAProfiled", {"brand_dna": state.brand_dna})
                return {
                    "status": "success",
                    "task_type": task_type,
                    "tenant_id": state.tenant_id,
                    "brand_dna": state.brand_dna,
                    "rag_facts": state.rag_facts,
                }

            # --- 2. CAMPAIGN SERVICE (Генерация и OTK) ---
            if task_type in {"plan_content", "generate_content_plan", "create_content_plan"}:
                res = await self.campaign_service.plan_content(user_data)
                self._log_trace(session_id, "CampaignService", "ContentPlanCreated", {"company_name": state.company_name})
                return res

            if task_type in {"get_placeholders", "placeholders", "suggest_placeholders", "get_idea_bank", "idea_bank", "quick_ideas"}:
                res = await self.campaign_service.get_ideas(niche=state.niche, count=int(user_data.get("limit", 5)))
                self._log_trace(session_id, "CampaignService", "IdeaBankQueried", {"niche": state.niche})
                return res

            if task_type in {"generate_poll", "poll_generate", "create_poll", "quiz_generate"}:
                res = await self.campaign_service.generate_poll(
                    topic=state.topic or "Опрос",
                    company_name=state.company_name or "UCust",
                    niche=state.niche,
                    is_quiz=("quiz" in task_type or target_format_enum == ContentFormatEnum.QUIZ),
                )
                self._log_trace(session_id, "CampaignService", "PollGenerated", {"topic": state.topic})
                return res

            if task_type in {"generate_image", "generate_photo", "edit_photo", "regenerate_image", "regenerate_photo", "re-generate"}:
                user_data["generate_image"] = True
                res = await self.campaign_service.generate_post(user_data, session_id=session_id)
                self._log_trace(session_id, "CampaignService", "PhotoGenerated", {"image_url": res.get("image_url")})
                return res

            if task_type in {"critic_review", "review_content"}:
                txt = user_data.get("text") or user_data.get("post_text") or ""
                res = await self.campaign_service.review_content(text=txt, topic=state.topic, target_audience=state.niche, niche=state.niche)
                self._log_trace(session_id, "CampaignService", "CriticReviewCompleted", {"score": res.get("score")})
                return res

            # --- 3. PUBLISHING SERVICE (Доставка и Адаптация) ---
            if task_type in {"publish_poll", "poll_publish"}:
                poll_payload = user_data.get("poll") or user_data
                ch = user_data.get("channel") or "@UcustAi"
                res = await self.publishing_service.publish_poll_payload(poll_payload, channel=ch, session_id=session_id)
                self._log_trace(session_id, "PublishingService", "PollPublished", {"channel": ch})
                return res

            if task_type in {"publish_post", "publish_content", "publish_showcase", "broadcast_achievement", "post_milestone"}:
                txt = user_data.get("post_text") or user_data.get("text") or ""
                ch = user_data.get("channel") or "@UcustAi"
                img = user_data.get("image_url") or user_data.get("photo_url")
                res = await self.publishing_service.publish_post_content(text=txt, channel=ch, image_url=img, company_name=state.company_name, session_id=session_id)
                self._log_trace(session_id, "PublishingService", "PostPublished", {"channel": ch, "status": res.get("status")})
                return res

            if task_type in {"track_post_performance", "process_audience_feedback", "feedback_loop"}:
                res = await self.publishing_service.track_performance(user_data, session_id=session_id)
                self._log_trace(session_id, "PublishingService", "PerformanceTracked", {"er": res.get("engagement_rate")})
                return res

            # --- 4. RAG ПРЯМЫЕ ОПЕРАЦИИ ---
            if task_type in {"rag_ingest", "ingest_rag", "index_knowledge"}:
                docs_raw = user_data.get("documents") or []
                rag_docs = [Document(doc_id=d.get("doc_id", str(uuid.uuid4())[:8]), text=d.get("text", ""), metadata=d.get("metadata", {})) for d in docs_raw if isinstance(d, dict)]
                count = await self.rag.ingest_documents_async(rag_docs)
                self._log_trace(session_id, "RAG", "DirectIngest", {"count": count})
                return {"status": "success", "indexed_chunks": count}

            if task_type in {"rag_query", "query_rag", "search_knowledge"}:
                q = user_data.get("query") or user_data.get("prompt") or ""
                t_id = user_data.get("tenant_id") or "default_tenant"
                # Проверяем кэш RAG с TTL (4 часа)
                cached_ctx = self.redis_cache.get_cached_rag_query(q, tenant_id=t_id)
                if cached_ctx:
                    return {"status": "success", "context": cached_ctx.get("context", ""), "has_context": cached_ctx.get("has_context", True), "cached": True}
                rag_res = await self.rag.query_async(q, tenant_id=t_id)
                rag_dict = {"context": rag_res.formatted_context, "has_context": rag_res.has_sufficient_context}
                self.redis_cache.set_cached_rag_query(q, tenant_id=t_id, result=rag_dict, ttl=14400)
                return {"status": "success", **rag_dict}

            if task_type in {"get_graph_data", "graph_data", "metrics"}:
                return {"status": "success", "metrics": self.get_frontend_graph_data()}

            # --- 5. END-TO-END PIPELINE (Генерация полного поста / кампании) ---
            auto_pub = bool(user_data.get("auto_publish", False))
            res = await self.campaign_service.generate_post(user_data, session_id=session_id)
            if auto_pub and res.get("post_text"):
                ch = user_data.get("channel") or "@UcustAi"
                pub_res = await self.publishing_service.publish_post_content(
                    text=res.get("clean_user_post_text") or res.get("post_text"),
                    channel=ch,
                    image_url=res.get("image_url"),
                    company_name=state.company_name,
                    session_id=session_id,
                )
                res["auto_publish_result"] = pub_res

            self._log_trace(session_id, "PipelineFacade", "TaskCompleted", {
                "task_type": task_type,
                "duration": res.get("telemetry", {}).get("total_duration", 0),
            })

            # Structured JSON Log & Observability
            task_duration = time.time() - task_start_time
            structured_log = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "logger": "PipelineOrchestratorFacade",
                "level": "INFO",
                "event": "task_execution_completed",
                "task_type": task_type,
                "session_id": session_id,
                "tenant_id": state.tenant_id,
                "status": "success",
                "duration_sec": round(task_duration, 3),
            }
            logger.info(json.dumps(structured_log, ensure_ascii=False))
            try:
                from core.observability import ObservabilityManager
                ObservabilityManager.record_task_duration(task_type, task_duration, status="success")
            except Exception:
                pass

            return res

        except Exception as exc:
            task_duration = time.time() - task_start_time
            print(f"[PipelineFacade] ⚠️ Ошибка выполнения задачи '{task_type}': {exc}")
            err_log = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "logger": "PipelineOrchestratorFacade",
                "level": "ERROR",
                "event": "task_execution_failed",
                "task_type": task_type,
                "session_id": session_id,
                "error": str(exc),
                "status": "error",
                "duration_sec": round(task_duration, 3),
            }
            logger.error(json.dumps(err_log, ensure_ascii=False))
            try:
                from core.observability import ObservabilityManager
                ObservabilityManager.record_task_duration(task_type, task_duration, status="error")
            except Exception:
                pass
            return {"status": "error", "task_type": task_type, "message": str(exc), "session_id": session_id}


    def get_frontend_graph_data(self) -> List[dict]:
        """Безопасная отдача агрегированных данных фронтенду для графиков (DLP защищено)."""
        mock_raw_db_data = [
            {"niche": "IT Automation", "count": 15, "secret_id": "sys_999", "pass_hash": "xxx"},
            {"niche": "Beauty SMM", "count": 8, "secret_id": "sys_123", "pass_hash": "yyy"},
        ]
        return SecurityGuard.sanitize_graph_data(mock_raw_db_data)


# Обратная совместимость для всех импортов в проекте
UnifiedOrchestrator = PipelineOrchestratorFacade


class AgentState(str, Enum):
    IDLE = "IDLE"
    COLLECTING = "COLLECTING"
    ANALYZING = "ANALYZING"
    GENERATING = "GENERATING"
    REVIEWING = "REVIEWING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AgentOrchestrator:
    """Совместимый адаптер для вызовов конвейера агентов."""
    def __init__(self, database=None):
        self.database = database
        self.unified = UnifiedOrchestrator(db_session=database)

    async def run_pipeline(self, context):
        try:
            user_data = {
                "user_id": context.user_profile_id or "user_default",
                "questionnaire": context.questionnaire
            }
            if context.questionnaire and hasattr(context.questionnaire, "step1") and context.questionnaire.step1:
                user_data["name"] = context.questionnaire.step1.business_name
                user_data["company_name"] = context.questionnaire.step1.business_name
                user_data["city"] = context.questionnaire.step1.region
            await self.unified.execute_task("onboarding", user_data)
            return context
        except Exception:
            return context


def build_default_orchestrator(database=None):
    return AgentOrchestrator(database=database)


__all__ = [
    "PipelineOrchestratorFacade",
    "UnifiedOrchestrator",
    "SecurityGuard",
    "AgentState",
    "AgentOrchestrator",
    "build_default_orchestrator",
]
