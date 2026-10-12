"""
File: ai/api/streaming.py
Распределенная шина событий (PipelineEventBus) и Server-Sent Events (SSE) стример.
Поддерживает:
1. Redis Pub/Sub для трансляции событий между воркерами FastAPI и фоновыми Celery тасками.
2. Автовосстановление соединения через Last-Event-ID и историю событий в Redis (TTL 1ч).
3. Heartbeat / Keep-Alive ping (: ping\n\n) для защиты от сброса соединения таймаутами Nginx/Cloudflare.
4. Fallback на локальную asyncio.Queue при отсутствии Redis.
"""

from __future__ import annotations

import os
import json
import time
import asyncio
import logging
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Optional, Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, Request, Header, HTTPException, status
from fastapi.responses import StreamingResponse

logger = logging.getLogger("PipelineStreaming")

try:
    import redis.asyncio as aioredis
    HAS_AIOREDIS = True
except ImportError:
    HAS_AIOREDIS = False

router = APIRouter(prefix="/api/v1/pipeline", tags=["Pipeline Live Streaming"])


class PipelineEvent(BaseModel):
    """Строгая Pydantic v2 схема события этапа генерации."""
    event_id: str = Field(default_factory=lambda: f"{int(time.time())}_{os.urandom(3).hex()}")
    event_type: str = Field(..., description="step_started | step_progress | step_completed | pipeline_finished | pipeline_error")
    session_id: str = Field(...)
    stage: str = Field(..., description="brand_dna | rag_research | content_draft | critic_review | visual_render | publishing")
    progress_pct: int = Field(default=0, ge=0, le=100)
    message: str = Field(default="")
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_sse_format(self) -> str:
        """Сериализация в стандартный SSE фрейм с event, id и data."""
        data_json = json.dumps(self.model_dump(mode="json"), ensure_ascii=False)
        return f"id: {self.event_id}\nevent: {self.event_type}\ndata: {data_json}\n\n"


