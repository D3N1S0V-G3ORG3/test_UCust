"""
File: ai/api/rate_limiter.py
Атомарный Redis Token Bucket Rate Limiter и Concurrency Guard для FastAPI Gateway.
Реализует:
1. Атомарный Lua-скрипт в Redis для потокобезопасного списания токенов без Race Conditions между воркерами.
2. Fast-Fail с возвратом HTTP 429 Too Many Requests и заголовками Retry-After, X-RateLimit-*.
3. Bounded in-memory fallback при локальной разработке без Redis.
4. Concurrency Guard для жесткого ограничения одновременных тяжелых генераций на тенант.
"""

from __future__ import annotations

import os
import time
import math
import asyncio
import logging
from typing import Optional, Callable, Dict, Tuple
from fastapi import Request, HTTPException, status, Response

logger = logging.getLogger("RateLimiter")

try:
    import redis.asyncio as aioredis
    HAS_AIOREDIS = True
except ImportError:
    HAS_AIOREDIS = False

# Атомарный Lua скрипт Token Bucket для Redis
TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local now = tonumber(ARGV[4])

local data = redis.call("HMGET", key, "tokens", "last_updated")
local tokens = tonumber(data[1])
local last_updated = tonumber(data[2])

if not tokens or not last_updated then
    tokens = capacity
    last_updated = now
else
    local elapsed = math.max(0, now - last_updated)
    tokens = math.min(capacity, tokens + (elapsed * refill_rate))
    last_updated = now
end

if tokens >= requested then
    tokens = tokens - requested
    redis.call("HMSET", key, "tokens", tokens, "last_updated", last_updated)
    local ttl = math.ceil(capacity / refill_rate) * 2
    redis.call("EXPIRE", key, math.max(60, ttl))
    return {1, math.floor(tokens), 0}
else
    local missing = requested - tokens
    local retry_after = math.ceil(missing / refill_rate)
    return {0, math.floor(tokens), math.max(1, retry_after)}
end
"""


class RedisTokenBucketRateLimiter:
    """
    Потокобезопасный распределенный лимитер запросов (Token Bucket):
    - Выполняет списание токенов атомарно через Redis Lua Script.
    - При отсутствии Redis переключается на thread-safe in-memory словарь.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis_client: Optional[aioredis.Redis] = None
        self._lua_script_sha: Optional[str] = None
        # Fallback: key -> (current_tokens, last_updated_timestamp)
        self._memory_buckets: Dict[str, Tuple[float, float]] = {}
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        if not HAS_AIOREDIS:
            return None
        if self._redis_client is None:
            try:
                client = aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2.0
                )
                await client.ping()
                self._redis_client = client
                self._lua_script_sha = await client.script_load(TOKEN_BUCKET_LUA)
                logger.info("🟢 [RateLimiter] Загружен атомарный Token Bucket Lua скрипт в Redis.")
            except Exception as e:
                logger.warning(f"⚠️ [RateLimiter] Redis недоступен: {e}. Fallback на In-Memory Token Bucket.")
                self._redis_client = None
        return self._redis_client

    async def check_rate_limit(
        self,
        key: str,
        refill_rate: float,
        capacity: int,
        requested: int = 1
    ) -> Tuple[bool, int, int]:
        """
        Проверяет и списывает токены для ключа.
        Возвращает: (is_allowed, remaining_tokens, retry_after_sec)
        """
        now = time.time()
        client = await self._get_redis()

        if client is not None:
            try:
                redis_key = f"ratelimit:{key}"
                res = await client.evalsha(
                    self._lua_script_sha,
                    1,
                    redis_key,
                    capacity,
                    refill_rate,
                    requested,
                    now
                )
                allowed = bool(res[0] == 1)
                remaining = int(res[1])
                retry_after = int(res[2])
                return allowed, remaining, retry_after
            except Exception as e:
                logger.warning(f"[RateLimiter] Ошибка Redis evalsha: {e}. Fallback на in-memory.")

        # In-memory Token Bucket fallback
        async with self._lock:
            if key not in self._memory_buckets:
                tokens = float(capacity)
                last_updated = now
            else:
                tokens, last_updated = self._memory_buckets[key]
                elapsed = max(0.0, now - last_updated)
                tokens = min(float(capacity), tokens + (elapsed * refill_rate))
                last_updated = now

            if tokens >= requested:
                tokens -= requested
                self._memory_buckets[key] = (tokens, last_updated)
                return True, int(tokens), 0
            else:
                missing = requested - tokens
                retry_after = max(1, math.ceil(missing / refill_rate))
                return False, int(tokens), retry_after


