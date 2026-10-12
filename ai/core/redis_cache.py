"""
File: ai/core/redis_cache.py
Менеджер кэширования этапов конвейера и семантического поиска RAG.
Реализует безопасное кэширование с bounded TTL и защитой от утечек памяти (bounded fallback cache).
"""

from __future__ import annotations

import json
import time
import hashlib
import logging
from typing import Any, Optional, Dict, Tuple
from collections import OrderedDict

logger = logging.getLogger("RedisCacheManager")

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class RedisCacheManager:
    """
    Менеджер кэширования состояний Оркестратора и RAG-запросов.
    Использует Redis с автоматическим fallback на ограниченный in-memory LRU-кэш с TTL.
    """
    def __init__(
        self,
        host: str = 'localhost',
        port: int = 6379,
        db: int = 0,
        max_fallback_size: int = 500
    ):
        self.connected = False
        self.max_fallback_size = max_fallback_size
        # Fallback кэш: key -> (value, expire_timestamp)
        self._fallback_cache: OrderedDict[str, Tuple[Any, Optional[float]]] = OrderedDict()
        self.redis_client = None

        if REDIS_AVAILABLE:
            try:
                self.redis_client = redis.Redis(
                    host=host,
                    port=port,
                    db=db,
                    decode_responses=True,
                    socket_connect_timeout=2.0
                )
                self.redis_client.ping()
                self.connected = True
                logger.info("[RedisCacheManager] 🟢 Успешное подключение к Redis.")
            except Exception as e:
                logger.warning(f"[RedisCacheManager] ⚠️ Redis недоступен: {e}. Fallback на bounded In-Memory.")
        else:
            logger.warning("[RedisCacheManager] ⚠️ Модуль 'redis' не установлен. Fallback на bounded In-Memory.")

    def _evict_fallback_if_needed(self):
        """Очищает просроченные ключи и удерживает размер in-memory кэша в пределах max_fallback_size."""
        now = time.time()
        # 1. Удаление просроченных записей
        expired_keys = [
            k for k, (_, exp) in self._fallback_cache.items()
            if exp is not None and now > exp
        ]
        for k in expired_keys:
            self._fallback_cache.pop(k, None)

        # 2. LRU вытеснение, если размер превышает порог
        while len(self._fallback_cache) > self.max_fallback_size:
            self._fallback_cache.popitem(last=False)

    def get_cached_result(self, action: str, payload_hash: str) -> Optional[dict]:
        """
        Проверяет, есть ли уже вычисленный результат для данного действия и хэша.
        """
        key = f"trace:{action}:{payload_hash}"
        if self.connected and self.redis_client:
            try:
                cached = self.redis_client.get(key)
                if cached:
                    logger.debug(f"[RedisCacheManager] ⚡ Найдено в Redis! Action: {action}, Hash: {payload_hash[:8]}")
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"[RedisCacheManager] Ошибка чтения из Redis: {e}")

        # Fallback in-memory
        if key in self._fallback_cache:
            val, exp = self._fallback_cache[key]
            if exp is not None and time.time() > exp:
                self._fallback_cache.pop(key, None)
                return None
            # Обновляем LRU позицию
            self._fallback_cache.move_to_end(key)
            logger.debug(f"[RedisCacheManager] ⚡ Найдено в локальном кэше! Action: {action}, Hash: {payload_hash[:8]}")
            return val
        return None

    def set_cached_result(self, action: str, payload_hash: str, result: Any, ttl: int = 3600):
        """
        Сохраняет результат работы агента (по умолчанию TTL = 1 час).
        """
        key = f"trace:{action}:{payload_hash}"
        if self.connected and self.redis_client:
            try:
                self.redis_client.setex(key, ttl, json.dumps(result, ensure_ascii=False))
                logger.debug(f"[RedisCacheManager] 💾 Результат закеширован в Redis. Action: {action}")
                return
            except Exception as e:
                logger.warning(f"[RedisCacheManager] Ошибка записи в Redis: {e}")

        # Fallback
        exp = time.time() + ttl if ttl > 0 else None
        if key in self._fallback_cache:
            self._fallback_cache.pop(key, None)
        self._fallback_cache[key] = (result, exp)
        self._evict_fallback_if_needed()
        logger.debug(f"[RedisCacheManager] 💾 Результат закеширован локально. Action: {action}")

    # -------------------------------------------------------------------------
    # RAG Semantic Cache (TTL = 4 часа по умолчанию)
    # -------------------------------------------------------------------------

    def _rag_key(self, query: str, tenant_id: str) -> str:
        q_hash = hashlib.sha256(f"{tenant_id}:{query.strip().lower()}".encode('utf-8')).hexdigest()
        return f"rag:{tenant_id}:{q_hash}"

    def get_cached_rag_query(self, query: str, tenant_id: str = "default") -> Optional[Any]:
        """
        Возвращает закешированный RAG контекст/результат для тенанта и запроса.
        """
        key = self._rag_key(query, tenant_id)
        if self.connected and self.redis_client:
            try:
                cached = self.redis_client.get(key)
                if cached:
                    logger.debug(f"[RedisCacheManager] ⚡ RAG кэш попадание для тенанта '{tenant_id}'")
                    return json.loads(cached)
            except Exception as e:
                logger.warning(f"[RedisCacheManager] Ошибка чтения RAG кэша: {e}")

        if key in self._fallback_cache:
            val, exp = self._fallback_cache[key]
            if exp is not None and time.time() > exp:
                self._fallback_cache.pop(key, None)
                return None
            self._fallback_cache.move_to_end(key)
            return val
        return None

    def set_cached_rag_query(
        self,
        query: str,
        tenant_id: str = "default",
        result: Any = None,
        ttl: int = 14400
    ) -> None:
        """
        Сохраняет результат RAG поиска с дефолтным TTL 4 часа (14400 секунд).
        """
        key = self._rag_key(query, tenant_id)
        if self.connected and self.redis_client:
            try:
                self.redis_client.setex(key, ttl, json.dumps(result, ensure_ascii=False))
                return
            except Exception as e:
                logger.warning(f"[RedisCacheManager] Ошибка записи RAG кэша: {e}")

        exp = time.time() + ttl if ttl > 0 else None
        if key in self._fallback_cache:
            self._fallback_cache.pop(key, None)
        self._fallback_cache[key] = (result, exp)
        self._evict_fallback_if_needed()

    def clear_expired(self) -> int:
        """Принудительно очищает просроченные записи из fallback-кэша. Возвращает кол-во удаленных."""
        now = time.time()
        expired_keys = [
            k for k, (_, exp) in self._fallback_cache.items()
            if exp is not None and now > exp
        ]
        for k in expired_keys:
            self._fallback_cache.pop(k, None)
        return len(expired_keys)
