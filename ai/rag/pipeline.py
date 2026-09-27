"""
Clean RAG Pipeline Facade with Multi-Tenant Partitioning

Директива 6+7: async-методы для Lock-защищённой инвалидации кэша и поиска.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import asyncio
from typing import List, Dict, Any, Optional
from rag.models import Document, Chunk, RAGContext
from rag.sanitizer import SemanticChunker, TextSanitizer
from rag.hybrid_retriever import HybridRetriever
from rag.reranker import CrossEncoderReranker
from rag.guard import AntiHallucinationGuard

class CleanRAGPipeline:
    """
    Высоконадежный локальный Clean RAG пайплайн для UCust с жесткой изоляцией tenant_id.

    Директивы 6+7: все мутирующие операции над кэшем доступны в async-вариантах
    с Lock-защитой для безопасного параллельного доступа от 50+ тенантов.
    """
    def __init__(
        self,
        target_chunk_tokens: int = 350,
        overlap_tokens: int = 50,
        min_confidence_threshold: float = 0.55,
        reranker_model: str = "BAAI/bge-reranker-base"
    ):
        self.chunker = SemanticChunker(target_chunk_tokens, overlap_tokens)
        self.retriever = HybridRetriever()
        self.reranker = CrossEncoderReranker(reranker_model)
        self.guard = AntiHallucinationGuard(min_confidence_threshold)

    def ingest_documents(self, documents: List[Document]) -> int:
        all_chunks: List[Chunk] = []
        for doc in documents:
            chunks = self.chunker.chunk_document(doc)
            all_chunks.extend(chunks)

        if all_chunks:
            self.retriever.index_chunks(all_chunks)
            print(f"[CleanRAGPipeline] 📥 Успешно проиндексировано {len(all_chunks)} семантических чанков из {len(documents)} документов.")

        return len(all_chunks)

    # ── Sync методы (обратная совместимость) ─────────────────────────────────

    def invalidate_cache(self, tenant_id: Optional[str] = None):
        """Синхронная инвалидация кэша поисковых результатов для тенанта."""
        self.retriever.invalidate_cache(tenant_id)

    def delete_tenant(self, tenant_id: str):
        """Синхронное удаление документов тенанта и сброс его кэша."""
        self.retriever.delete_tenant(tenant_id)

    def query(self, query_text: str, top_k_retrieval: int = 10, top_n_rerank: int = 5, tenant_id: Optional[str] = None) -> RAGContext:
        cleaned_query = TextSanitizer.sanitize(query_text)
        if not cleaned_query:
            return self.guard.format_and_guard(query_text, [])

        # 1. Гибридный поиск с Multi-Tenant фильтром (Bounded: top_k_retrieval=10)
        retrieved_candidates = self.retriever.hybrid_search(cleaned_query, top_k=top_k_retrieval, tenant_id=tenant_id)

        # 2. Кросс-энкодер переранжирование (top_n_rerank=5)
        reranked_results = self.reranker.rerank(cleaned_query, retrieved_candidates, top_n=top_n_rerank)

        # 3. Guardrail защиты от галлюцинаций
        rag_context = self.guard.format_and_guard(cleaned_query, reranked_results)

        return rag_context

    # ── Async методы (Директива 6+7: Lock-защищённые операции) ───────────────

    async def invalidate_cache_async(self, tenant_id: Optional[str] = None):
        """
        Директива 6+7: Асинхронная инвалидация кэша под asyncio.Lock.
        Вызывается из ORM Hook BrandKnowledgeManager._invalidate_and_notify().
        Гарантирует отсутствие Race Condition при параллельных записях от 50+ тенантов.
        """
        await self.retriever.invalidate_cache_async(tenant_id)

    async def delete_tenant_async(self, tenant_id: str):
        """Директива 7: Асинхронное удаление тенанта с Lock-защитой кэша."""
        await self.retriever.delete_tenant_async(tenant_id)

    async def ingest_documents_async(self, documents: List[Document]) -> int:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.ingest_documents, documents)

    async def query_async(
        self,
        query_text: str,
        top_k_retrieval: int = 10,
        top_n_rerank: int = 5,
        tenant_id: Optional[str] = None
    ) -> RAGContext:
        """
        Директива 7: Использует hybrid_search_async с Lock-защищённой записью в кэш.
        Безопасен для параллельного вызова из 50+ asyncio-тасков.
        """
        cleaned_query = TextSanitizer.sanitize(query_text)
        if not cleaned_query:
            return self.guard.format_and_guard(query_text, [])

        # 1. Lock-защищённый гибридный поиск
        retrieved_candidates = await self.retriever.hybrid_search_async(
            cleaned_query, top_k=top_k_retrieval, tenant_id=tenant_id
        )

        # 2. Реранкинг (CPU-bound → executor)
        loop = asyncio.get_running_loop()
        reranked_results = await loop.run_in_executor(
            None, self.reranker.rerank, cleaned_query, retrieved_candidates, top_n_rerank
        )

        # 3. Guardrail
        return self.guard.format_and_guard(cleaned_query, reranked_results)

