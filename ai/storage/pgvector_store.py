"""
File: ai/storage/pgvector_store.py
Боевая интеграция с PostgreSQL pgvector (>= 0.7.0).
Использует halfvec(1536) (FP16), Negative Inner Product (<#>) и Hard Delete каскадную инвалидацию.
"""

from __future__ import annotations

import json
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
    
    1. Квантование halfvec(1536): сокращает объем памяти таблицы и HNSW-индекса на 50%.
    2. Negative Inner Product (<#>): вычисляет (dot_product * -1) для нормализованных векторов,
       исключая деление и ускоряя поиск на 15-20%.
    3. Hard Delete Invalidation: каскадное удаление старых версий фактов (ON DELETE CASCADE)
       исключает 'черные дыры' и Post-filtering деградацию HNSW графа при Soft Delete.
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
        Атомарный Upsert факта с физическим удалением старых версий (Hard Delete).
        Физическое удаление запускает перестроение связей в графе HNSW.
        """
        if len(embedding) != EMBEDDING_DIM:
            # Предупреждение или выравнивание размерности при несовпадении
            logger.warning(
                f"[PGVectorStore] Нестандартная размерность вектора {len(embedding)}, "
                f"ожидается {EMBEDDING_DIM}."
            )

        if self.connected:
            try:
                from sqlalchemy import text
                # 1. Hard Delete старой версии в рамках транзакции
                delete_stmt = text("""
                    DELETE FROM fact_metadata 
                    WHERE project_id = :project_id 
                      AND (sku_id = :sku_id OR (:sku_id IS NULL AND sku_id IS NULL))
                      AND fact_type = :fact_type
                """)
                await self.db.execute(
                    delete_stmt,
                    {"project_id": project_id, "sku_id": sku_id, "fact_type": fact_type}
                )

                # 2. Вставка новых метаданных
                insert_meta_stmt = text("""
                    INSERT INTO fact_metadata (project_id, sku_id, fact_type, version, valid_until)
                    VALUES (:project_id, :sku_id, :fact_type, :version, :valid_until)
                    RETURNING id
                """)
                res = await self.db.execute(
                    insert_meta_stmt,
                    {
                        "project_id": project_id,
                        "sku_id": sku_id,
                        "fact_type": fact_type,
                        "version": version,
                        "valid_until": valid_until
                    }
                )
                fact_id = res.scalar_one()

                # 3. Вставка вектора halfvec(1536)
                emb_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
                insert_emb_stmt = text("""
                    INSERT INTO fact_embeddings (fact_id, embedding)
                    VALUES (:fact_id, CAST(:emb AS halfvec))
                """)
                await self.db.execute(insert_emb_stmt, {"fact_id": fact_id, "emb": emb_str})
                await self.db.commit()

                logger.info(f"💾 [PGVectorStore] Факт {fact_id} ({fact_type}) успешно сохранен с halfvec(1536).")
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
        Поиск релевантных фактов через Negative Inner Product (<#>) в HNSW-индексе halfvec.
        Порог косинусного сходства 0.82 транслируется в (embedding <#> query) < -0.82.
        """
        neg_ip_threshold = -float(similarity_threshold)

        if self.connected:
            try:
                from sqlalchemy import text
                emb_str = "[" + ",".join(str(float(x)) for x in query_embedding) + "]"
                search_stmt = text("""
                    SELECT 
                        fm.id as fact_id,
                        fm.sku_id,
                        fm.fact_type,
                        fm.version,
                        (fe.embedding <#> CAST(:emb AS halfvec)) * -1.0 as similarity_score
                    FROM fact_embeddings fe
                    JOIN fact_metadata fm ON fe.fact_id = fm.id
                    WHERE fm.project_id = :project_id
                      AND (fm.valid_until IS NULL OR fm.valid_until > CURRENT_TIMESTAMP)
                      AND (fe.embedding <#> CAST(:emb AS halfvec)) < :neg_ip_threshold
                    ORDER BY fe.embedding <#> CAST(:emb AS halfvec) ASC
                    LIMIT :limit
                """)
                res = await self.db.execute(
                    search_stmt,
                    {
                        "project_id": project_id,
                        "emb": emb_str,
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
            # Inner product for normalized vectors
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
