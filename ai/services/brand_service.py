"""
File: ai/services/brand_service.py
Модуль сбора данных, извлечения Brand DNA и анализа конкурентно-рыночного контекста.
Часть мультиагентной системы UCust AI (Фаза P1).
"""

from __future__ import annotations

import os
import uuid
import asyncio
import logging
from typing import Any, Dict, List, Optional

from schemas.pipeline_state import PipelineState
from rag.models import Document
from storage.models import UserProfile

logger = logging.getLogger("BrandService")


class BrandService:
    """
    Сервис сбора данных и брендового анализа:
    - Вызов неблокирующих коллекторов (Web, Telegram, VK, Geo, PDF/DOCX)
    - Мультимодальный анализ визуалов (Moondream2 VQA)
    - Извлечение паспорта бренда (Brand DNA) и SWOT-анализ
    - Сохранение и загрузка профилей в SQL БД
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

    async def process_brand(
        self,
        state: PipelineState,
        user_data: Optional[Dict[str, Any]] = None,
    ) -> PipelineState:
        """
        Главный пайплайн сервиса бренда:
        Принимает PipelineState, обогащает его Brand DNA, фактами из RAG и возвращает обновленный state.
        """
        data = user_data or {}
        company_name = state.company_name or data.get("company_name", "UCust")
        niche = state.niche or data.get("niche", "бизнес")

        # 1. Анализ вложений (Moondream VQA), если переданы
        if state.attachments:
            try:
                vqa_res = await self.analyze_attachments(
                    attachments=state.attachments,
                    topic=state.topic,
                    company_name=company_name,
                )
                if vqa_res and vqa_res.get("summary"):
                    state.rag_facts.append(f"Визуальный стиль бренда: {vqa_res['summary']}")
            except Exception as e:
                logger.warning(f"[BrandService] Ошибка анализа вложений: {e}")

        # 2. Извлечение Brand DNA через OnboardingAgent
        try:
            from skills.onboarding_agent import OnboardingAgent

            agent = OnboardingAgent()
            doc_paths = data.get("documents") or data.get("files") or []
            if isinstance(doc_paths, str):
                doc_paths = [doc_paths]

            dna = await agent.ingest_and_profile_brand(
                tenant_id=state.tenant_id,
                company_name=company_name,
                niche=niche,
                website_url=state.website_url or data.get("website") or data.get("url"),
                telegram_channel=state.telegram_channel or data.get("channel"),
                document_paths=doc_paths if doc_paths else None,
                raw_notes=state.raw_notes or data.get("raw_notes"),
            )
            if hasattr(dna, "model_dump"):
                state.brand_dna = dna.model_dump()
            elif hasattr(dna, "dict"):
                state.brand_dna = dna.dict()
            else:
                state.brand_dna = dict(dna)

            state.company_name = state.brand_dna.get("company_name") or company_name
            state.niche = state.brand_dna.get("industry") or state.brand_dna.get("niche") or niche
            state.tone_of_voice = state.brand_dna.get("tone_of_voice") or state.tone_of_voice

            for usp in state.brand_dna.get("key_usp", []):
                state.rag_facts.append(f"УТП: {usp}")
        except Exception as dna_err:
            logger.warning(f"[BrandService] Fallback извлечения Brand DNA: {dna_err}")
            state.brand_dna = {
                "brand_name": company_name,
                "company_name": company_name,
                "industry": niche,
                "tone_of_voice": state.tone_of_voice,
                "key_usp": ["Автономный маркетинг", "Индивидуальный стиль"],
            }

        # 3. Синхронизация фактов в RAG, если RAG инициализирован
        if self.rag and state.rag_facts:
            try:
                rag_docs = [
                    Document(
                        doc_id=f"brand_fact_{state.tenant_id}_{idx+1}",
                        text=fact,
                        metadata={
                            "category": "brand_dna",
                            "company_name": company_name,
                            "tenant_id": state.tenant_id,
                        },
                    )
                    for idx, fact in enumerate(state.rag_facts)
                ]
                await self.rag.ingest_documents_async(rag_docs)
            except Exception as r_err:
                logger.warning(f"[BrandService] Ошибка сохранения Brand DNA в RAG: {r_err}")

        return state

    async def analyze_attachments(
        self,
        attachments: List[Any],
        topic: str = "",
        company_name: str = "UCust",
    ) -> Dict[str, Any]:
        """Неблокирующий анализ визуальных медиа через MoondreamVQASkill."""
        from skills.moondream_vqa import MoondreamVQASkill

        moondream = MoondreamVQASkill()
        return await asyncio.to_thread(
            moondream.analyze_attachments_batch,
            attachments=attachments,
            topic=topic,
            company_name=company_name,
        )

    async def scan_sources(
        self,
        target_url: str = "",
        telegram_channel: str = "",
        company_name: str = "UCust",
    ) -> Dict[str, Any]:
        """Быстрый конкурентный скан внешних источников (Web + Telegram + авто-чейн соцсетей)."""
        import re
        from collectors.website_collector import WebsiteCollector
        from collectors.telethon_collector import TelethonCollector

        site_task = None
        tg_task = None

        if target_url:
            site_collector = WebsiteCollector()
            site_task = site_collector.collect_website_async(target_url)

        if telegram_channel:
            tg_collector = TelethonCollector()
            tg_task = tg_collector.collect_async(channel=telegram_channel, limit=10)

        site_data, tg_data = None, None
        if site_task and tg_task:
            site_data, tg_data = await asyncio.gather(site_task, tg_task, return_exceptions=True)
        elif site_task:
            site_data = await site_task
        elif tg_task:
            tg_data = await tg_task

        # 1. Авто-чейн Telegram (если канал не был передан в запросе, но найден на сайте)
        if not telegram_channel and site_data and isinstance(site_data, dict):
            discovered_tg = site_data.get("social_links", {}).get("telegram", [])
            if discovered_tg:
                raw_tg = discovered_tg[0]
                tg_match = re.search(r'(?:t\.me|telegram\.me)/([a-zA-Z0-9_+]+)', raw_tg)
                if tg_match and not tg_match.group(1).lower().endswith('bot'):
                    telegram_channel = f"@{tg_match.group(1)}"
                else:
                    telegram_channel = raw_tg

                logger.info(f"[BrandService] 🔗 Авто-чейн: найден Telegram-канал на сайте: {telegram_channel}. Запуск сбора постов...")
                try:
                    tg_collector = TelethonCollector()
                    tg_data = await tg_collector.collect_async(channel=telegram_channel, limit=10)
                except Exception as tg_err:
                    logger.warning(f"[BrandService] Ошибка авто-сбора Telegram {telegram_channel}: {tg_err}")

        # 2. Авто-чейн VK (если группа найдена на сайте)
        vk_data = None
        if site_data and isinstance(site_data, dict):
            discovered_vk = site_data.get("social_links", {}).get("vk", [])
            if discovered_vk:
                try:
                    from collectors.vk_collector import VKCollector
                    vk_collector = VKCollector()
                    vk_res = await vk_collector.collect_group_async(group_id_or_url=discovered_vk[0], limit=10)
                    vk_data = vk_res.get("data", vk_res)
                except Exception as vk_err:
                    logger.warning(f"[BrandService] Ошибка авто-сбора VK: {vk_err}")

        # 3. Формирование единого контракта с prefilled_profile и raw_sources для бэкенда
        site_dict = site_data if isinstance(site_data, dict) else {}
        b_name = company_name if (company_name and company_name != "UCust") else (site_dict.get("title") or "UCust")
        niche = site_dict.get("description", "")[:60] if site_dict.get("description") else "Бизнес и услуги"
        description = site_dict.get("description", "")
        brand_colors = [site_dict.get("theme_color")] if site_dict.get("theme_color") else ["#3b82f6", "#1e293b"]
        contacts = site_dict.get("contacts", {"phones": [], "emails": []})
        social_profiles = site_dict.get("social_links", {})

        prefilled_profile = {
            "business_name": b_name,
            "niche": niche,
            "city": "Москва",
            "description": description,
            "brand_colors": brand_colors,
            "contacts": contacts,
            "reviews_summary": None,
            "social_links": {
                "website": target_url or site_dict.get("url"),
                "telegram": telegram_channel or (social_profiles.get("telegram", [None])[0] if social_profiles.get("telegram") else None),
                "vk": (social_profiles.get("vk", [None])[0] if social_profiles.get("vk") else None),
                "max": (social_profiles.get("max", [None])[0] if social_profiles.get("max") else None),
            }
        }

        raw_sources = {
            "website": site_data if not isinstance(site_data, Exception) else None,
            "telegram": tg_data.payload if hasattr(tg_data, "payload") else tg_data,
            "vk": vk_data,
            "maps": None,
        }

        return {
            "status": "success",
            "task_type": "quick_scan",
            "company_name": b_name,
            "prefilled_profile": prefilled_profile,
            "raw_sources": raw_sources,
            "website_data": site_data if not isinstance(site_data, Exception) else None,
            "telegram_data": tg_data.payload if hasattr(tg_data, "payload") else tg_data,
        }

    async def collect_telegram(
        self,
        channel: str,
        limit: int = 10,
        include_media_vqa: bool = True,
        company_name: str = "",
    ) -> Dict[str, Any]:
        """Неблокирующий сбор постов Telegram и анализ медиа."""
        from collectors.telethon_collector import TelethonCollector

        tg_collector = TelethonCollector()
        tg_data = await tg_collector.collect_async(channel=channel, limit=limit)
        payload = tg_data.payload if hasattr(tg_data, "payload") else tg_data

        media_vqa_result = None
        if include_media_vqa and isinstance(payload, dict) and payload.get("messages"):
            collected_photos = []
            for msg in payload.get("messages", []):
                if isinstance(msg, dict) and msg.get("photo_url"):
                    collected_photos.append(msg["photo_url"])
                elif isinstance(msg, dict) and msg.get("media_path"):
                    collected_photos.append(msg["media_path"])

            if collected_photos:
                try:
                    from skills.moondream_vqa import MoondreamVQASkill
                    vqa = MoondreamVQASkill()
                    media_vqa_result = await asyncio.to_thread(
                        vqa.analyze_attachments_batch,
                        attachments=collected_photos[:5],
                        topic=f"Анализ ленты Telegram-канала {channel}",
                        company_name=company_name or channel,
                    )
                except Exception as ve:
                    logger.warning(f"[BrandService] Ошибка VLM анализа медиа Telegram: {ve}")

        return {
            "status": "success",
            "channel": channel,
            "source": "telegram",
            "data": payload,
            "media_analysis": media_vqa_result,
        }

    async def collect_vk(self, group_id_or_url: str, limit: int = 10) -> Dict[str, Any]:
        """Сбор постов группы VK."""
        from collectors.vk_collector import VKCollector

        vk_collector = VKCollector()
        vk_res = await vk_collector.collect_group_async(group_id_or_url=group_id_or_url, limit=limit)
        return {
            "status": "success",
            "group_id": group_id_or_url,
            "source": "vk",
            "data": vk_res.get("data", vk_res),
        }

    async def collect_geo(
        self,
        url_or_id: str,
        limit: int = 10,
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Сбор отзывов гео-сервисов (2GIS / Яндекс Карты)."""
        provider_name = (provider or "").lower()
        if "yandex" in url_or_id.lower() or provider_name == "yandex":
            from collectors.yandex_collector import YandexMapsCollector
            geo_res = await YandexMapsCollector().collect_reviews_async(url_or_id, limit=limit)
        else:
            from collectors.twogis_collector import TwoGisCollector
            geo_res = await TwoGisCollector().collect_reviews_async(url_or_id, limit=limit)

        return {
            "status": "success",
            "source": geo_res.get("source", "geo"),
            "url": url_or_id,
            "data": geo_res,
        }

    async def collect_website(self, url: str) -> Dict[str, Any]:
        """Сбор и структурирование данных сайта."""
        from collectors.website_collector import WebsiteCollector

        collector = WebsiteCollector()
        site_data = await collector.collect_website_async(url)
        return {
            "status": "success" if site_data.get("status") != "error" else "error",
            "source": "website",
            "url": url,
            "data": site_data,
        }

    async def extract_documents(
        self,
        file_paths: List[str],
        company_name: str = "Наша Компания",
        niche: str = "Бизнес",
    ) -> Dict[str, Any]:
        """Пакетное неблокирующее извлечение документов (PDF, DOCX, TXT) и обогащение RAG."""
        from collectors.document_collector import DocumentCollector

        doc_collector = DocumentCollector()
        extracted = await asyncio.to_thread(doc_collector.extract_documents_batch, file_paths)

        indexed_count = 0
        if self.rag:
            try:
                indexed_count = await doc_collector.sync_documents_to_rag(company_name, niche, extracted, self.rag)
            except Exception as r_err:
                logger.warning(f"[BrandService] Ошибка синхронизации документов с RAG: {r_err}")

        dossier = await asyncio.to_thread(doc_collector.synthesize_dossier_from_docs, extracted)

        return {
            "status": "success",
            "company_name": company_name,
            "niche": niche,
            "extracted_count": len(extracted),
            "indexed_count": indexed_count,
            "dossier": dossier,
            "extracted": extracted,
        }

    async def load_profile(
        self,
        user_id: Optional[str] = None,
        profile_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Безопасная неблокирующая вычитка профиля из SQL БД."""
        if not self.db or not (user_id or profile_id):
            return None

        def _load_sync():
            try:
                rec = None
                if profile_id:
                    rec = self.db.query(UserProfile).filter(UserProfile.id == profile_id).first()
                elif user_id:
                    rec = self.db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
                if rec:
                    step1_data = rec.step1 if isinstance(rec.step1, dict) else {}
                    return {
                        "id": rec.id,
                        "company_name": rec.company_name,
                        "niche": rec.niche,
                        "city": rec.city,
                        "country": rec.country,
                        "tone": step1_data.get("voice_and_tone"),
                        "brand_colors": step1_data.get("brand_colors"),
                        "visual_grid_dna": rec.visual_grid_dna,
                        "brand_dossier": rec.brand_dossier,
                    }
                return None
            except Exception as e:
                try:
                    self.db.rollback()
                except Exception:
                    pass
                logger.warning(f"[BrandService] Ошибка загрузки профиля: {e}")
                return None

        return await asyncio.to_thread(_load_sync)

    async def save_profile(
        self,
        user_id: str,
        company_name: str,
        niche: str,
        city: str,
        country: str,
        brand_profile: Dict[str, Any],
        visual_grid_dna: Optional[Dict[str, Any]] = None,
        brand_dossier: Optional[Dict[str, Any]] = None,
        social_links: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """Неблокирующее сохранение паспорта бренда в SQL БД."""
        if not self.db:
            return None

        def _save_sync() -> Optional[int]:
            try:
                profile = UserProfile(
                    external_user_id=user_id,
                    user_id=user_id,
                    company_name=company_name,
                    niche=niche,
                    city=city,
                    country=country,
                    target_audience=brand_profile.get("market", {}).get("segment", ""),
                    step1={
                        "voice_and_tone": brand_profile.get("tone", []),
                        "positioning": brand_profile.get("positioning", ""),
                        "brand_colors": brand_profile.get("brand_colors", []),
                    },
                    step2=brand_profile.get("market", {}),
                    step3=brand_profile.get("swot", {}),
                    step4={"services": brand_profile.get("services", [])},
                    step5={"goals": brand_profile.get("goals", [])},
                    visual_grid_dna=visual_grid_dna,
                    brand_dossier=brand_dossier or {},
                    social_links=social_links or {},
                )
                self.db.add(profile)
                self.db.commit()
                self.db.refresh(profile)
                return profile.id
            except Exception as e:
                try:
                    self.db.rollback()
                except Exception:
                    pass
                logger.warning(f"[BrandService] Ошибка сохранения профиля в SQL: {e}")
                return None

        return await asyncio.to_thread(_save_sync)