class DistributedPipelineEventBus:
    """
    Распределенная шина событий:
    - Публикует события в Redis Pub/Sub (канал `pipeline:events:{session_id}`).
    - Сохраняет историю событий в Redis List (`pipeline:history:{session_id}`) для Last-Event-ID.
    - Обеспечивает плавный fallback на in-memory очереди при локальном запуске без Redis.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self._redis_client: Optional[aioredis.Redis] = None
        self._in_memory_channels: Dict[str, List[asyncio.Queue]] = {}
        self._in_memory_history: Dict[str, List[PipelineEvent]] = {}
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
                logger.info("🟢 [EventBus] Успешное подключение к Redis Pub/Sub для SSE.")
            except Exception as e:
                logger.warning(f"⚠️ [EventBus] Redis Pub/Sub недоступен: {e}. Применен in-memory fallback.")
                self._redis_client = None
        return self._redis_client

    async def publish_event(self, event: PipelineEvent) -> None:
        """
        Публикует событие в канал сессии и сохраняет в историю.
        Безопасно вызывается из FastAPI воркеров или Celery задач.
        """
        client = await self._get_redis()
        event_dict = event.model_dump(mode="json")
        event_json = json.dumps(event_dict, ensure_ascii=False)
        channel_name = f"pipeline:events:{event.session_id}"
        history_key = f"pipeline:history:{event.session_id}"

        if client is not None:
            try:
                # 1. Публикация в канал подписчиков
                await client.publish(channel_name, event_json)
                # 2. Сохранение в кольцевую историю (TTL 1 час)
                await client.rpush(history_key, event_json)
                await client.expire(history_key, 3600)
                logger.debug(f"📡 [EventBus:Redis] Опубликовано '{event.event_type}' в {channel_name}")
                return
            except Exception as e:
                logger.warning(f"[EventBus] Ошибка Redis publish: {e}. Используем fallback.")

        # In-memory fallback
        async with self._lock:
            # Сохраняем в локальную историю
            if event.session_id not in self._in_memory_history:
                self._in_memory_history[event.session_id] = []
            self._in_memory_history[event.session_id].append(event)

            # Отправляем локальным слушателям
            queues = self._in_memory_channels.get(event.session_id, [])
            for q in queues:
                await q.put(event)
            logger.debug(f"📡 [EventBus:Memory] Опубликовано '{event.event_type}' локально ({len(queues)} слушателей)")

    async def subscribe_stream(
        self,
        session_id: str,
        last_event_id: Optional[str] = None,
        heartbeat_interval_sec: float = 15.0
    ) -> AsyncGenerator[str, None]:
        """
        Асинхронный генератор SSE стрима:
        1. Воспроизводит пропущенные события из истории при наличии Last-Event-ID.
        2. Слушает живой Redis Pub/Sub канал (или in-memory очередь).
        3. Отправляет keep-alive пинги для предотвращения сброса соединения Nginx.
        """
        client = await self._get_redis()

        # --- 1. Воспроизведение пропущенной истории (Last-Event-ID recovery) ---
        history_events: List[PipelineEvent] = []
        if client is not None:
            try:
                raw_history = await client.lrange(f"pipeline:history:{session_id}", 0, -1)
                for item in raw_history:
                    try:
                        history_events.append(PipelineEvent(**json.loads(item)))
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"[EventBus] Не удалось прочитать историю из Redis: {e}")
        else:
            async with self._lock:
                history_events = list(self._in_memory_history.get(session_id, []))

        # Если передан last_event_id — фильтруем только новые события
        replay_started = False if last_event_id else True
        for h_event in history_events:
            if not replay_started:
                if h_event.event_id == last_event_id:
                    replay_started = True
                continue
            yield h_event.to_sse_format()
            if h_event.event_type in ("pipeline_finished", "pipeline_error"):
                return

        # --- 2. Подписка на живой поток событий ---
        if client is not None:
            channel_name = f"pipeline:events:{session_id}"
            pubsub = client.pubsub()
            await pubsub.subscribe(channel_name)
            logger.info(f"🟢 [SSE] Клиент подключился к стриму сессии {session_id} (Redis PubSub)")

            try:
                while True:
                    try:
                        # Ожидаем сообщение с таймаутом для heartbeat
                        msg = await asyncio.wait_for(
                            pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                            timeout=heartbeat_interval_sec
                        )
                        if msg and msg.get("type") == "message":
                            data = msg.get("data")
                            if data:
                                event_obj = PipelineEvent(**json.loads(data))
                                yield event_obj.to_sse_format()
                                if event_obj.event_type in ("pipeline_finished", "pipeline_error"):
                                    break
                    except asyncio.TimeoutError:
                        # Heartbeat ping против таймаутов прокси
                        yield ": ping\n\n"
            finally:
                try:
                    await pubsub.unsubscribe(channel_name)
                    await pubsub.close()
                except Exception:
                    pass
                logger.info(f"🔌 [SSE] Клиент отключился от стрима сессии {session_id}")

        else:
            # In-memory fallback подписка
            local_queue: asyncio.Queue[PipelineEvent] = asyncio.Queue()
            async with self._lock:
                if session_id not in self._in_memory_channels:
                    self._in_memory_channels[session_id] = []
                self._in_memory_channels[session_id].append(local_queue)

            logger.info(f"🟢 [SSE] Клиент подключился к локальному стриму сессии {session_id}")
            try:
                while True:
                    try:
                        event_obj = await asyncio.wait_for(local_queue.get(), timeout=heartbeat_interval_sec)
                        yield event_obj.to_sse_format()
                        if event_obj.event_type in ("pipeline_finished", "pipeline_error"):
                            break
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                async with self._lock:
                    if session_id in self._in_memory_channels:
                        try:
                            self._in_memory_channels[session_id].remove(local_queue)
                        except ValueError:
                            pass
                logger.info(f"🔌 [SSE] Клиент отключился от локального стрима {session_id}")


# Глобальный инстанс шины
global_event_bus = DistributedPipelineEventBus()


@router.get(
    "/stream/{session_id}",
    summary="Server-Sent Events (SSE) стриминг прогресса генерации",
    description="Транслирует этапы выполнения конвейера (PIM Grounding, Saiga Draft, Munger OTK, Renders) в реальном времени.",
    response_class=StreamingResponse,
)
async def stream_pipeline_progress(
    session_id: str,
    request: Request,
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID")
):
    """
    SSE эндпоинт стриминга прогресса мультиагентного конвейера.
    Возвращает media_type='text/event-stream' с заголовками для отключения буферизации Nginx.
    """
    stream_generator = global_event_bus.subscribe_stream(
        session_id=session_id,
        last_event_id=last_event_id
    )

    headers = {
        "Content-Type": "text/event-stream; charset=utf-8",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # Отключение буферизации Nginx
    }

    return StreamingResponse(
        stream_generator,
        media_type="text/event-stream",
        headers=headers
    )