class ConcurrencyLimiter:
    """
    Ограничитель одновременных тяжелых генераций (Concurrency Guard).
    Предотвращает запуск более N одновременных пайплайнов на одного клиента/тенант.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis_client: Optional[aioredis.Redis] = None
        self._memory_counts: Dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def _get_redis(self) -> Optional[aioredis.Redis]:
        if not HAS_AIOREDIS:
            return None
        if self._redis_client is None:
            try:
                client = aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2.0
                )
                await client.ping()
                self._redis_client = client
            except Exception:
                self._redis_client = None
        return self._redis_client

    async def acquire(self, key: str, max_concurrent: int = 3) -> bool:
        """Попытка захвата слота параллельной генерации."""
        client = await self._get_redis()
        redis_key = f"concurrency:{key}"
        if client is not None:
            try:
                current = await client.incr(redis_key)
                if current == 1:
                    await client.expire(redis_key, 600)  # Таймаут 10 минут на случай зависания
                if current > max_concurrent:
                    await client.decr(redis_key)
                    return False
                return True
            except Exception:
                pass

        async with self._lock:
            current = self._memory_counts.get(key, 0)
            if current >= max_concurrent:
                return False
            self._memory_counts[key] = current + 1
            return True

    async def release(self, key: str) -> None:
        """Освобождение слота после завершения пайплайна."""
        client = await self._get_redis()
        redis_key = f"concurrency:{key}"
        if client is not None:
            try:
                val = await client.decr(redis_key)
                if val <= 0:
                    await client.delete(redis_key)
                return
            except Exception:
                pass

        async with self._lock:
            if key in self._memory_counts:
                self._memory_counts[key] = max(0, self._memory_counts[key] - 1)
                if self._memory_counts[key] == 0:
                    del self._memory_counts[key]


# Глобальные синглтоны
global_rate_limiter = RedisTokenBucketRateLimiter()
global_concurrency_limiter = ConcurrencyLimiter()


def get_client_identifier(request: Request) -> str:
    """Извлекает tenant_id из заголовков или авторизации, либо откатывается на client IP."""
    tenant = request.headers.get("X-Tenant-ID") or request.headers.get("x-tenant-id")
    if tenant:
        return f"tenant:{tenant}"
    
    # Попытка извлечь IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
        return f"ip:{ip}"
    
    client_host = request.client.host if request.client else "unknown_client"
    return f"ip:{client_host}"


class RateLimitGuard:
    """
    FastAPI Dependency для защиты эндпоинтов по алгоритму Token Bucket.
    """
    def __init__(self, rps: float = 10.0, burst: int = 20, cost: int = 1):
        self.refill_rate = rps
        self.capacity = burst
        self.cost = cost

    async def __call__(self, request: Request, response: Response):
        client_key = get_client_identifier(request)
        allowed, remaining, retry_after = await global_rate_limiter.check_rate_limit(
            key=client_key,
            refill_rate=self.refill_rate,
            capacity=self.capacity,
            requested=self.cost
        )

        response.headers["X-RateLimit-Limit"] = str(self.capacity)
        response.headers["X-RateLimit-Remaining"] = str(remaining)

        if not allowed:
            response.headers["Retry-After"] = str(retry_after)
            logger.warning(f"🚫 [RateLimit] Превышен лимит запросов для '{client_key}' (Retry-After: {retry_after}s)")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)}
            )
