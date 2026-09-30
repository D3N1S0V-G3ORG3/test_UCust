"""
File: ai/bridge/comfy_bridge.py
Отказоустойчивый сетевой оркестратор для удаленного пула ComfyUI GPU-воркеров.
Реализует:
1. Балансировку по наименьшей нагрузке (Least Load VRAM Routing) с чистым RAII-учетом ресурсов.
2. Автономный рендеринг: бесшовный переход на HTTP polling /history/{prompt_id} при обрыве WebSocket.
3. Распознавание и аппаратную изоляцию CUDA OOM (mark_node_degraded) без опасного CPU Fallback.
4. Строгий детерминированный SLA: единый глобальный asyncio.wait_for (120s / 300s) на весь пайплайн.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
import websockets

logger = logging.getLogger("ComfyUIBridge")


class CudaOOMError(Exception):
    """Исключение при нехватке видеопамяти (CUDA Out of Memory) на удаленном GPU узле."""
    pass


class RenderTimeoutError(Exception):
    """Превышение максимального времени генерации (Circuit Breaker)."""
    pass


class ComfyUIExecutionError(Exception):
    """Внутренняя ошибка исполнения нод графа ComfyUI."""
    pass


class GPUNode:
    """Модель состояния отдельного удаленного GPU-инстанса в кластере."""

    def __init__(self, url: str, total_vram_gb: float = 24.0):
        self.url = url.rstrip("/")
        self.total_vram_gb = total_vram_gb
        self.allocated_vram_gb: float = 0.0
        self.is_healthy: bool = True
        self.degraded_until: float = 0.0
        self.active_tasks_count: int = 0

    @property
    def is_available(self) -> bool:
        if not self.is_healthy:
            return False
        if time.time() < self.degraded_until:
            return False
        return True

    @property
    def available_vram_gb(self) -> float:
        return max(0.0, self.total_vram_gb - self.allocated_vram_gb)


class GPULoadBalancer:
    """
    Балансировщик нагрузки пула удаленных GPU-воркеров.
    Маршрутизирует задачи по стратегии Least Load (наибольший запас доступной VRAM)
    и изолирует сбойные ноды при обнаружении CUDA OOM с сохранением RAII-консистентности.
    """

    def __init__(self, node_urls: Optional[List[str]] = None):
        if not node_urls:
            raw_hosts = os.getenv("COMFYUI_HOSTS", "")
            if raw_hosts:
                urls = [h.strip() for h in raw_hosts.split(",") if h.strip()]
            else:
                h = os.getenv("COMFYUI_HOST", "127.0.0.1")
                p = os.getenv("COMFYUI_PORT", "8188")
                urls = [f"http://{h}:{p}"]
        else:
            urls = node_urls

        self.nodes: List[GPUNode] = [GPUNode(u) for u in urls]
        self._lock = asyncio.Lock()
        logger.info(f"🚀 [GPULoadBalancer] Инициализирован пул из {len(self.nodes)} GPU-нод: {[n.url for n in self.nodes]}")

    async def acquire_node(self, vram_required_gb: float = 6.0) -> str:
        """
        Выбирает наименее загруженную здоровую GPU-ноду с достаточным запасом VRAM.
        """
        async with self._lock:
            available_nodes = [n for n in self.nodes if n.is_available]
            if not available_nodes:
                # Если все ноды временно деградировали, проверяем окончание таймаута
                now = time.time()
                for n in self.nodes:
                    if now >= n.degraded_until:
                        n.is_healthy = True
                available_nodes = [n for n in self.nodes if n.is_available]

            if not available_nodes:
                raise RuntimeError("❌ [GPULoadBalancer] Все удаленные GPU-ноды временно недоступны или перегружены.")

            # Сортировка по доступной VRAM (по убыванию) и числу активных задач (по возрастанию)
            available_nodes.sort(key=lambda n: (n.available_vram_gb, -n.active_tasks_count), reverse=True)
            chosen_node = available_nodes[0]

            chosen_node.allocated_vram_gb += vram_required_gb
            chosen_node.active_tasks_count += 1
            logger.info(
                f"🎯 [GPULoadBalancer] Выделена нода {chosen_node.url} "
                f"(Свободно VRAM: {chosen_node.available_vram_gb:.1f}GB, Активных задач: {chosen_node.active_tasks_count})"
            )
            return chosen_node.url

    async def release_node(self, node_url: str, vram_gb: float = 6.0) -> None:
        """
        Симметричное освобождение VRAM-квоты ноды (принцип RAII).
        """
        async with self._lock:
            for n in self.nodes:
                if n.url == node_url.rstrip("/"):
                    n.allocated_vram_gb = max(0.0, n.allocated_vram_gb - vram_gb)
                    n.active_tasks_count = max(0, n.active_tasks_count - 1)
                    break

    async def mark_node_degraded(self, node_url: str, cooldown_seconds: int = 180) -> None:
        """
        Маркировка ноды как деградировавшей при CUDA OOM.
        Метка (is_healthy = False) исключает ноду из новых назначений,
        но счетчики VRAM не обнуляются принудительно — освобождение выполняется
        строго симметрично через finally-блоки активных корутин (защита от VRAM Underflow).
        """
        async with self._lock:
            for n in self.nodes:
                if n.url == node_url.rstrip("/"):
                    n.is_healthy = False
                    n.degraded_until = time.time() + cooldown_seconds
                    logger.critical(
                        f"💥 [GPULoadBalancer] Нода {n.url} поймала CUDA OOM! "
                        f"Изоляция из пула на {cooldown_seconds}с (до {time.strftime('%H:%M:%S', time.localtime(n.degraded_until))})."
                    )
                    break


class ComfyUIBridge:
    """
    Асинхронный отказоустойчивый мост взаимодействия с ComfyUI кластером.
    """

    def __init__(self, gpu_pool: Optional[GPULoadBalancer] = None, pool: Optional[GPULoadBalancer] = None):
        self.pool = pool or gpu_pool or GPULoadBalancer()

    async def render_asset(
        self,
        workflow_json: Dict[str, Any],
        is_video: bool = False,
        post_id: Optional[str] = None,
        dev_simulation_mode: bool = False
    ) -> bytes:
        """
        Основной метод рендеринга ассета:
        1. Least Load VRAM маршрутизация.
        2. Жесткий глобальный SLA таймаут (120с / 300с) на весь процесс.
        3. Мониторинг WebSocket с фолбэком на HTTP polling при разрыве TCP.
        4. Изоляция CUDA OOM и RAII-освобождение ресурсов.
        """
        if dev_simulation_mode:
            logger.info(f"🛠️ [DEV MODE] Симуляция генерации ассета для {post_id} (0 GPU).")
            await asyncio.sleep(0.1)
            return (
                b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
                b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
            )

        vram_cost = 12.0 if is_video else 6.0
        timeout_sec = 300 if is_video else 120
        node_url = await self.pool.acquire_node(vram_required_gb=vram_cost)

        async def _execute_with_fallback() -> bytes:
            prompt_id = await self._queue_prompt(node_url, workflow_json)
            logger.info(f"📤 [ComfyUI] Задача {prompt_id} отправлена на {node_url} (timeout={timeout_sec}s)")
            try:
                return await self._monitor_websocket(node_url, prompt_id)
            except (websockets.ConnectionClosed, websockets.WebSocketException, httpx.TransportError, httpx.NetworkError, ConnectionError, OSError) as net_err:
                logger.warning(
                    f"⚠️ [ComfyUI] Обрыв WebSocket на {node_url} ({net_err}). "
                    f"ComfyUI продолжает автономный рендеринг. Переход в режим HTTP Polling..."
                )
                # Поллинг подчиняется родительскому глобальному таймауту asyncio.wait_for
                return await self._poll_history(node_url, prompt_id)

        try:
            # Глобальный Circuit Breaker на весь пайплайн (очередь + мониторинг + поллинг)
            return await asyncio.wait_for(
                _execute_with_fallback(),
                timeout=timeout_sec
            )
        except asyncio.TimeoutError:
            raise RenderTimeoutError(f"Превышен глобальный SLA таймаут {timeout_sec}с при рендере на {node_url}")
        except CudaOOMError:
            # Изоляция деградировавшей ноды без CPU Fallback
            await self.pool.mark_node_degraded(node_url)
            raise
        finally:
            # RAII: Симметричный декремент ресурсов гарантирован при любом исходе
            await self.pool.release_node(node_url, vram_gb=vram_cost)

    async def render_image(
        self,
        spec: Any,
        post_id: str,
        dev_simulation_mode: bool = False
    ) -> bytes:
        """Совместимый интерфейс для существующих контроллеров."""
        from ai.bridge.comfy_workflow_templates import WorkflowBuilder
        workflow = WorkflowBuilder.build_payload(
            prompt=spec.prompt,
            negative_prompt=spec.negative_prompt,
            width=spec.width,
            height=spec.height,
            seed=spec.seed,
            filename_prefix=f"ucust_{post_id}"
        )
        return await self.render_asset(
            workflow_json=workflow,
            is_video=False,
            post_id=post_id,
            dev_simulation_mode=dev_simulation_mode
        )

    async def _queue_prompt(self, node_url: str, workflow: Dict[str, Any]) -> str:
        """Отправка графа в REST API /prompt."""
        url = f"{node_url}/prompt"
        client_id = str(uuid.uuid4())
        payload = {"prompt": workflow, "client_id": client_id}

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=15.0)
            response.raise_for_status()
            return response.json().get("prompt_id")

    async def _monitor_websocket(self, node_url: str, prompt_id: str) -> bytes:
        """Слушает WebSocket-поток событий ComfyUI с TCP Watchdog (ping_interval=10)."""
        ws_url = node_url.replace("http://", "ws://").replace("https://", "wss://") + f"/ws?clientId={prompt_id}"

        async with websockets.connect(ws_url, ping_interval=10, ping_timeout=5, max_size=None) as ws:
            async for raw_msg in ws:
                if not isinstance(raw_msg, str):
                    continue

                msg = json.loads(raw_msg)
                msg_type = msg.get("type")
                data = msg.get("data", {})

                if msg_type == "execution_error" and data.get("prompt_id") == prompt_id:
                    exc_msg = str(data.get("exception_message", "")).lower()
                    exc_type = str(data.get("exception_type", "")).lower()
                    if "out of memory" in exc_msg or "cuda" in exc_msg or "oom" in exc_type:
                        raise CudaOOMError(f"CUDA OOM на {node_url}: {exc_msg}")
                    raise ComfyUIExecutionError(f"ComfyUI Execution Error: {exc_msg}")

                if msg_type == "executed" and data.get("prompt_id") == prompt_id:
                    return await self._fetch_output_from_history(node_url, prompt_id)

        # Если сокет закрылся без явного executed
        return await self._fetch_output_from_history(node_url, prompt_id)

    async def _poll_history(self, node_url: str, prompt_id: str) -> bytes:
        """
        Фолбэк опрос эндпоинта /history/{prompt_id} при сетевом сбое сокета.
        Подчиняется родительскому глобальному таймауту asyncio.wait_for.
        """
        url = f"{node_url}/history/{prompt_id}"

        async with httpx.AsyncClient() as client:
            while True:
                try:
                    resp = await client.get(url, timeout=10.0)
                    if resp.status_code == 200:
                        history_data = resp.json()
                        if prompt_id in history_data:
                            task_info = history_data[prompt_id]
                            # Проверяем ошибки
                            status_info = task_info.get("status", {})
                            if status_info.get("status_str") == "error":
                                messages = status_info.get("messages", [])
                                err_text = str(messages).lower()
                                if "out of memory" in err_text or "cuda" in err_text:
                                    raise CudaOOMError(f"CUDA OOM (из /history) на {node_url}: {err_text}")
                                raise ComfyUIExecutionError(f"ComfyUI Execution Error: {err_text}")

                            # Извлекаем outputs
                            outputs = task_info.get("outputs", {})
                            for node_id, node_output in outputs.items():
                                images = node_output.get("images", [])
                                if images:
                                    filename = images[0].get("filename")
                                    subfolder = images[0].get("subfolder", "")
                                    img_type = images[0].get("type", "output")
                                    return await self._fetch_image_bytes(node_url, filename, subfolder, img_type)
                except (CudaOOMError, ComfyUIExecutionError):
                    raise
                except Exception as exc:
                    logger.debug(f"⏳ [Polling] Ожидание завершения {prompt_id} на {node_url}... ({exc})")

                await asyncio.sleep(2.0)

    async def _fetch_output_from_history(self, node_url: str, prompt_id: str) -> bytes:
        """Извлечение имени файла из истории и загрузка готового медиа-ассета."""
        url = f"{node_url}/history/{prompt_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=15.0)
            resp.raise_for_status()
            history = resp.json()

            task_info = history.get(prompt_id, {})
            outputs = task_info.get("outputs", {})
            for node_id, node_output in outputs.items():
                images = node_output.get("images", [])
                if images:
                    filename = images[0].get("filename")
                    subfolder = images[0].get("subfolder", "")
                    img_type = images[0].get("type", "output")
                    return await self._fetch_image_bytes(node_url, filename, subfolder, img_type)

        raise RuntimeError(f"В истории ComfyUI ({prompt_id}) отсутствуют сгенерированные изображения.")

    async def _fetch_image_bytes(
        self,
        node_url: str,
        filename: str,
        subfolder: str = "",
        type_: str = "output"
    ) -> bytes:
        """Скачивание бинарных данных изображения через /view."""
        params = {"filename": filename, "subfolder": subfolder, "type": type_}
        url = f"{node_url}/view"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=60.0)
            resp.raise_for_status()
            return resp.content
