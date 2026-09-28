# File: skills/comfy_cli_runner.py | Module: skills | Part of Intellectual Property Submission.
"""
ComfyUI CLI & Headless API Runner Module for UCust.AI.

Loads High-Quality Photo Generation workflow JSON graphs (such as Photo_generations.json),
programmatically updates prompts, seeds, dimensions and aspect ratios, and triggers
headless photorealistic image rendering via ComfyUI local API (http://127.0.0.1:8188) or CLI runner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import sys
from typing import Any, Dict, Optional, Tuple, Union

try:
    import httpx
except ImportError:
    httpx = None

logger = logging.getLogger("comfy_cli_runner")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT_REALISM_WORKFLOW = os.path.join(PROJECT_ROOT, "realism2.0.json")
PROJECT_ROOT_PHOTO_WORKFLOW = os.path.join(PROJECT_ROOT, "Photo_generations.json")
PROJECT_ROOT_WORKFLOW = os.path.join(PROJECT_ROOT, "Ltx_generations.json")
MODELS_COMFY_WORKFLOW = os.path.join(PROJECT_ROOT, "models", "comfyui", "realism2.0.json")
LOCAL_TEMPLATE_PATH = os.path.join(PROJECT_ROOT, "skills", "templates", "realism2.0.json")
DEFAULT_WORKFLOW_DESKTOP_PATH = r"C:\Users\Metal\Desktop\realism2.0.json"


class ComfyCLIRunner:
    """
    CLI & Headless API Runner for executing ComfyUI Photorealistic Image Generation & Editing workflow graphs.
    Поддерживает:
    - Realism 2.0 (Qwen-Image / Qwen-VL-Edit / FluxKontext)
    - Переключение Mode: Edit (Node 72) True/False (генерация с нуля по шуму vs редактирование 3 референсов)
    - Раскладку изображений 1, 2, 3 по нодам LoadImage (55, 64, 65) в точном порядке
    - Промпт-инжиниринг от Сайги и управление KSampler сидами/разрешением (до 1024x1024)
    """

    ASPECT_RATIO_MAP = {
        "1:1": (1152, 1152),
        "4:5": (1024, 1280),
        "16:9": (1344, 768),
        "9:16": (768, 1344),
        "3:4": (960, 1280),
        "4:3": (1280, 960)
    }

    def __init__(
        self,
        comfyui_url: Optional[str] = None,
        output_dir: Optional[str] = None,
        workflow_template_path: Optional[str] = None,
        timeout: float = 600.0,
    ) -> None:
        self.comfyui_url = (comfyui_url or os.getenv("COMFYUI_URL", "http://127.0.0.1:8188")).rstrip("/")
        self.output_dir = output_dir or os.getenv("COMFYUI_OUTPUT_DIR", os.path.join(PROJECT_ROOT, "output", "photos"))
        self.workflow_template_path = (
            workflow_template_path
            or os.getenv("COMFYUI_WORKFLOW_PATH")
            or (
                PROJECT_ROOT_REALISM_WORKFLOW
                if os.path.exists(PROJECT_ROOT_REALISM_WORKFLOW)
                else PROJECT_ROOT_PHOTO_WORKFLOW
                if os.path.exists(PROJECT_ROOT_PHOTO_WORKFLOW)
                else LOCAL_TEMPLATE_PATH
                if os.path.exists(LOCAL_TEMPLATE_PATH)
                else MODELS_COMFY_WORKFLOW
                if os.path.exists(MODELS_COMFY_WORKFLOW)
                else PROJECT_ROOT_WORKFLOW
                if os.path.exists(PROJECT_ROOT_WORKFLOW)
                else DEFAULT_WORKFLOW_DESKTOP_PATH
            )
        )
        self.timeout = timeout

        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(
            "ComfyCLIRunner initialized for Photo Generation: url='%s', output_dir='%s', workflow_path='%s'",
            self.comfyui_url,
            self.output_dir,
            self.workflow_template_path,
        )

    def load_workflow(self, custom_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Loads the Photo Generation ComfyUI workflow JSON from specified path or default location.
        """
        path = custom_path or self.workflow_template_path

        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    workflow_data = json.load(f)
                logger.info("Loaded ComfyUI workflow JSON template from '%s' (%d bytes)", path, os.path.getsize(path))
                return workflow_data
            except Exception as exc:
                logger.warning("Error reading workflow JSON at '%s': %s. Using default fallback.", path, exc)

        logger.info("Workflow file not found at '%s'. Using fallback Photo JSON graph.", path)
        return self._build_fallback_workflow("Commercial SMM Candid Photo", 42)

    def customize_workflow(
        self,
        workflow_json: Dict[str, Any],
        photo_prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        aspect_ratio: str = "1:1",
        images: Optional[List[str]] = None,
        edit_mode: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Programmatically updates prompt text, negative prompt, seeds, dimensions,
        edit mode boolean (Node 72), and multi-image inputs (Nodes 55, 64, 65).
        """
        chosen_seed = seed if seed is not None else random.randint(100000, 999999999999)
        width, height = self.ASPECT_RATIO_MAP.get(aspect_ratio, (1152, 1152))
        # Определение типа сцены: наличие людей vs животные/электроника/экраны
        prompt_lower = (photo_prompt or "").lower()
        has_human = any(
            w in prompt_lower for w in [
                "человек", "девушк", "парен", "мужчин", "женщин", "портрет",
                "лицо", "модел", "основател", "фаундер", "бариста", "врач", "доктор",
                "man", "woman", "person", "human", "face", "portrait", "founder", "model"
            ]
        ) and not any(w in prompt_lower for w in ["плата", "esp32", "esp-32", "чип"])

        has_animal = any(
            w in prompt_lower for w in [
                "кот", "кошк", "котен", "котенок", "котейк", "собак", "щенок", "пес", "пёс",
                "животн", "шерст", "мех", "cat", "dog", "puppy", "kitten", "fur", "animal", "pet"
            ]
        )

        has_screen_or_ui = any(
            w in prompt_lower for w in [
                "монитор", "экран", "дисплей", "ноутбук", "график", "чарт", "дашборд",
                "интерфейс", "текст", "код", "таблиц", "объявлен", "вывеск",
                "monitor", "screen", "display", "laptop", "chart", "dashboard", "ui", "code", "typography", "signboard"
            ]
        )

        is_electronics = any(
            w in prompt_lower for w in [
                "плата", "микросхем", "микроконтроллер", "esp32", "esp-32",
                "arduino", "ардуино", "pcb", "circuit board", "qfn", "fr4", "fr-4",
                "чип", "пайк", "soldering", "паяльн"
            ]
        )

        # Режим максимального фотореализма (Master Realism Mode):
        # На Tesla A100 80GB полностью отключаем Lightning LoRA (bypassed) и задействуем
        # кастомный сэмплер RES4LYF (ClownsharKSampler_Beta) на 30 шагах с CFG 3.8-4.2
        use_high_fidelity = True

        if is_electronics and not negative_prompt:
            default_neg = (
                "spider legs, caterpillar legs, bent legs, thick fringe, cartoon legs, protruding bent pins from pcb edges, "
                "legs on all four sides, curved pins, organic mesh, blurry, out of focus, soft edges, chromatic aberration, "
                "low resolution artifacts, smudged textures, 3d render, cartoon, oversaturated"
            )
        else:
            default_neg = (
                negative_prompt
                or "fused fingers, extra digits, missing fingers, malformed hands, fingers melting into objects, blurred hands, phantom fingers, mutated hands, "
                "computational photography blur, fake depth of field, synthetic bokeh, flat background, "
                "thick plastic hair, helmet hair, perfect grooming, CGI hair, hair clumps, stylized clay hair, "
                "Unreal Engine 5, octane render, digital painting, video game protagonist, hero shot, flawless, 3D render, "
                "airbrushed, plastic, smooth skin, overly retouched, wax, porcelain, perfect skin, "
                "wax figure, mannequin, doll skin, filtered, beauty filter, smooth waxy skin, flat lighting, "
                "blurry, out of focus, soft edges, chromatic aberration, cartoon, anime, illustration, "
                "overly smooth, fake lighting, oversaturated, bad anatomy, deformed hands, low resolution artifacts, smudged textures"
            )

        # Определение режима: True = Edit (есть референсы/исходники), False = Generate (с нуля из шума)
        is_edit = edit_mode if edit_mode is not None else bool(images and len(images) > 0)
        
        # Подготовка списка файлов изображений (до 3 штук)
        img_names = []
        if images and len(images) > 0:
            for im in images:
                img_names.append(os.path.basename(str(im)))
        
        img1 = img_names[0] if len(img_names) > 0 else "1.png"
        img2 = img_names[1] if len(img_names) > 1 else img1
        img3 = img_names[2] if len(img_names) > 2 else (img_names[1] if len(img_names) > 1 else img1)

        # Case 1: Standard ComfyUI GUI export format with "nodes" array
        if isinstance(workflow_json, dict) and "nodes" in workflow_json:
            for node in workflow_json.get("nodes", []):
                nid = node.get("id")
                node_type = node.get("type", "")
                title = str(node.get("title", ""))

                # 0a. Полное отключение Lightning LoRA (Node 6) для раскрытия физики диффузии RES4LYF
                if node_type in {"LoraLoaderBypassModelOnly", "LoraLoader"} or nid == 6:
                    if nid == 6 or "lightning" in str(node.get("widgets_values", [])).lower():
                        lightning_strength = 0.0
                        if "widgets_values" in node and len(node["widgets_values"]) >= 2:
                            node["widgets_values"][1] = lightning_strength
                        if "widgets_values_named" in node:
                            node["widgets_values_named"]["strength_model"] = lightning_strength
                        node["mode"] = 2  # Полный bypass Lightning LoRA

                # 0b. Точная калибровка Famegrid_RealSkinFix LoRA (Node 19) с весом 0.68
                if node_type in {"LoraLoaderBypassModelOnly", "LoraLoader"} or nid == 19:
                    if nid == 19 or "skin" in str(node.get("widgets_values", [])).lower():
                        skin_strength = 0.68 if has_human else 0.0
                        if "widgets_values" in node and len(node["widgets_values"]) >= 2:
                            node["widgets_values"][1] = skin_strength
                        if "widgets_values_named" in node:
                            node["widgets_values_named"]["strength_model"] = skin_strength
                        if has_human:
                            node["mode"] = 0  # Active for human skin
                        else:
                            node["mode"] = 2  # Bypassed for animals/objects/monitors

                # 1. Mode: Edit Switch (Node 72 / PrimitiveBoolean)
                if nid == 72 or node_type == "PrimitiveBoolean" or "Mode: Edit" in title or "Edit" in title:
                    if "widgets_values" in node:
                        node["widgets_values"] = [is_edit]
                    if "widgets_values_named" in node:
                        node["widgets_values_named"]["value"] = is_edit

                # 2. LoadImage nodes (Node 55 -> Image 1, Node 64 -> Image 2, Node 65 -> Image 3)
                if node_type == "LoadImage":
                    target_img = img1
                    if nid == 55 or "Image 1" in title or "image 1" in title.lower():
                        target_img = img1
                    elif nid == 64 or "Image 2" in title or "image 2" in title.lower():
                        target_img = img2
                    elif nid == 65 or "Image 3" in title or "image 3" in title.lower():
                        target_img = img3

                    if "widgets_values" in node and len(node["widgets_values"]) > 0:
                        node["widgets_values"][0] = target_img
                    if "widgets_values_named" in node:
                        node["widgets_values_named"]["image"] = target_img

                # 3. Prompts (TextEncodeQwenImageEditPlus / CLIPTextEncode / JAX_EasyPromptSimple)
                if node_type == "TextEncodeQwenImageEditPlus":
                    if nid == 60 or "Positive" in title or not title:
                        if "widgets_values" in node and len(node["widgets_values"]) > 0:
                            node["widgets_values"][0] = photo_prompt
                        if "widgets_values_named" in node:
                            node["widgets_values_named"]["prompt"] = photo_prompt
                    elif nid == 61 or "Negative" in title:
                        if "widgets_values" in node and len(node["widgets_values"]) > 0:
                            node["widgets_values"][0] = default_neg
                        if "widgets_values_named" in node:
                            node["widgets_values_named"]["prompt"] = default_neg

                elif node_type == "JAX_EasyPromptSimple":
                    if "widgets_values" in node and len(node["widgets_values"]) >= 2:
                        node["widgets_values"][0] = photo_prompt
                        node["widgets_values"][1] = default_neg
                    if "widgets_values_named" in node:
                        node["widgets_values_named"]["positive"] = photo_prompt
                        node["widgets_values_named"]["negative"] = default_neg

                elif node_type == "CLIPTextEncode" or "Positive" in title:
                    if "widgets_values" in node and len(node["widgets_values"]) > 0:
                        node["widgets_values"][0] = photo_prompt

                # 4. Dimensions & Scaling (EmptySD3LatentImage / ImageScale / ImageScaleToTotalPixels)
                if node_type in {"EmptySD3LatentImage", "EmptyLatentImage"}:
                    if "widgets_values" in node and len(node["widgets_values"]) >= 2:
                        node["widgets_values"][0] = width
                        node["widgets_values"][1] = height
                    if "widgets_values_named" in node:
                        node["widgets_values_named"]["width"] = width
                        node["widgets_values_named"]["height"] = height

                if node_type == "ImageScale":
                    if nid == 82:
                        target_w = int(width * 1.5)
                        target_h = int(height * 1.5)
                    else:
                        target_w = width
                        target_h = height

                    if "widgets_values" in node and len(node["widgets_values"]) >= 3:
                        node["widgets_values"][1] = target_w
                        node["widgets_values"][2] = target_h
                    if "widgets_values_named" in node:
                        node["widgets_values_named"]["width"] = target_w
                        node["widgets_values_named"]["height"] = target_h

                # 5. RES4LYF & Anti-CGI Sampler (ClownsharKSampler_Beta / KSampler / SDE Samplers)
                sampler_steps = 30
                sampler_cfg = 3.2 if has_human else 3.8
                # Переключение на SDE-семплирование и SGM Uniform / Beta для ликвидации пластикового "мультяшного" света
                sampler_name = "dpmpp_2m_sde"
                sampler_scheduler = "sgm_uniform"

                if node_type == "KSampler":
                    if "widgets_values" in node and len(node["widgets_values"]) >= 1:
                        node["widgets_values"][0] = chosen_seed
                        if len(node["widgets_values"]) >= 6:
                            node["widgets_values"][2] = sampler_steps
                            node["widgets_values"][3] = sampler_cfg
                            node["widgets_values"][4] = sampler_name
                            node["widgets_values"][5] = sampler_scheduler
                        if len(node["widgets_values"]) >= 7 and not is_edit:
                            node["widgets_values"][6] = 1.0 # 100% генерация из шума
                    if "widgets_values_named" in node:
                        node["widgets_values_named"]["seed"] = chosen_seed
                        node["widgets_values_named"]["steps"] = sampler_steps
                        node["widgets_values_named"]["cfg"] = sampler_cfg
                        node["widgets_values_named"]["sampler_name"] = sampler_name
                        node["widgets_values_named"]["scheduler"] = sampler_scheduler
                        if not is_edit:
                            node["widgets_values_named"]["denoise"] = 1.0

                elif node_type == "ClownsharKSampler_Beta":
                    if "widgets_values" in node and len(node["widgets_values"]) >= 8:
                        # Не перезаписываем sampler_name, сохраняем родной linear/euler от RES4LYF
                        node["widgets_values"][3] = sampler_steps
                        if not is_edit:
                            node["widgets_values"][5] = 1.0 # denoise = 1.0 for generation from noise
                        node["widgets_values"][6] = sampler_cfg
                        node["widgets_values"][7] = chosen_seed
                    if "widgets_values_named" in node:
                        node["widgets_values_named"]["steps"] = sampler_steps
                        node["widgets_values_named"]["cfg"] = sampler_cfg
                        node["widgets_values_named"]["seed"] = chosen_seed
                        if not is_edit:
                            node["widgets_values_named"]["denoise"] = 1.0


                # 5b. FreeU (V2) - Разделение низких и высоких частот (физическое дробление бликов и хайлайтов)
                if node_type in {"FreeU", "FreeU_V2", "FreeUAdvanced"}:
                    if "widgets_values" in node and len(node["widgets_values"]) >= 4:
                        node["widgets_values"][0] = 1.1  # b1: low-freq weight (базовый свет)
                        node["widgets_values"][1] = 1.2  # b2
                        node["widgets_values"][2] = 0.9  # s1: high-freq weight (микрорельеф)
                        node["widgets_values"][3] = 0.2  # s2
                    if "widgets_values_named" in node:
                        node["widgets_values_named"]["b1"] = 1.1
                        node["widgets_values_named"]["b2"] = 1.2
                        node["widgets_values_named"]["s1"] = 0.9
                        node["widgets_values_named"]["s2"] = 0.2

                # 5c. Dynamic Thresholding (Mimic CFG) - Срез пересветов и гашение CGI-глянца
                if "DynamicThresholding" in node_type or "RescaleCFG" in node_type:
                    if "widgets_values_named" in node:
                        if "mimic_cfg" in node["widgets_values_named"]:
                            node["widgets_values_named"]["mimic_cfg"] = 7.0
                        if "threshold_percentile" in node["widgets_values_named"]:
                            node["widgets_values_named"]["threshold_percentile"] = 0.995
                        if "mode" in node["widgets_values_named"]:
                            node["widgets_values_named"]["mode"] = "HalfCosine"

                # 6. UNET & Memory Optimization
                if node_type == "UNETLoader":
                    if "widgets_values" in node and len(node["widgets_values"]) >= 2:
                        node["widgets_values"][1] = "fp8_e4m3fn"
                    if "widgets_values_named" in node:
                        node["widgets_values_named"]["weight_dtype"] = "fp8_e4m3fn"

                # 7. Device optimization
                if node_type == "CLIPLoader":
                    if "widgets_values" in node and len(node["widgets_values"]) >= 3 and node["widgets_values"][2] == "cpu":
                        node["widgets_values"][2] = "default"
                    if "widgets_values_named" in node and node["widgets_values_named"].get("device") == "cpu":
                        node["widgets_values_named"]["device"] = "default"

                # 8. Impact Pack FaceDetailer & HandDetailer (Multi-bbox Detection & Edge Locks)
                if "Detailer" in node_type or "FaceDetailer" in node_type or "HandDetailer" in node_type:
                    if "widgets_values_named" in node:
                        if "max_detect" in node["widgets_values_named"]:
                            node["widgets_values_named"]["max_detect"] = 4 # Detect all hands in frame
                        if "bbox_threshold" in node["widgets_values_named"]:
                            node["widgets_values_named"]["bbox_threshold"] = 0.35
                        if "feather" in node["widgets_values_named"]:
                            node["widgets_values_named"]["feather"] = 25
                        if "denoise" in node["widgets_values_named"]:
                            node["widgets_values_named"]["denoise"] = 0.38
                    if "widgets_values" in node and len(node["widgets_values"]) >= 5:
                        if "seed" in str(node.get("properties", {})).lower():
                            pass

                # 9. ControlNet Canny / Depth edge boundary locking
                if "ControlNetApply" in node_type or "ControlNet" in node_type:
                    if "widgets_values_named" in node:
                        if "strength" in node["widgets_values_named"] and node["widgets_values_named"]["strength"] > 0.3:
                            node["widgets_values_named"]["strength"] = 0.15 # Lightweight edge guard
                    if "widgets_values" in node and len(node["widgets_values"]) >= 2:
                        if isinstance(node["widgets_values"][1], (int, float)) and node["widgets_values"][1] > 0.3:
                            node["widgets_values"][1] = 0.15

                # 10. ModelSamplingAuraFlow (Qwen-Image 2512 shift=3.10 optimization)
                if "ModelSamplingAuraFlow" in node_type or node_type == "ModelSamplingSD3":
                    if "widgets_values_named" in node and "shift" in node["widgets_values_named"]:
                        node["widgets_values_named"]["shift"] = 3.10
                    if "widgets_values" in node and len(node["widgets_values"]) >= 1:
                        node["widgets_values"][0] = 3.10

                # 11. VAEDecodeTiled (tile_size=512, overlap=64)
                if "VAEDecodeTiled" in node_type:
                    if "widgets_values_named" in node:
                        if "tile_size" in node["widgets_values_named"]:
                            node["widgets_values_named"]["tile_size"] = 512
                        if "overlap" in node["widgets_values_named"]:
                            node["widgets_values_named"]["overlap"] = 64
                    if "widgets_values" in node and len(node["widgets_values"]) >= 2:
                        node["widgets_values"][0] = 512
                        node["widgets_values"][1] = 64

            logger.info(
                "Customized ComfyUI Realism 2.0 graph: edit_mode=%s, images=[%s, %s, %s], prompt='%s...', seed=%d, size=%dx%d",
                is_edit, img1, img2, img3, photo_prompt[:40], chosen_seed, width, height
            )
            return workflow_json

        # Case 2: ComfyUI Prompt API format (dict mapping node_id -> node_obj)
        if isinstance(workflow_json, dict):
            for node_id, node_data in workflow_json.items():
                if not isinstance(node_data, dict):
                    continue
                class_type = node_data.get("class_type", "")
                inputs = node_data.get("inputs", {})

                if class_type in {"CLIPTextEncode", "CLIPTextEncodeSequence"} and "text" in inputs:
                    inputs["text"] = photo_prompt

                if class_type == "JAX_EasyPromptSimple":
                    inputs["positive"] = photo_prompt
                    inputs["negative"] = default_neg

                if class_type in {"EmptySD3LatentImage", "EmptyLatentImage"}:
                    inputs["width"] = width
                    inputs["height"] = height

                if class_type in {"KSampler", "SamplerCustomAdvanced", "RandomNoise"}:
                    if "seed" in inputs:
                        inputs["seed"] = chosen_seed
                    if "sampler_name" in inputs:
                        inputs["sampler_name"] = "dpmpp_2m_sde"
                    if "scheduler" in inputs:
                        inputs["scheduler"] = "sgm_uniform"
                elif class_type == "ClownsharKSampler_Beta":
                    if "seed" in inputs:
                        inputs["seed"] = chosen_seed
                    if "steps" in inputs:
                        inputs["steps"] = 30
                    if "cfg" in inputs:
                        inputs["cfg"] = 3.2 if has_human else 3.8

                if class_type in {"ModelSamplingAuraFlow", "ModelSamplingSD3"} and "shift" in inputs:
                    inputs["shift"] = 3.10

                if class_type == "VAEDecodeTiled":
                    if "tile_size" in inputs:
                        inputs["tile_size"] = 512
                    if "overlap" in inputs:
                        inputs["overlap"] = 64


                if class_type in {"FreeU", "FreeU_V2", "FreeUAdvanced"}:
                    inputs["b1"] = 1.1
                    inputs["b2"] = 1.2
                    inputs["s1"] = 0.9
                    inputs["s2"] = 0.2

                if "DynamicThresholding" in class_type or "RescaleCFG" in class_type:
                    inputs["mimic_cfg"] = 7.0
                    inputs["threshold_percentile"] = 0.995

                # HandDetailer / FaceDetailer Multi-Hand Detection & Denoise
                if class_type in {"FaceDetailer", "HandDetailer", "DetailerForEach", "FaceDetailerPipe"}:
                    if "max_detect" in inputs:
                        inputs["max_detect"] = 4
                    if "bbox_threshold" in inputs:
                        inputs["bbox_threshold"] = 0.35
                    if "feather" in inputs:
                        inputs["feather"] = 25
                    if "denoise" in inputs:
                        inputs["denoise"] = 0.38
                    if "guide_size" in inputs:
                        inputs["guide_size"] = 1024
                    if "max_size" in inputs:
                        inputs["max_size"] = 1024
                    if "seed" in inputs:
                        inputs["seed"] = chosen_seed

                # ControlNet edge locking
                if "ControlNetApply" in class_type and "strength" in inputs:
                    if float(inputs["strength"]) > 0.3:
                        inputs["strength"] = 0.15

            logger.info("Customized ComfyUI API Photo graph with prompt='%s...', seed=%d", photo_prompt[:40], chosen_seed)
            return workflow_json

        return workflow_json

    async def is_server_online(self, timeout: float = 3.0) -> bool:
        """
        Проверяет доступность локального сервера ComfyUI (http://127.0.0.1:8188).
        """
        if httpx is None:
            return False
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.get(f"{self.comfyui_url}/system_stats")
                return res.status_code == 200
        except Exception:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    res = await client.get(f"{self.comfyui_url}/")
                    return res.status_code in {200, 302, 404}
            except Exception:
                return False

    async def stop_server(self) -> bool:
        """
        Полное отключение ComfyUI сервера и освобождение порта 8188 и VRAM GPU.
        """
        print("[ComfyCLIRunner] 🛑 Остановка ComfyUI сервера (полное отключение)...")
        logger.info("Stopping ComfyUI server on %s", self.comfyui_url)

        # 1. Попытка мягкого прерывания задач через API
        if httpx is not None:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    await client.post(f"{self.comfyui_url}/interrupt")
            except Exception:
                pass

        # 2. Остановка на Linux / Unix сервере (/opt/ucust)
        if sys.platform != "win32":
            try:
                import subprocess
                subprocess.run("fuser -k 8188/tcp 2>/dev/null || true", shell=True, timeout=5)
                subprocess.run("pkill -9 -f 'main.py.*8188' 2>/dev/null || true", shell=True, timeout=5)
                subprocess.run("pkill -9 -f 'ComfyUI/main.py' 2>/dev/null || true", shell=True, timeout=5)
                print("[ComfyCLIRunner] 🔌 Процессы ComfyUI на Linux успешно завершены.")
            except Exception as e:
                logger.warning("Error terminating ComfyUI processes on Linux: %s", e)
        else:
            # 3. Остановка на Windows
            try:
                import subprocess
                try:
                    out = subprocess.check_output('netstat -ano | findstr :8188', shell=True, text=True, errors='ignore')
                except subprocess.CalledProcessError:
                    out = ""
                for line in out.strip().splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 5 and "LISTENING" in parts:
                        pid = parts[-1]
                        if pid.isdigit() and int(pid) > 0:
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                print("[ComfyCLIRunner] 🔌 Процессы ComfyUI на Windows успешно завершены.")
            except Exception as e:
                logger.warning("Error terminating ComfyUI processes on Windows: %s", e)

        await asyncio.sleep(2.0)
        return True

    async def start_server(self, wait_timeout: float = 45.0) -> bool:
        """
        Полный запуск ComfyUI сервера и ожидание готовности к приему задач (до 45 сек).
        """
        print("[ComfyCLIRunner] 🚀 Запуск ComfyUI сервера...")
        logger.info("Starting ComfyUI server...")

        import subprocess

        # Поиск директории ComfyUI
        comfy_dir_candidates = [
            "/opt/ucust/ComfyUI",
            os.path.abspath(os.path.join(PROJECT_ROOT, "..", "ComfyUI")),
            os.path.abspath(os.path.join(PROJECT_ROOT, "ComfyUI")),
            "C:/Users/Metal/Documents/ComfyUI",
            "C:/ComfyUI",
            "/root/ComfyUI"
        ]
        comfy_dir = None
        for cd in comfy_dir_candidates:
            if os.path.isdir(cd) and os.path.exists(os.path.join(cd, "main.py")):
                comfy_dir = cd
                break

        if not comfy_dir:
            print("[ComfyCLIRunner] ⚠️ Директория ComfyUI с main.py не найдена. Проверьте путь установки.")
            return False

        # Поиск исполняемого файла Python
        python_candidates = [
            "/opt/ucust/venv/bin/python",
            "/opt/ucust/ai/venv/bin/python",
            os.path.abspath(os.path.join(PROJECT_ROOT, "..", "venv", "bin", "python")),
            sys.executable,
            "python3",
            "python"
        ]
        python_bin = None
        for py in python_candidates:
            if os.path.exists(py) and os.access(py, os.X_OK):
                python_bin = py
                break
            elif py in {"python3", "python", sys.executable}:
                python_bin = py
                break

        log_file = "/opt/ucust/comfyui.log" if os.path.exists("/opt/ucust") else os.path.join(comfy_dir, "comfy.log")

        # Запуск фонового процесса
        try:
            if sys.platform != "win32":
                start_sh = os.path.join(PROJECT_ROOT, "scripts", "start_comfyui.sh")
                if os.path.exists(start_sh) and os.access(start_sh, os.X_OK):
                    subprocess.Popen(["/bin/bash", start_sh], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                else:
                    log_fd = open(log_file, "a", encoding="utf-8")
                    subprocess.Popen(
                        [python_bin, "main.py", "--listen", "0.0.0.0", "--port", "8188"],
                        cwd=comfy_dir,
                        stdout=log_fd,
                        stderr=subprocess.STDOUT,
                        start_new_session=True
                    )
            else:
                log_fd = open(log_file, "a", encoding="utf-8")
                subprocess.Popen(
                    [python_bin, "main.py", "--listen", "127.0.0.1", "--port", "8188"],
                    cwd=comfy_dir,
                    stdout=log_fd,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP") else 0
                )
            print(f"[ComfyCLIRunner] ⚡ Процесс ComfyUI запущен (лог: {log_file}). Ожидание инициализации моделей...")
        except Exception as start_err:
            print(f"[ComfyCLIRunner] ⚠️ Ошибка при запуске ComfyUI: {start_err}")
            return False

        # Ожидание готовности сервера к приему запросов
        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < wait_timeout:
            await asyncio.sleep(2.0)
            if await self.is_server_online():
                print(f"[ComfyCLIRunner] ✅ ComfyUI сервер успешно запущен и готов к работе ({self.comfyui_url})!")
                return True

        print(f"[ComfyCLIRunner] ⚠️ Сервер ComfyUI не ответил на пинг за {wait_timeout} сек.")
        return False

    async def restart_server(self, wait_timeout: float = 45.0) -> bool:
        """
        Выполняет полный цикл перезапуска: отключение (shutdown/kill) -> запуск -> верификация доступности.
        """
        print("[ComfyCLIRunner] 🔄 Запущен полный перезапуск ComfyUI сервера (Stop -> Start)...")
        await self.stop_server()
        return await self.start_server(wait_timeout=wait_timeout)

    async def ensure_server_online(self, wait_timeout: float = 45.0) -> bool:
        """
        Проверяет подключение к ComfyUI перед генерацией.
        Если соединение отсутствует — автоматически выполняет полное отключение и включение.
        """
        if await self.is_server_online():
            return True

        print("[ComfyCLIRunner] 🔌 Соединение с ComfyUI отсутствует (127.0.0.1:8188). Инициация автовосстановления...")
        return await self.restart_server(wait_timeout=wait_timeout)

    def to_api_prompt(self, workflow_json: Dict[str, Any]) -> Dict[str, Any]:
        """
        Converts ComfyUI GUI export workflow JSON format (with 'nodes' & 'links')
        into the ComfyUI API Prompt format expected by POST /prompt endpoint.
        """
        if not isinstance(workflow_json, dict) or "nodes" not in workflow_json:
            return workflow_json

        # Determine if edit mode is active and if human skin LoRA is active
        is_edit = False
        has_human = False
        for node in workflow_json.get("nodes", []):
            nid = node.get("id")
            if nid == 72 or node.get("type") == "PrimitiveBoolean" or "Mode: Edit" in str(node.get("title", "")):
                if "widgets_values" in node and len(node["widgets_values"]) > 0:
                    is_edit = bool(node["widgets_values"][0])
                elif "widgets_values_named" in node and "value" in node["widgets_values_named"]:
                    is_edit = bool(node["widgets_values_named"]["value"])
            if (nid == 19 or "skin" in str(node.get("widgets_values", [])).lower()) and node.get("mode") == 0:
                has_human = True

        # 1. Build link map: link_id -> [from_node_id_str, from_slot_idx]
        links_map = {}
        for link in workflow_json.get("links", []):
            if isinstance(link, (list, tuple)) and len(link) >= 3:
                link_id = link[0]
                from_node = str(link[1])
                from_slot = link[2]

                # If link comes from Latent Input Switch (Node 73), bypass it directly!
                if from_node == "73" or from_node == 73:
                    if is_edit:
                        from_node, from_slot = "58", 0  # VAEEncode
                    else:
                        from_node, from_slot = "74", 0  # EmptySD3LatentImage / EmptyLatentImage

                # If link comes from Image Comparer (Node 68), bypass it directly to VAEDecode (Node 53)!
                if from_node == "68" or from_node == 68:
                    from_node, from_slot = "53", 0  # VAEDecode output image

                # Для портретов людей: исключаем 4x-UltraSharp (81/82), забираем чистый VAE декод (48) с пленочным зерном и порами!
                if has_human and (from_node == "82" or from_node == "81"):
                    from_node, from_slot = "48", 0  # VAEDecodeTiled output image

                links_map[link_id] = [from_node, from_slot]

        # 2. Build API Prompt nodes (skipping GUI-only and unneeded switch/comparer nodes)
        gui_only_types = {
            "Image Comparer (rgthree)",
            "Image Comparer",
            "Latent Input Switch",
            "PrimitiveBoolean",
            "Note",
            "Markdown",
            "PreviewImage",
            "Fast Groups Bypasser (rgthree)",
            "Fast Muter (rgthree)",
            "Bookmark (rgthree)"
        }

        api_prompt = {}
        for node in workflow_json.get("nodes", []):
            node_id = str(node.get("id"))
            class_type = node.get("type")
            if not class_type or class_type in gui_only_types or "comparer" in class_type.lower():
                continue

            inputs = {}

            # Add named widget values
            if "widgets_values_named" in node and isinstance(node["widgets_values_named"], dict):
                inputs.update(node["widgets_values_named"])

            # Add linked inputs (skip links coming from filtered GUI nodes)
            for inp in node.get("inputs", []):
                inp_name = inp.get("name")
                link_id = inp.get("link")
                if link_id is not None and link_id in links_map:
                    # In Text-to-Image mode (not is_edit), do NOT attach dummy images to TextEncode!
                    if not is_edit and class_type == "TextEncodeQwenImageEditPlus" and inp_name in {"image1", "image2", "image3"}:
                        continue
                    inputs[inp_name] = links_map[link_id]

            api_prompt[node_id] = {
                "class_type": class_type,
                "inputs": inputs
            }

        # 3. Маршрутизация финального сохранения изображения
        # Для портретов людей берем чистый некастрированный вывод VAEDecodeTiled (Node 48)
        # напрямую, без сглаживающего апскейлера 4x-UltraSharp, чтобы сохранить микрорельеф пор и зерно
        if has_human and "21" in api_prompt and "inputs" in api_prompt["21"]:
            api_prompt["21"]["inputs"]["images"] = ["48", 0]

        return api_prompt

    async def upload_attachment(self, att: Any, client: Optional[Any] = None) -> str:
        """
        Сохраняет и загружает изображение в ComfyUI (через /upload/image API или локальную директорию).
        Возвращает имя файла в ComfyUI.
        """
        import base64
        import io
        import uuid

        filename = f"upload_{uuid.uuid4().hex[:12]}.png"
        raw_bytes = None

        if isinstance(att, dict):
            local_cand = att.get("local_path")
            if local_cand and os.path.exists(local_cand):
                att = local_cand
            else:
                att = att.get("dataUrl") or att.get("url") or att.get("file_path") or att

        if isinstance(att, str):
            if att.startswith("data:image"):
                try:
                    _, b64data = att.split(",", 1)
                    raw_bytes = base64.b64decode(b64data)
                except Exception as e:
                    logger.warning("Error decoding base64 attachment: %s", e)
            elif os.path.exists(att):
                filename = os.path.basename(att)
                try:
                    with open(att, "rb") as f:
                        raw_bytes = f.read()
                except Exception as e:
                    logger.warning("Error reading local attachment file '%s': %s", att, e)
            elif att.startswith("http://") or att.startswith("https://"):
                try:
                    import httpx as hx
                    with hx.Client(timeout=15.0, follow_redirects=True) as dl_client:
                        resp = dl_client.get(att)
                        if resp.is_success and len(resp.content) > 100:
                            raw_bytes = resp.content
                            clean_name = os.path.basename(att.split("?")[0])
                            if not clean_name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                                clean_name = f"{uuid.uuid4().hex[:8]}.png"
                            filename = clean_name
                except Exception as dl_err:
                    logger.warning("Error fetching attachment from URL '%s': %s", att, dl_err)
            else:
                clean_name = os.path.basename(att.split("?")[0])
                filename = clean_name if clean_name else "1.png"

        # Конвертация в стандартный PNG/RGB если это необычный формат (например ico)
        if raw_bytes:
            try:
                from PIL import Image
                with Image.open(io.BytesIO(raw_bytes)) as pil_img:
                    rgb_img = pil_img.convert("RGB")
                    buf = io.BytesIO()
                    rgb_img.save(buf, format="PNG")
                    raw_bytes = buf.getvalue()
                    if not filename.lower().endswith(".png"):
                        filename = f"{os.path.splitext(filename)[0]}.png"
            except Exception as pil_err:
                logger.debug("Pillow normalization skipped: %s", pil_err)

        # 1. Прямая запись на диск в папки ComfyUI/input
        if raw_bytes:
            input_dirs = [
                os.path.join(PROJECT_ROOT, "..", "ComfyUI", "input"),
                "/opt/ucust/ComfyUI/input",
                "ComfyUI/input"
            ]
            for in_dir in input_dirs:
                if os.path.exists(in_dir):
                    try:
                        dest_f = os.path.join(in_dir, filename)
                        with open(dest_f, "wb") as f_out:
                            f_out.write(raw_bytes)
                        logger.info("Saved input attachment locally to '%s'", dest_f)
                    except Exception as ex:
                        pass

        # 2. Загрузка через ComfyUI API /upload/image
        if raw_bytes and client and httpx:
            try:
                files = {"image": (filename, raw_bytes, "image/png")}
                data = {"overwrite": "true", "type": "input"}
                upload_res = await client.post(f"{self.comfyui_url}/upload/image", files=files, data=data)
                if upload_res.is_success:
                    up_json = upload_res.json()
                    filename = up_json.get("name", filename)
                    logger.info("Uploaded image to ComfyUI input via API: %s", filename)
            except Exception as up_err:
                logger.warning("Failed to upload image via ComfyUI API: %s", up_err)

        return filename

    async def _ensure_default_input_images(self, client: Optional[Any] = None) -> None:
        """Гарантирует наличие файла-заглушки 1.png в ComfyUI input для предотвращения ошибок валидации."""
        try:
            # 1. Попытка создания на диске
            input_dirs = [
                os.path.join(PROJECT_ROOT, "..", "ComfyUI", "input"),
                "/opt/ucust/ComfyUI/input",
                "ComfyUI/input"
            ]
            for in_dir in input_dirs:
                if os.path.exists(in_dir):
                    target_file = os.path.join(in_dir, "1.png")
                    if not os.path.exists(target_file):
                        try:
                            from PIL import Image
                            img = Image.new("RGB", (64, 64), color=(30, 30, 30))
                            img.save(target_file, format="PNG")
                        except Exception:
                            pass

            # 2. Попытка загрузки через ComfyUI API /upload/image
            if client is not None:
                try:
                    from PIL import Image
                    import io
                    buf = io.BytesIO()
                    img = Image.new("RGB", (64, 64), color=(30, 30, 30))
                    img.save(buf, format="PNG")
                    buf.seek(0)
                    files = {"image": ("1.png", buf, "image/png")}
                    data = {"overwrite": "true"}
                    await client.post(f"{self.comfyui_url}/upload/image", files=files, data=data)
                except Exception:
                    pass
        except Exception:
            pass

    async def execute_workflow(
        self,
        workflow_graph: Optional[Dict[str, Any]] = None,
        photo_prompt: str = "Commercial SMM photo",
        raw_topic: str = "",
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        aspect_ratio: str = "1:1",
        attachments: Optional[List[Any]] = None,
        edit_mode: Optional[bool] = None,
    ) -> Dict[str, Optional[str]]:
        """
        Submits photo prompt graph to ComfyUI local API / CLI runner and returns generated image file paths.
        """
        online = await self.ensure_server_online()
        use_mocks = os.getenv("USE_MOCKS", "false").lower() == "true"

        uploaded_images = []
        if online and not use_mocks and httpx is not None and attachments:
            try:
                async with httpx.AsyncClient(timeout=30.0) as up_client:
                    await self._ensure_default_input_images(up_client)
                    for att in attachments[:3]:
                        fname = await self.upload_attachment(att, client=up_client)
                        if fname:
                            uploaded_images.append(fname)
            except Exception as e:
                logger.warning("Error preparing image uploads for ComfyUI: %s", e)
        elif attachments:
            for att in attachments[:3]:
                fname = await self.upload_attachment(att, client=None)
                if fname:
                    uploaded_images.append(fname)

        graph = workflow_graph or self.load_workflow()
        customized_graph = self.customize_workflow(
            graph,
            photo_prompt=photo_prompt,
            negative_prompt=negative_prompt,
            seed=seed,
            aspect_ratio=aspect_ratio,
            images=uploaded_images if uploaded_images else None,
            edit_mode=edit_mode,
        )

        if online and not use_mocks and httpx is not None:
            try:
                url = f"{self.comfyui_url}/prompt"
                api_payload_graph = self.to_api_prompt(customized_graph)
                payload = {"prompt": api_payload_graph}
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    await self._ensure_default_input_images(client)
                    response = await client.post(url, json=payload)
                    if response.is_success:
                        res_json = response.json()
                        prompt_id = res_json.get("prompt_id")
                        print(f"[PhotoGeneratorSkill] ⚡ Задача принята ComfyUI (prompt_id={prompt_id}), идет диффузия...")
                        logger.info("ComfyUI Photo prompt submitted successfully (prompt_id=%s)", prompt_id)

                        # Poll completion history up to timeout
                        for poll_idx in range(int(self.timeout // 2)):
                            await asyncio.sleep(2.0)
                            if (poll_idx + 1) % 5 == 0:
                                print(f"[PhotoGeneratorSkill] ⏳ ComfyUI диффузия выполняется (прошло {(poll_idx + 1) * 2} сек)...")
                            try:
                                hist_res = await client.get(f"{self.comfyui_url}/history/{prompt_id}", timeout=10.0)
                            except Exception as hist_err:
                                logger.debug("Transient error polling ComfyUI history (will retry): %s", hist_err)
                                continue

                            if hist_res.is_success:
                                history = hist_res.json().get(prompt_id, {})
                                status_info = history.get("status", {})
                                if status_info.get("status_str") == "error":
                                    print(f"[PhotoGeneratorSkill] ⚠️ ComfyUI ошибка ноды: {status_info.get('messages', status_info)}")
                                    break
                                outputs = history.get("outputs", {})
                                if outputs:
                                    for node_id, node_out in outputs.items():
                                        image_list = node_out.get("images", [])
                                        for img in image_list:
                                            fname = img.get("filename")
                                            if fname:
                                                subfolder = img.get("subfolder", "")
                                                img_type = img.get("type", "output")
                                                dest_path = os.path.join(self.output_dir, fname)
                                                
                                                # Download / fetch full image data
                                                downloaded = False
                                                try:
                                                    params = {"filename": fname}
                                                    if subfolder:
                                                        params["subfolder"] = subfolder
                                                    if img_type:
                                                        params["type"] = img_type
                                                    img_resp = await client.get(f"{self.comfyui_url}/view", params=params, timeout=30.0)
                                                    if img_resp.is_success and len(img_resp.content) > 1000:
                                                        with open(dest_path, "wb") as f:
                                                            f.write(img_resp.content)
                                                        downloaded = True
                                                except Exception as dl_err:
                                                    logger.warning("Error downloading photo from ComfyUI API: %s", dl_err)
                                                    
                                                # Локальный поиск в папке ComfyUI/output на сервере (если API вернул пустой буфер)
                                                if not downloaded or not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1000:
                                                    import shutil
                                                    cand_dirs = [
                                                        os.path.join(PROJECT_ROOT, "..", "ComfyUI", "output"),
                                                        "/opt/ucust/ComfyUI/output",
                                                        "ComfyUI/output"
                                                    ]
                                                    for cdir in cand_dirs:
                                                        src_f = os.path.join(cdir, subfolder, fname) if subfolder else os.path.join(cdir, fname)
                                                        if os.path.exists(src_f) and os.path.getsize(src_f) > 1000:
                                                            shutil.copy2(src_f, dest_path)
                                                            downloaded = True
                                                            break
                                                    
                                                print(f"[PhotoGeneratorSkill] 🖼️ Фото успешно получено из ComfyUI: {dest_path}")
                                                return {
                                                    "status": "success",
                                                    "photo_path": dest_path,
                                                    "file_path": dest_path,
                                                    "image_url": f"/output/photos/{fname}",
                                                    "photo_url": f"/output/photos/{fname}",
                                                    "media_url": f"{self.comfyui_url}/view?filename={fname}",
                                                }
                    else:
                        print(f"[PhotoGeneratorSkill] ⚠️ ComfyUI вернул ошибку ({response.status_code}): {response.text}")
            except Exception as exc:
                print(f"[PhotoGeneratorSkill] ⚠️ Ошибка при обращении к ComfyUI: {exc}")
                logger.warning("ComfyUI execution exception: %s", exc)

        # Строгое правило: НИКАКИХ синтетических 2D-карточек и заглушек!
        # Если ComfyUI вернул ошибку или оффлайн — возвращаем no_image, чтобы пост вышел чистым текстом без фото.
        print("[PhotoGeneratorSkill] ℹ️ Фото не сгенерировано ComfyUI. Публикация будет выполнена строго без фото (чистый текст).")
        return {
            "status": "no_image",
            "photo_path": None,
            "file_path": None,
            "image_url": None,
            "photo_url": None,
            "media_url": None,
        }

    def _build_fallback_workflow(self, photo_prompt: str, seed: int) -> Dict[str, Any]:
        """Constructs basic fallback Photo graph."""
        return {
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2512_fp8_e4m3fn.safetensors"}},
            "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_2.5_vl_7b_fp8_scaled.safetensors"}},
            "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
            "4": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
            "15": {"class_type": "JAX_EasyPromptSimple", "inputs": {"positive": photo_prompt, "negative": "blurry, bad anatomy"}},
            "16": {"class_type": "ClownsharKSampler_Beta", "inputs": {"seed": seed, "steps": 30, "cfg": 3.1}},
            "21": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI"}},
        }


__all__ = ["ComfyCLIRunner", "DEFAULT_WORKFLOW_DESKTOP_PATH"]
