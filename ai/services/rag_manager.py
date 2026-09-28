"""
File: ai/services/rag_manager.py
CRUD операции и семантический поиск по tenant_id с multi-tenancy изоляцией.

Директива 6: инвалидация кэша RAG выполняется строго на прикладном уровне (ORM Hook),
без SQL-триггеров и синхронных HTTP-вызовов. Event Bus уведомляет подписчиков асинхронно.
"""

from __future__ import annotations

import uuid
try:
    import numpy as np
except ImportError:
    np = None
from typing import List, Dict, Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from rag.pipeline import CleanRAGPipeline

try:
    from sqlalchemy.future import select
    from sqlalchemy import text
except (ImportError, Exception):
    select = None
    text = lambda x: x

try:
    from core.database import AsyncSessionLocal, IS_POSTGRES
    from models.db_models import BrandProfileModel, TenantKnowledgeChunk
except ImportError:
    from ai.core.database import AsyncSessionLocal, IS_POSTGRES
    from ai.models.db_models import BrandProfileModel, TenantKnowledgeChunk


class InMemoryEventBus:
    """
    Лёгкий in-process Event Bus для публикации событий без внешних зависимостей.
    В production-окружении заменяется на Redis Pub/Sub или RabbitMQ без изменения интерфейса.
    """
    def __init__(self):
        self._subscribers: Dict[str, List[Any]] = {}

    def subscribe(self, event_type: str, handler) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Асинхронная публикация — fan-out ко всем подписчикам без ожидания."""
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:
                pass  # Изолируем сбои подписчиков от основного потока


# Singleton Event Bus (в production заменяется DI-контейнером)
_default_event_bus = InMemoryEventBus()


class BrandKnowledgeManager:
    """
    Менеджер базы знаний бренда и RAG:
    - Изолирует тенантов на уровне SQL (tenant_id)
    - Обеспечивает сохранение и чтение Brand DNA
    - Выполняет семантический поиск через pgvector <=> или numpy fallback

    Директива 6: при любом изменении данных тенанта выполняется автоматическая
    инвалидация RAG-кэша на прикладном уровне (ORM Hook) + публикация события
    knowledge_updated в Event Bus. SQL-триггеры не используются.
    """

    def __init__(
        self,
        rag_pipeline: Optional["CleanRAGPipeline"] = None,
        event_bus: Optional[InMemoryEventBus] = None,
    ):
        # Директива 6: внедрение зависимостей через конструктор
        self.rag_pipeline = rag_pipeline
        self.event_bus = event_bus or _default_event_bus

    async def _invalidate_and_notify(self, tenant_id: str) -> None:
        """
        Директива 6: ORM Hook — вызывается после каждой мутации данных тенанта.
        1. Прямой async сброс RAG-кэша (≤ 15ms, нет сетевых вызовов).
        2. Асинхронная публикация события knowledge_updated в Event Bus.
        """
        # Шаг 1: прямой сброс кэша сервиса (нет SQL, нет сети)
        if self.rag_pipeline is not None:
            await self.rag_pipeline.invalidate_cache_async(tenant_id)

        # Шаг 2: fan-out уведомление подписчикам через Event Bus
        await self.event_bus.publish(
            "knowledge_updated",
            {"tenant_id": tenant_id}
        )

    @staticmethod
    async def upsert_brand_dna(tenant_id: str, dna_data: Dict[str, Any]) -> None:
        """Сохранение экстрагированного профиля бренда после работы OnboardingAgent."""
        async with AsyncSessionLocal() as session:
            stmt = select(BrandProfileModel).where(BrandProfileModel.tenant_id == tenant_id)
            result = await session.execute(stmt)
            profile = result.scalars().first()

            industry_val = dna_data.get("industry_type") or dna_data.get("industry") or (profile.industry_type if profile else "general")
            if not profile:
                profile = BrandProfileModel(
                    tenant_id=tenant_id,
                    company_name=dna_data.get("company_name", tenant_id),
                    industry_type=industry_val
                )
                session.add(profile)

            profile.company_name = dna_data.get("company_name", profile.company_name)
            profile.industry_type = industry_val
            profile.tone_of_voice = dna_data.get("tone_of_voice", profile.tone_of_voice or "")
            profile.brand_props = dna_data.get("brand_props", profile.brand_props or [])
            profile.contacts = dna_data.get("contacts", profile.contacts or {})
            profile.forbidden_topics = dna_data.get("forbidden_topics", profile.forbidden_topics or [])

            await session.commit()

    @staticmethod
    async def get_brand_dna(tenant_id: str) -> Optional[Dict[str, Any]]:
        """Извлечение профиля бренда по tenant_id."""
        async with AsyncSessionLocal() as session:
            stmt = select(BrandProfileModel).where(BrandProfileModel.tenant_id == tenant_id)
            result = await session.execute(stmt)
            profile = result.scalars().first()
            if not profile:
                return None
            return {
                "tenant_id": profile.tenant_id,
                "company_name": profile.company_name,
                "industry_type": profile.industry_type,
                "tone_of_voice": profile.tone_of_voice,
                "brand_props": profile.brand_props or [],
                "contacts": profile.contacts or {},
                "forbidden_topics": profile.forbidden_topics or []
            }

    async def save_knowledge_chunks(
        self,
        tenant_id: str,
        source_type: str,
        chunks_with_embeddings: List[dict]
    ) -> None:
        """
        Директива 6: ORM Hook — пакетная запись чанков с автоматической инвалидацией RAG-кэша.

        Порядок операций:
        1. INSERT чанков в БД (транзакция)
        2. Commit транзакции
        3. ORM Hook: invalidate_cache + event_bus.publish (без SQL-триггеров)

        Критерий Д6: commit + invalidate ≤ 15ms (нет сетевых вызовов к внешним сервисам).
        """
        async with AsyncSessionLocal() as session:
            for item in chunks_with_embeddings:
                chunk = TenantKnowledgeChunk(
                    chunk_id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    source_type=source_type,
                    content=item["text"],
                    embedding=item["vector"]
                )
                session.add(chunk)
            await session.commit()
            # ORM Hook: срабатывает строго ПОСЛЕ успешного commit
            await self._invalidate_and_notify(tenant_id)

    @staticmethod
    async def semantic_search(
        tenant_id: str,
        query_vector: List[float],
        top_k: int = 3,
        threshold: float = 0.82
    ) -> List[str]:
        """
        Извлекает наиболее релевантные чанки знаний строго в рамках одного tenant_id.
        Использует косинусное сходство (pgvector нативно или numpy локально).
        """
        async with AsyncSessionLocal() as session:
            if IS_POSTGRES:
                # Нативный поиск через pgvector ( <=> - оператор косинусного расстояния)
                # Cosine Similarity = 1 - Cosine Distance
                stmt = (
                    select(TenantKnowledgeChunk.content)
                    .where(TenantKnowledgeChunk.tenant_id == tenant_id)
                    .where(1 - TenantKnowledgeChunk.embedding.cosine_distance(query_vector) >= threshold)
                    .order_by(TenantKnowledgeChunk.embedding.cosine_distance(query_vector))
                    .limit(top_k)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
            else:
                # Фоллбек для SQLite (Локальное вычисление numpy)
                stmt = select(TenantKnowledgeChunk).where(TenantKnowledgeChunk.tenant_id == tenant_id)
                result = await session.execute(stmt)
                chunks = result.scalars().all()

                scored_chunks = []
                q_vec = np.array(query_vector)
                q_norm = np.linalg.norm(q_vec)
                if q_norm == 0:
                    return []

                for chunk in chunks:
                    c_vec = np.array(chunk.embedding)
                    c_norm = np.linalg.norm(c_vec)
                    if c_norm == 0:
                        continue
                    similarity = float(np.dot(q_vec, c_vec) / (q_norm * c_norm))
                    if similarity >= threshold:
                        scored_chunks.append((similarity, chunk.content))

                # Сортировка по убыванию сходства
                scored_chunks.sort(key=lambda x: x[0], reverse=True)
                return [c[1] for c in scored_chunks[:top_k]]

    
    @staticmethod
    async def upsert_brand_dna(tenant_id: str, dna_data: Dict[str, Any]) -> None:
        """Сохранение экстрагированного профиля бренда после работы OnboardingAgent."""
        async with AsyncSessionLocal() as session:
            stmt = select(BrandProfileModel).where(BrandProfileModel.tenant_id == tenant_id)
            result = await session.execute(stmt)
            profile = result.scalars().first()

            industry_val = dna_data.get("industry_type") or dna_data.get("industry") or (profile.industry_type if profile else "general")
            if not profile:
                profile = BrandProfileModel(
                    tenant_id=tenant_id,
                    company_name=dna_data.get("company_name", tenant_id),
                    industry_type=industry_val
                )
                session.add(profile)

            profile.company_name = dna_data.get("company_name", profile.company_name)
            profile.industry_type = industry_val
            profile.tone_of_voice = dna_data.get("tone_of_voice", profile.tone_of_voice or "")
            profile.brand_props = dna_data.get("brand_props", profile.brand_props or [])
            profile.contacts = dna_data.get("contacts", profile.contacts or {})
            profile.forbidden_topics = dna_data.get("forbidden_topics", profile.forbidden_topics or [])

            await session.commit()

    @staticmethod
    async def get_brand_dna(tenant_id: str) -> Optional[Dict[str, Any]]:
        """Извлечение профиля бренда по tenant_id."""
        async with AsyncSessionLocal() as session:
            stmt = select(BrandProfileModel).where(BrandProfileModel.tenant_id == tenant_id)
            result = await session.execute(stmt)
            profile = result.scalars().first()
            if not profile:
                return None
            return {
                "tenant_id": profile.tenant_id,
                "company_name": profile.company_name,
                "industry_type": profile.industry_type,
                "tone_of_voice": profile.tone_of_voice,
                "brand_props": profile.brand_props or [],
                "contacts": profile.contacts or {},
                "forbidden_topics": profile.forbidden_topics or []
            }

    @staticmethod
    async def save_knowledge_chunks(tenant_id: str, source_type: str, chunks_with_embeddings: List[dict]) -> None:
        """Пакетное сохранение векторных чанков в БД."""
        async with AsyncSessionLocal() as session:
            for item in chunks_with_embeddings:
                chunk = TenantKnowledgeChunk(
                    chunk_id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    source_type=source_type,
                    content=item["text"],
                    embedding=item["vector"]
                )
                session.add(chunk)
            await session.commit()

    @staticmethod
    async def semantic_search(
        tenant_id: str, 
        query_vector: List[float], 
        top_k: int = 3, 
        threshold: float = 0.82
    ) -> List[str]:
        """
        Извлекает наиболее релевантные чанки знаний строго в рамках одного tenant_id.
        Использует косинусное сходство (pgvector нативно или numpy локально).
        """
        async with AsyncSessionLocal() as session:
            if IS_POSTGRES:
                # Нативный поиск через pgvector ( <=> - оператор косинусного расстояния)
                # Cosine Similarity = 1 - Cosine Distance
                stmt = (
                    select(TenantKnowledgeChunk.content)
                    .where(TenantKnowledgeChunk.tenant_id == tenant_id)
                    .where(1 - TenantKnowledgeChunk.embedding.cosine_distance(query_vector) >= threshold)
                    .order_by(TenantKnowledgeChunk.embedding.cosine_distance(query_vector))
                    .limit(top_k)
                )
                result = await session.execute(stmt)
                return list(result.scalars().all())
            else:
                # Фоллбек для SQLite (Локальное вычисление numpy)
                stmt = select(TenantKnowledgeChunk).where(TenantKnowledgeChunk.tenant_id == tenant_id)
                result = await session.execute(stmt)
                chunks = result.scalars().all()
                
                scored_chunks = []
                q_vec = np.array(query_vector)
                q_norm = np.linalg.norm(q_vec)
                if q_norm == 0:
                    return []
                
                for chunk in chunks:
                    c_vec = np.array(chunk.embedding)
                    c_norm = np.linalg.norm(c_vec)
                    if c_norm == 0:
                        continue
                    similarity = float(np.dot(q_vec, c_vec) / (q_norm * c_norm))
                    if similarity >= threshold:
                        scored_chunks.append((similarity, chunk.content))
                
                # Сортировка по убыванию сходства
                scored_chunks.sort(key=lambda x: x[0], reverse=True)
                return [c[1] for c in scored_chunks[:top_k]]
