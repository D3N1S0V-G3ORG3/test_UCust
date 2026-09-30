"""
File: ai/core/llm_provider.py
Потокобезопасный Singleton-провайдер инференса для llama-cpp-python (Saiga / Llama-3).
Поддерживает автоматическую адаптацию под Dev/Production окружение и безопасный fallback.
"""

from __future__ import annotations

import os
import asyncio
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional

logger = logging.getLogger("LLMProvider")


class SaigaLLMSkill:
    """
    Потокобезопасный Singleton для инференса локальной LLM Сайга (Llama-3 / NeMo).
    Веса загружаются в память строго один раз.
    Использует строгую сериализацию инференса (asyncio.Lock + single ThreadPoolExecutor),
    предотвращая OpenMP Thread Thrashing и L3 Cache Eviction при исполнении на CPU.
    """
    _instance: Optional[SaigaLLMSkill] = None
    _lock = threading.Lock()
    _llm: Any = None
    _is_mock: bool = False
    _single_thread_pool: Optional[ThreadPoolExecutor] = None
    _async_lock: Optional[asyncio.Lock] = None

    def __new__(
        cls, 
        model_path: str = "/opt/ucust/models/saiga_llama3_8b.Q4_K_M.gguf", 
        dev_mode: bool = False
    ) -> SaigaLLMSkill:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SaigaLLMSkill, cls).__new__(cls)
                cls._instance._initialize_model(model_path, dev_mode)
            return cls._instance

    def _initialize_model(self, model_path: str, dev_mode: bool):
        logger.info(f"🧠 Инициализация LLM провайдера. Путь: {model_path}, dev_mode: {dev_mode}")
        self._single_thread_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="saiga_cpu_worker")
        self._async_lock = None
        
        # Поиск возможных путей к модели
        candidates = [
            model_path,
            os.path.abspath(model_path),
            os.path.join(os.path.dirname(__file__), "..", "..", "models", "saiga_llama3_8b.Q4_K_M.gguf"),
            os.path.join("/opt/ucust/models", "saiga_llama3_8b.Q4_K_M.gguf")
        ]
        
        resolved_path = None
        for p in candidates:
            if os.path.exists(p):
                resolved_path = p
                break

        if resolved_path:
            try:
                from llama_cpp import Llama
                gpu_layers = 0 if dev_mode else int(os.getenv("LLAMA_GPU_LAYERS", "-1"))
                logger.info(f"🚀 Загрузка весов Saiga GGUF из {resolved_path} (n_gpu_layers={gpu_layers})...")
                self._llm = Llama(
                    model_path=resolved_path,
                    n_gpu_layers=gpu_layers,
                    n_ctx=4096,
                    verbose=False
                )
                self._is_mock = False
                logger.info("✅ Saiga LLM успешно загружена в память.")
                return
            except Exception as e:
                logger.warning(f"⚠️ Ошибка загрузки llama-cpp-python ({e}). Включение Mock/Rule fallback.")
        else:
            logger.info(f"ℹ️ Файл модели не найден по путям {candidates}. Включение детерминированного эмулятора.")

        self._llm = None
        self._is_mock = True

    async def generate_chat_async(self, messages: List[Dict[str, str]], max_tokens: int = 600) -> str:
        """
        Асинхронная сериализованная генерация ответа.
        Гарантирует 1 конкурентный инференс на CPU, позволяя C++/BLAS ядру
        задействовать 100% потоков без переключения контекста и деградации L3 кэша.
        """
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()

        if self._single_thread_pool is None:
            self._single_thread_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="saiga_cpu_worker")

        async with self._async_lock:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                self._single_thread_pool,
                self.generate_chat,
                messages,
                max_tokens
            )

    def generate_chat(self, messages: List[Dict[str, str]], max_tokens: int = 600) -> str:
        """
        Синхронная генерация ответа через ChatML / Llama-3 формат.
        При отсутствии весов на Dev-стенде возвращает детерминированный структурированный результат.
        """
        if self._llm is not None and not self._is_mock:
            try:
                response = self._llm.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=0.7,
                    top_p=0.9,
                    repeat_penalty=1.15
                )
                return response["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.error(f"❌ Ошибка инференса Saiga LLM: {e}")

        # Детерминированный Fallback генератор для тестов / сред без GGUF весов
        return self._generate_fallback(messages)

    def _generate_fallback(self, messages: List[Dict[str, str]]) -> str:
        user_msg = next((m["content"] for m in messages if m["role"] == "user"), "")
        sys_msg = next((m["content"] for m in messages if m["role"] == "system"), "")

        # Извлекаем ToV и факты
        tov_line = "Стандарты надежности и качества"
        for line in sys_msg.split("\n"):
            if "Tone of Voice" in line:
                tov_line = line.replace("2. Tone of Voice на сегодня:", "").strip()

        # Базовый Telegram каркас: Хук -> Цитата -> Оффер/CTA
        hook = "📌 Профессиональный разбор процессов и стандарты качества"
        body = f"Каждая деталь в цепочке определяет итоговую надежность результата.\n> {tov_line}\n"
        
        if "ОБЯЗАТЕЛЬНО включи" in user_msg:
            extracted_items = user_msg.split("ОБЯЗАТЕЛЬНО включи в текст следующие коммерческие позиции и цены из меню/прайса:")[-1].strip()
            body += f"> Актуальные позиции: {extracted_items}\n"

        cta = "📩 Ознакомьтесь с подробными условиями по ссылке в описании профиля или запросите консультацию в директ."
        return f"{hook}\n\n{body}\n{cta}"
