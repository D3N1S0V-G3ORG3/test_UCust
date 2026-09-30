"""
File: ai/storage/pgvector_store.py
Боевая интеграция с PostgreSQL pgvector (>= 0.7.0).
Использует halfvec(1536) (FP16), Negative Inner Product (<#>), денормализованный HNSW Pre-Filtering
и атомарный ON CONFLICT UPSERT для исключения Race Conditions и деградации поиска.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("PGVectorStore")

# Размерность эмбеддингов
EMBEDDING_DIM: int = 1536

# Порог косинусного сходства для дедупликации (0.82)
DEFAULT_SIMILARITY_THRESHOLD: float = 0.82


class PGVectorStore:
    """
    Хранилище семантических векторов на базе PostgreSQL pgvector (halfvec + HNSW).
    
    1. HNSW Pre-Filtering: денормализация project_id в fact_embeddings позволяет pgvector
       отсекать нерелевантные узлы непосредственно при обходе графа HNSW, сохраняя O(log N).
    2. ACID Идемпотентность (ON CONFLICT): атомарный UPSERT по бизнес-ключу
       (project_id, sku_id, fact_type) защищает от Race Conditions и дубликатов при параллельном инжестинге.
    3. Квантование halfvec(1536) & Negative Inner Product (<#>): снижает объем RAM на 50%
       и исключает затратные операции деления на нормы векторов.
    """

    def __init__(self, db_session: Any = None):
        self.db = db_session
        self.connected = bool(db_session is not None)
        self._fallback_records: List[Dict[str, Any]] = []

    async def upsert_fact(
        self,
        project_id: str,
        sku_id: Optional[str],
        fact_type: str,
        embedding: List[float],
        version: int = 1,
        valid_until: Optional[datetime] = None
    ) -> int:
        """
        Атомарный UPSERT факта и его эмбеддинга (ON CONFLICT DO UPDATE).
        """
        if len(embedding) != EMBEDDING_DIM:
            logger.warning(
                f"[PGVectorStore] Нестандартная размерность вектора {len(embedding)}, "
                f"ожидается {EMBEDDING_DIM}."
            )

        if self.connected:
            try:
                from sqlalchemy import text
                
                # 1. Атомарный UPSERT метаданных по UNIQUE констрейнту uq_fact_business_key
                upsert_meta_stmt = text("""
                    INSERT INTO fact_metadata (project_id, sku_id, fact_type, version, valid_until)
                    VALUES (:project_id, :sku_id, :fact_type, :version, :valid_until)
                    ON CONFLICT (project_id, sku_id, fact_type) 
                    DO UPDATE SET 
                        version = EXCLUDED.version,
                        valid_until = EXCLUDED.valid_until
                    RETURNING id
                """)
                res = await self.db.execute(
                    upsert_meta_stmt,
                    {
                        "project_id": project_id,
                        "sku_id": sku_id,
                        "fact_type": fact_type,
                        "version": version,
                        "valid_until": valid_until
                    }
                )
                fact_id = res.scalar_one()

                # 2. Атомарный UPSERT вектора с денормализацией ВСЕХ фильтруемых полей
                # Передаем вектор напрямую: asyncpg передает binary float8[], PostgreSQL кастует в halfvec
                upsert_emb_stmt = text("""
                    INSERT INTO fact_embeddings (fact_id, project_id, valid_until, embedding)
                    VALUES (:fact_id, :project_id, :valid_until, :emb::halfvec)
                    ON CONFLICT (fact_id) 
                    DO UPDATE SET 
                        embedding = EXCLUDED.embedding,
                        project_id = EXCLUDED.project_id,
                        valid_until = EXCLUDED.valid_until
                """)
                await self.db.execute(
                    upsert_emb_stmt,
                    {
                        "fact_id": fact_id,
                        "project_id": project_id,
                        "valid_until": valid_until,
                        "emb": embedding
                    }
                )
                await self.db.commit()

                logger.info(
                    f"💾 [PGVectorStore] Факт {fact_id} ({fact_type}, project={project_id}) "
                    f"атомарно сохранен с halfvec(1536)."
                )
                return fact_id
            except Exception as e:
                logger.error(f"❌ [PGVectorStore] Ошибка при upsert факта: {e}", exc_info=True)
                if hasattr(self.db, "rollback"):
                    await self.db.rollback()
                raise

        # In-Memory Fallback
        self._fallback_records = [
            r for r in self._fallback_records
            if not (r["project_id"] == project_id and r["sku_id"] == sku_id and r["fact_type"] == fact_type)
        ]
        fact_id = len(self._fallback_records) + 1
        self._fallback_records.append({
            "id": fact_id,
            "project_id": project_id,
            "sku_id": sku_id,
            "fact_type": fact_type,
            "version": version,
            "valid_until": valid_until,
            "embedding": embedding
        })
        return fact_id

    async def search_relevant_facts(
        self,
        project_id: str,
        query_embedding: List[float],
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Поиск релевантных фактов с HNSW Pre-Filtering по fe.project_id и fe.valid_until.
        Порог косинусного сходства 0.82 транслируется в (embedding <#> query) < -0.82.
        """
        neg_ip_threshold = -float(similarity_threshold)

        if self.connected:
            try:
                from sqlalchemy import text
                search_stmt = text("""
                    SELECT 
                        fm.id as fact_id,
                        fm.sku_id,
                        fm.fact_type,
                        fm.version,
                        (fe.embedding <#> :emb::halfvec) * -1.0 as similarity_score
                    FROM fact_embeddings fe
                    JOIN fact_metadata fm ON fe.fact_id = fm.id
                    -- Истинный Pre-filtering: ВСЕ предикаты лежат в таблице индекса
                    WHERE fe.project_id = :project_id
                      AND (fe.valid_until IS NULL OR fe.valid_until > CURRENT_TIMESTAMP)
                      AND (fe.embedding <#> :emb::halfvec) < :neg_ip_threshold
                    ORDER BY fe.embedding <#> :emb::halfvec ASC
                    LIMIT :limit
                """)
                res = await self.db.execute(
                    search_stmt,
                    {
                        "project_id": project_id,
                        "emb": query_embedding,
                        "neg_ip_threshold": neg_ip_threshold,
                        "limit": limit
                    }
                )
                rows = res.mappings().all()
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"❌ [PGVectorStore] Ошибка поиска фактов: {e}", exc_info=True)
                return []

        # Fallback In-Memory search via inner product
        results = []
        for r in self._fallback_records:
            if r["project_id"] != project_id:
                continue
            if r["valid_until"] and r["valid_until"] <= datetime.utcnow():
                continue
            sim = sum(a * b for a, b in zip(query_embedding, r["embedding"]))
            if sim >= similarity_threshold:
                results.append({
                    "fact_id": r["id"],
                    "sku_id": r["sku_id"],
                    "fact_type": r["fact_type"],
                    "version": r["version"],
                    "similarity_score": sim
                })
        results.sort(key=lambda x: x["similarity_score"], reverse=True)
        return results[:limit]

    async def is_duplicate(
        self,
        project_id: str,
        embedding: List[float],
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD
    ) -> Tuple[bool, float]:
        """
        Проверка уникальности через Negative Inner Product.
        Возвращает (is_duplicate, max_similarity).
        """
        facts = await self.search_relevant_facts(
            project_id=project_id,
            query_embedding=embedding,
            similarity_threshold=threshold,
            limit=1
        )
        if facts:
            max_sim = facts[0]["similarity_score"]
            return True, max_sim
        return False, 0.0
