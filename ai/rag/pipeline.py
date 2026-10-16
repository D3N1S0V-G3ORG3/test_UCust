"""
Clean RAG Pipeline Facade with Multi-Tenant Partitioning and 4-Layer Knowledge Stratification

Директива 6+7: async-методы для Lock-защищённой инвалидации кэша и поиска.
Директива Stratified RAG: 4-слойная изоляция Hard Ground Truth, Brand DNA, Audience Priors и Episodic Memory.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import asyncio
from typing import List, Dict, Any, Optional
from rag.models import Document, Chunk, RAGContext, DocCategoryEnum, TrustTierEnum, PlatformTargetEnum, RetrievalResult
from rag.sanitizer import SemanticChunker, TextSanitizer
from rag.hybrid_retriever import HybridRetriever
from rag.reranker import CrossEncoderReranker
from rag.guard import AntiHallucinationGuard

class CleanRAGPipeline:
    """
    Высоконадежный локальный Clean RAG пайплайн для UCust с жесткой изоляцией tenant_id
    и 4-слойной стратификацией знаний (Hard Ground Truth, Brand DNA, Audience Priors, Episodic Memory).
    """
    def __init__(
        self,
        target_chunk_tokens: int = 350,
        overlap_tokens: int = 50,
        min_confidence_threshold: float = 0.55,
        reranker_model: str = "BAAI/bge-reranker-base",
        max_context_tokens: int = 1500,
        max_episodic_directives: int = 3
    ):
        self.chunker = SemanticChunker(target_chunk_tokens, overlap_tokens)
        self.retriever = HybridRetriever()
        self.reranker = CrossEncoderReranker(reranker_model)
        self.guard = AntiHallucinationGuard(
            min_confidence_threshold=min_confidence_threshold,
            max_context_tokens=max_context_tokens,
            max_episodic_directives=max_episodic_directives
        )

    def add_directive(
        self,
        tenant_id: str,
        directive_text: str,
        source: str = "user_directive",
        platform_target: str = "all",
        doc_category: str = DocCategoryEnum.EPISODIC_MEMORY.value,
        trust_tier: str = TrustTierEnum.SYSTEM_DIRECTIVE.value
    ) -> Chunk:
        """
        Синхронное добавление директивы/факта с автоматической инвалидацией кэша тенанта.
        Гарантирует отсутствие Stale Data при обновлении инструкций владельца.
        """
        import time
        doc = Document(
            doc_id=f"dir_{tenant_id}_{int(time.time() * 1000)}",
            text=directive_text,
            metadata={
                "tenant_id": tenant_id,
                "client_id": tenant_id,
                "doc_category": doc_category,
                "trust_tier": trust_tier,
                "platform_target": platform_target,
                "source": source
            },
            source=source
        )
        self.ingest_documents([doc])
        self.invalidate_cache(tenant_id)
        chunks = self.chunker.chunk_document(doc)
        return chunks[0] if chunks else Chunk(chunk_id=doc.doc_id, doc_id=doc.doc_id, text=doc.text, token_count=len(doc.text.split()))

    async def add_directive_async(
        self,
        tenant_id: str,
        directive_text: str,
        source: str = "user_directive",
        platform_target: str = "all",
        doc_category: str = DocCategoryEnum.EPISODIC_MEMORY.value,
        trust_tier: str = TrustTierEnum.SYSTEM_DIRECTIVE.value
    ) -> Chunk:
        """
        Асинхронное добавление директивы/факта с Lock-защищённой инвалидацией кэша тенанта.
        """
        import time
        doc = Document(
            doc_id=f"dir_{tenant_id}_{int(time.time() * 1000)}",
            text=directive_text,
            metadata={
                "tenant_id": tenant_id,
                "client_id": tenant_id,
                "doc_category": doc_category,
                "trust_tier": trust_tier,
                "platform_target": platform_target,
                "source": source
            },
            source=source
        )
        await self.ingest_documents_async([doc])
        await self.invalidate_cache_async(tenant_id)
        chunks = self.chunker.chunk_document(doc)
        return chunks[0] if chunks else Chunk(chunk_id=doc.doc_id, doc_id=doc.doc_id, text=doc.text, token_count=len(doc.text.split()))

    async def add_hard_fact_async(
        self,
        tenant_id: str,
        fact_text: str,
        source: str = "owner_confirmation",
        platform_target: str = "all"
    ) -> Chunk:
        """Добавление проверенного факта в слой hard_fact с trust_tier=VERIFIED_BY_OWNER."""
        return await self.add_directive_async(
            tenant_id=tenant_id,
            directive_text=fact_text,
            source=source,
            platform_target=platform_target,
            doc_category=DocCategoryEnum.HARD_FACT.value,
            trust_tier=TrustTierEnum.VERIFIED_BY_OWNER.value
        )

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

    def query(
        self,
        query_text: str,
        top_k_retrieval: int = 10,
        top_n_rerank: int = 5,
        tenant_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> RAGContext:
        cleaned_query = TextSanitizer.sanitize(query_text)
        if not cleaned_query:
            return self.guard.format_and_guard(query_text, [])

        # 1. Гибридный поиск с Multi-Tenant фильтром и Metadata Pre-Filtering
        retrieved_candidates = self.retriever.hybrid_search(
            cleaned_query, top_k=top_k_retrieval, tenant_id=tenant_id, filters=filters
        )
        try:
            from services.trend_service import TrendService
            retrieved_candidates = TrendService.filter_active_trend_documents(retrieved_candidates)
        except Exception:
            pass

        # 2. Кросс-энкодер переранжирование (top_n_rerank=5)
        reranked_results = self.reranker.rerank(cleaned_query, retrieved_candidates, top_n=top_n_rerank)

        # 3. Guardrail защиты от галлюцинаций
        rag_context = self.guard.format_and_guard(cleaned_query, reranked_results)
        self._record_telemetry(tenant_id, cleaned_query, rag_context)

        return rag_context

    def query_stratified_context(
        self,
        query_text: str,
        tenant_id: str,
        platform_target: Optional[str] = None,
        layers: Optional[List[str]] = None,
        per_layer_k: int = 3,
        top_n_rerank: int = 10
    ) -> RAGContext:
        """
        Синхронное извлечение сбалансированного 4-слойного контекста:
        - hard_fact (Жёсткие факты: цены, габариты, сроки)
        - brand_dna (ДНК бренда: ToV, редполитика)
        - audience_priors (Боли ЦА: триггеры, возражения, FAQ)
        - episodic_memory (Свежие директивы владельца)
        """
        cleaned_query = TextSanitizer.sanitize(query_text)
        if not cleaned_query:
            return self.guard.format_and_guard(query_text, [])

        target_layers = layers or [
            DocCategoryEnum.HARD_FACT.value,
            DocCategoryEnum.BRAND_DNA.value,
            DocCategoryEnum.AUDIENCE_PRIORS.value,
            DocCategoryEnum.EPISODIC_MEMORY.value,
        ]

        seen_chunk_ids = set()
        merged_candidates: List[RetrievalResult] = []

        for layer in target_layers:
            layer_filters: Dict[str, Any] = {"doc_category": layer, "tenant_id": tenant_id}
            if platform_target:
                layer_filters["platform_target"] = platform_target

            candidates = self.retriever.hybrid_search(
                cleaned_query, top_k=per_layer_k * 2, tenant_id=tenant_id, filters=layer_filters
            )
            for c in candidates:
                if c.chunk.chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(c.chunk.chunk_id)
                    merged_candidates.append(c)

        # Если слои пустые (например, старые неразмеченные документы), делаем fallback
        if not merged_candidates:
            fallback_filters: Dict[str, Any] = {"tenant_id": tenant_id}
            if platform_target:
                fallback_filters["platform_target"] = platform_target
            merged_candidates = self.retriever.hybrid_search(
                cleaned_query, top_k=per_layer_k * 4, tenant_id=tenant_id, filters=fallback_filters
            )

        try:
            from services.trend_service import TrendService
            merged_candidates = TrendService.filter_active_trend_documents(merged_candidates)
        except Exception:
            pass

        reranked_results = self.reranker.rerank(cleaned_query, merged_candidates, top_n=top_n_rerank)
        rag_context = self.guard.format_and_guard(cleaned_query, reranked_results)
        self._record_telemetry(tenant_id, cleaned_query, rag_context)
        return rag_context

    @staticmethod
    def _record_telemetry(tenant_id: Optional[str], query: str, context: RAGContext):
        try:
            from analytics.rag_telemetry import RAGTelemetryTracker
            RAGTelemetryTracker.get_instance().record_query(
                tenant_id=tenant_id or "global",
                query=query,
                context=context
            )
        except Exception:
            pass

    @classmethod
    def get_telemetry_summary(cls) -> Dict[str, Any]:
        """Возвращает сводку телеметрии качества RAG и усечения контекста для дашборда администратора."""
        from analytics.rag_telemetry import RAGTelemetryTracker
        return RAGTelemetryTracker.get_instance().get_summary().model_dump()

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
        tenant_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> RAGContext:
        """
        Директива 7: Использует hybrid_search_async с Lock-защищённой записью в кэш и Metadata Pre-Filtering.
        Безопасен для параллельного вызова из 50+ asyncio-тасков.
        """
        cleaned_query = TextSanitizer.sanitize(query_text)
        if not cleaned_query:
            return self.guard.format_and_guard(query_text, [])

        # 1. Lock-защищённый гибридный поиск с pre-filtering
        retrieved_candidates = await self.retriever.hybrid_search_async(
            cleaned_query, top_k=top_k_retrieval, tenant_id=tenant_id, filters=filters
        )
        try:
            from services.trend_service import TrendService
            retrieved_candidates = TrendService.filter_active_trend_documents(retrieved_candidates)
        except Exception:
            pass

        # 2. Реранкинг (CPU-bound → executor)
        loop = asyncio.get_running_loop()
        reranked_results = await loop.run_in_executor(
            None, self.reranker.rerank, cleaned_query, retrieved_candidates, top_n_rerank
        )

        # 3. Guardrail
        rag_context = self.guard.format_and_guard(cleaned_query, reranked_results)
        self._record_telemetry(tenant_id, cleaned_query, rag_context)
        return rag_context

    async def query_stratified_context_async(
        self,
        query_text: str,
        tenant_id: str,
        platform_target: Optional[str] = None,
        layers: Optional[List[str]] = None,
        per_layer_k: int = 3,
        top_n_rerank: int = 10
    ) -> RAGContext:
        """
        Директива 4-слойной стратификации знаний (Async):
        Выполняет параллельный поиск по слоям:
        1. Hard Ground Truth (hard_fact)
        2. Brand DNA & Redpolicy (brand_dna)
        3. Audience Priors (audience_priors)
        4. Episodic Memory (episodic_memory)
        Гарантирует, что генеративная модель получит сбалансированную информацию без вытеснения редполитики или фактов.
        """
        cleaned_query = TextSanitizer.sanitize(query_text)
        if not cleaned_query:
            return self.guard.format_and_guard(query_text, [])

        target_layers = layers or [
            DocCategoryEnum.HARD_FACT.value,
            DocCategoryEnum.BRAND_DNA.value,
            DocCategoryEnum.AUDIENCE_PRIORS.value,
            DocCategoryEnum.EPISODIC_MEMORY.value,
        ]

        # Параллельный поиск по всем целевым слоям
        async def _fetch_layer(layer_name: str) -> List[RetrievalResult]:
            layer_filters: Dict[str, Any] = {"doc_category": layer_name, "tenant_id": tenant_id}
            if platform_target:
                layer_filters["platform_target"] = platform_target
            return await self.retriever.hybrid_search_async(
                cleaned_query, top_k=per_layer_k * 2, tenant_id=tenant_id, filters=layer_filters
            )

        layer_results = await asyncio.gather(*[_fetch_layer(l) for l in target_layers])

        seen_chunk_ids = set()
        merged_candidates: List[RetrievalResult] = []
        for cand_list in layer_results:
            for c in cand_list:
                if c.chunk.chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(c.chunk.chunk_id)
                    merged_candidates.append(c)

        # Если слои пустые (старые документы без разметки), делаем общий запрос
        if not merged_candidates:
            fallback_filters: Dict[str, Any] = {"tenant_id": tenant_id}
            if platform_target:
                fallback_filters["platform_target"] = platform_target
            merged_candidates = await self.retriever.hybrid_search_async(
                cleaned_query, top_k=per_layer_k * 4, tenant_id=tenant_id, filters=fallback_filters
            )

        try:
            from services.trend_service import TrendService
            merged_candidates = TrendService.filter_active_trend_documents(merged_candidates)
        except Exception:
            pass

        loop = asyncio.get_running_loop()
        reranked_results = await loop.run_in_executor(
            None, self.reranker.rerank, cleaned_query, merged_candidates, top_n_rerank
        )

        rag_context = self.guard.format_and_guard(cleaned_query, reranked_results)
        self._record_telemetry(tenant_id, cleaned_query, rag_context)
        return rag_context
