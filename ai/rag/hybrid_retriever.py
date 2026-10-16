"""
2. Hybrid Search & Embeddings with Multi-Tenant Partitioning
Dense Search (Векторный поиск по эмбеддингам) + Sparse Search (BM25 по ключевым терминам SMM).
Объединение выдачи через Reciprocal Rank Fusion (RRF) с жесткой изоляцией по tenant_id.
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import os
import math
import re
import threading
from typing import List, Dict, Any, Optional, Tuple
from collections import Counter
from rag.models import Chunk, RetrievalResult

def _matches_filters(
    chunk_meta: Dict[str, Any],
    filters: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None
) -> bool:
    """
    Строгий пре-фильтр чанков перед вычислением Dense / Sparse скоров.
    Изолирует арендаторов (client_id / tenant_id) и стратифицирует слои (doc_category, trust_tier, platform_target).
    """
    if not chunk_meta:
        chunk_meta = {}

    # 1. Изоляция тенанта / клиента
    req_tenant = tenant_id or (filters.get("tenant_id") or filters.get("client_id") if filters else None)
    if req_tenant:
        c_tenant = chunk_meta.get("tenant_id") or chunk_meta.get("client_id") or (chunk_meta.get("company_name", "").strip().lower().replace(" ", "_") if chunk_meta.get("company_name") else "")
        if not c_tenant or c_tenant.strip().lower() not in {req_tenant.strip().lower(), "global"}:
            return False

    if not filters:
        return True

    for k, expected in filters.items():
        if k in {"tenant_id", "client_id"}:
            continue

        if hasattr(expected, "value"):
            expected = expected.value

        actual = chunk_meta.get(k)
        if actual is None and k == "doc_category":
            actual = chunk_meta.get("category")

        if actual is None:
            if k == "platform_target":
                actual = "all"
            else:
                return False

        if hasattr(actual, "value"):
            actual = actual.value

        # Сравнение списков
        if isinstance(expected, (list, set, tuple)):
            exp_set = {str(x.value if hasattr(x, "value") else x).strip().lower() for x in expected}
            if str(actual).strip().lower() not in exp_set:
                return False
        elif isinstance(actual, (list, set, tuple)):
            act_set = {str(x.value if hasattr(x, "value") else x).strip().lower() for x in actual}
            if str(expected).strip().lower() not in act_set:
                return False
        elif isinstance(expected, str) and isinstance(actual, str):
            # Если фильтруем платформу, "all" подходит под любую платформу
            if k == "platform_target" and (actual.lower() == "all" or expected.lower() == "all"):
                continue
            if actual.strip().lower() != expected.strip().lower():
                return False
        else:
            if actual != expected:
                return False

    return True


class LocalDenseStore:
    """
    Локальное векторное хранилище с вычислением косинусного сходства
    и мульти-тенантной фильтрацией по tenant_id и слоям метаданных.
    """
    def __init__(self, embedding_dim: int = 384):
        self.embedding_dim = embedding_dim
        self.chunks: List[Chunk] = []
        self.embeddings: List[List[float]] = []
        self.model = None
        self._lock = threading.RLock()
        
        if os.getenv("ENABLE_NEURAL_MODELS", "0") == "1":
            try:
                from sentence_transformers import SentenceTransformer
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
                self.model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2", device=device, local_files_only=True)
            except Exception:
                self.model = None
        else:
            self.model = None

    def _encode_text(self, text: str) -> List[float]:
        if self.model is not None:
            try:
                emb = self.model.encode(text, normalize_embeddings=True)
                return emb.tolist()
            except Exception:
                pass
                
        vec = [0.0] * self.embedding_dim
        tokens = re.findall(r'\w+', text.lower())
        if not tokens:
            return vec
            
        for token in tokens:
            idx = abs(hash(token)) % self.embedding_dim
            vec[idx] += 1.0
            
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]
        return vec

    def add_chunks(self, chunks: List[Chunk]):
        with self._lock:
            for chunk in chunks:
                self.chunks.append(chunk)
                emb = self._encode_text(chunk.text)
                self.embeddings.append(emb)

    def delete_by_tenant(self, tenant_id: str) -> int:
        """Удаление всех чанков тенанта из векторного хранилища."""
        with self._lock:
            tid = tenant_id.strip().lower()
            new_chunks = []
            new_embeddings = []
            deleted = 0
            for chunk, emb in zip(self.chunks, self.embeddings):
                c_tenant = (chunk.metadata.get("tenant_id") or chunk.metadata.get("company_name", "")).strip().lower().replace(" ", "_")
                if c_tenant == tid:
                    deleted += 1
                else:
                    new_chunks.append(chunk)
                    new_embeddings.append(emb)
            self.chunks = new_chunks
            self.embeddings = new_embeddings
            return deleted

    def search(
        self,
        query: str,
        top_k: int = 10,
        tenant_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[Chunk, float]]:
        with self._lock:
            if not self.chunks:
                return []
                
            q_emb = self._encode_text(query)
            scored: List[Tuple[Chunk, float]] = []
            
            for chunk, emb in zip(self.chunks, self.embeddings):
                if not _matches_filters(chunk.metadata, filters=filters, tenant_id=tenant_id):
                    continue
                sim = sum(q * e for q, e in zip(q_emb, emb))
                scored.append((chunk, float(sim)))
                
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]


class BM25SparseRetriever:
    """
    Лексический поиск BM25 для точного нахождения редких SMM-терминов
    с поддержкой фильтрации по tenant_id.
    """
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.chunks: List[Chunk] = []
        self.doc_lengths: List[int] = []
        self.avg_doc_length: float = 0.0
        self.doc_freqs: Dict[str, int] = Counter()
        self.corpus_size: int = 0
        self.doc_term_counts: List[Dict[str, int]] = []
        self._lock = threading.RLock()

    def _tokenize(self, text: str) -> List[str]:
        return [t for t in re.findall(r'[a-zA-Zа-яА-Я0-9_@]+', text.lower()) if len(t) > 1]

    def add_chunks(self, chunks: List[Chunk]):
        with self._lock:
            for chunk in chunks:
                self.chunks.append(chunk)
                tokens = self._tokenize(chunk.text)
                term_count = Counter(tokens)
                self.doc_term_counts.append(term_count)
                self.doc_lengths.append(len(tokens))
                
                for term in term_count.keys():
                    self.doc_freqs[term] += 1
                    
            self.corpus_size = len(self.chunks)
            self.avg_doc_length = sum(self.doc_lengths) / self.corpus_size if self.corpus_size > 0 else 0.0

    def delete_by_tenant(self, tenant_id: str) -> int:
        """Удаление всех чанков тенанта из разреженного индекса BM25."""
        with self._lock:
            tid = tenant_id.strip().lower()
            new_chunks = []
            deleted = 0
            for chunk in self.chunks:
                c_tenant = (chunk.metadata.get("tenant_id") or chunk.metadata.get("company_name", "")).strip().lower().replace(" ", "_")
                if c_tenant == tid:
                    deleted += 1
                else:
                    new_chunks.append(chunk)
            
            # Пересчет индекса BM25
            self.chunks = []
            self.doc_lengths = []
            self.avg_doc_length = 0.0
            self.doc_freqs = Counter()
            self.corpus_size = 0
            self.doc_term_counts = []
            if new_chunks:
                for chunk in new_chunks:
                    self.chunks.append(chunk)
                    tokens = self._tokenize(chunk.text)
                    term_count = Counter(tokens)
                    self.doc_term_counts.append(term_count)
                    self.doc_lengths.append(len(tokens))
                    for term in term_count.keys():
                        self.doc_freqs[term] += 1
                self.corpus_size = len(self.chunks)
                self.avg_doc_length = sum(self.doc_lengths) / self.corpus_size if self.corpus_size > 0 else 0.0
            return deleted

    def search(
        self,
        query: str,
        top_k: int = 10,
        tenant_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Tuple[Chunk, float]]:
        with self._lock:
            if not self.chunks:
                return []
                
            q_tokens = self._tokenize(query)
            if not q_tokens:
                return []
                
            scores: List[float] = [0.0] * self.corpus_size
            
            for token in q_tokens:
                df = self.doc_freqs.get(token, 0)
                if df == 0:
                    continue
                    
                idf = math.log(1.0 + (self.corpus_size - df + 0.5) / (df + 0.5))
                
                for i, term_counts in enumerate(self.doc_term_counts):
                    if i >= len(self.chunks):
                        continue
                    chunk = self.chunks[i]
                    if not _matches_filters(chunk.metadata, filters=filters, tenant_id=tenant_id):
                        continue
                            
                    tf = term_counts.get(token, 0)
                    if tf == 0:
                        continue
                    doc_len = self.doc_lengths[i]
                    numerator = tf * (self.k1 + 1.0)
                    denominator = tf + self.k1 * (1.0 - self.b + self.b * (doc_len / (self.avg_doc_length or 1.0)))
                    scores[i] += idf * (numerator / denominator)
                    
            max_score = max(scores) if scores and max(scores) > 0 else 1.0
            results = [(self.chunks[i], scores[i] / max_score) for i in range(self.corpus_size) if scores[i] > 0]
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]


class HybridRetriever:
    """
    Гибридный поисковый движок с поддержкой Multi-Tenant изоляции и потокобезопасного кэша.
    Объединяет Dense (Векторный) и Sparse (BM25) результаты через Reciprocal Rank Fusion (RRF).

    Директива 7: все операции записи/удаления _query_cache защищены asyncio.Lock
    для предотвращения Race Condition при параллельных asyncio-тасках (50+ тенантов).
    """
    def __init__(self, rrf_k: int = 60, dense_weight: float = 0.6, sparse_weight: float = 0.4):
        self.dense_store = LocalDenseStore()
        self.sparse_retriever = BM25SparseRetriever()
        self.rrf_k = rrf_k
        self.dense_weight = dense_weight
        self.sparse_weight = sparse_weight
        self._query_cache: Dict[str, List[RetrievalResult]] = {}
        # Директива 7: единый asyncio.Lock для атомарных операций над кэшем
        self._cache_lock: Optional[Any] = None  # Lazy-init для совместимости с sync-контекстом

    def _get_cache_lock(self):
        """Lazy-инициализация Lock в рамках текущего event loop."""
        import asyncio
        if self._cache_lock is None:
            try:
                self._cache_lock = asyncio.Lock()
            except RuntimeError:
                # Нет активного event loop (sync-контекст) — Lock не нужен
                pass
        return self._cache_lock

    def index_chunks(self, chunks: List[Chunk]):
        """Индексирование чанков с синхронной инвалидацией кэша затронутых тенантов."""
        self.dense_store.add_chunks(chunks)
        self.sparse_retriever.add_chunks(chunks)
        # Инвалидация кэша для затронутых tenant_id (Edge Case 3, Директива 4)
        affected_tenants = {
            (c.metadata.get("tenant_id") or c.metadata.get("company_name", "")).strip().lower().replace(" ", "_")
            for c in chunks if c.metadata
        }
        for tid in affected_tenants:
            if tid:
                self._invalidate_cache_sync(tid)
            else:
                self._query_cache.clear()

    async def index_chunks_async(self, chunks: List[Chunk]):
        """Асинхронная версия индексирования с Lock-защищённой инвалидацией."""
        self.dense_store.add_chunks(chunks)
        self.sparse_retriever.add_chunks(chunks)
        affected_tenants = {
            (c.metadata.get("tenant_id") or c.metadata.get("company_name", "")).strip().lower().replace(" ", "_")
            for c in chunks if c.metadata
        }
        for tid in affected_tenants:
            if tid:
                await self.invalidate_cache_async(tid)
            else:
                async with self._get_or_create_lock():
                    self._query_cache.clear()

    def _invalidate_cache_sync(self, tenant_id: Optional[str] = None):
        """
        Синхронная инвалидация — только для вызовов вне asyncio event loop.
        Использует list() snapshot для безопасной итерации при concurrent dict modifications.
        """
        if not tenant_id:
            self._query_cache.clear()
            return
        tid = tenant_id.strip().lower()
        # list() snapshot предотвращает RuntimeError: dictionary changed size during iteration
        keys_to_delete = [k for k in list(self._query_cache.keys()) if k.startswith(f"{tid}:")]
        for k in keys_to_delete:
            self._query_cache.pop(k, None)

    def invalidate_cache(self, tenant_id: Optional[str] = None):
        """Sync-совместимая инвалидация (для обратной совместимости с sync-кодом)."""
        self._invalidate_cache_sync(tenant_id)

    async def invalidate_cache_async(self, tenant_id: Optional[str] = None):
        """
        Директива 7: Потокобезопасная асинхронная инвалидация под asyncio.Lock.
        Исключает KeyError и состояния гонки при параллельных записях от 50+ тенантов.
        """
        lock = self._get_or_create_lock()
        async with lock:
            if not tenant_id:
                self._query_cache.clear()
                return
            tid = tenant_id.strip().lower()
            keys_to_delete = [k for k in list(self._query_cache.keys()) if k.startswith(f"{tid}:")]
            for k in keys_to_delete:
                self._query_cache.pop(k, None)

    def _get_or_create_lock(self):
        """Потокобезопасное создание Lock в рамках текущего event loop."""
        import asyncio
        if self._cache_lock is None:
            self._cache_lock = asyncio.Lock()
        return self._cache_lock

    def delete_tenant(self, tenant_id: str):
        """Синхронное удаление данных тенанта и сброс его кэша."""
        self.dense_store.delete_by_tenant(tenant_id)
        self.sparse_retriever.delete_by_tenant(tenant_id)
        self._invalidate_cache_sync(tenant_id)

    async def delete_tenant_async(self, tenant_id: str):
        """Директива 7: Асинхронное удаление тенанта с Lock-защитой кэша."""
        self.dense_store.delete_by_tenant(tenant_id)
        self.sparse_retriever.delete_by_tenant(tenant_id)
        await self.invalidate_cache_async(tenant_id)

    def _make_cache_key(self, query: str, top_k: int, tenant_id: Optional[str] = None, filters: Optional[Dict[str, Any]] = None) -> str:
        tid = tenant_id.strip().lower() if tenant_id else (filters.get("tenant_id") or filters.get("client_id") or "global" if filters else "global")
        f_str = ""
        if filters:
            f_str = ":" + "_".join(f"{k}={v}" for k, v in sorted(filters.items()) if k not in {"tenant_id", "client_id"})
        return f"{tid}:{query.strip().lower()}:{top_k}{f_str}"

    def hybrid_search(
        self,
        query: str,
        top_k: int = 10,
        tenant_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[RetrievalResult]:
        """Синхронный поиск с read-only обращением к кэшу и поддержкой Metadata Pre-Filtering."""
        cache_key = self._make_cache_key(query, top_k, tenant_id, filters)
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        final_results = self._compute_hybrid_search(query, top_k, tenant_id, filters)
        # Запись в кэш (sync-контекст): простой dict — атомарно на GIL уровне
        self._query_cache[cache_key] = final_results
        return final_results

    async def hybrid_search_async(
        self,
        query: str,
        top_k: int = 10,
        tenant_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[RetrievalResult]:
        """
        Директива 7: Асинхронный поиск с Lock-защищённой записью в кэш и Metadata Pre-Filtering.
        - Cache lookup/write: в event loop (GIL-атомарны, O(1))
        - CPU-bound compute: в ThreadPoolExecutor (не блокирует event loop)
        Использовать вместо hybrid_search() при работе в asyncio-окружении с 50+ concurrent users.
        """
        import asyncio
        cache_key = self._make_cache_key(query, top_k, tenant_id, filters)

        # Чтение без Lock — dict.get() атомарен в CPython (GIL), O(1)
        cached = self._query_cache.get(cache_key)
        if cached is not None:
            return cached

        # CPU-bound вычисление → executor, не блокирует event loop
        loop = asyncio.get_running_loop()
        final_results = await loop.run_in_executor(
            None, self._compute_hybrid_search, query, top_k, tenant_id, filters
        )

        # Директива 7: Lock только при записи — предотвращает dirty-write race condition
        lock = self._get_or_create_lock()
        async with lock:
            # Double-checked locking: другая таска могла уже записать пока мы считали
            if cache_key not in self._query_cache:
                self._query_cache[cache_key] = final_results

        return self._query_cache.get(cache_key, final_results)

    def _compute_hybrid_search(
        self,
        query: str,
        top_k: int,
        tenant_id: Optional[str],
        filters: Optional[Dict[str, Any]] = None
    ) -> List[RetrievalResult]:
        """Вычисление RRF-комбинации Dense + Sparse результатов с pre-filtering."""
        dense_results = self.dense_store.search(query, top_k=top_k * 2, tenant_id=tenant_id, filters=filters)
        sparse_results = self.sparse_retriever.search(query, top_k=top_k * 2, tenant_id=tenant_id, filters=filters)

        chunk_map: Dict[str, Chunk] = {}
        dense_scores: Dict[str, float] = {}
        sparse_scores: Dict[str, float] = {}
        rrf_scores: Dict[str, float] = {}

        for rank, (chunk, score) in enumerate(dense_results):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            dense_scores[cid] = score
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + self.dense_weight * (1.0 / (self.rrf_k + rank + 1))

        for rank, (chunk, score) in enumerate(sparse_results):
            cid = chunk.chunk_id
            chunk_map[cid] = chunk
            sparse_scores[cid] = score
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + self.sparse_weight * (1.0 / (self.rrf_k + rank + 1))

        combined: List[RetrievalResult] = []
        for cid, chunk in chunk_map.items():
            combined.append(
                RetrievalResult(
                    chunk=chunk,
                    dense_score=dense_scores.get(cid, 0.0),
                    sparse_score=sparse_scores.get(cid, 0.0),
                    hybrid_score=rrf_scores.get(cid, 0.0)
                )
            )

        combined.sort(key=lambda x: x.hybrid_score, reverse=True)
        return combined[:top_k]

