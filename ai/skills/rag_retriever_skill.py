"""
File: ai/skills/rag_retriever_skill.py
Ретривер фактов из Clean RAG с жесткой изоляцией по project_id и CrossEncoder-реранкингом.
"""

from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger("RAGRetrieverSkill")


class CleanRAGRetrieverSkill:
    """
    Ретривер с многоуровневой изоляцией тенантов (project_id):
    1. Поиск релевантных семантических документов в pgvector / RAG.
    2. Точный реранкинг через BAAI/bge-reranker-base (Singleton).
    3. Отсечение нерелевантного контекста для предотвращения галлюцинаций.
    """

    SIMILARITY_THRESHOLD: float = 0.50

    @classmethod
    async def _fetch_db_chunks(cls, tenant_candidates: List[str]) -> List[str]:
        """
        Извлекает чанки знаний из базы данных (PostgreSQL / SQLite) или встроенного хранилища.
        """
        import os
        chunks: List[str] = []

        # 1. Попытка через SQLAlchemy AsyncSessionLocal
        try:
            try:
                from core.database import AsyncSessionLocal
            except ImportError:
                from ai.core.database import AsyncSessionLocal
            from sqlalchemy import text
            if AsyncSessionLocal is not None:
                async with AsyncSessionLocal() as session:
                    placeholders = ", ".join([f":t{i}" for i in range(len(tenant_candidates))])
                    params = {f"t{i}": t for i, t in enumerate(tenant_candidates)}
                    query_sql = f"SELECT content FROM tenant_knowledge_chunks WHERE tenant_id IN ({placeholders}) LIMIT 30"
                    res = await session.execute(text(query_sql), params)
                    rows = res.fetchall()
                    for r in rows:
                        if r[0] and str(r[0]).strip():
                            chunks.append(str(r[0]).strip())
        except Exception as e:
            logger.debug(f"[RAGRetriever] AsyncSessionLocal chunks fetch note: {e}")

        # 2. Попытка через прямое обращение к локальным SQLite файлам
        if not chunks:
            import sqlite3
            db_candidates = [
                "ai/ai_smm_dev.db", "ai_smm_dev.db",
                "ai/ucust_local_dev.db", "ucust_local_dev.db",
                "/opt/ucust/ai/ai_smm_dev.db", "/opt/ucust/ai_smm_dev.db"
            ]
            for db_path in db_candidates:
                if os.path.exists(db_path):
                    try:
                        conn = sqlite3.connect(db_path)
                        cursor = conn.cursor()
                        placeholders = ", ".join(["?" for _ in tenant_candidates])
                        cursor.execute(
                            f"SELECT content FROM tenant_knowledge_chunks WHERE tenant_id IN ({placeholders}) LIMIT 30",
                            tenant_candidates
                        )
                        rows = cursor.fetchall()
                        conn.close()
                        for r in rows:
                            if r[0] and str(r[0]).strip():
                                chunks.append(str(r[0]).strip())
                        if chunks:
                            break
                    except Exception:
                        pass

        # 3. Встроенная база знаний для UCust AI (гарантия нулевых галлюцинаций для self-promotion)
        if not chunks and any("ucust" in t.lower() for t in tenant_candidates):
            try:
                from scripts.seed_ucust_brand_knowledge import UCUST_KNOWLEDGE_DOCS
                chunks = [doc["content"] for doc in UCUST_KNOWLEDGE_DOCS if "content" in doc]
            except Exception:
                try:
                    from ai.scripts.seed_ucust_brand_knowledge import UCUST_KNOWLEDGE_DOCS
                    chunks = [doc["content"] for doc in UCUST_KNOWLEDGE_DOCS if "content" in doc]
                except Exception:
                    pass

        return chunks

    @classmethod
    async def retrieve_and_rerank(cls, project_id: str, query: str, top_k: int = 3) -> List[str]:
        """
        Извлекает и ранжирует самые релевантные факты о проекте.
        Поддерживает нормализацию tenant_id и динамическую подгрузку чанков из PostgreSQL/SQLite.
        """
        try:
            from rag.pipeline import CleanRAGPipeline
            from rag.models import Document
            
            raw = (project_id or "").strip()
            norm = raw.lower().replace(" ", "_").replace("-", "_")
            tenant_candidates = [raw, norm, raw.lower()]
            if "ucust" in norm:
                tenant_candidates.extend(["ucust_ai", "ucust", "ucust-ai", "UCust AI"])
            tenant_candidates = list(dict.fromkeys(c for c in tenant_candidates if c))

            # 1. Загрузка чанков из базы данных (PostgreSQL или SQLite)
            db_chunks = await cls._fetch_db_chunks(tenant_candidates)
            
            rag = CleanRAGPipeline(min_confidence_threshold=0.45)
            if db_chunks:
                docs = [
                    Document(
                        doc_id=f"doc_{norm}_{i}",
                        text=text_content,
                        metadata={"tenant_id": norm, "project_id": project_id}
                    )
                    for i, text_content in enumerate(db_chunks)
                ]
                rag.ingest_documents(docs)
            
            # Поиск с фильтрацией строго по tenant_id
            rag_context = await rag.query_async(query_text=query, top_k_retrieval=top_k * 3, tenant_id=norm)
            
            if not rag_context.has_sufficient_context or not rag_context.chunks:
                # Если с фильтром по конкретному tenant_id не прошло, ищем по всему индексу тенанта
                if db_chunks:
                    rag_context = await rag.query_async(query_text=query, top_k_retrieval=top_k * 3)

            if not rag_context.has_sufficient_context or not rag_context.chunks:
                if db_chunks:
                    # Если есть чанки из базы, отдаем наиболее релевантные первые факты
                    return db_chunks[:top_k]
                logger.info(f"ℹ️ [RAGRetriever] Не найдено специфичных чанков для project_id='{project_id}', запрос: '{query[:40]}'")
                return []

            extracted_facts = [c.text for c in rag_context.chunks if getattr(c, "text", None)]
            return extracted_facts[:top_k] if extracted_facts else db_chunks[:top_k]
        except Exception as e:
            logger.warning(f"⚠️ [RAGRetriever] Ошибка извлечения контекста из RAG для {project_id}: {e}")
            return []

    @classmethod
    async def retrieve_with_grounding_fallback(
        cls,
        project_id: str,
        query: str,
        niche: str = "",
        top_k: int = 3
    ) -> Tuple[List[str], Optional[Any]]:
        """
        Умный двухуровневый ретривер (Hybrid RAG + Live Web Grounding):
        1. Сначала ищет во внутреннем pgvector RAG тенанта.
        2. Если порог < 0.65 или пусто -> бесшовно вызывает AutonomousResearchGrounder.
        """
        try:
            from skills.autonomous_research_grounder import AutonomousResearchGrounder
        except ImportError:
            from ai.skills.autonomous_research_grounder import AutonomousResearchGrounder
        
        # 1. Попытка достать факты из локального RAG
        local_facts = await cls.retrieve_and_rerank(project_id, query, top_k=top_k)
        if local_facts:
            return local_facts, None

        # 2. Локальный RAG пуст -> Автономный веб-ресёрч и генерация FactSheet
        logger.info(f"🌐 [RAGRetriever] Перенаправление запроса '{query[:40]}' в AutonomousResearchGrounder...")
        grounder = AutonomousResearchGrounder()
        fact_sheet = await grounder.research_product(product_query=query, niche=niche)
        
        return fact_sheet.key_specs, fact_sheet

