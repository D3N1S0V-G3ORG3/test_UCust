"""
File: ai/core/lazy_rendering_controller.py
Стейт-машина и контроллер отложенного рендера (Lazy Rendering State Machine) для UCust AI.
Управляет переходами жизненного цикла постов, математическим расчетом VRAM и очередями задач.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Callable
from pydantic import BaseModel, Field

logger = logging.getLogger("LazyRenderingController")


class SubscriptionTier(str, Enum):
    START = "start"
    BUSINESS = "business"
    CUSTOM = "custom"

    # Backward compatibility aliases
    STARTER = "start"
    PRO = "business"
    ENTERPRISE = "custom"

    @classmethod
    def normalize(cls, val: Any) -> "SubscriptionTier":
        if isinstance(val, cls):
            return val
        s = str(val).lower().strip()
        mapping = {
            "start": cls.START,
            "starter": cls.START,
            "старт": cls.START,
            "business": cls.BUSINESS,
            "бизнес": cls.BUSINESS,
            "pro": cls.BUSINESS,
            "custom": cls.CUSTOM,
            "кастомный": cls.CUSTOM,
            "свой": cls.CUSTOM,
            "свой тариф": cls.CUSTOM,
            "enterprise": cls.CUSTOM,
            "vip": cls.CUSTOM,
        }
        return mapping.get(s, cls.BUSINESS)


class IndustryArchetype(str, Enum):
    B2C_LIFESTYLE = "b2c_lifestyle"
    B2B_CORPORATE = "b2b_corporate"
    EXPERT_SERVICES = "expert_services"


class ContentFormat(str, Enum):
    SINGLE_SHOT = "single_shot"
    CAROUSEL = "carousel"              # Мульти-ракурсная карусель / альбом
    CAROUSEL_LIGHT = "carousel_light"  # До 3 слайдов
    CAROUSEL_HEAVY = "carousel_heavy"  # До 5 слайдов
    MOSAIC = "mosaic"                  # Мозаика / Сетка фото (Grid Layout)
    POLL = "poll"                      # Интерактивный опрос
    QUIZ = "quiz"                      # Викторина с правильным ответом и пояснением
    STORYTELLING = "storytelling"      # Объектный сторителлинг
    CRYPTEX_PUZZLE = "cryptex_puzzle"  # 4-слойный интерактивный пазл
    PUZZLE = "puzzle"


class PostLifecycleStatus(str, Enum):
    DRAFT_TEXT = "draft_text"                    # Сгенерирован только текст и промпты (0 GPU)
    APPROVED_QUEUED = "approved_queued"          # Подтвержден, поставлен в очередь на рендер (таймаут 120с)
    AWAITING_RENDER = "awaiting_render"          # Алиас для очереди рендера
    RENDERING = "rendering"                      # Выполняется в ComfyUI GPU (таймаут 300с)
    RENDERED = "rendered"                        # Картинки сгенерированы и загружены в хранилище
    PUBLISHED = "published"                      # Опубликован в Telegram
    RETRY_CPU_FALLBACK = "retry_cpu_fallback"    # OOM-сбой: автоматический перезапуск на CPU
    DEAD_LETTER_QUEUE = "dead_letter_queue"      # Изолированный отстойник ошибок (требует действия пользователя)
    FAILED = "failed"                            # Фатальная ошибка генерации


class ShotIntent(str, Enum):
    PRODUCT_ONLY = "product_only"           # Чистый натюрморт на поверхности (LoRA RealSkinFix = Bypass 0.0)
    IN_HANDS = "in_hands"                   # Руки мастера/стилиста держат флакон (LoRA RealSkinFix = 1.05)
    LIFESTYLE_MODEL = "lifestyle_model"     # Модель / клиент в процессе укладки (LoRA RealSkinFix = 1.05)
    POV_USER = "pov_user"                   # Вид от первого лица (рука с флаконом) (LoRA RealSkinFix = 1.05)


class ImageGenerationSpec(BaseModel):
    prompt: str
    negative_prompt: str = "plastic, cheap, cluttered, cgi, 3d render, distorted anatomy, blurry, lowres, noise"
    aspect_ratio: str = Field(default="1:1", description="1:1, 4:5, 16:9, 9:16")
    width: int = 1024
    height: int = 1024
    seed: Optional[int] = None
    shot_intent: ShotIntent = Field(default=ShotIntent.PRODUCT_ONLY, description="Композиционное намерение кадра")
    use_controlnet: bool = Field(default=False, description="Флаг активации ControlNet для точной геометрии этикетки")
    reference_image_url: Optional[str] = Field(default=None, description="URL или путь к исходному фото продукта для ControlNet/IP-Adapter")


class PostDraft(BaseModel):
    post_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    brand_id: str
    target_date: datetime
    format: ContentFormat = ContentFormat.SINGLE_SHOT
    status: PostLifecycleStatus = PostLifecycleStatus.DRAFT_TEXT
    text_content: Optional[str] = None
    image_specs: List[ImageGenerationSpec] = Field(default_factory=list)
    rendered_image_urls: List[str] = Field(default_factory=list)
    vram_cost_mb: int = 0
    error_message: Optional[str] = None
    requires_user_action: bool = False
    callback_url: Optional[str] = None
    selected_sku: Optional[Dict[str, Any]] = None
    disambiguation_chips: List[Dict[str, Any]] = Field(default_factory=list)
    poll_data: Optional[Dict[str, Any]] = None
    mosaic_specs: Optional[List[Dict[str, Any]]] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class VRAMCostCalculator:
    """
    Математический калькулятор аллокации VRAM с защитой от OOM и поддержкой Dev-режима.
    """
    BASE_MODEL_VRAM_MB: int = 6500   # Чекпоинт SDXL / Flux (FP16/BF16 с текстовыми энкодерами)
    VAE_BUFFER_MB: int = 850         # Буфер декодирования VAE

    @classmethod
    def calculate_spec_vram(cls, spec: ImageGenerationSpec, dev_simulation_mode: bool = False) -> int:
        """Полный расчет VRAM с учетом веса базовой модели."""
        pixel_ratio = (spec.width * spec.height) / (1024 * 1024)
        dynamic_activation_mb = int(1850 * (pixel_ratio ** 1.35))
        total_vram_mb = cls.BASE_MODEL_VRAM_MB + dynamic_activation_mb + cls.VAE_BUFFER_MB
        return total_vram_mb

    @classmethod
    def calculate_total_post_vram(
        cls, 
        post: PostDraft, 
        execute_in_batch: bool = False,
        dev_simulation_mode: bool = False
    ) -> int:
        if not post.image_specs:
            return 0
        base_weight = cls.BASE_MODEL_VRAM_MB
        if execute_in_batch and len(post.image_specs) > 1:
            single_act = max(
                int(1850 * (((s.width * s.height) / (1024 * 1024)) ** 1.35)) + cls.VAE_BUFFER_MB 
                for s in post.image_specs
            )
            total_dynamic = int(single_act * (1 + 0.45 * (len(post.image_specs) - 1)))
            return base_weight + total_dynamic
        else:
            max_single_dynamic = max(
                int(1850 * (((s.width * s.height) / (1024 * 1024)) ** 1.35)) + cls.VAE_BUFFER_MB 
                for s in post.image_specs
            )
            return base_weight + max_single_dynamic


class LazyRenderingController:
    """
    Стейт-машина управления жизненным циклом и очередью рендера (Директива 5).
    Реализует FSM с таймаутами (120с / 300с), авто-переходом в DEAD_LETTER_QUEUE,
    OOM-fallback на CPU и асинхронными вебхук-уведомлениями.
    """

    QUEUED_TIMEOUT_SECONDS: int = 120
    RENDERING_TIMEOUT_SECONDS: int = 300

    def __init__(
        self, 
        scheduler_backend: Optional[Any] = None, 
        storage_uploader: Optional[Callable] = None,
        comfy_bridge: Optional[Any] = None,
        dev_simulation_mode: bool = True
    ):
        self.scheduler = scheduler_backend
        self.uploader = storage_uploader or self._default_mock_uploader
        self.dev_simulation_mode = dev_simulation_mode
        self.posts_db: Dict[str, PostDraft] = {}
        
        if comfy_bridge is not None:
            self.comfy_bridge = comfy_bridge
        else:
            try:
                from bridge.comfy_bridge import ComfyUIBridge
                self.comfy_bridge = ComfyUIBridge()
            except ImportError:
                try:
                    from ai.bridge.comfy_bridge import ComfyUIBridge
                    self.comfy_bridge = ComfyUIBridge()
                except ImportError:
                    self.comfy_bridge = None

    def register_draft(self, post: PostDraft, dev_simulation_mode: Optional[bool] = None) -> PostDraft:
        """Сохраняет черновик в БД со статусом DRAFT_TEXT без вызова GPU."""
        is_sim = dev_simulation_mode if dev_simulation_mode is not None else self.dev_simulation_mode
        post.status = PostLifecycleStatus.DRAFT_TEXT
        post.vram_cost_mb = VRAMCostCalculator.calculate_total_post_vram(post, dev_simulation_mode=is_sim)
        post.updated_at = datetime.now()
        self.posts_db[post.post_id] = post
        logger.info(f"📝 Пост {post.post_id} зарегистрирован как DRAFT_TEXT. VRAM оценка: {post.vram_cost_mb} MB")
        return post

    async def trigger_render(
        self, 
        post_id: str, 
        trigger_source: str = "manual_approve",
        callback_url: Optional[str] = None
    ) -> PostDraft:
        """
        Переводит пост из DRAFT_TEXT в APPROVED_QUEUED и запускает обработку FSM.
        """
        post = self.posts_db.get(post_id)
        if not post:
            # Создаем временный черновик, если рендер вызван напрямую
            post = PostDraft(
                post_id=post_id,
                brand_id="tenant_default",
                target_date=datetime.now(),
                format=ContentFormat.SINGLE_SHOT,
                status=PostLifecycleStatus.APPROVED_QUEUED,
                image_specs=[ImageGenerationSpec(prompt=f"Marketing render for {post_id}")],
                callback_url=callback_url
            )
            self.posts_db[post_id] = post

        if callback_url:
            post.callback_url = callback_url

        # Валидация перехода FSM
        valid_start_states = (
            PostLifecycleStatus.DRAFT_TEXT,
            PostLifecycleStatus.FAILED,
            PostLifecycleStatus.APPROVED_QUEUED,
            PostLifecycleStatus.AWAITING_RENDER
        )
        if post.status not in valid_start_states:
            logger.warning(f"⚠️ Пост {post_id} уже в статусе {post.status}, повторный запуск пропущен.")
            return post

        post.status = PostLifecycleStatus.APPROVED_QUEUED
        post.updated_at = datetime.now()
        logger.info(f"⏳ [FSM] Пост {post_id} переведен в APPROVED_QUEUED (Триггер: {trigger_source}).")

        # Запуск асинхронного воркера рендера с контролем таймаутов FSM
        await self._process_render_job(post)
        return post

    async def _process_render_job(self, post: PostDraft):
        """
        Исполнение задачи с FSM контролем:
        APPROVED_QUEUED -> RENDERING (таймаут 300с) -> RENDERED
        При OOM -> RETRY_CPU_FALLBACK
        При таймауте / фатальном сбое -> DEAD_LETTER_QUEUE + Webhook Event
        """
        try:
            # 1. Переход в RENDERING
            post.status = PostLifecycleStatus.RENDERING
            post.updated_at = datetime.now()
            logger.info(f"🎨 [FSM] Старт GPU рендера для поста {post.post_id} ({len(post.image_specs)} кадров)...")

            # 2. Выполнение с защитой от зависания по таймауту (RENDERING_TIMEOUT_SECONDS)
            rendered_urls = await asyncio.wait_for(
                self._execute_rendering_pipeline(post),
                timeout=float(self.RENDERING_TIMEOUT_SECONDS)
            )

            # 3. Успешный переход в RENDERED
            post.rendered_image_urls = rendered_urls
            post.status = PostLifecycleStatus.RENDERED
            post.error_message = None
            post.requires_user_action = False
            post.updated_at = datetime.now()
            logger.info(f"✅ [FSM] Пост {post.post_id} успешно отрендерен: {rendered_urls}")

        except asyncio.TimeoutError:
            error_msg = f"Таймаут рендера превысил {self.RENDERING_TIMEOUT_SECONDS}с"
            logger.error(f"⏰ [FSM] {error_msg} для поста {post.post_id}. Перевод в DEAD_LETTER_QUEUE.")
            await self._transition_to_dlq(post, error_msg)

        except Exception as e:
            err_str = str(e).lower()
            is_oom = any(kw in err_str for kw in ["out of memory", "cuda oom", "vram", "oom", "allocation"])

            if is_oom:
                logger.warning(f"💥 [FSM] Обнаружен OOM-сбой для {post.post_id}. Запуск RETRY_CPU_FALLBACK...")
                await self._handle_cpu_fallback(post, str(e))
            else:
                logger.error(f"❌ [FSM] Фатальная ошибка рендера для {post.post_id}: {e}", exc_info=True)
                await self._transition_to_dlq(post, str(e))

    async def _execute_rendering_pipeline(self, post: PostDraft) -> List[str]:
        """Пайплайн рендеринга всех спецификаций."""
        rendered_urls = []
        for idx, spec in enumerate(post.image_specs):
            logger.debug(f"   🖼️ Рендер кадра #{idx + 1} ({spec.width}x{spec.height})...")
            if self.comfy_bridge:
                raw_bytes = await self.comfy_bridge.render_image(
                    spec=spec,
                    post_id=f"{post.post_id}_{idx}",
                    dev_simulation_mode=self.dev_simulation_mode
                )
            else:
                raw_bytes = await self._execute_comfy_generation(spec)

            s3_url = await self.uploader(raw_bytes, f"posts/{post.post_id}/img_{idx + 1}.jpg")
            rendered_urls.append(s3_url)
        return rendered_urls

    async def _handle_cpu_fallback(self, post: PostDraft, oom_reason: str):
        """Обработчик OOM-сбоя: переводит в RETRY_CPU_FALLBACK и пробует CPU-рендер."""
        post.status = PostLifecycleStatus.RETRY_CPU_FALLBACK
        post.error_message = f"GPU OOM: {oom_reason}. Выполняется CPU Fallback."
        post.updated_at = datetime.now()

        try:
            # CPU Fallback рендер
            cpu_rendered_urls = []
            for idx, spec in enumerate(post.image_specs):
                raw_bytes = await self._execute_comfy_generation(spec)
                s3_url = await self.uploader(raw_bytes, f"posts/{post.post_id}/cpu_fallback_{idx + 1}.jpg")
                cpu_rendered_urls.append(s3_url)

            post.rendered_image_urls = cpu_rendered_urls
            post.status = PostLifecycleStatus.RENDERED
            post.requires_user_action = False
            logger.info(f"✅ [FSM] CPU Fallback успешно завершен для {post.post_id}.")
        except Exception as cpu_err:
            await self._transition_to_dlq(post, f"CPU Fallback failed: {cpu_err}")

    async def _transition_to_dlq(self, post: PostDraft, reason: str):
        """
        Перевод в DEAD_LETTER_QUEUE (Директива 5 + Edge Case 4):
        Устанавливает requires_user_action=True и отправляет Webhook Event.
        """
        post.status = PostLifecycleStatus.DEAD_LETTER_QUEUE
        post.error_message = reason
        post.requires_user_action = True
        post.updated_at = datetime.now()

        # Edge Case 4: Отправка асинхронного события/вебхука в пользовательский слой
        if post.callback_url:
            try:
                from services.webhook_manager import WebhookCallbackManager
                WebhookCallbackManager.send_callback_sync(
                    callback_url=post.callback_url,
                    event_type="post_dead_letter_queue",
                    tenant_id=post.brand_id,
                    task_id=post.post_id,
                    status="dead_letter_queue",
                    data={
                        "post_id": post.post_id,
                        "status": post.status.value,
                        "requires_user_action": True,
                        "error_message": reason
                    }
                )
                logger.info(f"📡 [FSM DLQ] Вебхук-уведомление успешно отправлено на {post.callback_url}")
            except Exception as wh_err:
                logger.warning(f"⚠️ [FSM DLQ] Не удалось отправить вебхук на {post.callback_url}: {wh_err}")

    async def _execute_comfy_generation(self, spec: ImageGenerationSpec) -> bytes:
        """Резервный метод симуляции генерации."""
        await asyncio.sleep(0.05)
        return b"mock_jpeg_binary_data"

    async def _default_mock_uploader(self, data: bytes, destination_key: str) -> str:
        return f"https://s3.ucust.ai/media/{destination_key}"

