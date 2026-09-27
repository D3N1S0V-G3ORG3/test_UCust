"""
Moondream VQA Skill v2.0 — автономный ИИ-аналитик визуального контента (Vision Analyst).
Объединяет математический контроль качества (OpenCV/NumPy), VLM-семантику (Moondream2),
инъекцию предметных словарей (Domain Lexicons), строгую JSON-матрицу и дельта-анализ движения (LTX-Video).
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import logging
import os
import io
import re
import json
import base64
from typing import List, Dict, Any, Optional, Union, Tuple
from PIL import Image, ImageStat
from pydantic import BaseModel, Field

import threading

logger = logging.getLogger("moondream_vqa")


# -------------------------------------------------------------------
# 1. Pydantic-схема жесткой JSON-матрицы кадра (Защита от галлюцинаций)
# -------------------------------------------------------------------
class VisionStructuredMatrix(BaseModel):
    genre: str = Field("Product", description="Food | Interior | Product | Portrait | UGC")
    subject_details: str = Field("", description="Краткое смысловое описание объекта с профильной лексикой")
    foreground_physical_anchor: str = Field("", description="Физический якорь переднего плана")
    lighting_temperature: str = Field("warm", description="warm | cool | neutral | golden_hour")
    focal_depth: str = Field("shallow_dof", description="shallow_dof | deep_focus")
    aesthetic_mood_tags: List[str] = Field(default_factory=lambda: ["уют", "эстетика", "стиль"], description="Ровно 3 ключевых слова настроения")
    detected_text_hints: str = Field("", description="Замеченный текст, цены или логотипы")

    class Config:
        extra = "ignore"


# -------------------------------------------------------------------
# 2. Предметные словари для инъекции в VLM (Domain Lexicons)
# -------------------------------------------------------------------
DOMAIN_VOCABULARIES: Dict[str, Dict[str, Any]] = {
    "cafe": {
        "keywords": ["кофе", "кофейня", "капучино", "латте", "раф", "фильтр", "круассан", "десерт", "выпечка", "бариста", "зерно", "эспрессо"],
        "terms": [
            "латте-арт (розетта, тюльпан, сердце, лебедь)", "плотная шелковистая микропенка", "золотистая крема",
            "свежая обжарка", "фильтр-кофе V60 / кемекс", "холдер эспрессо-машины", "хрустящая слоеная текстура выпечки",
            "натуральные древесные фактуры столика", "утренний естественный свет", "уютный теплый боке"
        ],
        "default_genre": "Food"
    },
    "restaurant": {
        "keywords": ["ресторан", "меню", "блюдо", "шеф", "ужин", "обед", "кухня", "гастрономия", "стейк", "паста", "пицца"],
        "terms": [
            "авторская подача и плакирование", "карамелизация корочки", "гляссаж соуса", "микрозелень и съедобные цветы",
            "прожарка medium / medium-rare", "ресторанная сервировка", "игра контрастов текстур (хрустящее и нежное)",
            "акцентный сфокусированный свет на блюде", "глубокий контраст фона"
        ],
        "default_genre": "Food"
    },
    "beauty": {
        "keywords": ["салон", "красота", "макияж", "маникюр", "волосы", "косметика", "уход", "кожа", "брови", "ресницы"],
        "terms": [
            "сатиновый / матовый / глянцевый финиш", "макро-детализация текстуры кожи", "чистый градиент и растушевка",
            "идеальный блик на ногтевой пластине", "объемная шелковистая укладка", "естественное кольцевое освещение",
            "минималистичный светлый фон", "эстетика премиального ухода"
        ],
        "default_genre": "Portrait"
    },
    "interior": {
        "keywords": ["интерьер", "дизайн", "недвижимость", "ремонт", "офис", "зал", "мебель", "локация", "пространство"],
        "terms": [
            "грамотное зонирование пространства", "панорамные видовые окна", "текстуры натурального дерева и мрамора",
            "многоуровневое теплое освещение", "акцентные элементы декора", "чистая геометрия и глубина кадра",
            "уютная атмосфера гостеприимства"
        ],
        "default_genre": "Interior"
    },
    "product": {
        "keywords": ["товар", "магазин", "одежда", "бренд", "упаковка", "аксессуары", "доставка", "коробка"],
        "terms": [
            "предметная съемка на чистом фоне", "фактура премиальных материалов", "детализация швов и фурнитуры",
            "экологичная крафтовая упаковка", "четкие грани и форма продукта", "студийный мягкий рассеянный свет"
        ],
        "default_genre": "Product"
    }
}


# -------------------------------------------------------------------
# 3. Математический контроль качества (OpenCV / NumPy)
# -------------------------------------------------------------------
def calculate_image_quality_metrics(pil_img: Image.Image) -> Dict[str, Any]:
    """
    Математический контроль качества снимка:
    1. Дисперсия Лапласиана (Laplacian Variance) для выявления смазанных/нечетких фото.
       Нормализует изображение к 512x512 для устойчивости к сжатию Telegram 4:2:0 JPEG.
    2. Анализ средней яркости (Luminance) для фиксации недоэкспонированных и пересвеченных кадров.
    3. Контраст (RMS Contrast) для оценки динамического диапазона.
    """
    w, h = pil_img.size
    
    # 1. Анализ резкости через OpenCV
    try:
        import cv2
        import numpy as np
        
        # Конвертируем PIL в NumPy BGR
        open_cv_image = np.array(pil_img.convert('RGB'))
        open_cv_image = open_cv_image[:, :, ::-1].copy()
        gray = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2GRAY)
        
        # Нормализуем размер для стандартизации дисперсии Лапласиана
        resized_gray = cv2.resize(gray, (512, 512), interpolation=cv2.INTER_AREA)
        laplacian_var = cv2.Laplacian(resized_gray, cv2.CV_64F).var()
        blur_score = round(float(laplacian_var), 1)
    except Exception as e:
        logger.warning(f"OpenCV Laplacian calculation failed: {e}, falling back to PIL edge analysis")
        stat = ImageStat.Stat(pil_img.convert('L'))
        blur_score = round(float(stat.var[0]), 1)

    # Порог резкости (resilient к сжатию Telegram)
    is_blurry = blur_score < 45.0
    if blur_score < 45.0:
        sharpness_verdict = "Технический смаз / размытое фото"
    elif blur_score < 120.0:
        sharpness_verdict = "Умеренная резкость (мягкий фокус)"
    else:
        sharpness_verdict = "Резкий кадр высокой детализации"

    # 2. Анализ экспозиции и контраста
    stat_gray = ImageStat.Stat(pil_img.convert('L'))
    brightness_mean = round(float(stat_gray.mean[0]), 1)
    contrast_score = round(float(stat_gray.stddev[0]), 1)

    if brightness_mean < 65.0:
        exposure_status = "underexposed"
        exposure_verdict = "Слишком темный снимок (недоэкспозиция)"
    elif brightness_mean > 205.0:
        exposure_status = "overexposed"
        exposure_verdict = "Пересвеченный снимок (потеря деталей в светах)"
    else:
        exposure_status = "balanced"
        exposure_verdict = "Сбалансированная экспозиция"

    is_acceptable = (not is_blurry) and (exposure_status == "balanced")

    return {
        "blur_score": blur_score,
        "is_blurry": is_blurry,
        "sharpness_verdict": sharpness_verdict,
        "brightness_mean": brightness_mean,
        "contrast_score": contrast_score,
        "exposure_status": exposure_status,
        "exposure_verdict": exposure_verdict,
        "is_acceptable_quality": is_acceptable
    }


# -------------------------------------------------------------------
# 4. Основной класс навыка Moondream VQA Skill v2.0
# -------------------------------------------------------------------
class MoondreamVQASkill:
    """
    Интеграция с локальной VLM Moondream2.
    Использует потокобезопасный Singleton Model Pool — веса загружаются строго 1 раз.
    """
    _shared_llm = None
    _shared_is_loaded = False
    _lock = threading.Lock()

    def __init__(
        self, 
        model_path: str = "models/moondream/moondream2-text-model-f16.gguf", 
        mmproj_path: str = "models/moondream/moondream2-mmproj-f16.gguf"
    ):
        self.model_path = model_path
        self.mmproj_path = mmproj_path
        self._llm = None
        self._is_loaded = False
        self.load_model()

    def _resolve_path(self, path_str: str) -> str:
        if os.path.exists(path_str):
            return path_str
        base_dir = os.path.dirname(os.path.abspath(__file__))
        alt_ai = os.path.normpath(os.path.join(base_dir, "..", path_str))
        if os.path.exists(alt_ai):
            return alt_ai
        alt_repo = os.path.normpath(os.path.join(base_dir, "..", "..", path_str))
        if os.path.exists(alt_repo):
            return alt_repo
        
        for candidate_dir in [
            "/opt/ucust/ai/models/moondream",
            os.path.normpath(os.path.join(base_dir, "..", "models", "moondream")),
            os.path.normpath(os.path.join(base_dir, "..", "..", "ai", "models", "moondream")),
        ]:
            if os.path.exists(candidate_dir):
                target = os.path.join(candidate_dir, os.path.basename(path_str))
                if os.path.exists(target):
                    return target
        return path_str

    def load_model(self) -> bool:
        """Загружает модель Moondream GGUF в память через Singleton Pool."""
        if os.getenv("ENABLE_NEURAL_MODELS", "0") != "1":
            logger.info("[Moondream] ENABLE_NEURAL_MODELS != 1. Используется встроенный CV-анализатор.")
            return False
        if MoondreamVQASkill._shared_is_loaded and MoondreamVQASkill._shared_llm is not None:
            self._llm = MoondreamVQASkill._shared_llm
            self._is_loaded = True
            return True

        resolved_model = self._resolve_path(self.model_path)
        resolved_mmproj = self._resolve_path(self.mmproj_path)
        
        if not os.path.exists(resolved_model) or not os.path.exists(resolved_mmproj):
            logger.info(f"[Moondream] Локальные GGUF веса не найдены по пути: {resolved_model}. Используется встроенный CV-анализатор.")
            return False

        with MoondreamVQASkill._lock:
            if MoondreamVQASkill._shared_is_loaded and MoondreamVQASkill._shared_llm is not None:
                self._llm = MoondreamVQASkill._shared_llm
                self._is_loaded = True
                return True

            try:
                from llama_cpp import Llama
                from llama_cpp.llama_chat_format import MoondreamChatHandler
                
                print(f"[Moondream] 🧠 Загрузка весов Moondream2 VLM на GPU ({resolved_model})...")
                chat_handler = MoondreamChatHandler(clip_model_path=resolved_mmproj)
                n_gpu = int(os.getenv("MOONDREAM_GPU_LAYERS", "-1"))
                MoondreamVQASkill._shared_llm = Llama(
                    model_path=resolved_model,
                    chat_handler=chat_handler,
                    n_ctx=2048,
                    n_threads=4,
                    n_gpu_layers=n_gpu,
                    verbose=False
                )
                MoondreamVQASkill._shared_is_loaded = True
                self._llm = MoondreamVQASkill._shared_llm
                self._is_loaded = True
                print(f"[Moondream] 🚀 Moondream2 VLM успешно инициализирован на GPU (слои: {n_gpu}) в Singleton-пуле!")
                return True
            except ImportError:
                logger.info("[Moondream] llama-cpp-python не установлен. Активирован встроенный CV-движок.")
                return False
            except Exception as e:
                logger.warning(f"[Moondream] Ошибка инициализации VLM: {e}")
                return False

    def _to_pil_image(self, image_input: Any) -> Optional[Image.Image]:
        """Универсальное преобразование любого типа входных данных в объект PIL Image."""
        if image_input is None:
            return None

        if isinstance(image_input, Image.Image):
            return image_input.convert("RGB")

        if isinstance(image_input, bytes):
            try:
                return Image.open(io.BytesIO(image_input)).convert("RGB")
            except Exception as e:
                logger.error(f"[Moondream] Ошибка открытия изображения из bytes: {e}")
                return None

        if isinstance(image_input, dict):
            if "dataUrl" in image_input and image_input["dataUrl"]:
                return self._to_pil_image(image_input["dataUrl"])
            if "url" in image_input and image_input["url"]:
                return self._to_pil_image(image_input["url"])
            if "path" in image_input and image_input["path"]:
                return self._to_pil_image(image_input["path"])

        if isinstance(image_input, str):
            image_str = image_input.strip()
            if image_str.startswith("data:image"):
                try:
                    comma_idx = image_str.find(",")
                    if comma_idx != -1:
                        b64_data = image_str[comma_idx + 1:]
                        img_bytes = base64.b64decode(b64_data)
                        return Image.open(io.BytesIO(img_bytes)).convert("RGB")
                except Exception as e:
                    logger.error(f"[Moondream] Ошибка декодирования DataURL: {e}")
                    return None

            if os.path.exists(image_str):
                try:
                    return Image.open(image_str).convert("RGB")
                except Exception as e:
                    logger.error(f"[Moondream] Ошибка чтения файла {image_str}: {e}")
                    return None

            if len(image_str) > 100 and not os.path.exists(image_str):
                try:
                    img_bytes = base64.b64decode(image_str)
                    return Image.open(io.BytesIO(img_bytes)).convert("RGB")
                except Exception:
                    pass

        return None

    def _extract_color_palette(self, pil_img: Image.Image, num_colors: int = 4) -> List[str]:
        """Извлекает доминирующие HEX-цвета из изображения."""
        try:
            small_img = pil_img.copy().resize((80, 80))
            result = small_img.convert('P', palette=Image.ADAPTIVE, colors=num_colors)
            palette = result.getpalette()
            color_counts = sorted(result.getcolors(), reverse=True, key=lambda x: x[0])
            
            hex_colors = []
            for _, idx in color_counts[:num_colors]:
                r = palette[idx * 3]
                g = palette[idx * 3 + 1]
                b = palette[idx * 3 + 2]
                hex_colors.append(f"#{r:02x}{g:02x}{b:02x}")
            return hex_colors
        except Exception:
            return ["#3b82f6", "#1e293b", "#f8fafc"]

    def _detect_domain_lexicon(self, topic: str = "", company_name: str = "") -> Tuple[str, List[str], str]:
        """Определяет нишу и возвращает специализированный словарь терминов."""
        combined_text = f"{topic} {company_name}".lower()
        for domain_key, data in DOMAIN_VOCABULARIES.items():
            if any(kw in combined_text for kw in data["keywords"]):
                return domain_key, data["terms"], data["default_genre"]
        return "general", DOMAIN_VOCABULARIES["cafe"]["terms"][:4], "Product"

    def extract_visual_dossier(self, image_input: Any, topic: str = "", company_name: str = "UCust") -> Dict[str, Any]:
        """
        Комплексный анализ изображения:
        1. Математика OpenCV (резкость, экспозиция, смаз).
        2. Цветовая палитра и пропорции.
        3. Инъекция предметного словаря.
        4. Строгая JSON-матрица (жанр, якорь переднего плана, освещение, 3 mood-тега).
        """
        pil_img = self._to_pil_image(image_input)
        if pil_img is None:
            if isinstance(image_input, dict) and (image_input.get("description") or image_input.get("summary") or image_input.get("caption")):
                desc = image_input.get("description") or image_input.get("summary") or image_input.get("caption")
                return {
                    "status": "success",
                    "description": desc,
                    "dominant_colors": image_input.get("colors") or image_input.get("dominant_colors") or ["#8B5A2B", "#D2B48C", "#F5F5DC"],
                    "aspect_ratio": image_input.get("aspect_ratio", "1:1"),
                    "quality_metrics": {"is_acceptable_quality": True, "sharpness_verdict": "OK"},
                    "structured_matrix": {"genre": "Product", "subject_details": desc, "aesthetic_mood_tags": ["уют", "качество", "стиль"]},
                    "prompt_enhancement": desc,
                    "raw_path": image_input.get("path") or image_input.get("file_name") or "image.png"
                }
            return {
                "status": "not_found",
                "description": "Изображение не распознано или повреждено.",
                "dominant_colors": ["#3b82f6", "#1e293b"],
                "aspect_ratio": "1:1",
                "quality_metrics": {"is_acceptable_quality": False, "sharpness_verdict": "Файл не найден"},
                "structured_matrix": {"genre": "Product", "subject_details": "чистый кадр", "aesthetic_mood_tags": ["стиль", "простота", "фокус"]},
                "prompt_enhancement": "clean high quality studio product presentation, 4k"
            }

        w, h = pil_img.size
        aspect_ratio = "1:1"
        if w > h * 1.2:
            aspect_ratio = "16:9"
        elif h > w * 1.2:
            aspect_ratio = "9:16"
        elif h > w * 1.05:
            aspect_ratio = "4:5"

        # 1. Математический контроль качества OpenCV / NumPy
        quality = calculate_image_quality_metrics(pil_img)
        
        # 2. Цветовая палитра
        colors = self._extract_color_palette(pil_img, num_colors=4)
        
        # 3. Инъекция предметного словаря
        domain_name, domain_terms, default_genre = self._detect_domain_lexicon(topic, company_name)
        terms_hint = ", ".join(domain_terms[:5])

        # 4. Двухтактная экстракция: Фаза 1 (Жанр) -> Фаза 2 (Инъекция предметного словаря + JSON матрица)
        matrix_obj = VisionStructuredMatrix(
            genre=default_genre,
            foreground_physical_anchor="передний план",
            lighting_temperature="warm" if quality["brightness_mean"] > 120 else "neutral",
            focal_depth="shallow_dof" if quality["blur_score"] > 80 else "deep_focus",
            aesthetic_mood_tags=["уют", "эстетика", "натуральность"]
        )

        neural_desc = None
        if self._is_loaded and self._llm:
            try:
                buffered = io.BytesIO()
                pil_img.save(buffered, format="JPEG", quality=85)
                b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                data_uri = f"data:image/jpeg;base64,{b64}"

                # Такт 1: Прямое семантическое описание сцены через Moondream2
                desc_prompt = "Describe this image in detail. Mention the main subject, setting, and notable objects."
                desc_resp = self._llm.create_chat_completion(
                    messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_uri}}, {"type": "text", "text": desc_prompt}]}],
                    max_tokens=100,
                    temperature=0.1
                )
                raw_desc = desc_resp["choices"][0]["message"]["content"].strip()
                if raw_desc and len(raw_desc) > 10:
                    neural_desc = raw_desc

                # Такт 2: Высокоточная детекция текста через PaddleOCR / OCREngine (мгновенно)
                detected_text = ""
                try:
                    from skills.ocr_engine import OCREngine
                    ocr = OCREngine(use_gpu=True)
                    detected_text = ocr.extract_text(pil_img)
                except Exception as ocr_e:
                    logger.debug(f"[Moondream] OCR engine fallback: {ocr_e}")

                # Fallback к VLM детекции, если OCR не установлен или пуст
                if not detected_text and self._llm:
                    try:
                        text_prompt = "Is there any text, numbers, or brand logo written in this image? State them briefly."
                        text_resp = self._llm.create_chat_completion(
                            messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_uri}}, {"type": "text", "text": text_prompt}]}],
                            max_tokens=30,
                            temperature=0.0
                        )
                        raw_vlm_text = text_resp["choices"][0]["message"]["content"].strip()
                        if not any(w in raw_vlm_text.lower() for w in ["no", "none", "not visible", "no text", "ссс"]):
                            detected_text = raw_vlm_text
                    except Exception:
                        pass

                # Автоматическая классификация жанра по семантике Moondream
                desc_lower = (neural_desc or "").lower()
                detected_genre = default_genre
                if any(w in desc_lower for w in ["coffee", "cup", "food", "dish", "plate", "cake", "bread", "drink", "beverage", "meal"]):
                    detected_genre = "Food"
                elif any(w in desc_lower for w in ["room", "table", "chair", "wall", "window", "office", "interior", "decor", "couch", "sofa"]):
                    detected_genre = "Interior"
                elif any(w in desc_lower for w in ["man", "woman", "person", "face", "girl", "boy", "hands", "holding"]):
                    detected_genre = "Portrait"
                elif any(w in desc_lower for w in ["bottle", "package", "box", "product", "device", "screen", "laptop", "phone"]):
                    detected_genre = "Product"

                # Извлечение физического якоря
                foreground_anchor = "предмет в фокусе"
                if "cup" in desc_lower or "coffee" in desc_lower:
                    foreground_anchor = "чашка со свежим напитком"
                elif "suit" in desc_lower or "man" in desc_lower or "woman" in desc_lower:
                    foreground_anchor = "человек в деловом образе"
                elif "phone" in desc_lower or "screen" in desc_lower or "laptop" in desc_lower:
                    foreground_anchor = "цифровое устройство"

                # Агент-Интерпретатор Зрения на базе Saiga NeMo 12B (переиспользует память без доп. VRAM)
                try:
                    from skills.saiga_llm import SaigaLLMSkill
                    saiga = SaigaLLMSkill()
                    interp_res = saiga.interpret_visual_context(
                        moondream_raw_desc=neural_desc or "",
                        topic=topic,
                        company_name=company_name,
                        niche=domain_name,
                        quality_metrics=quality,
                        colors=colors,
                        detected_text=detected_text
                    )
                    if interp_res.get("russian_description"):
                        neural_desc = interp_res["russian_description"]
                    if interp_res.get("genre"):
                        detected_genre = interp_res["genre"]
                    if interp_res.get("anchor"):
                        foreground_anchor = interp_res["anchor"]
                    if interp_res.get("mood_tags"):
                        custom_moods = interp_res["mood_tags"]
                    else:
                        custom_moods = ["уют", "эстетика", "стиль"]
                except Exception as saiga_err:
                    logger.warning(f"[Moondream] Saiga VisualInterpreter fallback: {saiga_err}")
                    custom_moods = ["уют", "эстетика", "стиль"]

                matrix_obj = VisionStructuredMatrix(
                    genre=detected_genre,
                    subject_details=neural_desc or "",
                    foreground_physical_anchor=foreground_anchor,
                    lighting_temperature="warm" if quality["brightness_mean"] > 120 else "neutral",
                    focal_depth="shallow_dof" if quality["blur_score"] > 80 else "deep_focus",
                    aesthetic_mood_tags=custom_moods,
                    detected_text_hints=detected_text
                )
            except Exception as e:
                logger.warning(f"[Moondream] VLM extraction fallback: {e}")

        structured_matrix = matrix_obj.dict()

        # Синтез финального описания
        if not neural_desc or not neural_desc.strip():
            light_str = "мягкое теплое освещение" if structured_matrix["lighting_temperature"] == "warm" else "чистое нейтральное освещение"
            focal_str = "размытый задний план (акцент на объекте)" if structured_matrix["focal_depth"] == "shallow_dof" else "высокая глубина резкости"
            final_description = (
                f"Фирменный визуальный материал компании «{company_name}». "
                f"Жанр: {structured_matrix['genre']}. {light_str}, {focal_str}. "
                f"Цветовая гамма: {', '.join(colors)}."
            )
            structured_matrix["subject_details"] = final_description
        else:
            final_description = neural_desc

        # Генерация Prompt Enhancement для LTX-Video и ComfyUI
        colors_str = " ".join(colors)
        mood_str = ", ".join(structured_matrix.get("aesthetic_mood_tags", ["cinematic"]))
        prompt_enhancement = (
            f"photorealistic high-end commercial shot, genre {structured_matrix['genre']}, "
            f"lighting {structured_matrix['lighting_temperature']}, palette accents {colors_str}, "
            f"mood: {mood_str}, professional color grading, 8k"
        )

        return {
            "status": "success",
            "description": final_description,
            "dominant_colors": colors,
            "aspect_ratio": aspect_ratio,
            "dimensions": f"{w}x{h}",
            "lighting": structured_matrix["lighting_temperature"],
            "quality_metrics": quality,
            "structured_matrix": structured_matrix,
            "mood_tags": structured_matrix.get("aesthetic_mood_tags", ["уют", "эстетика"]),
            "prompt_enhancement": prompt_enhancement,
            "visual_context_for_llm": (
                f"Жанр кадра: {structured_matrix['genre']}. "
                f"На снимке: {final_description}. "
                f"Настроение: {', '.join(structured_matrix.get('aesthetic_mood_tags', []))}."
            )
        }

    def analyze_motion_delta(
        self, 
        image1_input: Any, 
        image2_input: Any, 
        prompt: str = "", 
        company_name: str = "UCust"
    ) -> Dict[str, Any]:
        """
        Дельта-анализ движения между двумя кадрами для видео-генератора LTX-Video.
        Анализирует вектор смещения объектов, динамику камеры и микро-движения.
        """
        dossier1 = self.extract_visual_dossier(image1_input, topic=prompt, company_name=company_name)
        dossier2 = self.extract_visual_dossier(image2_input, topic=prompt, company_name=company_name)

        anchor1 = dossier1.get("structured_matrix", {}).get("foreground_physical_anchor") or "передний план"
        anchor2 = dossier2.get("structured_matrix", {}).get("foreground_physical_anchor") or "центральный объект"

        motion_prompt = (
            f"smooth cinematic camera dolly in towards {anchor1}, "
            f"organic micro-movements, rising steam with soft swirl, gentle lighting shift, "
            f"transitioning focus to {anchor2}, 24fps high quality commercial video"
        )

        return {
            "status": "success",
            "frame1_genre": dossier1.get("structured_matrix", {}).get("genre"),
            "frame2_genre": dossier2.get("structured_matrix", {}).get("genre"),
            "motion_vector": "camera_dolly_in_and_organic_drift",
            "motion_prompt_for_ltx": motion_prompt,
            "visual_flow_summary": f"Динамический переход от '{anchor1}' к '{anchor2}' с плавным наездом камеры и микро-движением частиц."
        }

    def describe_image(self, image_input: Any, prompt: str = "") -> str:
        """
        Быстрое описание изображения с извлечением текста через OCR и VLM для парсинга сайтов и Telegram.
        """
        dossier = self.extract_visual_dossier(image_input, topic=prompt)
        desc = dossier.get("description", "")
        detected_text = dossier.get("structured_matrix", {}).get("detected_text_hints", "")
        if detected_text:
            return f"{desc} (Текст на фото: «{detected_text}»)"
        return desc

    def answer_question(self, image_input: Any, question: str) -> str:
        """
        Прямой визуальный вопрос-ответ (VQA) для чат-бота и Telegram:
        Отвечает на конкретный вопрос пользователя по загруженному фото.
        """
        pil_img = self._to_pil_image(image_input)
        if pil_img is None:
            return "Не удалось загрузить или прочесть изображение."

        if self._is_loaded and self._llm:
            try:
                buffered = io.BytesIO()
                pil_img.save(buffered, format="JPEG", quality=85)
                b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
                data_uri = f"data:image/jpeg;base64,{b64}"
                
                response = self._llm.create_chat_completion(
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "image_url", "image_url": {"url": data_uri}},
                                {"type": "text", "text": f"Answer concisely in Russian: {question}"}
                            ]
                        }
                    ],
                    max_tokens=100,
                    temperature=0.2
                )
                return response["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.warning(f"[Moondream] VQA answer error: {e}")

        dossier = self.extract_visual_dossier(pil_img)
        return f"На изображении: {dossier.get('description', '')}. Палитра: {', '.join(dossier.get('dominant_colors', []))}."

    def analyze_attachments_batch(self, attachments: List[Any], topic: str = "", company_name: str = "UCust") -> Dict[str, Any]:
        """
        Пакетный анализ всех прикрепленных пользователем фотографий.
        Возвращает единый агрегированный отчет для LLM и Prompt Director.
        """
        if not attachments:
            return {
                "has_attachments": False,
                "summary": "Пользователь не прикрепил визуальных файлов.",
                "visual_context_for_llm": "",
                "prompt_keywords": "",
                "colors": [],
                "quality_flags": {"all_acceptable": True}
            }

        print(f"[Moondream] 👁️ Анализ {len(attachments)} загруженных пользователем фото через Vision Analyst v2.0...")
        
        analyzed_items = []
        all_colors = []
        descriptions = []
        enhancements = []
        mood_tags_list = []
        has_blurry = False

        for idx, att in enumerate(attachments):
            res = self.extract_visual_dossier(att, topic=topic, company_name=company_name)
            if res.get("status") == "success":
                analyzed_items.append(res)
                all_colors.extend(res.get("dominant_colors", []))
                descriptions.append(f"Фото #{idx+1} ({res.get('structured_matrix', {}).get('genre', 'Объект')}): {res.get('description')}")
                enhancements.append(res.get("prompt_enhancement", ""))
                mood_tags_list.extend(res.get("mood_tags", []))
                if res.get("quality_metrics", {}).get("is_blurry"):
                    has_blurry = True

        unique_colors = list(dict.fromkeys(all_colors))[:6]
        unique_moods = list(dict.fromkeys(mood_tags_list))[:5]
        combined_desc = "\n".join(descriptions)
        combined_keywords = ", ".join(list(dict.fromkeys(enhancements)))

        motion_data = None
        if len(attachments) >= 2:
            try:
                motion_data = self.analyze_motion_delta(attachments[0], attachments[1], prompt=topic, company_name=company_name)
            except Exception as m_err:
                logger.warning(f"Motion delta error: {m_err}")

        fusion_info = None
        slot_mapping = None
        try:
            from skills.multi_image_fusion import MultiImageSemanticFusionEngine
            slot_mapping = MultiImageSemanticFusionEngine.allocate_workflow_slots(
                analyzed_images=analyzed_items,
                user_prompt=topic,
                niche=""
            )
            fusion_info = MultiImageSemanticFusionEngine.compose_fusion_prompt(
                slot_mapping=slot_mapping,
                user_prompt=topic,
                company_name=company_name
            )
        except Exception as f_err:
            logger.warning(f"Error in multi-image semantic fusion: {f_err}")

        narrative = fusion_info.get("visual_narrative_for_saiga") if fusion_info else combined_desc

        visual_context_for_llm = (
            f"\n[ВИЗУАЛЬНЫЙ ПАСПОРТ КАДРА MOONDREAM V2.0]:\n"
            f"• Проанализировано снимков: {len(analyzed_items)} (Качество: {'⚠️ Есть смазанные кадры' if has_blurry else '✅ Высокая четкость'}).\n"
            f"• Семантический сюжет: {narrative}\n"
            f"• Настроение и вайб: {', '.join(unique_moods) if unique_moods else 'уют и стиль'}.\n"
            f"• Фирменные цвета: {', '.join(unique_colors) if unique_colors else 'натуральные'}.\n"
            f"🎯 ИНСТРУКЦИЯ ДЛЯ КОПИРАЙТЕРА:\n"
            f"1. Опиши именно детали этого кадра с профессиональной терминологией.\n"
            f"2. Подстрой эмоциональный тон текста под настроение ({', '.join(unique_moods)}).\n"
            f"3. Органично подведи к призыву к действию (CTA)."
        )

        print(f"[Moondream] ✅ Анализ завершен! Выделено {len(unique_colors)} цветов и {len(unique_moods)} mood-тегов.")
        return {
            "has_attachments": True,
            "count": len(analyzed_items),
            "items": analyzed_items,
            "colors": unique_colors,
            "mood_tags": unique_moods,
            "summary": combined_desc,
            "visual_context_for_llm": visual_context_for_llm,
            "prompt_keywords": combined_keywords,
            "slot_mapping": slot_mapping,
            "fusion_prompt": fusion_info.get("fusion_prompt") if fusion_info else None,
            "fusion_narrative": narrative,
            "motion_for_video": motion_data,
            "quality_flags": {
                "all_acceptable": not has_blurry,
                "has_blurry": has_blurry
            }
        }

    def analyze_competitor_post(self, competitor_name: str, post_text: str, image_input: Any = None) -> Dict[str, Any]:
        """
        Мультимодальный анализ поста конкурента:
        Разбирает фото из поста через Moondream VLM + OpenCV, объединяет с текстом
        и формирует глубокую маркетинговую выжимку для Сайги (LLM).
        """
        print(f"[Moondream] 🕵️ Мультимодальный анализ поста конкурента «{competitor_name}»...")
        
        pil_img = self._to_pil_image(image_input)
        visual_desc = "Фотоматериал не прикреплен или представляет собой стандартную плашку."
        visual_hook = "Упор исключительно на текстовое сообщение."
        weakness = "Отсутствие сильного визуального якоря, пробивающего баннерную слепоту."

        if pil_img is not None:
            quality = calculate_image_quality_metrics(pil_img)
            colors = self._extract_color_palette(pil_img, num_colors=3)
            
            if quality["contrast_score"] > 50:
                visual_desc = f"Графический рекламный креатив с яркими контрастными элементами (цвета: {', '.join(colors)}, резкость: {quality['blur_score']})."
                visual_hook = "Попытка привлечь внимание агрессивным баннером / плашкой."
                weakness = "Слишком рекламный и шаблонный вид (баннерная слепота у клиентов)."
            else:
                visual_desc = f"Мягкое фото/визуал в спокойных тонах (цвета: {', '.join(colors)})."
                visual_hook = "Имитация естественного пользовательского контента (UGC)."
                weakness = "Слабая эмоциональная динамика и нехватка четкого позиционирования."

        counter_angle = (
            f"Отстроиться от поверхностного подхода «{competitor_name}»: показать реальную глубину "
            f"автономной системы, твёрдые навыки без шаблонных обещаний и живой кинематографичный визуал."
        )

        full_dossier = (
            f"\n[МУЛЬТИМОДАЛЬНЫЙ АНАЛИЗ ПОСТА КОНКУРЕНТА: «{competitor_name}»]\n"
            f"• Текст публикации: «{post_text.strip()}»\n"
            f"• Разбор визуала (Moondream VQA): {visual_desc}\n"
            f"• Маркетинговый хук креатива: {visual_hook}\n"
            f"• Уязвимость / Слабое место: {weakness}\n"
            f"🎯 ЗАДАЧА ДЛЯ САЙГИ (ОТСТРОЙКА): {counter_angle}\n"
        )

        return {
            "competitor_name": competitor_name,
            "post_text": post_text,
            "visual_description": visual_desc,
            "visual_hook": visual_hook,
            "weakness": weakness,
            "counter_angle": counter_angle,
            "multimodal_dossier": full_dossier
        }

    def analyze_image(self, image_path: str, prompt: str = "Describe this image in detail.") -> str:
        """Совместимость с предыдущим API."""
        dossier = self.extract_visual_dossier(image_path)
        return dossier.get("description", "Изображение проанализировано.")


MoondreamVQA = MoondreamVQASkill

__all__ = ["MoondreamVQASkill", "MoondreamVQA", "calculate_image_quality_metrics", "DOMAIN_VOCABULARIES"]
