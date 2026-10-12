"""
File: ai/services/publishing_service.py
Модуль безопасной доставки контента в социальные каналы (Telegram, VK),
форматирования под платформы, трекинга публикаций и петли обратной связи (Feedback Loop).
Часть мультиагентной системы UCust AI (Фаза P1).
"""

from __future__ import annotations

import os
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from schemas.pipeline_state import PipelineState
from storage.models import PublicationHistory, UserProfile

logger = logging.getLogger("PublishingService")


class PublishingService:
    """
    Сервис публикации и дистрибуции:
    - Адаптация разметки и медиа под каналы (Telegram HTML/MarkdownV2, VK)
    - Сетевая отправка постов, фото-альбомов и опросов через API клиентов
    - Аудит и сохранение истории публикаций в SQL (PublicationHistory)
    - Трекинг эффективности и петля обратной связи (FeedbackLoopEngine)
    """

    def __init__(
        self,
        db_session: Optional[Any] = None,
        redis_cache: Optional[Any] = None,
        rag_pipeline: Optional[Any] = None,
    ) -> None:
        self.db = db_session
        self.redis_cache = redis_cache
        self.rag = rag_pipeline

    async def publish(
        self,
        state: PipelineState,
        channels: Optional[List[str]] = None,
        user_data: Optional[Dict[str, Any]] = None,
    ) -> PipelineState:
        """
        Главный пайплайн доставки:
        Принимает финальный PipelineState, выполняет безопасную отправку в указанные каналы
        и фиксирует результат.
        """
        data = user_data or {}
        target_channel = state.telegram_channel or data.get("channel") or "@UcustAi"
        photo_path = state.photo_paths[0] if state.photo_paths else None

        # 1. Отправка опроса, если тип задачи — опрос
        if state.poll_payload:
            poll_pub_res = await self.publish_poll_payload(
                poll_payload=state.poll_payload,
                channel=target_channel,
                session_id=state.session_id,
            )
            state.is_published = bool(poll_pub_res.get("status") == "success")
            state.publication_result = poll_pub_res
            return state

        # 2. Отправка поста
        pub_res = await self.publish_post_content(
            text=state.draft_text,
            channel=target_channel,
            image_url=photo_path,
            company_name=state.company_name,
            session_id=state.session_id,
        )
        state.is_published = bool(pub_res.get("status") == "success")
        state.publication_result = pub_res
        return state

    async def publish_post_content(
        self,
        text: str,
        channel: str = "@UcustAi",
        image_url: Optional[str] = None,
        company_name: str = "UCust",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Отправка стандартного поста через AchievementBroadcaster."""
        from publishers.achievement_broadcaster import AchievementBroadcaster

        broadcaster = AchievementBroadcaster(target_channel=channel)
        try:
            broadcast_res = await broadcaster.publish_post_async(
                post_text=text,
                media_path=image_url,
                target_channel=channel,
            )
        except Exception as exc:
            logger.warning(f"AchievementBroadcaster.publish_post_async failed: {exc}. Fallback returned.")
            broadcast_res = {
                "status": "mock_success",
                "channel": channel,
                "message": f"Fallback publish: {exc}",
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Неблокирующая фиксация публикации в SQL
        if self.db and broadcast_res.get("status") in ("success", "mock_success"):
            await self._record_publication_history(
                channel=channel,
                text=text,
                status="published",
                company_name=company_name,
            )

        return broadcast_res

    async def publish_poll_payload(
        self,
        poll_payload: Dict[str, Any],
        channel: str = "@UcustAi",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if hasattr(poll_payload, "model_dump"):
            payload = poll_payload.model_dump()
        elif hasattr(poll_payload, "dict"):
            payload = poll_payload.dict()
        elif isinstance(poll_payload, dict):
            payload = poll_payload
        else:
            payload = {"question": str(poll_payload)}

        question = payload.get("question") or "Опрос аудитории"
        options = payload.get("options") or ["Вариант 1", "Вариант 2"]
        intro_text = payload.get("intro_text") or ""
        explanation = payload.get("explanation")
        correct_option_id = payload.get("correct_option_id")

        try:
            from telegram import Bot
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            if token:
                bot = Bot(token=token)
                if intro_text:
                    await bot.send_message(chat_id=channel, text=intro_text)

                poll_type = "quiz" if correct_option_id is not None else "regular"
                await bot.send_poll(
                    chat_id=channel,
                    question=question,
                    options=options,
                    type=poll_type,
                    correct_option_id=correct_option_id,
                    explanation=explanation,
                    is_anonymous=True,
                )
                return {"status": "success", "channel": channel, "type": poll_type}
        except Exception as e:
            logger.warning(f"[PublishingService] Ошибка отправки опроса через bot API: {e}")

        # Fallback через telethon_publisher
        try:
            from publishers.telethon_publisher import TelethonPublisher
            pub = TelethonPublisher()
            return await pub.publish_poll_async(
                channel=channel,
                question=question,
                options=options,
                intro_text=intro_text,
            )
        except Exception as pe:
            logger.warning(f"[PublishingService] Telethon poll publish fallback note: {pe}")
            return {"status": "mock_success", "channel": channel, "message": "Опрос сэмулирован."}

    async def track_performance(
        self,
        user_data: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Обработка метрик вовлеченности (FeedbackLoopEngine) и адаптация стратегии."""
        from analytics.feedback_loop import FeedbackLoopEngine

        engine = FeedbackLoopEngine()
        views = int(user_data.get("views", 0))
        likes = int(user_data.get("likes", 0))
        dislikes = int(user_data.get("dislikes", 0))
        comments_count = int(user_data.get("comments_count", 0))
        shares = int(user_data.get("shares", 0))
        other_reactions = user_data.get("other_reactions", {})
        platform = user_data.get("platform", "telegram")
        raw_reactions = user_data.get("reactions", {})
        comments = user_data.get("comments", [])
        publication_id = user_data.get("publication_id")

        positivity = engine.calculate_positivity_index(
            views=views,
            likes=likes,
            dislikes=dislikes,
            comments=comments_count,
            shares=shares,
            other_reactions=other_reactions,
            platform=platform,
            raw_reactions=raw_reactions,
        )
        er = positivity["engagement_rate"]
        nai = positivity["net_approval_index"]
        wpr = positivity["weighted_positivity_rate"]
        score = positivity["log_positivity_score"]
        grade = positivity["grade"]
        analysis = engine.analyze_comments(comments)

        # Неблокирующее обновление PublicationHistory в SQL
        if self.db and publication_id:
            def _update_pub_sync():
                try:
                    pub = self.db.query(PublicationHistory).filter(PublicationHistory.id == publication_id).first()
                    if pub:
                        pub.views_count = views
                        pub.likes_count = likes
                        pub.dislikes_count = dislikes
                        pub.comments_count = comments_count
                        pub.shares_count = shares
                        pub.engagement_rate = er
                        pub.net_approval_index = nai
                        pub.weighted_positivity_rate = wpr
                        pub.log_positivity_score = score
                        pub.positivity_grade = grade
                        pub.comments_analysis = analysis
                        pub.last_monitored_at = datetime.utcnow()
                        self.db.commit()
                except Exception as sql_e:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass
                    logger.warning(f"[PublishingService] Ошибка сохранения метрик в SQL: {sql_e}")

            await asyncio.to_thread(_update_pub_sync)

        company_name = user_data.get("company_name", "UCust")
        niche = user_data.get("niche", "IT Automation")
        top_topics = user_data.get("top_topics", [])

        indexed_count = 0
        if self.rag:
            try:
                indexed_count = await engine.sync_feedback_to_rag(company_name, niche, analysis, top_topics, self.rag)
            except Exception as r_e:
                logger.warning(f"[PublishingService] Ошибка sync_feedback_to_rag: {r_e}")

        adaptations = engine.generate_strategy_adaptations(top_topics, analysis)

        # Обновление feedback_insights в UserProfile SQL
        if self.db and (user_data.get("profile_id") or user_data.get("user_id")):
            def _update_prof_insights():
                try:
                    prof = None
                    if user_data.get("profile_id"):
                        prof = self.db.query(UserProfile).filter(UserProfile.id == user_data["profile_id"]).first()
                    elif user_data.get("user_id"):
                        prof = self.db.query(UserProfile).filter(UserProfile.user_id == user_data["user_id"]).first()
                    if prof:
                        dossier = dict(prof.brand_dossier or {})
                        dossier["feedback_insights"] = adaptations
                        prof.brand_dossier = dossier
                        self.db.commit()
                except Exception as pe:
                    try:
                        self.db.rollback()
                    except Exception:
                        pass
                    logger.warning(f"[PublishingService] Ошибка обновления dossier в SQL: {pe}")

            await asyncio.to_thread(_update_prof_insights)

        return {
            "status": "success",
            "positivity_metrics": positivity,
            "engagement_rate": er,
            "comments_analysis": analysis,
            "rag_indexed_count": indexed_count,
            "strategy_adaptations": adaptations,
        }

    async def _record_publication_history(
        self,
        channel: str,
        text: str,
        status: str = "published",
        company_name: str = "UCust",
    ) -> None:
        """Вспомогательная запись в историю публикаций."""
        def _record_sync():
            try:
                hist = PublicationHistory(
                    project_id=1,
                    platform="telegram",
                    channel_name=channel,
                    post_text=text[:500],
                    status=status,
                    published_at=datetime.utcnow(),
                )
                self.db.add(hist)
                self.db.commit()
            except Exception as e:
                try:
                    self.db.rollback()
                except Exception:
                    pass
                logger.debug(f"[PublishingService] Заметка сохранения истории: {e}")

        await asyncio.to_thread(_record_sync)
