import os
import sys
import uuid
import json
import time
import hashlib
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from storage.models import UserProfile, OrchestratorTrace, PublicationHistory, ProjectMetadata, ContentTask

class SecurityGuard:
    """
    Модуль безопасности. Защищает от Prompt Injection, джейлбрейков (амнезии)
    и прямых запросов на выгрузку БД.
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

    # Строгий запрет на утечку внутренних моделей, нод, связей и настроек
    PROTECTED_IP_TERMS = [
        "ltx", "ltx-video", "ltxv", "saiga", "moondream", "comfyui", "safetensors",
        "lora", "clip", "latent", "cfg", "emptyllatent", "checkpoint", "vlm",
        "gemma", "sdxl", "flux", "unipc", "karras", "sampler", "vae", "controlnet",
        "qwen", "qwen_image", "qwen_2.5_vl", "famegrid", "realskinfix", "auraflow",
        "clownshark", "emptysd3latent", "unetloader", "cliploader", "vaedecodetiled"
    ]
    
    @classmethod
    def sanitize_public_text(cls, text: str) -> str:
        """
        Защита коммерческой тайны и IP: вырезает и маскирует любые упоминания
        внутренних моделей, весов, нод и параметров генерации из публичных текстов.
        """
        if not text:
            return ""
        clean = text
        for term in cls.PROTECTED_IP_TERMS:
            pattern = re.compile(rf'\b{re.escape(term)}\b', re.IGNORECASE)
            clean = pattern.sub("UCust AI Engine", clean)
        return clean

    @classmethod
    def check_user_input(cls, user_text: str) -> bool:
        """
        Проверяет ввод пользователя на попытки взлома, инъекций, обфускации
        (раскладка клавиатуры, омоглифы, Base64, спецсимволы) и запрещенный политический/экстремистский контент.
        Возвращает True, если безопасно, и False, если есть подозрения.
        """
        if not user_text:
            return True

        # 1. Полномочный аудит безопасности через PoliticalAndLegalGuard с деобфускацией
        try:
            from skills.political_legal_guard import PoliticalAndLegalGuard
            is_safe, reason = PoliticalAndLegalGuard.validate_content(user_text)
            if not is_safe:
                print(f"[SecurityGuard] 🚨 ОТКЛОНЕНО СИСТЕМОЙ БЕЗОПАСНОСТИ: {reason} в запросе пользователя!")
                return False
        except Exception as e:
            print(f"[SecurityGuard] ⚠️ Ошибка проверки через PoliticalAndLegalGuard ({e}), задействован базовый контур...")

        text_lower = user_text.lower()
        for kw in cls.FORBIDDEN_KEYWORDS:
            if kw in text_lower:
                print(f"[SecurityGuard] 🚨 ОБНАРУЖЕНА ПОПЫТКА ВЗЛОМА: '{kw}' в запросе пользователя!")
                return False
                
        for hw in cls.HARMFUL_AND_OFFENSIVE_TERMS:
            if hw in text_lower:
                print(f"[SecurityGuard] 🚨 ОБНАРУЖЕН ЗАПРЕЩЕННЫЙ/ТОКСИЧНЫЙ КОНТЕНТ: '{hw}'!")
                return False
        return True


    @classmethod
    def validate_content_tone_of_voice(cls, content_text: str, custom_forbidden_words: Optional[List[str]] = None) -> tuple[bool, Optional[str]]:
        """
        Tone-of-Voice Gatekeeper: Проверяет исходящий контент перед отправкой на фронтенд/в API.
        Отсекает фальшь, глобальные стоп-слова, а также кастомные стоп-слова бренда из BrandGuidelines.
        """
        if not content_text:
            return True, None
            
        content_lower = content_text.lower()
        # 1. Глобальные стоп-слова
        for word in cls.TONE_STOPWORDS:
            if word in content_lower:
                print(f"[SecurityGuard] ⚠️ БРАК КОНТЕНТА (Tone of Voice): обнаружено стоп-выражение '{word}'!")
                return False, f"Нарушение гайдлайнов качества: обнаружено запрещенное слово/символ '{word}'"

        # 2. Кастомные стоп-слова клиента (Brand Guidelines)
        if custom_forbidden_words:
            for c_word in custom_forbidden_words:
                if c_word and c_word.lower() in content_lower:
                    print(f"[SecurityGuard] ⚠️ БРАК КОНТЕНТА (Brand Guidelines): обнаружено стоп-слово бренда '{c_word}'!")
                    return False, f"Нарушение редполитики бренда: запрещено использовать слово '{c_word}'"

        return True, None


    @classmethod
    def sanitize_graph_data(cls, raw_data: List[Dict]) -> List[Dict]:
        """
        Очищает данные перед отправкой на фронтенд для отрисовки графов.
        Удаляет все PII (персональные данные), хэши и внутренние ID.
        """
        sanitized = []
        for item in raw_data:
            clean_item = {
                "metric_name": item.get("niche", "Unknown"),
                "value": item.get("count", 0)
            }
            sanitized.append(clean_item)
        return sanitized


class UnifiedOrchestrator:
    """
    Унифицированный Архитектор (Chief Orchestrator).
    Единая точка входа для всех задач (пайплайны, графы, фронтенд).
    Полностью контролирует безопасность и потоки данных.
    """
    def __init__(self, db_session=None, vector_store=None, redis_cache=None):
        from storage.pgvector_store import PGVectorStore
        from core.redis_cache import RedisCacheManager
        from rag.pipeline import CleanRAGPipeline
        
        self.db = db_session
        self.vector_store = vector_store or (PGVectorStore(self.db) if self.db else None)
        self.redis_cache = redis_cache or RedisCacheManager()
        self.rag = CleanRAGPipeline(min_confidence_threshold=0.55)

        # 1. Автоматический контроль хранения файлов (Кэш: 5 часов, Генерации: 30 дней)
        try:
            from storage.media_retention import MediaRetentionManager
            cleaner = MediaRetentionManager()
            retention_days = int(os.getenv("MEDIA_RETENTION_DAYS", "30"))
            temp_hours = float(os.getenv("TEMP_CACHE_RETENTION_HOURS", "5.0"))
            auto_archive = os.getenv("MEDIA_AUTO_ARCHIVE", "true").lower() == "true"
            cleaner.cleanup_expired_files(
                retention_days=retention_days,
                temp_cache_retention_hours=temp_hours,
                archive_generations=auto_archive
            )
        except Exception:
            pass

        # 2. Инициализация внутреннего календаря и временного якоря
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
        payload_hash = self._hash_payload(payload)
        
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
                print(f"[UnifiedOrchestrator] ⚠️ Ошибка сохранения трейса в БД: {e}")
        
        # 2. Кешируем стейт в Redis для ускорения будущих запусков
        self.redis_cache.set_cached_result(action, payload_hash, payload)

    async def execute_task(self, task_type: str, user_data: dict, session_id: Optional[str] = None) -> dict:
        """
        Универсальный обработчик задач (точка входа для фронтенда и API).
        """
        session_id = session_id or str(uuid.uuid4())
        print(f"\n[UnifiedOrchestrator] ⚖️ Новая задача '{task_type}', сессия: {session_id}")
        
        # 1. Проверка безопасности (Security Layer)
        raw_input = user_data.get("raw_social_input", "")
        if not SecurityGuard.check_user_input(raw_input):
            return {"status": "error", "message": "Security Violation: запрос отклонен."}
            
        # 2. Универсальный Vision Analyst (Moondream2) для любых загруженных пользователем фото
        attachments = user_data.get("attachments") or user_data.get("photos") or []
        if isinstance(attachments, dict):
            attachments = [attachments]
        if not attachments and user_data.get("image_url"):
            attachments = [{"url": user_data.get("image_url")}]
        if not attachments and user_data.get("dataUrl"):
            attachments = [{"dataUrl": user_data.get("dataUrl")}]

        moondream_analysis = None
        if attachments:
            try:
                from skills.moondream_vqa import MoondreamVQASkill
                moondream = MoondreamVQASkill()
                company_name_for_md = user_data.get("company_name") or user_data.get("name") or "UCust"
                prompt_for_md = user_data.get("prompt") or user_data.get("topic") or ""
                moondream_analysis = moondream.analyze_attachments_batch(
                    attachments=attachments,
                    topic=prompt_for_md,
                    company_name=company_name_for_md
                )
                self._log_trace(session_id, "MoondreamAnalyst", "AttachmentsAnalyzed", {
                    "count": moondream_analysis.get("count", 0),
                    "colors": moondream_analysis.get("colors", []),
                    "summary": moondream_analysis.get("summary", "")
                })
                print(f"[UnifiedOrchestrator] 🧠 Moondream успешно проанализировал {moondream_analysis.get('count')} фото пользователя!")
            except Exception as e:
                print(f"[UnifiedOrchestrator] ⚠️ Ошибка Moondream анализа: {e}")

        if task_type in {"quick_vision", "analyze_attachments", "analyze_photo", "vision"}:
            extracted_matrix = None
            if moondream_analysis:
                if moondream_analysis.get("items") and len(moondream_analysis["items"]) > 0:
                    extracted_matrix = moondream_analysis["items"][0].get("structured_matrix")
                elif moondream_analysis.get("structured_matrix"):
                    extracted_matrix = moondream_analysis.get("structured_matrix")

            return {
                "status": "success",
                "task_type": task_type,
                "photos_count": moondream_analysis.get("count", 0) if moondream_analysis else 0,
                "brand_colors": moondream_analysis.get("colors", []) if moondream_analysis else [],
                "mood_tags": moondream_analysis.get("mood_tags", []) if moondream_analysis else [],
                "quality_flags": moondream_analysis.get("quality_flags", {}) if moondream_analysis else {},
                "structured_matrix": extracted_matrix,
                "items": moondream_analysis.get("items", []) if moondream_analysis else [],
                "slot_mapping": moondream_analysis.get("slot_mapping") if moondream_analysis else None,
                "fusion_prompt": moondream_analysis.get("fusion_prompt") if moondream_analysis else None,
                "visual_narrative": moondream_analysis.get("fusion_narrative") if moondream_analysis else None,
                "prompt_keywords": moondream_analysis.get("prompt_keywords") if moondream_analysis else ""
            }

        if task_type in {"analyze_documents", "extract_documents", "parse_documents"}:
            from collectors.document_collector import DocumentCollector
            from rag.pipeline import Document
            doc_collector = DocumentCollector()
            doc_paths = user_data.get("documents") or user_data.get("files") or user_data.get("document_paths") or []
            if isinstance(doc_paths, str):
                doc_paths = [doc_paths]
            extracted_docs = doc_collector.extract_documents_batch(doc_paths)
            rag_docs = []
            company_name = user_data.get("company_name", "UCust")
            for idx, doc in enumerate(extracted_docs):
                if doc.get("status") == "success" and doc.get("raw_text"):
                    rag_docs.append(Document(
                        doc_id=f"doc_{company_name}_{idx+1}",
                        text=f"Документ '{doc['file_name']}':\n{doc['raw_text']}",
                        metadata={"category": "client_files", "company_name": company_name}
                    ))
            indexed_count = 0
            if rag_docs:
                try:
                    indexed_count = await self.rag.ingest_documents_async(rag_docs)
                except Exception as r_err:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка индексации документов: {r_err}")
            return {
                "status": "success",
                "task_type": task_type,
                "company_name": company_name,
                "documents_count": len(extracted_docs),
                "extracted_documents": extracted_docs,
                "indexed_in_rag_count": indexed_count
            }

        if task_type in {"parse_telegram", "collect_telegram", "telegram"}:
            from collectors.telethon_collector import TelethonCollector
            channel = user_data.get("channel") or user_data.get("url") or user_data.get("target") or "@UcustAi"
            limit = int(user_data.get("limit", 10))
            include_media_vqa = user_data.get("include_media_vqa", True)
            
            tg_collector = TelethonCollector()
            tg_data = await tg_collector.collect_async(channel=channel, limit=limit)
            payload = tg_data.payload if hasattr(tg_data, "payload") else tg_data
            
            media_vqa_result = None
            if include_media_vqa and isinstance(payload, dict) and payload.get("messages"):
                # Собираем фото из постов, если они есть
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
                        media_vqa_result = vqa.analyze_attachments_batch(
                            attachments=collected_photos[:5],
                            topic=f"Анализ ленты Telegram-канала {channel}",
                            company_name=user_data.get("company_name", channel)
                        )
                    except Exception as ve:
                        print(f"[UnifiedOrchestrator] ⚠️ Ошибка VLM анализа медиа Telegram: {ve}")

            self._log_trace(session_id, "TelethonCollector", "TelegramParsed", {
                "channel": channel,
                "posts_count": len(payload.get("messages", [])) if isinstance(payload, dict) else 0,
                "has_media_vqa": bool(media_vqa_result)
            })

            return {
                "status": "success",
                "task_type": task_type,
                "channel": channel,
                "source": "telegram",
                "data": payload,
                "media_analysis": media_vqa_result
            }

        if task_type in {"parse_vk", "collect_vk", "vk"}:
            from collectors.vk_collector import VKCollector
            group_id = user_data.get("group_id") or user_data.get("url") or user_data.get("target") or "ucust_ai"
            limit = int(user_data.get("limit", 10))
            
            vk_collector = VKCollector()
            vk_res = await vk_collector.collect_group_async(group_id_or_url=group_id, limit=limit)
            
            self._log_trace(session_id, "VKCollector", "VKParsed", {
                "group_id": group_id,
                "status": vk_res.get("status")
            })

            return {
                "status": "success",
                "task_type": task_type,
                "group_id": group_id,
                "source": "vk",
                "data": vk_res.get("data", vk_res)
            }

        if task_type in {"parse_geo", "collect_geo", "maps", "2gis", "yandex"}:
            url_or_id = user_data.get("url") or user_data.get("organization_id") or user_data.get("target") or ""
            provider = (user_data.get("provider") or "").lower()
            limit = int(user_data.get("limit", 10))

            if "yandex" in url_or_id.lower() or provider == "yandex":
                from collectors.yandex_collector import YandexMapsCollector
                geo_res = await YandexMapsCollector().collect_reviews_async(url_or_id, limit=limit)
            else:
                from collectors.twogis_collector import TwoGisCollector
                geo_res = await TwoGisCollector().collect_reviews_async(url_or_id, limit=limit)

            self._log_trace(session_id, "GeoCollector", "GeoReviewsParsed", {
                "url": url_or_id,
                "source": geo_res.get("source")
            })

            return {
                "status": "success",
                "task_type": task_type,
                "source": geo_res.get("source", "geo"),
                "url": url_or_id,
                "data": geo_res
            }

        if task_type in {"parse_website", "collect_website", "website"}:
            from collectors.website_collector import WebsiteCollector
            url = user_data.get("url") or user_data.get("target") or ""
            if not url:
                return {"status": "error", "message": "Параметр 'url' обязателен для задачи parse_website."}
            
            collector = WebsiteCollector()
            site_data = await collector.collect_website_async(url)
            
            self._log_trace(session_id, "WebsiteCollector", "WebsiteParsed", {
                "url": url,
                "status": site_data.get("status")
            })

            return {
                "status": "success" if site_data.get("status") != "error" else "error",
                "task_type": task_type,
                "source": "website",
                "url": url,
                "data": site_data
            }

        if task_type in {"rag_ingest", "ingest_rag", "index_knowledge"}:
            from rag.models import Document
            docs_data = user_data.get("documents") or []
            data_dict = user_data.get("data") or user_data.get("profile") or user_data.get("project_profile_draft")
            
            tenant_id = user_data.get("project_id") or user_data.get("brand_id") or user_data.get("tenant_id") or "default_brand"
            rag_docs = []

            # 1. Если передан структурированный 5-экранный профиль онбординга
            if isinstance(data_dict, dict):
                about = data_dict.get("about", {})
                market = data_dict.get("market", {})
                swot = data_dict.get("swot", {})
                services = data_dict.get("services", [])
                goals = data_dict.get("goals", {})

                comp_name = about.get("name") or tenant_id
                
                # Экран 1: О проекте
                about_text = f"О проекте / компании: {comp_name}\nНиша: {about.get('niche', '')}\nПозиционирование: {about.get('positioning', '')}\nГород: {about.get('city', '')}\nОписание: {about.get('description', '')}"
                rag_docs.append(Document(doc_id=f"rag_about_{tenant_id}", text=about_text, metadata={"category": "about", "tenant_id": tenant_id, "project_id": tenant_id}))

                # Экран 2: Рынок и конкуренты
                market_text = f"Рынок и конкуренты для {comp_name}:\nКонкуренты: {market.get('competitors', [])}\nГеография: {market.get('geography', '')}\nСегмент ЦА: {market.get('audience_segment', '')}\nТренды: {market.get('trends', [])}"
                rag_docs.append(Document(doc_id=f"rag_market_{tenant_id}", text=market_text, metadata={"category": "market", "tenant_id": tenant_id, "project_id": tenant_id}))

                # Экран 3: SWOT анализ
                swot_text = f"SWOT анализ компании {comp_name}:\nСильные стороны: {swot.get('strengths', [])}\nСлабые стороны: {swot.get('weaknesses', [])}\nВозможности: {swot.get('opportunities', [])}\nУгрозы: {swot.get('threats', [])}"
                rag_docs.append(Document(doc_id=f"rag_swot_{tenant_id}", text=swot_text, metadata={"category": "swot", "tenant_id": tenant_id, "project_id": tenant_id}))

                # Экран 4: Услуги и цены
                if services:
                    serv_lines = []
                    for s in services:
                        if isinstance(s, dict):
                            serv_lines.append(f"- {s.get('name')}: {s.get('description', '')} (Цена: {s.get('price', 'по запросу')})")
                        else:
                            serv_lines.append(f"- {s}")
                    serv_text = f"Услуги и предложения компании {comp_name}:\n" + "\n".join(serv_lines)
                    rag_docs.append(Document(doc_id=f"rag_services_{tenant_id}", text=serv_text, metadata={"category": "services", "tenant_id": tenant_id, "project_id": tenant_id}))

                # Экран 5: Цели контента и Tone of Voice
                goals_text = f"Цели контента и Tone of Voice для {comp_name}:\nЦели: {goals.get('content_goals', [])}\nTone of Voice: {goals.get('tone_of_voice', [])}"
                rag_docs.append(Document(doc_id=f"rag_goals_{tenant_id}", text=goals_text, metadata={"category": "goals", "tenant_id": tenant_id, "project_id": tenant_id}))

            # 2. Обработка произвольного списка документов
            if isinstance(docs_data, str):
                docs_data = [{"text": docs_data}]
            elif isinstance(docs_data, dict):
                docs_data = [docs_data]
            
            for idx, item in enumerate(docs_data):
                if isinstance(item, str):
                    rag_docs.append(Document(
                        doc_id=f"doc_{tenant_id}_{idx+1}",
                        text=item,
                        metadata={"tenant_id": tenant_id, "brand_id": tenant_id, "project_id": tenant_id}
                    ))
                elif isinstance(item, dict) and item.get("text"):
                    meta = item.get("metadata", {})
                    meta.setdefault("tenant_id", tenant_id)
                    meta.setdefault("brand_id", tenant_id)
                    meta.setdefault("project_id", tenant_id)
                    rag_docs.append(Document(
                        doc_id=item.get("doc_id") or f"doc_{tenant_id}_{idx+1}",
                        text=item["text"],
                        metadata=meta,
                        source=item.get("source", "backend_api")
                    ))

            indexed_count = 0
            if rag_docs:
                try:
                    indexed_count = await self.rag.ingest_documents_async(rag_docs)
                except Exception as r_err:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка индексации RAG: {r_err}")

            return {
                "status": "success",
                "task_type": task_type,
                "project_id": tenant_id,
                "tenant_id": tenant_id,
                "documents_received": len(rag_docs),
                "chunks_indexed": indexed_count
            }

        if task_type in {"rag_query", "query_rag", "search_knowledge"}:
            query_str = user_data.get("query") or user_data.get("prompt") or ""
            top_k = int(user_data.get("top_k", 5))
            tenant_id = user_data.get("brand_id") or user_data.get("tenant_id")

            rag_context = await self.rag.query_async(query_str, top_k_retrieval=top_k, tenant_id=tenant_id)
            return {
                "status": "success",
                "task_type": task_type,
                "query": rag_context.query,
                "has_sufficient_context": rag_context.has_sufficient_context,
                "top_score": round(rag_context.top_score, 3),
                "context": rag_context.formatted_context if rag_context.has_sufficient_context else None,
                "fallback_message": rag_context.fallback_message,
                "retrieved_chunks_count": len(rag_context.chunks)
            }

        if task_type in {"quick_scan", "scan_sources", "fast_onboarding"}:
            from collectors.website_collector import WebsiteCollector
            from collectors.vk_collector import VKCollector
            from collectors.twogis_collector import TwoGISCollector
            urls = user_data.get("urls") or []
            if isinstance(urls, str):
                urls = [urls]
            safe_urls = [u for u in urls if SecurityGuard.check_user_input(u) and not any(h in u.lower() for h in ["localhost", "127.0.0.1", "10.0.", "192.168.", "169.254."])]
            site_urls = [u for u in safe_urls if not any(k in u.lower() for k in ["vk.com", "t.me", "2gis.", "yandex."])]
            vk_urls = [u for u in safe_urls if "vk.com" in u.lower()]
            map_urls = [u for u in safe_urls if any(k in u.lower() for k in ["2gis.", "yandex."])]

            async def _f_site():
                if site_urls:
                    return await WebsiteCollector().collect_website_async(site_urls[0])
                return None

            async def _f_vk():
                if vk_urls:
                    return await VKCollector().collect_group_async(vk_urls[0])
                return None

            async def _f_map():
                if map_urls:
                    return await TwoGISCollector().collect_reviews_async(map_urls[0])
                return None

            site_res, vk_res, map_res = await asyncio.gather(_f_site(), _f_vk(), _f_map(), return_exceptions=True)
            
            b_colors = []
            if moondream_analysis and moondream_analysis.get("colors"):
                b_colors.extend(moondream_analysis["colors"])
            if isinstance(site_res, dict) and site_res.get("theme_color"):
                b_colors.append(site_res["theme_color"])

            comp_title = user_data.get("company_name") or (site_res.get("title") if isinstance(site_res, dict) else "") or "Мой бизнес"
            comp_niche = user_data.get("niche") or (site_res.get("description", "")[:60] if isinstance(site_res, dict) else "") or "Бизнес и услуги"

            return {
                "status": "success",
                "task_type": task_type,
                "prefilled_profile": {
                    "business_name": comp_title,
                    "niche": comp_niche,
                    "city": user_data.get("city", "Москва"),
                    "description": site_res.get("description", "") if isinstance(site_res, dict) else "",
                    "brand_colors": list(dict.fromkeys(b_colors))[:5] or ["#3b82f6", "#1e293b"],
                    "contacts": site_res.get("contacts") if isinstance(site_res, dict) else {},
                    "reviews_summary": map_res.get("summary") if isinstance(map_res, dict) else None,
                    "social_links": {
                        "website": site_urls[0] if site_urls else None,
                        "vk": vk_urls[0] if vk_urls else None
                    }
                },
                "raw_sources": {
                    "website": site_res if not isinstance(site_res, Exception) else None,
                    "vk": vk_res if not isinstance(vk_res, Exception) else None,
                    "maps": map_res if not isinstance(map_res, Exception) else None
                }
            }

        if task_type in {"get_placeholders", "placeholders", "suggest_placeholders"}:
            from skills.smart_idea_bank import SmartIdeaBank
            idea_bank = SmartIdeaBank()
            niche = user_data.get("niche") or "Бизнес"
            company_name = user_data.get("company_name") or "UCust"
            limit = int(user_data.get("limit", 5))
            placeholders = idea_bank.get_dynamic_placeholders(niche=niche, company_name=company_name, limit=limit)
            return {
                "status": "success",
                "task_type": task_type,
                "niche": niche,
                "company_name": company_name,
                "placeholders": [p.dict() for p in placeholders]
            }

        if task_type in {"get_idea_bank", "idea_bank", "quick_ideas"}:
            from skills.smart_idea_bank import SmartIdeaBank
            idea_bank = SmartIdeaBank()
            niche = user_data.get("niche") or "Бизнес"
            country = user_data.get("country") or "россия"
            days_ahead = int(user_data.get("days_ahead", 21))
            company_name = user_data.get("company_name") or "UCust"
            ideas = idea_bank.get_quick_ideas_bank(niche=niche, country=country, days_ahead=days_ahead, company_name=company_name)
            return {
                "status": "success",
                "task_type": task_type,
                "niche": niche,
                "country": country,
                "ideas_count": len(ideas),
                "ideas": [i.dict() for i in ideas]
            }

        if task_type in {"evaluate_funnel_placement", "evaluate_placement", "check_funnel_safety"}:
            from skills.smart_idea_bank import SmartIdeaBank
            idea_bank = SmartIdeaBank()
            topic = user_data.get("topic") or user_data.get("prompt") or ""
            niche = user_data.get("niche") or "Бизнес"
            company_name = user_data.get("company_name") or "UCust"
            target_slot_date = user_data.get("target_slot_date")
            target_slot_type = user_data.get("target_slot_type")
            is_override = bool(user_data.get("is_override_scheduled_slot", False))
            
            verdict = idea_bank.evaluate_funnel_placement(
                topic=topic,
                niche=niche,
                company_name=company_name,
                target_slot_date=target_slot_date,
                target_slot_type=target_slot_type,
                is_override_scheduled_slot=is_override
            )
            return {
                "status": "success",
                "task_type": task_type,
                "verdict": verdict.dict()
            }

        if task_type in {"onboarding", "onboard_user", "analyze_brand", "interviewer"}:
            from skills.saiga_llm import SaigaLLMSkill
            from collectors.website_collector import WebsiteCollector
            import re
            
            project_id = user_data.get("project_id") or user_data.get("tenant_id") or user_data.get("brand_id") or "proj_default"
            company_name = user_data.get("name") or user_data.get("company_name") or user_data.get("brand_name") or project_id
            raw_social_input = (
                user_data.get("source_url") or 
                user_data.get("raw_social_input") or 
                user_data.get("link") or 
                user_data.get("website") or 
                user_data.get("channel") or ""
            )
            activity = user_data.get("niche_hint") or user_data.get("activity") or user_data.get("niche") or "IT Automation"
            city = user_data.get("city") or "Москва"
            
            print(f"[UnifiedOrchestrator] 🎙️ Агент-Интервьюер: Анализ входных данных для '{company_name}' ({activity}), source: '{raw_social_input}'...")
            
            collected_intel = []
            website_data = None
            tg_data = None

            # 1. Сбор данных из Telegram (если передан t.me/... или @channel)
            if "@" in raw_social_input or "t.me/" in raw_social_input:
                try:
                    from collectors.telethon_collector import TelethonCollector
                    tg_collector = TelethonCollector()
                    tg_res = await tg_collector.collect_async(channel=raw_social_input, limit=10)
                    payload = tg_res.payload if hasattr(tg_res, "payload") else tg_res
                    if isinstance(payload, dict) and payload.get("messages"):
                        tg_messages = [m.get("text", "") for m in payload.get("messages", []) if isinstance(m, dict) and m.get("text")]
                        if tg_messages:
                            tg_text = "\n".join(tg_messages[:10])
                            collected_intel.append(f"Данные из Telegram ({raw_social_input}):\n{tg_text}")
                            user_data["telegram_dossier"] = tg_text
                            self._log_trace(session_id, "TelethonCollector", "TelegramAnalyzed", {
                                "channel": raw_social_input,
                                "posts_count": len(tg_messages)
                            })
                except Exception as tg_err:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка сбора Telegram: {tg_err}")

            # 2. Автоматический глубокий анализ сайта компании, если передан URL (не Telegram / VK)
            found_urls = re.findall(r'https?://[^\s,;]+|(?:www\.)?[a-zA-Z0-9-]+\.(?:ru|com|io|org|net|pro|ai|me|cc|by|kz|tech|online|store|shop|app|dev)(?:/[^\s,;]*)?', raw_social_input)
            for u in found_urls:
                if not any(excluded in u.lower() for excluded in ["t.me", "vk.com", "yandex.", "2gis."]):
                    try:
                        collector = WebsiteCollector()
                        website_data = await collector.collect_website_async(u)
                        if website_data.get("status") == "success":
                            self._log_trace(session_id, "WebsiteCollector", "WebsiteAnalyzed", {
                                "url": website_data.get("url"),
                                "title": website_data.get("title"),
                                "description": website_data.get("description")
                            })
                            # Обогащаем user_data
                            user_data["website_dossier"] = website_data.get("structured_dossier")
                            if website_data.get("structured_dossier"):
                                collected_intel.append(f"Данные с веб-сайта ({u}):\n{website_data['structured_dossier']}")
                            if website_data.get("description") and activity == "IT Automation":
                                user_data["niche"] = website_data.get("description")[:80]
                            break
                    except Exception as wex:
                        print(f"[UnifiedOrchestrator] ⚠️ Ошибка парсинга сайта: {wex}")

            self._log_trace(session_id, "Agent_Interviewer", "Extracted_Context", {
                "company_name": company_name,
                "project_id": project_id,
                "raw_social_input": raw_social_input,
                "activity": activity,
                "city": city,
                "has_website_data": bool(website_data),
                "intel_sources_count": len(collected_intel)
            })
            
            # 3. Сайга и Аналитик формируют бренд-профиль с учетом собранной аналитики
            saiga = SaigaLLMSkill()
            clean_posts_input = collected_intel if collected_intel else ([website_data["structured_dossier"]] if website_data and website_data.get("structured_dossier") else None)
            brand_profile = saiga.analyze_brand_profile(user_data, clean_posts=clean_posts_input)

            # 4. Подключение Визуального Директора для анализа сетки ленты (Grid DNA & Brandbook)
            from skills.advanced_visual_director import AdvancedVisualDirector
            all_collected_images = []
            if website_data and website_data.get("cached_images"):
                all_collected_images.extend(website_data["cached_images"])
            elif website_data and website_data.get("images"):
                all_collected_images.extend(website_data["images"])
            if attachments:
                all_collected_images.extend(attachments)

            vis_director = AdvancedVisualDirector()
            visual_grid_dna = vis_director.analyze_visual_grid(
                images=all_collected_images,
                niche=user_data.get("niche") or activity
            )
            brand_profile["visual_grid_dna"] = visual_grid_dna
            brand_profile["brand_colors"] = visual_grid_dna.get("brand_hex_palette", [])
            brand_profile["dominant_color"] = visual_grid_dna.get("dominant_color")
            brand_profile["next_visual_recommendation"] = visual_grid_dna.get("next_post_recommendation")

            self._log_trace(session_id, "VisualDirector", "GridDNAAnalyzed", {
                "palette": visual_grid_dna.get("brand_hex_palette"),
                "images_analyzed": visual_grid_dna.get("analyzed_images_count"),
                "recommended_slot": visual_grid_dna.get("next_post_recommendation", {}).get("target_slot")
            })

            # 5. Генерация глубокой контент-стратегии и портрета покупателя (Persona & Strategy Engine)
            from skills.content_strategy_engine import ContentStrategyEngine
            strat_engine = ContentStrategyEngine()
            strategy_data = strat_engine.generate_strategy(
                company_name=company_name,
                niche=brand_profile.get("field", activity),
                target_audience=brand_profile.get("market", {}).get("segment", ""),
                key_usp=brand_profile.get("positioning", "")
            )
            brand_profile["buyer_persona"] = strategy_data.get("buyer_persona", {})
            brand_profile["funnel_matrix"] = strategy_data.get("funnel_matrix", {})
            brand_profile["viral_hooks"] = strategy_data.get("hooks_arsenal", [])

            if website_data:
                brand_profile["website_data"] = {
                    "title": website_data.get("title"),
                    "description": website_data.get("description"),
                    "headings": website_data.get("headings", []),
                    "images": website_data.get("images", []),
                    "contacts": website_data.get("contacts", {}),
                    "social_links": website_data.get("social_links", {})
                }
            if moondream_analysis and moondream_analysis.get("colors"):
                brand_profile["moondream_colors"] = moondream_analysis.get("colors")
                brand_profile["visual_summary"] = moondream_analysis.get("summary")
            self._log_trace(session_id, "Agent_Saiga", "Synthesized_Profile", brand_profile)
            self._log_trace(session_id, "Agent_ContentStrategist", "StrategySynthesized", strategy_data)
            
            # 6. Векторизация и индексация в RAG (6 семантических категорий фактов)
            from rag.models import Document
            rag_docs = []
            pains_list = strategy_data.get("buyer_persona", {}).get("primary_pains", [])
            triggers_list = strategy_data.get("buyer_persona", {}).get("buying_triggers", [])
            swot_data = brand_profile.get("swot", {})
            services_list = brand_profile.get("services", [])

            # Doc 1: Brand DNA & Positioning
            rag_docs.append(Document(
                doc_id=f"brand_dna_{company_name}",
                text=f"Компания: {company_name}\nНиша: {brand_profile.get('field', activity)}\nГород: {city}\nПозиционирование (УТП): {brand_profile.get('positioning', '')}\nTone of Voice: {brand_profile.get('tone', [])}\nЦелевая аудитория: {brand_profile.get('market', {}).get('segment', '')}",
                metadata={"category": "brand_dna", "company_name": company_name, "tenant_id": project_id, "project_id": project_id, "user_id": user_data.get("user_id")}
            ))

            # Doc 2: Pain Points & Buying Triggers
            rag_docs.append(Document(
                doc_id=f"pains_{company_name}",
                text=f"Боли, страхи и возражения клиентов компании {company_name}:\n- " + "\n- ".join(pains_list) + "\nТриггеры покупки и доверия:\n- " + "\n- ".join(triggers_list),
                metadata={"category": "pain_points", "company_name": company_name, "tenant_id": project_id, "project_id": project_id}
            ))

            # Doc 3: Competitor Dossier & Advantages
            rag_docs.append(Document(
                doc_id=f"competitors_{company_name}",
                text=f"Конкурентный анализ и отстройка компании {company_name}:\nСильные стороны: {swot_data.get('strengths', [])}\nВозможности рынка: {swot_data.get('opportunities', [])}\nГлавное отличие: {brand_profile.get('positioning', '')}",
                metadata={"category": "competitors", "company_name": company_name, "tenant_id": project_id, "project_id": project_id}
            ))

            # Doc 4: Visual Grid DNA & Palette
            if visual_grid_dna:
                rag_docs.append(Document(
                    doc_id=f"visual_grid_{company_name}",
                    text=f"Визуальный брендбук и сетка ленты 3x3 для {company_name}:\nФирменная палитра (Hex): {visual_grid_dna.get('brand_hex_palette', [])}\nДоминирующий цвет: {visual_grid_dna.get('dominant_color')}\nРекомендация по кадру: {visual_grid_dna.get('next_post_recommendation', {}).get('advice')}",
                    metadata={"category": "visual_grid_dna", "company_name": company_name, "tenant_id": project_id, "project_id": project_id}
                ))

            # Doc 5: Services & Pricing Offers
            if services_list:
                rag_docs.append(Document(
                    doc_id=f"services_{company_name}",
                    text=f"Услуги и ключевые предложения компании {company_name}:\n- " + "\n- ".join([str(s) for s in services_list]),
                    metadata={"category": "services", "company_name": company_name, "tenant_id": project_id, "project_id": project_id}
                ))

            # Doc 6: Website Knowledge Base
            if website_data and website_data.get("structured_dossier"):
                rag_docs.append(Document(
                    doc_id=f"website_{company_name}",
                    text=f"Фактическая информация с официального сайта {company_name}:\n{website_data['structured_dossier']}",
                    metadata={"category": "website_knowledge", "company_name": company_name, "tenant_id": project_id, "project_id": project_id}
                ))

            # 7. Календарь государственных, профессиональных и городских праздников для локации
            country = user_data.get("country") or brand_profile.get("market", {}).get("country") or "Россия"
            try:
                from collectors.event_holiday_collector import EventHolidayCollector
                holiday_events = EventHolidayCollector().get_calendar_events(
                    country=country,
                    city=city,
                    niche=brand_profile.get("field", activity),
                    days_count=60
                )
                if holiday_events:
                    holidays_str = "\n".join([f"- {e['date']}: {e['title']} ({e['vibe']})" for e in holiday_events[:10]])
                    rag_docs.append(Document(
                        doc_id=f"geo_and_holidays_{company_name}",
                        text=f"География, локальные события и праздники компании {company_name}:\nСтрана: {country}\nГород: {city}\nНиша: {brand_profile.get('field', activity)}\nБлижайшие инфоповоды и праздники:\n{holidays_str}",
                        metadata={"category": "holidays_and_events", "company_name": company_name, "country": country, "city": city, "tenant_id": project_id, "project_id": project_id}
                    ))
            except Exception as h_err:
                print(f"[UnifiedOrchestrator] ⚠️ Ошибка сбора календаря праздников: {h_err}")

            # 8. Извлечение информации из загруженных документов клиента (PDF, DOCX, PPTX)
            client_docs_data = None
            from collectors.document_collector import DocumentCollector
            doc_collector = DocumentCollector()
            doc_candidates = (user_data.get("documents") or user_data.get("files") or 
                              user_data.get("file_paths") or user_data.get("document_paths") or [])
            if isinstance(doc_candidates, str):
                doc_candidates = [doc_candidates]
            
            valid_doc_paths = [
                f for f in doc_candidates 
                if isinstance(f, str) and os.path.splitext(f)[1].lower() in {".pdf", ".docx", ".pptx", ".txt", ".md", ".csv"} and os.path.exists(f)
            ]
            if valid_doc_paths:
                try:
                    client_docs_data = doc_collector.extract_documents_batch(valid_doc_paths)
                    for d_idx, doc_item in enumerate(client_docs_data):
                        if doc_item.get("status") == "success" and doc_item.get("raw_text"):
                            rag_docs.append(Document(
                                doc_id=f"client_doc_{company_name}_{d_idx+1}",
                                text=f"Документ клиента '{doc_item['file_name']}' ({doc_item['format'].upper()}) для {company_name}:\n{doc_item['raw_text']}",
                                metadata={"category": "client_files", "company_name": company_name, "file_name": doc_item["file_name"], "tenant_id": project_id, "project_id": project_id}
                            ))
                    print(f"[UnifiedOrchestrator] 📄 Извлечено {len(client_docs_data)} клиентских документов для '{company_name}'.")
                except Exception as doc_err:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка парсинга документов клиента: {doc_err}")

            try:
                indexed_count = await self.rag.ingest_documents_async(rag_docs)
                print(f"[UnifiedOrchestrator] 📚 Векторная база знаний RAG успешно обогащена: {indexed_count} чанков для '{company_name}'.")
                self._log_trace(session_id, "CleanRAGPipeline", "KnowledgeIndexed", {"indexed_chunks": indexed_count, "company": company_name})
            except Exception as rag_err:
                print(f"[UnifiedOrchestrator] ⚠️ Ошибка индексации RAG: {rag_err}")

            # 9. Формирование стандартизированного 5-экранного проекта (5-Screen UI Onboarding Draft)
            formatted_services = []
            for s in brand_profile.get("services", []):
                if isinstance(s, dict):
                    formatted_services.append({
                        "name": s.get("title") or s.get("name", "Услуга"),
                        "description": s.get("items") or s.get("description", ""),
                        "price": s.get("price", "по запросу")
                    })
                else:
                    formatted_services.append({
                        "name": str(s),
                        "description": "",
                        "price": "по запросу"
                    })

            project_profile_draft = {
                "about": {
                    "name": company_name,
                    "niche": brand_profile.get("field", activity),
                    "positioning": brand_profile.get("positioning", ""),
                    "city": brand_profile.get("market", {}).get("geography", city),
                    "description": user_data.get("description") or (website_data.get("description") if website_data else "") or brand_profile.get("positioning", "")
                },
                "market": {
                    "competitors": brand_profile.get("market", {}).get("competitors", []),
                    "geography": brand_profile.get("market", {}).get("geography", city),
                    "audience_segment": brand_profile.get("market", {}).get("segment", ""),
                    "trends": brand_profile.get("market", {}).get("trends", [])
                },
                "swot": {
                    "strengths": brand_profile.get("swot", {}).get("strengths", []),
                    "weaknesses": brand_profile.get("swot", {}).get("weaknesses", []),
                    "opportunities": brand_profile.get("swot", {}).get("opportunities", []),
                    "threats": brand_profile.get("swot", {}).get("threats", [])
                },
                "services": formatted_services,
                "goals": {
                    "content_goals": brand_profile.get("goals", []),
                    "tone_of_voice": brand_profile.get("tone", [])
                }
            }

            # 10. Сохранение в реляционную БД (SQL)
            profile_id = None
            if self.db:
                try:
                    profile = UserProfile(
                        external_user_id=user_data.get("user_id", "default_user"),
                        user_id=user_data.get("user_id", "default_user"),
                        company_name=company_name,
                        niche=brand_profile.get("field", activity),
                        city=brand_profile.get("market", {}).get("geography", city),
                        country=country,
                        location_details={"country": country, "city": city, "holidays_count": len(holiday_events) if 'holiday_events' in locals() else 0},
                        target_audience=brand_profile.get("market", {}).get("segment", ""),
                        step1={"voice_and_tone": brand_profile.get("tone", []), "positioning": brand_profile.get("positioning", ""), "brand_colors": brand_profile.get("brand_colors", [])},
                        step2=brand_profile.get("market", {}),
                        step3=brand_profile.get("swot", {}),
                        step4={"services": brand_profile.get("services", [])},
                        step5={"goals": brand_profile.get("goals", [])},
                        visual_grid_dna=visual_grid_dna,
                        brand_dossier={
                            "website_dossier": website_data.get("structured_dossier") if website_data else None,
                            "documents_dossier": doc_collector.synthesize_dossier_from_docs(client_docs_data) if (client_docs_data and 'doc_collector' in locals()) else None,
                            "strategy": strategy_data,
                            "pains": pains_list
                        },
                        social_links={"link": raw_social_input, "socials": user_data.get("socials", [])}
                    )
                    self.db.add(profile)
                    self.db.commit()
                    self.db.refresh(profile)
                    profile_id = profile.id
                    self._log_trace(session_id, "ChiefOrchestrator", "ProfileSaved", {"profile_id": profile_id})
                    print(f"[UnifiedOrchestrator] ✅ Профиль #{profile_id} ('{company_name}', {country}, г. {city}) успешно сохранен в SQL БД!")
                except Exception as e:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка сохранения профиля в SQL БД: {e}")
            
            return {
                "status": "success",
                "task_type": task_type,
                "project_id": project_id,
                "tenant_id": project_id,
                "project_profile_draft": project_profile_draft,
                "profile": brand_profile,
                "profile_id": profile_id or 1
            }

        if task_type in {"onboard_brand", "brand_dna", "onboarding_agent"}:
            from skills.onboarding_agent import OnboardingAgent
            agent = OnboardingAgent(dev_mode=True)
            
            tenant_id = user_data.get("tenant_id") or user_data.get("user_id") or "tenant_default"
            company_name = user_data.get("company_name") or user_data.get("name") or "UCust"
            niche = user_data.get("niche") or user_data.get("activity") or "IT & Services"
            telegram_ch = user_data.get("telegram_channel") or user_data.get("channel")
            web_url = user_data.get("website_url") or user_data.get("url") or user_data.get("website")
            doc_paths = user_data.get("document_paths") or user_data.get("documents") or user_data.get("files")
            raw_notes = user_data.get("raw_notes") or user_data.get("notes")
            
            dna = await agent.ingest_and_profile_brand(
                tenant_id=tenant_id,
                company_name=company_name,
                niche=niche,
                telegram_channel=telegram_ch,
                website_url=web_url,
                document_paths=doc_paths if isinstance(doc_paths, list) else ([doc_paths] if doc_paths else None),
                raw_notes=raw_notes
            )
            
            self._log_trace(session_id, "OnboardingAgent", "BrandDNAProfiled", {
                "tenant_id": tenant_id,
                "company_name": company_name,
                "usp_count": len(dna.key_usp),
                "industry": dna.industry
            })
            
            return {
                "status": "success",
                "task_type": task_type,
                "tenant_id": tenant_id,
                "brand_dna": dna.dict()
            }

        if task_type in {"parse_documents", "ingest_client_files", "extract_documents"}:
            from collectors.document_collector import DocumentCollector
            doc_collector = DocumentCollector()
            
            file_paths = user_data.get("file_paths") or user_data.get("files") or user_data.get("documents") or []
            if isinstance(file_paths, str):
                file_paths = [file_paths]
                
            company_name = user_data.get("company_name", "Наша Компания")
            niche = user_data.get("niche", "Бизнес")
            
            extracted = doc_collector.extract_documents_batch(file_paths)
            indexed_count = await doc_collector.sync_documents_to_rag(company_name, niche, extracted, self.rag)
            dossier = doc_collector.synthesize_dossier_from_docs(extracted)
            
            self._log_trace(session_id, "DocumentCollector", "DocumentsParsed", {
                "files_count": len(file_paths),
                "indexed_chunks": indexed_count,
                "company": company_name
            })
            return {
                "status": "success",
                "extracted_documents": extracted,
                "rag_indexed_count": indexed_count,
                "synthesized_dossier": dossier
            }
            
        if task_type == "get_trends":
            from core.trend_scheduler import WeeklyTrendScheduler
            niche = user_data.get("niche", "IT и Автоматизация")
            scheduler = WeeklyTrendScheduler(self.redis_cache, self.vector_store)
            trends = await scheduler.get_trends_for_niche(niche)
            self._log_trace(session_id, "TrendHunter", "TrendsRetrieved", {"niche": niche})
            return {"status": "success", "trends": trends}

        if task_type == "prepare_holiday_greeting":
            from collectors.event_holiday_collector import EventHolidayCollector
            from skills.holiday_congratulator import HolidayCongratulatorSkill
            
            city = user_data.get("city", "Казань")
            country = user_data.get("country", "Россия")
            company_name = user_data.get("company_name", "Наша Компания")
            niche = user_data.get("niche", "Услуги")
            
            # 1. Сбор праздников через парсер
            collector = EventHolidayCollector()
            events = await collector.fetch_city_and_national_events(city, country)
            
            # 2. Сайга готовит поздравление и промокод
            congratulator = HolidayCongratulatorSkill()
            greeting = congratulator.generate_holiday_post(company_name, niche, city, events[0] if events else {})
            
            # 3. Tone of Voice Gatekeeper & Self-Healing Loop (автоматическое исправление)
            max_attempts = 2
            attempts = 0
            is_valid = False
            error_msg = None
            
            while not is_valid and attempts < max_attempts:
                attempts += 1
                is_valid, error_msg = SecurityGuard.validate_content_tone_of_voice(greeting.get("post_text", ""))
                if not is_valid:
                    print(f"[UnifiedOrchestrator] 🔄 Gatekeeper отклонил текст (попытка {attempts}): {error_msg}")
                    print(f"[UnifiedOrchestrator] 📨 Отправка текста автору (Сайге) на автономное самоисправление...")
                    healed_text = congratulator.saiga.self_heal_text(greeting.get("post_text", ""), error_msg)
                    greeting["post_text"] = healed_text
                else:
                    print(f"[UnifiedOrchestrator] 🛡️ Текст успешно валидирован Tone-of-Voice Gatekeeper (без стоп-слов и тавтологий).")
                    
            if not is_valid:
                print(f"[UnifiedOrchestrator] ❌ Не удалось автоматически исправить текст после {max_attempts} попыток.")
                return {"status": "retry_needed", "error": error_msg}
                
            self._log_trace(session_id, "HolidaySkill", "GreetingGenerated", {"city": city, "holiday": greeting.get("holiday_title")})
            return {"status": "success", "events": events, "prepared_greeting": greeting}

        if task_type in {"track_post_performance", "process_audience_feedback", "feedback_loop"}:
            from analytics.feedback_loop import FeedbackLoopEngine
            engine = FeedbackLoopEngine()
            
            publication_id = user_data.get("publication_id")
            comments = user_data.get("comments", [])
            views = user_data.get("views", 0)
            dislikes = user_data.get("dislikes", 0)
            shares = user_data.get("shares", 0)
            other_reactions = user_data.get("other_reactions", 0)
            platform = user_data.get("platform", "telegram")
            raw_reactions = user_data.get("reactions") or user_data.get("reactions_breakdown")
            comments_count = len(comments) if comments else user_data.get("comments_count", 0)
            
            # Расчет позитивности, чистого одобрения (NAI), взвешенного WPR и логарифмического Score с учетом мультиплатформенных реакций
            positivity = engine.calculate_positivity_metrics(
                views=views,
                likes=likes,
                dislikes=dislikes,
                comments=comments_count,
                shares=shares,
                other_reactions=other_reactions,
                platform=platform,
                raw_reactions=raw_reactions
            )
            er = positivity["engagement_rate"]
            nai = positivity["net_approval_index"]
            wpr = positivity["weighted_positivity_rate"]
            score = positivity["log_positivity_score"]
            grade = positivity["grade"]
            analysis = engine.analyze_comments(comments)
            
            # Сохранение в SQL (PublicationHistory & UserProfile)
            if self.db and publication_id:
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
                        print(f"[UnifiedOrchestrator] 📊 Метрики публикации #{publication_id} сохранены (Score: {score}, NAI: {nai}, WPR: {wpr}%, ER: {er}%).")
                except Exception as sql_e:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка сохранения метрик в SQL: {sql_e}")
            
            company_name = user_data.get("company_name", "UCust")
            niche = user_data.get("niche", "IT Automation")
            top_topics = user_data.get("top_topics", [])
            
            # Синхронизация инсайтов в RAG
            indexed_count = await engine.sync_feedback_to_rag(company_name, niche, analysis, top_topics, self.rag)
            adaptations = engine.generate_strategy_adaptations(top_topics, analysis)
            
            # Обновление стратегии в профиле SQL
            if self.db and (user_data.get("profile_id") or user_data.get("user_id")):
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
                except Exception as prof_e:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка обновления feedback_insights в SQL: {prof_e}")

            self._log_trace(session_id, "FeedbackLoopEngine", "FeedbackProcessed", {
                "er": er,
                "net_approval_index": nai,
                "weighted_positivity_rate": wpr,
                "log_positivity_score": score,
                "grade": grade,
                "objections": analysis.get("top_objections"),
                "questions": analysis.get("top_questions")
            })
            return {
                "status": "success",
                "positivity_metrics": positivity,
                "engagement_rate": er,
                "comments_analysis": analysis,
                "rag_indexed_count": indexed_count,
                "strategy_adaptations": adaptations
            }
            
        if task_type in {"plan_content", "generate_content_plan", "create_content_plan"}:
            from skills.content_strategy_engine import ContentStrategyEngine
            strat_engine = ContentStrategyEngine()
            
            # 1. Загрузка точного профиля из SQL
            company_name = user_data.get("company_name", "UCust")
            niche = user_data.get("niche", "IT Automation")
            city = user_data.get("city", "Москва")
            country = user_data.get("country", "Россия")
            visual_grid_dna = user_data.get("visual_grid_dna")
            feedback_insights = user_data.get("feedback_insights")

            if self.db and (user_data.get("user_id") or user_data.get("profile_id")):
                try:
                    profile_record = None
                    if user_data.get("profile_id"):
                        profile_record = self.db.query(UserProfile).filter(UserProfile.id == user_data["profile_id"]).first()
                    elif user_data.get("user_id"):
                        profile_record = self.db.query(UserProfile).filter(UserProfile.user_id == user_data["user_id"]).first()
                    
                    if profile_record:
                        company_name = profile_record.company_name or company_name
                        niche = profile_record.niche or niche
                        city = profile_record.city or city
                        country = profile_record.country or country
                        visual_grid_dna = profile_record.visual_grid_dna or visual_grid_dna
                        if not feedback_insights and profile_record.brand_dossier and isinstance(profile_record.brand_dossier, dict):
                            feedback_insights = profile_record.brand_dossier.get("feedback_insights")
                        print(f"[UnifiedOrchestrator] 🗄️ Профиль #{profile_record.id} ('{company_name}', {country}, г. {city}) успешно загружен из SQL БД для контент-плана.")
                except Exception as db_e:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка загрузки профиля из SQL: {db_e}")

            # 2. Семантический запрос в RAG по болям и триггерам аудитории
            rag_query_res = await self.rag.query_async(f"боли страхи возражения {company_name} {niche} {city}")
            rag_insights = {
                "pain_points": [c.text[:80] for c in rag_query_res.chunks] if rag_query_res.chunks else [
                    "Страх некачественного результата",
                    "Высокие цены и скрытые переплаты",
                    "Нехватка времени и сложный процесс"
                ],
                "context": rag_query_res.formatted_context
            }

            # 3. Синтез контент-плана с привязкой к 3x3 визуальной сетке, праздникам и обратной связи
            days_count = user_data.get("days_count", 7)
            start_date = user_data.get("start_date")
            content_plan = strat_engine.generate_content_plan(
                company_name=company_name,
                niche=niche,
                visual_grid_dna=visual_grid_dna,
                rag_insights=rag_insights,
                days_count=days_count,
                country=country,
                city=city,
                start_date=start_date,
                feedback_insights=feedback_insights
            )

            self._log_trace(session_id, "Agent_ContentStrategist", "ContentPlanGenerated", content_plan)
            print(f"[UnifiedOrchestrator] 📅 Контент-план на {days_count} дней успешно сгенерирован (Праздников внедрено: {content_plan.get('holidays_included_count', 0)})!")
            return {
                "status": "success",
                "content_plan": content_plan,
                "company_name": company_name,
                "niche": niche
            }

        if task_type == "generate_post":
            from skills.saiga_llm import SaigaLLMSkill
            from skills.advanced_visual_director import AdvancedVisualDirector
            from skills.photo_generator import PhotoGeneratorSkill
            
            # =========================================================================
            # КАСКАДНАЯ МАТРИЦА РАЗРЕШЕНИЯ КОНТЕКСТА (CASCADE FALLBACK RESOLUTION)
            # =========================================================================
            # 0. Извлечение расширенного контекста проекта (ProjectContext Enrichment)
            proj_ctx = user_data.get("project_context") or user_data.get("projectContext") or user_data.get("project") or {}
            if isinstance(proj_ctx, dict):
                company_name = proj_ctx.get("name") or proj_ctx.get("companyName") or user_data.get("company_name") or user_data.get("companyName") or "UCust"
                niche = proj_ctx.get("industry") or proj_ctx.get("niche") or user_data.get("niche") or "IT Automation / Сервис контента"
                city = proj_ctx.get("city") or user_data.get("city") or "Москва"
                tone = proj_ctx.get("toneOfVoice") or proj_ctx.get("tone_of_voice") or user_data.get("tone") or "Естественный и живой"
                if proj_ctx.get("description") and not user_data.get("usp"):
                    user_data["usp"] = proj_ctx.get("description")
                    user_data["description"] = proj_ctx.get("description")
                if proj_ctx.get("targetAudience") and not user_data.get("target_audience"):
                    user_data["target_audience"] = proj_ctx.get("targetAudience")
                if proj_ctx.get("socialLinks"):
                    user_data["social_links"] = proj_ctx.get("socialLinks")
                if proj_ctx.get("businessHours"):
                    user_data["business_hours"] = proj_ctx.get("businessHours")
                if proj_ctx.get("logoUrl"):
                    user_data["logo_url"] = proj_ctx.get("logoUrl")
                if proj_ctx.get("brandColors") and not user_data.get("brand_colors"):
                    user_data["brand_colors"] = proj_ctx.get("brandColors")
                if (proj_ctx.get("id") or proj_ctx.get("projectId")) and not user_data.get("project_id"):
                    user_data["project_id"] = proj_ctx.get("id") or proj_ctx.get("projectId")
                if proj_ctx.get("brandGuidelines"):
                    bg = proj_ctx.get("brandGuidelines")
                    if isinstance(bg, dict):
                        user_data["brand_guidelines"] = bg
                        if bg.get("forbiddenWords"):
                            user_data["forbidden_words"] = bg.get("forbiddenWords")
                        if bg.get("mandatoryPhrases"):
                            user_data["mandatory_phrases"] = bg.get("mandatoryPhrases")
                        if bg.get("addressingStyle"):
                            user_data["addressing_style"] = bg.get("addressingStyle")
                if proj_ctx.get("visualDna"):
                    vd = proj_ctx.get("visualDna")
                    if isinstance(vd, dict):
                        user_data["visual_dna"] = vd
                        if vd.get("brandColors") and not user_data.get("brand_colors"):
                            user_data["brand_colors"] = vd.get("brandColors")
                        if vd.get("moodKeywords") and not user_data.get("mood_keywords"):
                            user_data["mood_keywords"] = vd.get("moodKeywords")
                        if vd.get("visualStyle") and not user_data.get("visual_style"):
                            user_data["visual_style"] = vd.get("visualStyle")
                if proj_ctx.get("productsCatalog"):
                    user_data["products_catalog"] = proj_ctx.get("productsCatalog")
                if proj_ctx.get("keyBenefits"):
                    user_data["key_benefits"] = proj_ctx.get("keyBenefits")
                if proj_ctx.get("locations"):
                    user_data["locations"] = proj_ctx.get("locations")
                if proj_ctx.get("deliveryInfo"):
                    user_data["delivery_info"] = proj_ctx.get("deliveryInfo")
                if proj_ctx.get("language"):
                    user_data["language"] = proj_ctx.get("language")
                if proj_ctx.get("recentPostTopics"):
                    user_data["recent_post_topics"] = proj_ctx.get("recentPostTopics")
            else:
                tone = user_data.get("tone", "Естественный и живой")
                niche = user_data.get("niche", "IT Automation / Сервис контента")
                city = user_data.get("city", "Москва")
                company_name = user_data.get("company_name") or user_data.get("companyName") or "UCust"


            format_type = user_data.get("format", "post")
            offer = user_data.get("offer") or user_data.get("promo") or user_data.get("promoCode") or user_data.get("promo_code") or user_data.get("discount") or user_data.get("bonus")
            should_gen_image = user_data.get("generate_image", True) or format_type in ["post", "photo"]


            # 1. ТЕМАТИЧЕСКИЙ КАСКАД (User Prompt -> Content Plan Stack -> RAG / Auto Topic)
            user_prompt = user_data.get("prompt") or user_data.get("topic")
            plan_slot_topic = None
            if not user_prompt:
                active_plan = user_data.get("content_plan")
                if active_plan and isinstance(active_plan, dict) and active_plan.get("days"):
                    current_day_idx = int(user_data.get("plan_day_index", 0))
                    days_list = active_plan.get("days", [])
                    if current_day_idx < len(days_list):
                        slot = days_list[current_day_idx]
                        plan_slot_topic = slot.get("topic") or slot.get("title") or slot.get("hook")
                        if not offer and slot.get("cta_offer"):
                            offer = slot.get("cta_offer")
                        print(f"[CascadeResolver] 📅 Тема извлечена из слота #{current_day_idx+1} контент-плана: '{plan_slot_topic}'")

            prompt = user_prompt or plan_slot_topic or f"Специальное предложение и экспертиза в нише {niche}"
            if user_prompt:
                print(f"[CascadeResolver] 🎯 Приоритет 1 (Ручной ввод пользователя): '{prompt}'")
            elif plan_slot_topic:
                print(f"[CascadeResolver] 🎯 Приоритет 2 (Стек контент-плана): '{prompt}'")
            else:
                print(f"[CascadeResolver] 🎯 Приоритет 3 (Автопилот Сайги): '{prompt}'")

            # 1.1 Семантическая дедупликация и защита от повторов (Audit Agent)
            from skills.audit_deduplication_agent import AuditDeduplicationAgent
            recent_topics = user_data.get("recent_post_topics") or user_data.get("recent_topics") or []
            audit_agent = AuditDeduplicationAgent(custom_threshold=0.82)
            rubric_val = user_data.get("rubric", "general")
            dedup_verdict = audit_agent.evaluate_uniqueness(
                proposed_topic_or_text=prompt,
                recent_channel_posts=recent_topics,
                topic_category=rubric_val.lower() if isinstance(rubric_val, str) else "general"
            )
            original_prompt = prompt
            if dedup_verdict.is_duplicate and dedup_verdict.suggested_shifted_angle:
                print(f"[UnifiedOrchestrator] 🚫 [AuditAgent] Обнаружен дубль темы ({dedup_verdict.similarity_score} >= {audit_agent.threshold}). Сдвиг угла подачи: '{dedup_verdict.suggested_shifted_angle}'")
                prompt = f"{prompt} — {dedup_verdict.suggested_shifted_angle}"

            aspect_ratio = user_data.get("aspect_ratio")
            if not aspect_ratio:
                fmt_lower = format_type.lower()
                if any(k in fmt_lower for k in ["story", "stories", "reels", "shorts", "клип", "истори"]):
                    aspect_ratio = "9:16"
                elif any(k in fmt_lower for k in ["cover", "article", "youtube", "banner", "обложк", "стать"]):
                    aspect_ratio = "16:9"
                else:
                    aspect_ratio = "1:1"

            # 2. Загрузка точного профиля из SQL (если передан user_id / profile_id)
            if self.db and (user_data.get("user_id") or user_data.get("profile_id")):
                try:
                    profile_record = None
                    if user_data.get("profile_id"):
                        profile_record = self.db.query(UserProfile).filter(UserProfile.id == user_data["profile_id"]).first()
                    elif user_data.get("user_id"):
                        profile_record = self.db.query(UserProfile).filter(UserProfile.user_id == user_data["user_id"]).first()
                    
                    if profile_record:
                        company_name = profile_record.company_name or company_name
                        niche = profile_record.niche or niche
                        city = profile_record.city or city
                        if profile_record.step1 and isinstance(profile_record.step1, dict):
                            tone = profile_record.step1.get("voice_and_tone", tone) if not user_data.get("tone") else tone
                            if not user_data.get("brand_colors") and profile_record.step1.get("brand_colors"):
                                user_data["brand_colors"] = profile_record.step1.get("brand_colors")
                        if profile_record.visual_grid_dna:
                            user_data["visual_grid_dna"] = profile_record.visual_grid_dna
                            if not user_data.get("brand_colors"):
                                user_data["brand_colors"] = profile_record.visual_grid_dna.get("brand_hex_palette", [])
                        print(f"[UnifiedOrchestrator] 🗄️ Профиль #{profile_record.id} ('{company_name}') успешно загружен из SQL БД для генерации.")
                except Exception as sql_e:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка загрузки профиля из SQL: {sql_e}")

            # 2.1 Pre-Flight Context Router (4-Квадрантная классификация, Bridge Mode и блокировка воронки)
            from skills.context_router import ContextRouterSkill
            router = ContextRouterSkill()
            routing_directive = router.route_task(
                topic=prompt,
                company_name=company_name,
                niche=niche,
                user_data=user_data
            )
            tenant_id = routing_directive.tenant_id

            # 2.2 Семантический RAG-поиск с Multi-Tenant изоляцией и Pre-Flight контроль DRS
            from skills.data_richness_engine import DataRichnessEngine, DRSTier
            rag_fact_context = None
            drs_assessment = None
            data_richness_score = 0.20
            try:
                rag_query_text = f"{prompt} {niche} {company_name} {offer or ''}"
                rag_ctx = await self.rag.query_async(rag_query_text, tenant_id=tenant_id)
                if rag_ctx and (rag_ctx.has_sufficient_context or rag_ctx.formatted_context):
                    rag_fact_context = rag_ctx.formatted_context
                    drs_assessment = DataRichnessEngine.evaluate_text(rag_fact_context, company_name=company_name)
                    data_richness_score = drs_assessment.total_score / 100.0
                    print(f"[UnifiedOrchestrator] 📚 RAG контекст: {len(rag_fact_context)} симв. | DRS Score: {drs_assessment.total_score}/100 ({drs_assessment.tier.value.upper()}) | {drs_assessment.recommendation}")
                else:
                    # Агрегируем бриф, оффер и данные анкеты профиля для полноценной оценки плотности
                    profile_parts = [prompt]
                    if company_name and company_name != "Клиент":
                        profile_parts.append(f"Компания: {company_name}")
                    if niche:
                        profile_parts.append(f"Ниша: {niche}")
                    if offer:
                        profile_parts.append(f"Оффер: {offer}")
                    if isinstance(user_data, dict):
                        for k, v in user_data.items():
                            if isinstance(v, str) and v:
                                profile_parts.append(f"{k}: {v}")
                            elif isinstance(v, dict):
                                for sub_k, sub_v in v.items():
                                    if sub_v and isinstance(sub_v, str):
                                        profile_parts.append(f"{sub_k}: {sub_v}")
                    combined_brief = "\n".join(profile_parts)
                    drs_assessment = DataRichnessEngine.evaluate_text(combined_brief, company_name=company_name)
                    data_richness_score = drs_assessment.total_score / 100.0
                    print(f"[DataRichnessGate] ℹ️ Плотность данных профиля/брифа: {drs_assessment.total_score}/100 ({drs_assessment.tier.value.upper()}). {drs_assessment.recommendation}")
            except Exception as rag_err:
                print(f"[UnifiedOrchestrator] ⚠️ RAG query error: {rag_err}")
            
            print(f"[UnifiedOrchestrator] ✍️ Генерация поста для темы: '{prompt}', компания: '{company_name}', ниша: '{niche}', формат: {format_type}, тон: {tone}")
            
            # 1. Формирование маркетинговой директивы (5 Ступеней Ханта, JTBD, Value Ladder, Fogg CTA, Фреймворки)
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
                raw_feature=prompt
            )
            
            print(f"[UnifiedOrchestrator] 🎯 Воронка Ханта: {hunt_stage_enum.value.upper()} | Фреймворк: {framework_enum.value} | Триггер: {trigger_enum.value}")

            # 2. Visual-First Directing: Предварительный синтез визуального сюжета (Арт-директор)
            variation_index = int(user_data.get("variation_index", 0))
            custom_visual_prompt = user_data.get("custom_prompt") or user_data.get("positive_prompt")
            
            # Если выполнен Multi-Image Fusion — используем синтезированный Fusion-промпт
            if not custom_visual_prompt and moondream_analysis and moondream_analysis.get("fusion_prompt"):
                custom_visual_prompt = moondream_analysis["fusion_prompt"]
                print(f"[UnifiedOrchestrator] 🧩 Применен композиционный Fusion-промпт для 3 нод ComfyUI:\n  👉 {custom_visual_prompt}")

            from skills.photo_generator import CinematographyDirector
            brand_colors_input = user_data.get("brand_colors") or (moondream_analysis.get("colors") if moondream_analysis else None)
            cinematic_concept = CinematographyDirector.compose_cinematic_prompt(
                topic=prompt,
                niche=niche,
                brand_colors=brand_colors_input,
                variation_index=variation_index,
                routing=routing_directive,
                brand_props=user_data.get("brand_props") or user_data.get("visual_anchors"),
                brand_profile=user_data.get("brand_profile")
            )
            
            # Контекст визуала для копирайтера (Сайги), чтобы текст 100% совпадал с картинкой
            visual_scene_context_for_saiga = (
                f"Ключевой визуальный сюжет фотосессии: {cinematic_concept.get('prompt', '')[:250]}. "
                f"Ракурс: {cinematic_concept.get('perspective', '')}. "
                f"Световая схема: {cinematic_concept.get('lighting_scheme', '')}. "
                f"Опирайся на этот визуал, чтобы текст поста идеально гармонировал с кадром."
            )
            if moondream_analysis and moondream_analysis.get("visual_context_for_llm"):
                visual_scene_context_for_saiga += f" | {moondream_analysis['visual_context_for_llm']}"

            extracted_matrix = None
            if moondream_analysis:
                if moondream_analysis.get("items") and len(moondream_analysis["items"]) > 0:
                    extracted_matrix = moondream_analysis["items"][0].get("structured_matrix")
                elif moondream_analysis.get("structured_matrix"):
                    extracted_matrix = moondream_analysis.get("structured_matrix")

            saiga = SaigaLLMSkill()
            comments_ctx = user_data.get("comments") or user_data.get("comments_context") or user_data.get("top_objections_from_comments")
            audience_q = user_data.get("audience_questions") or user_data.get("top_audience_questions")
            brand_profile = user_data.get("brand_profile")

            # 3. Асинхронные параллельные задачи: Генерация текста + Диффузия фото (GPU Parallel)
            t_pipeline_start = time.time()
            async def _generate_text_pipeline():
                t_text_start = time.time()
                # 3.1 Генерация SMM текста в Сайге
                gen_res = saiga.generate_smm_post(
                    topic=prompt,
                    company_name=company_name,
                    niche=niche,
                    city=city,
                    tone=tone,
                    format_type=format_type,
                    visual_context=visual_scene_context_for_saiga,
                    comments_context=comments_ctx,
                    audience_questions=audience_q,
                    comments_enabled=bool(user_data.get("comments_enabled", False)),
                    brand_profile=brand_profile,
                    rag_context=rag_fact_context,
                    marketing_directive=marketing_bundle,
                    routing=routing_directive,
                    products_catalog=user_data.get("products_catalog"),
                    key_benefits=user_data.get("key_benefits"),
                    brand_guidelines=user_data.get("brand_guidelines"),
                    locations=user_data.get("locations"),
                    rubric=user_data.get("rubric"),
                    primary_cta=user_data.get("primary_cta"),
                    language=user_data.get("language", "ru"),
                    vision_matrix=extracted_matrix
                )
                p_text = gen_res.get("post_text", "")
                
                # 3.2 Валидация качества (Gatekeeper + Critic Munger)
                custom_forb = user_data.get("forbidden_words")
                from skills.critic_munger import CriticMungerSkill
                is_valid, error_msg = SecurityGuard.validate_content_tone_of_voice(p_text, custom_forbidden_words=custom_forb)
                if not is_valid:
                    p_text = saiga.self_heal_text(p_text, error_msg or "", routing=routing_directive)
                    
                critic = CriticMungerSkill(strictness=0.80)
                critic_res = critic.review_content(p_text, topic=prompt, target_audience=niche, routing=routing_directive)
                
                MAX_HEALING_RETRIES = 2
                healing_attempts = 0
                while not critic_res.get("passed") and healing_attempts < MAX_HEALING_RETRIES:
                    healing_attempts += 1
                    print(f"[UnifiedOrchestrator] 🛡️ Агент-Критик отклонил черновик (Итерация {healing_attempts}/{MAX_HEALING_RETRIES}, Score={critic_res['score']}): {critic_res['criticism']}. Запуск самоисправления...")
                    p_text = saiga.self_heal_text(p_text, critic_res.get("actionable_feedback", ""), routing=routing_directive)
                    is_valid, error_msg = SecurityGuard.validate_content_tone_of_voice(p_text, custom_forbidden_words=custom_forb)
                    if not is_valid:
                        p_text = saiga.self_heal_text(p_text, error_msg or "", routing=routing_directive)
                    critic_res = critic.review_content(p_text, topic=prompt, target_audience=niche, routing=routing_directive)


                t_text_duration = round(max(0.05, time.time() - t_text_start), 2)
                return {
                    "gen_result": gen_res,
                    "post_text": p_text,
                    "critic_res": critic_res,
                    "t_text_duration": t_text_duration
                }

            async def _generate_photo_pipeline():
                if not should_gen_image:
                    return None
                try:
                    t_photo_start = time.time()
                    photo_skill = PhotoGeneratorSkill()

                    # Упорядочивание вложений по слотам Realism 2.0 (Node 55, 64, 65)
                    ordered_atts = user_data.get("attachments")
                    if moondream_analysis and moondream_analysis.get("slot_mapping"):
                        sm = moondream_analysis["slot_mapping"]
                        cand_ordered = [
                            sm.get("image1_node55", {}).get("raw_path"),
                            sm.get("image2_node64", {}).get("raw_path"),
                            sm.get("image3_node65", {}).get("raw_path")
                        ]
                        valid_ordered = [c for c in cand_ordered if c is not None]
                        if valid_ordered:
                            ordered_atts = valid_ordered

                    photo_res = await photo_skill.generate_photo(
                        topic=prompt,
                        niche=niche,
                        aspect_ratio=aspect_ratio,
                        company_name=company_name,
                        brand_colors=brand_colors_input,
                        attachments=ordered_atts,
                        custom_prompt=custom_visual_prompt,
                        variation_index=variation_index,
                        routing=routing_directive,
                        brand_props=user_data.get("brand_props") or user_data.get("visual_anchors"),
                        brand_profile=brand_profile
                    )
                    image_url = photo_res.get("image_url")
                    t_photo_duration = round(time.time() - t_photo_start, 2) if image_url else None
                    return {
                        "photo_res": photo_res,
                        "image_url": image_url,
                        "photo_prompt": photo_res.get("positive_prompt") or "",
                        "t_photo_duration": t_photo_duration
                    }
                except Exception as ex:
                    print(f"[UnifiedOrchestrator] ⚠️ Ошибка параллельной генерации фото: {ex}")
                    return None

            print("[UnifiedOrchestrator] ⚡ Параллельный запуск генерации: Сайга (Текст + Pre-Mortem) ⨂ ComfyUI (Фото)")
            text_pipeline_res, photo_pipeline_res = await asyncio.gather(
                _generate_text_pipeline(),
                _generate_photo_pipeline()
            )

            gen_result = text_pipeline_res["gen_result"]
            post_text = text_pipeline_res["post_text"]
            critic_res = text_pipeline_res["critic_res"]
            t_text_duration = text_pipeline_res["t_text_duration"]

            image_url = None
            t_photo_duration = None
            photo_prompt = ""
            if photo_pipeline_res:
                image_url = photo_pipeline_res.get("image_url")
                t_photo_duration = photo_pipeline_res.get("t_photo_duration")
                photo_prompt = photo_pipeline_res.get("photo_prompt", "")
                photo_res = photo_pipeline_res.get("photo_res", {})

                # Сохранение финального промпта фото в RAG (категория photo_generation_history)
                if photo_prompt:
                    try:
                        from rag.models import Document
                        photo_id = os.path.splitext(os.path.basename(photo_res.get("file_path", "")))[0] if photo_res.get("file_path") else str(uuid.uuid4())[:8]
                        prompt_doc = Document(
                            doc_id=f"visual_prompt_{photo_id}",
                            text=(
                                f"Финальный промпт генерации фото для компании {company_name} (Ниша: {niche}):\n"
                                f"Тема: {prompt}\n"
                                f"Положительный промпт ComfyUI: {photo_prompt}\n"
                                f"Отрицательный промпт ComfyUI: {photo_res.get('negative_prompt', '')}\n"
                                f"Цвета бренда: {user_data.get('brand_colors', [])}\n"
                                f"Соотношение сторон: {aspect_ratio}\n"
                                f"Путь к файлу: {photo_res.get('file_path', '')}"
                            ),
                            metadata={
                                "category": "photo_generation_history",
                                "company_name": company_name,
                                "user_id": user_data.get("user_id"),
                                "file_path": photo_res.get("file_path", "")
                            }
                        )
                        await self.rag.ingest_documents_async([prompt_doc])
                        print(f"[UnifiedOrchestrator] 📚 Финальный фото-промпт успешно сохранен в RAG-память бренда.")
                    except Exception as rag_p_err:
                        print(f"[UnifiedOrchestrator] ⚠️ Ошибка сохранения промпта фото в RAG: {rag_p_err}")

            # 4. Очистка текста для пользователя (строго без хэштегов в теле поста)
            clean_user_post_text = "\n".join([
                line for line in post_text.strip().splitlines()
                if not line.strip().startswith("#") and not line.strip().startswith("🏷️ Хэштеги")
            ]).strip()

            # 5. Комплексное обогащение для Telegram (Expandable Blockquotes, <code>, <s>, <tg-spoiler>, Inline Buttons)
            from skills.telegram_rich_formatter import TelegramRichPostFormatter
            
            promo_val = gen_result.get("promo_code") or user_data.get("promo_code") or user_data.get("discount")
            rich_tg_data = TelegramRichPostFormatter.build_rich_telegram_post(
                text=clean_user_post_text,
                company_name=company_name,
                niche=niche,
                promo_code=promo_val,
                website_url=user_data.get("target_action_link") or user_data.get("website") or user_data.get("website_url") or (user_data.get("social_links", {}).get("website") if isinstance(user_data.get("social_links"), dict) else None),
                contacts=user_data.get("contacts"),
                social_links=user_data.get("social_links"),
                enable_expandable_blockquote=user_data.get("expandable_blockquote", True),
                enable_clickable_promo=user_data.get("enable_clickable_promo", True),
                enable_strikethrough=user_data.get("enable_strikethrough", True),
                enable_spoilers=user_data.get("enable_spoilers", True),
                enable_buttons=user_data.get("enable_buttons", True),
                cta_type=user_data.get("primary_cta") or user_data.get("cta_type", "general")
            )

            
            post_text_html = rich_tg_data["html_text"]
            post_text_tg_md = rich_tg_data["markdown_v2_text"]
            expandable_blocks = rich_tg_data["expandable_blocks"]
            reply_markup = rich_tg_data["reply_markup"]
            link_preview_opts = rich_tg_data["link_preview_options"]
            features_applied = rich_tg_data["features_applied"]

            hashtags_str = gen_result.get("hashtags", f"#{niche.replace(' ', '_')} #бизнес #качество")

            # 6. Опциональная авто-публикация
            publish_res = None
            if user_data.get("publish") or user_data.get("target_channel"):
                from publishers.achievement_broadcaster import AchievementBroadcaster
                target_ch = user_data.get("target_channel") or user_data.get("channel") or "@testaipublisher"
                broadcaster = AchievementBroadcaster(target_channel=target_ch)
                
                # Проверка: запросил ли пользователь коллаж явно
                as_collage_flag = TelegramRichPostFormatter.is_collage_requested(prompt=prompt, user_data=user_data)
                
                # Определение медиа: список вложений или сгенерированное фото
                pub_media = user_data.get("attachments") or user_data.get("photos") or image_url
                
                publish_text = post_text_html
                publish_res = await broadcaster.publish_post_async(
                    post_text=publish_text,
                    media_path=pub_media,
                    timings={
                        "text_gen_seconds": t_text_duration,
                        "photo_gen_seconds": t_photo_duration,
                        "total_seconds": round(time.time() - t_pipeline_start, 2)
                    },
                    hashtags=hashtags_str,
                    category=user_data.get("category", "Обновление"),
                    target_channel=target_ch
                )

            self._log_trace(session_id, "SaigaCopywriter", "PostGenerated", {"topic": prompt, "format": format_type})
            return {
                "status": "success",
                "text": clean_user_post_text,
                "post_text": clean_user_post_text,
                "post_text_html": post_text_html,
                "post_text_tg_markdown": post_text_tg_md,
                "reply_markup": reply_markup,
                "link_preview_options": link_preview_opts,
                "features_applied": features_applied,
                "expandable_blocks": expandable_blocks,
                "has_expandable_blockquote": bool(expandable_blocks),
                "promo_code": gen_result.get("promo_code"),
                "photo_prompt": photo_prompt,
                "image_url": image_url,
                "photo_url": image_url,
                "hashtags": hashtags_str,
                "confidence_score": 0.96,
                "format": format_type,
                "tone": tone,
                "critic_review": critic_res,
                "deduplication_verdict": {
                    "is_duplicate": dedup_verdict.is_duplicate,
                    "similarity_score": dedup_verdict.similarity_score,
                    "original_topic": original_prompt,
                    "suggested_shifted_angle": dedup_verdict.suggested_shifted_angle,
                    "reason": dedup_verdict.reason
                },
                "moondream_analysis": moondream_analysis,
                "publish_result": publish_res,
                "timings": {
                    "text_gen_seconds": t_text_duration,
                    "photo_gen_seconds": t_photo_duration,
                    "total_seconds": round(time.time() - t_pipeline_start, 2)
                }
            }

        if task_type in ["generate_image", "generate_photo", "edit_photo", "regenerate_image", "regenerate_photo", "re-generate"]:
            from skills.photo_generator import PhotoGeneratorSkill
            
            prompt = user_data.get("prompt") or user_data.get("topic") or "Специальное предложение"
            niche = user_data.get("niche", "Бизнес")
            aspect_ratio = user_data.get("aspect_ratio", "1:1")
            style = user_data.get("style", "photorealistic")
            brand_colors = user_data.get("brand_colors") or (moondream_analysis.get("colors") if moondream_analysis else None)
            company_name = user_data.get("company_name", "UCust")
            attachments = user_data.get("attachments") or user_data.get("images")
            
            # Поддержка перегенерации с вариацией интерьера, ракурса и освещения
            variation_index = int(user_data.get("variation_index", 1 if "regenerate" in task_type else 0))
            
            # Обогащение промпта от Сайги, если запрос от пользователя короткий
            photo_skill = PhotoGeneratorSkill()
            custom_prompt = user_data.get("custom_prompt") or user_data.get("positive_prompt")
            
            # Поддержка Multi-Image Semantic Fusion
            if not custom_prompt and moondream_analysis and moondream_analysis.get("fusion_prompt"):
                custom_prompt = moondream_analysis["fusion_prompt"]
                print(f"[UnifiedOrchestrator] 🧩 Применен Fusion-промпт для edit_photo/generate_photo:\n  👉 {custom_prompt}")

            ordered_attachments = attachments
            if moondream_analysis and moondream_analysis.get("slot_mapping"):
                sm = moondream_analysis["slot_mapping"]
                cand_ordered = [
                    sm.get("image1_node55", {}).get("raw_path"),
                    sm.get("image2_node64", {}).get("raw_path"),
                    sm.get("image3_node65", {}).get("raw_path")
                ]
                valid_ordered = [c for c in cand_ordered if c is not None]
                if valid_ordered:
                    ordered_attachments = valid_ordered

            photo_res = await photo_skill.generate_photo(
                topic=prompt,
                niche=niche,
                aspect_ratio=aspect_ratio,
                brand_colors=brand_colors,
                style=style,
                company_name=company_name,
                attachments=ordered_attachments,
                custom_prompt=custom_prompt,
                variation_index=variation_index
            )
            photo_res["moondream_analysis"] = moondream_analysis
            photo_res["variation_index"] = variation_index
            
            action_name = "PhotoRegenerated" if "regenerate" in task_type else "PhotoCreated"
            self._log_trace(session_id, "PhotoGenerator", action_name, {
                "topic": prompt,
                "aspect_ratio": aspect_ratio,
                "variation_index": variation_index,
                "edit_mode": bool(attachments and len(attachments) > 0),
                "attachments_count": len(attachments) if attachments else 0
            })
            return photo_res

        if task_type in ["analyze_competitor", "competitive_intel"]:
            from skills.competitive_intel import CompetitiveIntelSkill
            url = user_data.get("url") or user_data.get("competitor_url") or ""
            niche = user_data.get("niche", "")
            intel = CompetitiveIntelSkill()
            res = await intel.analyze_competitor_async(url, my_company_niche=niche)
            self._log_trace(session_id, "CompetitiveIntelAnalyst", "CompetitorAnalyzed", {
                "competitor_url": url,
                "status": res.get("status")
            })
            return res

        if task_type in ["generate_strategy", "content_strategy"]:
            from skills.content_strategy_engine import ContentStrategyEngine
            company_name = user_data.get("company_name", "UCust")
            niche = user_data.get("niche", "Бизнес")
            target_audience = user_data.get("target_audience", "")
            usp = user_data.get("usp", "")
            engine = ContentStrategyEngine()
            strat_res = engine.generate_strategy(company_name, niche, target_audience, usp)
            self._log_trace(session_id, "ContentStrategyEngine", "StrategyGenerated", {
                "company_name": company_name,
                "niche": niche
            })
            return strat_res

        if task_type in ["critic_review", "review_content"]:
            from skills.critic_munger import CriticMungerSkill
            text = user_data.get("text") or user_data.get("content") or ""
            topic = user_data.get("topic", "")
            niche = user_data.get("niche", "")
            strictness = float(user_data.get("strictness", 0.85))
            critic = CriticMungerSkill(strictness=strictness)
            review = critic.review_content(text, topic=topic, target_audience=niche)
            self._log_trace(session_id, "Agent_Critic_Munger", "ManualReviewCompleted", review)
            return {
                "status": "success",
                "review": review
            }

        if task_type in ["publish_post", "publish_content", "publish_showcase"]:
            from publishers.achievement_broadcaster import AchievementBroadcaster
            post_text = user_data.get("post_text") or user_data.get("text") or ""
            media_path = user_data.get("media_path") or user_data.get("image_url") or user_data.get("photo_url")
            timings = user_data.get("timings")
            hashtags = user_data.get("hashtags")
            category = user_data.get("category", "Обновление")
            target_ch = user_data.get("target_channel") or user_data.get("channel") or "@testaipublisher"
            
            broadcaster = AchievementBroadcaster(target_channel=target_ch)
            res = await broadcaster.publish_post_async(
                post_text=post_text,
                media_path=media_path,
                timings=timings,
                hashtags=hashtags,
                category=category,
                target_channel=target_ch
            )
            self._log_trace(session_id, "AchievementBroadcaster", "PostPublished", res)
            return res

        if task_type in ["broadcast_achievement", "post_milestone"]:
            from publishers.achievement_broadcaster import AchievementBroadcaster
            title = user_data.get("title", "Новое достижение UCust AI")
            desc = user_data.get("description") or user_data.get("desc", "Команда ИИ-агентов завершила важный этап.")
            metrics = user_data.get("metrics", [])
            media_path = user_data.get("media_path") or user_data.get("media")
            channel = user_data.get("channel", "@UcustAi")
            
            broadcaster = AchievementBroadcaster(target_channel=channel)
            res = await broadcaster.broadcast_milestone_async(
                title=title,
                description=desc,
                metrics=metrics,
                media_path=media_path
            )
            self._log_trace(session_id, "AchievementBroadcaster", "MilestoneBroadcasted", res)
            return res

        if task_type == "rag_query":
            from rag.pipeline import CleanRAGPipeline
            query_text = user_data.get("query", "")
            rag = CleanRAGPipeline(min_confidence_threshold=0.65)
            rag_res = await rag.query_async(query_text)
            return {
                "status": "success",
                "query": query_text,
                "has_sufficient_context": rag_res.has_sufficient_context,
                "context": rag_res.formatted_context,
                "top_score": rag_res.top_score,
                "fallback_message": rag_res.fallback_message
            }

        if task_type in ["get_graph_data", "graph_data", "metrics"]:
            metrics = self.get_frontend_graph_data()
            return {"status": "success", "task_type": task_type, "metrics": metrics}

        return {"status": "error", "message": f"Неизвестная задача '{task_type}'"}

    def get_frontend_graph_data(self) -> List[dict]:
        """
        Безопасная отдача данных фронтенду для графиков.
        Гарантирует, что исходники БД никогда не утекут напрямую.
        """
        print("\n[UnifiedOrchestrator] 📊 Фронтенд запросил данные для графов...")
        
        # Моделируем агрегированный запрос к БД
        # SELECT niche, count(*) FROM user_profiles GROUP BY niche;
        mock_raw_db_data = [
            {"niche": "IT Automation", "count": 15, "secret_id": "sys_999", "pass_hash": "xxx"},
            {"niche": "Beauty SMM", "count": 8, "secret_id": "sys_123", "pass_hash": "yyy"}
        ]
        
        # 2. Очистка данных перед отдачей клиенту (Data Loss Prevention)
        safe_data = SecurityGuard.sanitize_graph_data(mock_raw_db_data)
        print(f"[UnifiedOrchestrator] 🛡️ Данные очищены: {safe_data}")
        return safe_data


from enum import Enum

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
            res = await self.unified.execute_task("onboarding", user_data)
            return context
        except Exception:
            return context


def build_default_orchestrator(database=None):
    return AgentOrchestrator(database=database)


__all__ = [
    "UnifiedOrchestrator",
    "SecurityGuard",
    "AgentState",
    "AgentOrchestrator",
    "build_default_orchestrator"
]
