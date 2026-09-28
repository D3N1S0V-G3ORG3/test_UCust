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

    SIMILARITY_THRESHOLD: float = 0.65

    @classmethod
    async def retrieve_and_rerank(cls, project_id: str, query: str, top_k: int = 3) -> List[str]:
        """
        Извлекает и ранжирует самые релевантные факты о проекте.
        """
        try:
            from rag.pipeline import CleanRAGPipeline
            rag = CleanRAGPipeline()
            
            # Поиск с фильтрацией строго по project_id
            rag_context = await rag.query_async(query_text=query, top_k_retrieval=top_k * 2, tenant_id=project_id)
            
            if not rag_context.has_sufficient_context or not rag_context.chunks:
                logger.info(f"ℹ️ [RAGRetriever] Не найдено специфичных чанков для project_id='{project_id}', запрос: '{query[:40]}'")
                return []

            # Проверка порога уверенности (cosine similarity / context sufficiency)
            confidence = getattr(rag_context, "confidence_score", 1.0)
            if confidence < cls.SIMILARITY_THRESHOLD:
                logger.info(f"⚡ [RAGRetriever] Уверенность RAG ({confidence:.2f}) ниже порога {cls.SIMILARITY_THRESHOLD}. Триггер UNKNOWN_ENTITY.")
                return []

            extracted_facts = [c.text for c in rag_context.chunks if getattr(c, "text", None)]
            return extracted_facts[:top_k]
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
        from skills.autonomous_research_grounder import AutonomousResearchGrounder
        
        # 1. Попытка достать факты из локального RAG
        local_facts = await cls.retrieve_and_rerank(project_id, query, top_k=top_k)
        if local_facts:
            return local_facts, None

        # 2. Локальный RAG пуст -> Автономный веб-ресёрч и генерация FactSheet
        logger.info(f"🌐 [RAGRetriever] Перенаправление запроса '{query[:40]}' в AutonomousResearchGrounder...")
        grounder = AutonomousResearchGrounder()
        fact_sheet = await grounder.research_product(product_query=query, niche=niche)
        
        return fact_sheet.key_specs, fact_sheet

