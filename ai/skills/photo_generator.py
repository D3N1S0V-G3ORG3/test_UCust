"""
PhotoGeneratorSkill — Модуль автономной генерации фото и визуального контента для SMM.
Создает коммерческие промпты по стандартам современной фотографии (Sony A7R / Hasselblad),
управляет ракурсами, стилями, палитрой бренда и генерирует изображения.
"""

from __future__ import annotations

import sys
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import os
import re
import uuid
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional

try:
    from core.internal_calendar import InternalCalendarEngine
except ImportError:
    try:
        from ai.core.internal_calendar import InternalCalendarEngine
    except ImportError:
        InternalCalendarEngine = None

class ControlledVarianceEngine:
    """
    Механизм контролируемой энтропии (Controlled Variance & Dynamic RAG Identity):
    Исключает визуальную гомогенизацию и стоковые дубликаты лент у разных клиентов в одной нише.
    - 1. Параметрические матрицы (Wildcards: Surfaces, Backgrounds, Lighting)
    - 2. Интеграция визуальных якорей бренда (RAG Identity Injection)
    - 3. Ротация оптики и ракурсов (Macro 85mm, Medium 50mm, Wide 35mm)
    """

    SURFACES = {
        "tech": [
            "scandinavian light oak desk",
            "deep dark walnut wood table",
            "matte polished concrete surface",
            "industrial blackened steel desk",
            "white terrazzo desk",
            "minimalist brushed aluminum workspace"
        ],
        "horeca": [
            "rustic solid oak table",
            "textured dark walnut board",
            "rough natural slate slab",
            "aged reclaimed wood surface",
            "crinkled brown craft parchment",
            "cream handmade linen runner"
        ],
        "beauty": [
            "warm travertine marble surface",
            "minimalist ivory stone pedestal",
            "textured light beige oak table",
            "soft neutral matte ceramic vanity",
            "cream ribbed knit fabric surface"
        ],
        "general": [
            "contemporary matte oak table",
            "refined dark walnut wood",
            "clean stone surface",
            "authentic natural desk"
        ]
    }

    BACKGROUNDS = {
        "tech": [
            "minimalist architectural window blinds with soft daylight",
            "modern open steel bookshelf with tech books and indoor greenery",
            "frosted glass partition with subtle blurred office reflections",
            "weathered warm red brick loft wall in soft bokeh",
            "sunlit modern glass-partitioned meeting room in background"
        ],
        "horeca": [
            "warm open wooden display shelves with ceramic jars in soft bokeh",
            "cozy coffee boutique interior with soft circular golden bokeh",
            "rustic brick archway with soft natural daylight",
            "artisan kitchen background with hanging copper cookware in soft focus"
        ],
        "beauty": [
            "minimalist aesthetic salon background with soft round mirrors and travertine arches in creamy bokeh",
            "sunlit botanical atelier corner with soft green foliage",
            "warm neutral beige background with delicate dried botanicals in soft focus"
        ],
        "general": [
            "bright minimalist sunlit room in soft bokeh",
            "aesthetic textured architectural wall with natural shadow play",
            "warm ambient background with gentle depth of field"
        ]
    }

    LIGHTING_SCENARIOS = [
        "gentle morning window daylight with soft ambient room shadows",
        "soft overcast neutral ambient daylight with realistic micro-shadows",
        "subtle golden hour window sunbeams casting gentle organic room shadows",
        "soft diffused 4500K ceiling task illumination with realistic room shadows"
    ]

    CAMERA_OPTICS_ROSTER = [
        # 0: Macro (Детали и текстуры продукта)
        {"lens": "85mm f/1.8 macro lens", "perspective": "extreme close-up macro photography", "dof": "creamy shallow depth of field, blurred background bokeh"},
        # 1: Medium (Контекст и сбалансированная композиция)
        {"lens": "50mm f/2.8 prime lens", "perspective": "candid eye-level medium perspective", "dof": "natural progressive optical depth of field"},
        # 2: Wide (Общий план воркспейса / интерьер)
        {"lens": "35mm f/4.0 lens", "perspective": "wide-angle contextual workspace shot", "dof": "layered spatial depth from foreground to background"},
        # 3: Tabletop 45°
        {"lens": "50mm f/2.8 lens", "perspective": "45-degree angle tabletop perspective", "dof": "crisp subject focus with smooth rear falloff"}
    ]

    @classmethod
    def get_surface(cls, domain: str, index: int) -> str:
        pool = cls.SURFACES.get(domain, cls.SURFACES["general"])
        return pool[index % len(pool)]

    @classmethod
    def get_background(cls, domain: str, index: int) -> str:
        pool = cls.BACKGROUNDS.get(domain, cls.BACKGROUNDS["general"])
        return pool[index % len(pool)]

    @classmethod
    def get_lighting(cls, index: int) -> str:
        return cls.LIGHTING_SCENARIOS[index % len(cls.LIGHTING_SCENARIOS)]

    @classmethod
    def get_camera_optics(cls, index: int) -> Dict[str, str]:
        return cls.CAMERA_OPTICS_ROSTER[index % len(cls.CAMERA_OPTICS_ROSTER)]


class CinematicAestheticCore:
    """
    Фундаментальное Ядро Эстетики и Колористики (Hasselblad & Oscar-Grade Cinematography):
    Обеспечивает бескомпромиссное качество каждого кадра вне зависимости от сферы:
    - 1. Тотальная колористическая рифма (Герой + Текстиль/Одежда + Шторы/Интерьер в боке)
    - 2. Объемный свет с мягким спадом (45° Rembrandt key, inverse-square law falloff)
    - 3. 3-Плановая оптическая сепарация (Extreme Foreground -> Midground Hero -> Background Bokeh)
    - 4. Аналоговый рендеринг и материальность (Portra 400 ISO 400:1.15, Subsurface scattering, zero-CGI)
    """

    COLOR_PALETTES = {
        "sapphire": {
            "hero": "deep glossy sapphire-navy with subtle specular highlights",
            "makeup": "matching deep berry-sapphire matte velvet",
            "garments": [
                "flowing midnight-navy silk blouse sleeve catching soft ambient light",
                "crisp tailored charcoal-navy wool blazer cuff with minimalist timepiece",
                "airy deep-indigo relaxed linen shirt sleeve with tactile weave",
                "bare wrist with delicate minimalist silver openwork bracelet against travertine",
                "cozy ribbed deep navy cashmere knitwear"
            ],
            "interiors": [
                "rich navy-sapphire velvet drapes in soft background bokeh",
                "subtle dark-indigo textured lime-wash interior wall with soft shadow falloff",
                "minimalist travertine salon arch with deep navy ceramic accents in creamy bokeh",
                "ambient evening interior with delicate sapphire velvet chair in soft focus"
            ]
        },
        "burgundy": {
            "hero": "rich glossy deep burgundy wine and marsala with flawless mirror reflection",
            "makeup": "matching matte burgundy velvet",
            "garments": [
                "flowing rich wine-burgundy silk sleeve with soft light sheen",
                "crisp tailored deep marsala wool blazer cuff",
                "airy relaxed wine-toned natural linen shirt sleeve",
                "bare wrist with delicate minimalist gold chain bracelet against travertine",
                "cozy ribbed dark burgundy cashmere knitwear"
            ],
            "interiors": [
                "heavy burgundy velvet drapes in soft background bokeh",
                "warm dark marsala textured lime-wash wall with soft ambient light falloff",
                "aesthetic interior with deep wine-toned ceramic vase in creamy bokeh",
                "moody luxury lounge corner with soft burgundy upholstery in blurred background"
            ]
        },
        "chocolate": {
            "hero": "rich glossy warm chocolate-brown and creamy off-white with delicate artisanal art",
            "makeup": "matching warm nude-chocolate matte velvet",
            "garments": [
                "flowing warm mocha silk blouse sleeve catching soft studio light",
                "crisp tailored dark-chocolate wool blazer cuff",
                "airy relaxed toasted-almond linen shirt sleeve with tactile grain",
                "bare wrist with delicate minimalist gold chain against dark oak table",
                "cozy ribbed warm espresso cashmere knitwear"
            ],
            "interiors": [
                "warm dark chocolate linen drapes in soft background bokeh",
                "rich dark walnut paneled wall with soft organic light falloff",
                "minimalist beige travertine counter with dark ceramic vase in creamy bokeh",
                "cozy boutique interior with warm amber wood accents in soft focus"
            ]
        },
        "fuchsia": {
            "hero": "vibrant glossy fuchsia-magenta with high-shine mirror finish",
            "makeup": "bold matching matte fuchsia",
            "garments": [
                "flowing vibrant fuchsia-magenta silk blouse sleeve with soft specular sheen",
                "crisp tailored ivory wool blazer with subtle fuchsia silk pocket square cuff",
                "airy relaxed rose-hued linen shirt sleeve",
                "bare wrist with delicate minimalist silver heart ring and openwork bracelet",
                "cozy ribbed soft berry-fuchsia cashmere knitwear"
            ],
            "interiors": [
                "subtle fuchsia and warm ivory drapery in soft background bokeh",
                "aesthetic cream lime-wash wall with soft magenta floral accent in soft focus",
                "minimalist travertine vanity with delicate rose-magenta botanicals in creamy bokeh",
                "soft neutral background with subtle vibrant berry upholstery in blur"
            ]
        },
        "terracotta": {
            "hero": "warm autumn terracotta and amber caramel with delicate organic gloss",
            "makeup": "matching warm terracotta matte",
            "garments": [
                "flowing warm terracotta silk blouse sleeve with golden reflections",
                "crisp tailored warm camel wool blazer cuff",
                "airy relaxed burnt-orange linen shirt sleeve with tactile weave",
                "bare wrist with delicate minimalist gold cuff bracelet against stone",
                "cozy ribbed rustic terracotta cashmere knitwear"
            ],
            "interiors": [
                "warm terracotta linen curtains with sunlight filtering through in soft bokeh",
                "textured warm clay lime-wash wall casting gentle organic room shadows",
                "minimalist ceramic vase with dried autumn botanicals in creamy bokeh",
                "aesthetic warm interior with amber and terracotta elements in soft focus"
            ]
        },
        "emerald": {
            "hero": "deep glossy emerald-forest green with rich jewel-toned luster",
            "makeup": "matching deep berry-nude matte velvet with emerald eye accent",
            "garments": [
                "flowing deep emerald silk blouse sleeve with lustrous light reflections",
                "crisp tailored forest-green wool blazer cuff with gold button accent",
                "airy relaxed olive-emerald natural linen shirt sleeve",
                "bare wrist with delicate minimalist gold chain bracelet against marble",
                "cozy ribbed deep pine-green cashmere knitwear"
            ],
            "interiors": [
                "rich emerald velvet drapes in soft background bokeh",
                "textured dark olive lime-wash wall with soft directional shadow falloff",
                "minimalist travertine interior with lush monstera foliage in creamy bokeh",
                "luxury boutique lounge with deep green velvet armchair in blurred background"
            ]
        },
        "nude": {
            "hero": "clean minimalist milk-bath nude and porcelain with pristine mirror gloss",
            "makeup": "delicate matching natural nude matte velvet",
            "garments": [
                "flowing warm ivory silk blouse sleeve catching soft ambient light",
                "crisp tailored cream wool blazer cuff",
                "airy relaxed off-white natural linen shirt sleeve",
                "bare wrist with delicate minimalist gold band against travertine",
                "cozy ribbed oat-milk cashmere knitwear"
            ],
            "interiors": [
                "flowing cream linen drapes in soft background bokeh with filtered sunlight",
                "aesthetic textured ivory lime-wash wall with gentle organic shadow play",
                "minimalist travertine arches and clean ceramic vase in creamy bokeh",
                "bright airy studio interior with warm neutral palette in soft focus"
            ]
        }
    }

    @classmethod
    def resolve_color_rhyme(cls, topic: str, niche: str, var_idx: int) -> Dict[str, str]:
        text = f"{topic} {niche}".lower()
        palette_key = "nude"
        if any(w in text for w in ["сапфир", "синий", "navy", "синем", "голубой", "blue", "sapphire"]):
            palette_key = "sapphire"
        elif any(w in text for w in ["бордо", "марсал", "вишн", "burgundy", "marsala", "wine"]):
            palette_key = "burgundy"
        elif any(w in text for w in ["шоколад", "кофе", "brown", "коричнев", "chocolate", "mocha", "кориц", "синнабон"]):
            palette_key = "chocolate"
        elif any(w in text for w in ["фукси", "розов", "малин", "fuchsia", "pink", "magenta", "berry"]):
            palette_key = "fuchsia"
        elif any(w in text for w in ["терракот", "оранж", "карамел", "terracotta", "amber", "янтарь", "осень", "autumn"]):
            palette_key = "terracotta"
        elif any(w in text for w in ["изумруд", "зелен", "forest", "emerald", "green", "оливк"]):
            palette_key = "emerald"

        p_data = cls.COLOR_PALETTES.get(palette_key, cls.COLOR_PALETTES["nude"])
        garments = p_data["garments"]
        interiors = p_data["interiors"]
        return {
            "hero_color": p_data["hero"],
            "makeup": p_data["makeup"],
            "garment": garments[var_idx % len(garments)],
            "interior": interiors[var_idx % len(interiors)],
            "palette_key": palette_key
        }

    @classmethod
    def build_master_analog_prompt(
        cls,
        subject: str,
        environment: str,
        surface: str,
        background: str,
        foreground_anchor: str,
        camera_optics: Dict[str, str],
        lighting_anchor: str,
        color_rhyme: Dict[str, str],
        is_human: bool = False,
        rag_brand_anchors: str = "",
        optics_extra: str = "",
        scene_type: Optional[str] = None
    ) -> str:
        """
        Обратная совместимость: делегирует в современный QwenPromptAssembler.
        """
        return QwenPromptAssembler.build(
            subject=subject,
            environment=environment,
            surface=surface,
            background=background,
            foreground_anchor=foreground_anchor,
            camera_optics=camera_optics,
            lighting_anchor=lighting_anchor,
            color_rhyme=color_rhyme,
            is_human=is_human,
            rag_brand_anchors=rag_brand_anchors,
            optics_extra=optics_extra,
            scene_type=scene_type
        )

class QwenPromptAssembler:
    """
    Генератор промптов нового поколения под мультимодальную модель Qwen-Image 2512 (Qwen-2.5-VL 7B text encoder).
    
    Принципы Qwen-Image 2512:
    1. Связный естественный язык (Natural English Sentences) вместо набора тегов (comma-separated tag salad).
    2. Шестикомпонентная формула:
       Промпт = Субъект + Мимика/Поза + Одежда/Материалы + Окружение/Сцена + Свет/Атмосфера + Оптика/Камера
    3. Синтаксическая привязка атрибутов (Adjective-Noun Binding) через синтагмы предложения.
    4. Отсутствие конфликта альтернатив / суперпозиции (no 'or', 'either', 'maybe').
    5. Четкая пространственная локализация ('in the foreground', 'holding in hands', 'behind').
    6. Выделение текста в строгие двойные кавычки ("TEXT") с явным указанием объекта-носителя.
    7. Рекомендации параметров сэмплинга: CFG 3.0-3.5 (люди/кожа), 4.0-5.0 (продукты/пейзажи), ModelSamplingAuraFlow shift=3.10.
    """

    @classmethod
    def clean_tags_to_natural_text(cls, text: str) -> str:
        """
        Преобразует устаревшие теги SDXL с весами (напр. '(text:1.2)') в чистый связный английский текст.
        Устраняет суперпозиции (or/either) и чистит лишние знаки.
        """
        if not text:
            return ""
        # 1. Убираем синтаксис весов ComfyUI/A1111: (phrase:1.25) -> phrase
        cleaned = re.sub(r'\(([^:]+?)(?::\d+(?:\.\d+)?)?\)', r'\1', text)
        # 2. Убираем двойные скобки если остались
        cleaned = re.sub(r'[\(\)]', '', cleaned)
        # 3. Нормализация суперпозиций и неопределенностей
        cleaned = re.sub(r'\b(either|maybe)\b', '', cleaned, flags=re.IGNORECASE)
        # 4. Нормализация кавычек в строгие двойные прямые кавычки ""
        cleaned = re.sub(r'[«»“”„"]', '"', cleaned)
        # 5. Очистка двойных пробелов и запятых
        cleaned = re.sub(r'\s*,\s*', ', ', cleaned)
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        cleaned = re.sub(r'^,\s*', '', cleaned)
        cleaned = re.sub(r',\s*$', '', cleaned)
        return cleaned

    @classmethod
    def get_sampling_config(cls, scene_type: str = "general") -> Dict[str, Any]:
        """
        Оптимальные параметры генерации для Qwen-Image 2512 в ComfyUI.
        """
        if scene_type in {"portrait", "human", "lifestyle", "beauty"}:
            cfg = 3.2
            steps = 35
        elif scene_type in {"text", "typography", "signage", "poster"}:
            cfg = 6.0
            steps = 50
        elif scene_type in {"product", "culinary", "still_life"}:
            cfg = 4.5
            steps = 40
        else:
            cfg = 4.0
            steps = 35

        return {
            "cfg": cfg,
            "steps": steps,
            "sampler_name": "euler",
            "scheduler": "normal",
            "model_sampling_auraflow_shift": 3.10,
            "vae_tile_size": 512,
            "vae_tile_overlap": 64,
            "lora_real_skin_fix_max_weight": 0.85,
            "lora_lightning_steps": 4
        }

    @classmethod
    def get_negative_prompt(cls, scene_type: str = "general") -> str:
        """
        Формирует лаконичный и точный Negative Prompt по стандартам Qwen-Image 2512.
        Включает защиту от малинового румянца, пластикового тела, инверсии резкости фона и галлюцинаций.
        """
        base_negative = [
            "blurry", "low quality", "pixelated", "distorted",
            "watermark", "text overlay", "signature",
            "oversaturated", "artificial", "plastic-looking", "3D render", "CGI", "cgi", "cartoon", "anime"
        ]
        if scene_type in {"portrait", "human", "beauty", "lifestyle"}:
            base_negative.extend([
                "smooth plastic skin", "airbrushed face", "plastic chest skin", "airbrushed body", "blurry decollete",
                "bright pink blush", "intense rosy cheeks", "sunburn", "clown makeup", "painted blush", "rosacea", "unnatural cheek redness",
                "extra fingers", "deformed hands", "mutated hands", "fused fingers", "missing phalanges", "unnatural proportions",
                "stiff wire-like hair", "cross-eyed", "wandering gaze", "asymmetrical pupils",
                "same face syndrome", "identical faces", "mannequin", "wax figure",
                "sharp detailed background", "background noise", "floating objects", "deformed furniture", "deformed wall sockets", "disconnected wires"
            ])
        elif scene_type in {"product", "culinary", "still_life"}:
            base_negative.extend([
                "unrealistic reflections", "fake materials", "poor lighting",
                "artificial repetitive pattern", "out of place objects",
                "sharp detailed background", "floating objects"
            ])
        elif scene_type in {"text", "poster", "signage"}:
            base_negative.extend([
                "misspelled text", "garbled letters", "unreadable font", "gibberish text", "blurry typography", "double letters"
            ])
        return ", ".join(base_negative)

    @classmethod
    def build(
        cls,
        subject: str,
        environment: str,
        surface: str,
        background: str,
        foreground_anchor: str,
        camera_optics: Dict[str, str],
        lighting_anchor: str,
        color_rhyme: Dict[str, str],
        is_human: bool = False,
        rag_brand_anchors: str = "",
        optics_extra: str = "",
        scene_type: Optional[str] = None
    ) -> str:
        """
        Сборка 6-компонентного структурированного промпта на естественном английском языке:
        Промпт = Субъект + Мимика/Поза + Одежда/Материал + Окружение + Свет/Атмосфера + Камера/Оптика
        """
        subj_clean = cls.clean_tags_to_natural_text(subject)
        env_clean = cls.clean_tags_to_natural_text(environment)
        surf_clean = cls.clean_tags_to_natural_text(surface)
        bg_clean = cls.clean_tags_to_natural_text(background)
        fg_clean = cls.clean_tags_to_natural_text(foreground_anchor)
        rag_clean = cls.clean_tags_to_natural_text(rag_brand_anchors)
        light_clean = cls.clean_tags_to_natural_text(lighting_anchor)
        optics_extra_clean = cls.clean_tags_to_natural_text(optics_extra)

        lens = camera_optics.get("lens", "35mm prime lens")
        dof = camera_optics.get("dof", "natural optical depth of field")
        perspective = camera_optics.get("perspective", "candid eye-level perspective")

        interior_rhyme = color_rhyme.get("interior", "")
        garment_rhyme = color_rhyme.get("garment", "")

        sentences = []

        if is_human:
            # 1. Субъект, мимика, поза, одежда
            rag_part = f", {rag_clean.lstrip(', ')}" if rag_clean else ""
            garment_part = f", wearing {garment_rhyme}" if garment_rhyme else ""
            sentences.append(f"A candid photograph of {subj_clean}{rag_part}{garment_part}.")

            # 2. Окружение, глубина и передний план
            fg_part = f"In the foreground, {fg_clean} frames the scene. " if fg_clean else ""
            sentences.append(f"{fg_part}The subject is positioned in {env_clean} on {surf_clean}, with {bg_clean} and {interior_rhyme} in soft background.")

            # 3. Свет и атмосфера
            sentences.append(f"The scene is illuminated by {light_clean}, casting soft natural directional micro-shadows with realistic room contrast.")

            # 4. Оптика, камера и текстура (без CGI / пластика)
            hair_and_skin = "smooth neatly styled hair strands with natural soft shine, consistent detailed authentic human skin texture across face neck and shoulders with natural micro-pores, subtle neutral skin tone without harsh redness"
            extra_part = f"{optics_extra_clean}, " if optics_extra_clean else ""
            sentences.append(f"Captured with {lens} from a {perspective} with {dof}, featuring {extra_part}{hair_and_skin}, authentic human gaze, unedited snapshot clarity, zero CGI.")
        else:
            # Предметная съемка / Еда / Животные / Пейзаж
            rag_part = f", {rag_clean.lstrip(', ')}" if rag_clean else ""
            sentences.append(f"A commercial photograph of {subj_clean}{rag_part}.")

            fg_part = f"In the foreground, {fg_clean} creates layered depth. " if fg_clean else ""
            sentences.append(f"{fg_part}The subject rests on {surf_clean} in {env_clean}, surrounded by {bg_clean} and {interior_rhyme}.")

            sentences.append(f"Bathed in {light_clean}, creating authentic volumetric light falloff and rich natural shadows.")

            extra_part = f"{optics_extra_clean}, " if optics_extra_clean else ""
            sentences.append(f"Shot on {lens} with {dof}, showcasing {extra_part}tactile material micro-textures, genuine physical reflections, sharp focus, zero CGI.")

        return " ".join(sentences)


class CinematographyDirector:
    """
    Интеллектуальный режиссер-постановщик и арт-директор:
    Применяет профессиональные законы кинокомпозиции, световых схем,
    колористики и психологии восприятия кадра.
    """

    LIGHTING_SCHEMES = {
        "low_key": "Low-key directional moody light with natural deep shadows and high contrast, dark ambient background, dramatic light falloff",
        "high_key": "Natural daylight illumination with directional sunbeams and deep defined micro-shadows, stark contrast",
        "chiaroscuro": "Strong directional key side lighting casting deep chiaroscuro shadows, high contrast falloff, un-lifted rich dark shadows",
        "silhouette": "Natural backlit contour against bright background, deep rich blacks",
        "gobo_shadows": "Natural window shadow patterns across the scene with crisp shadow edges and deep contrast",
        "rim_backlight": "Strong directional backlighting contour with stark contrast and un-lifted deep shadows",
        "rembrandt": "Dramatic strong directional side light, Rembrandt lighting with deep micro-shadows, stark contrast and dramatic light falloff",
        "paramount": "Directional overhead light defining facial planes with deep chin and cheek micro-shadows",
        "spotlight": "Warm direct task light illuminating the subject with dramatic light falloff into darkness",
        "lens_flare": "Subtle optical lens flare, organic light leak with deep contrast preservation",
        "soft_diffused": "Directional morning window daylight with natural shadow falloff and deep micro-shadows",
        "dual_office": "Subtle dual lighting with a warm 3000K key lamp glow on subject contrasting with cool 5500K ambient daylight from background windows, stark light falloff",
        "overcast_diffused": "Directional daylight with rich micro-contrast and deep shadows, authentic outdoor depth",
        "warm_pendant": "Hanging pendant filament lamp casting strong directional warm key light with deep ambient shadows and dramatic falloff",
        "hard_chiaroscuro": "Strong single directional warm key light casting deep dramatic chiaroscuro shadows with stark contrast falloff and rich blacks",
        "golden_hour_rim": "Warm directional golden hour key light casting dramatic rim light and deep contrasted shadows",
        "editorial_studio": "Single directional key light from upper-left with deep shadow falloff, stark contrast, un-lifted micro-shadows"
    }

    COLOR_HARMONIES = {
        "teal_orange": "warm foreground key lighting contrasting with subtle cool background ambient light, complementary color temperature separation",
        "warm_analogous": "warm directional key light with deep organic shadows, subtle cool ambient air in background",
        "complementary": "warm foreground subject lighting contrasting with cool background ambient tones",
        "muted_editorial": "natural authentic color reproduction, stark contrast between warm key highlights and cool shadowed background",
        "monochrome": "natural monochrome analog film tones with deep rich blacks and high contrast"
    }

    COMPOSITION_GEOMETRIES = {
        "rule_of_thirds": "Rule of thirds framing with subject placed on natural focal points",
        "symmetry": "Balanced centered framing",
        "leading_lines": "Natural leading lines through the environment",
        "framing": "Natural framing through environmental elements",
        "diagonal_framing": "Diagonal dynamic leading lines across the frame with natural organic foreground framing element on one side creating rich three-dimensional spatial depth and an accent color sliver in the opposite corner",
        "negative_space": "Uncluttered composition with natural negative space",
        "triangles": "Natural triangular arrangement of scene elements",
        "golden_spiral": "Natural flowing compositional curve guiding the eye"
    }

    PERSPECTIVES = {
        "diagonal_organic_framing": "slightly elevated diagonal perspective looking down at the subject with standard prime lens, shallow depth of field with vibrant organic green foliage partially framing the frame from the left in soft blur, creamy background bokeh with subtle accent color in upper corner",
        "bokeh_shallow": "smooth progressive focal falloff, authentic optical lens blur, f/1.2 depth of field, blurred object in extreme foreground creating layered 3D depth, creamy natural background falloff",
        "low_angle_heroic": "slightly low-angle perspective, smooth progressive optical focal falloff, f/1.2 lens blur",
        "tabletop_commercial": "45-degree angle tabletop view, smooth progressive optical focal falloff, f/1.4 lens blur, blurred foreground edge framing the subject",
        "candid_eye_level": "35mm prime lens, authentic progressive optical lens blur, f/1.2 depth of field, layered foreground-to-background spatial depth",
        "culinary_macro_eyelevel": "35mm close-up macro lens, f/1.2 smooth optical focal falloff, blurred object in extreme foreground framing the subject, creamy layered background bokeh",
        "culinary_flatlay_topdown": "direct top-down 90-degree overhead perspective with rich micro-shadows and depth",
        "culinary_45_slice": "45-degree angled perspective with smooth optical focal falloff, f/1.4 depth of field, tactile foreground depth",
        "oversized_hero": "centered medium shot framing hero subject, f/1.2 smooth progressive focal falloff, blurred foreground bokeh",
        "candid_counter": "medium eye-level shot, candid interaction across counter, progressive optical lens blur with depth",
        "layered_artisan_table": "layered multi-tiered display, blurred object in extreme foreground, tack-sharp subject, creamy background falloff",
        "contemplative_profile": "medium close-up profile shot, smooth progressive focal falloff, f/1.2 depth of field with creamy bokeh",
        "active_desk_focus": "elevated side-angle desk perspective, blurred foreground coffee cup edge creating layered depth, f/1.2 optical falloff",
        "macro_nail_close_up": "tight macro lens, smooth progressive optical focal falloff, f/1.4 shallow depth of field, blurred foreground fabric edge creating physical layered depth, creamy atmospheric background falloff"
    }

    NICHE_EN_MAP = {
        "martech": "innovative AI MarTech software platform and digital marketing analytics",
        "маркетинг": "modern AI marketing automation and growth analytics platform",
        "saas": "cutting-edge cloud SaaS software and AI intelligence enterprise",
        "it": "modern high-tech IT software and artificial intelligence enterprise",
        "ии": "modern artificial intelligence and machine learning technology",
        "электроник": "electronics and embedded IoT hardware",
        "кофейн": "craft specialty coffee shop",
        "кофе": "specialty coffee and espresso bar",
        "ресторан": "fine dining gourmet restaurant",
        "пекарн": "artisan bakery and pastry shop",
        "кондитерск": "pastry confectionery and dessert boutique",
        "детейлинг": "luxury automotive detailing and ceramic studio",
        "автомобил": "modern automotive showroom and engineering workshop",
        "автосервис": "professional auto repair and diagnostic bay",
        "мебел": "high-end designer handcrafted furniture",
        "стоматолог": "modern pristine dental clinic",
        "медицин": "modern healthcare and wellness clinic",
        "фитнес": "state-of-the-art loft fitness gym",
        "спорт": "athletic sports and workout lifestyle",
        "ремонт": "architectural interior renovation and design",
        "недвижим": "luxury contemporary real estate",
        "юриспруд": "prestigious corporate law firm",
        "бьюти": "modern sunlit beauty and aesthetics salon",
        "зоо": "cozy pet boutique and veterinary care",
        "животн": "warm cozy pet lifestyle setting with beloved animals",
        "кот": "warm cozy sunlit living room with charming playful domestic cats",
        "собак": "vibrant outdoor park with joyful well-trained dogs",
        "религи": "historic sacred cultural architecture with stained glass and candle glow",
        "церков": "peaceful historic cathedral with serene architectural beauty",
        "цвет": "charming Parisian floral boutique and botanical atelier",
        "флорист": "artisan floral design studio and botanical boutique",
        "букет": "luxury artisan flower atelier with fresh dewy blooms",
        "посуд": "high-end artisanal ceramic, fine porcelain and tableware boutique",
        "фарфор": "luxury fine porcelain, bone china and handcrafted ceramic salon",
        "керамик": "artisan pottery and handcrafted ceramic studio",
        "маникюр": "luxury nail art and aesthetic manicure salon",
        "ногти": "high-end nail design and aesthetic manicure studio",
        "бизнес": "contemporary creative professional studio",
        "услуг": "modern professional service workspace"
    }

    @classmethod
    def compose_cinematic_prompt(
        cls,
        topic: str,
        niche: str = "бизнес",
        brand_colors: Optional[List[str]] = None,
        variation_index: int = 0,
        routing: Optional[Any] = None,
        brand_props: Optional[List[str]] = None,
        brand_profile: Optional[Dict[str, Any]] = None
    ) -> Dict[str, str]:
        """
        Генерирует высокохудожественный промпт для ComfyUI Realism 2.0
        с учетом механизма контролируемой энтропии (Controlled Variance),
        RAG-якорей бренда и ротации оптики/ракурсов.
        """
        topic_lower = topic.lower()
        niche_lower = (niche or "").lower()
        var = variation_index % 4

        # Предотвращение Semantic Bleed: если в теме указана конкретная предметная область, она имеет наивысший приоритет
        domain_priority = [
            # 1. Ногти, маникюр и бьюти (макро)
            "маникюр", "ногти", "гель-лак", "нейл", "ногот", "педикюр",
            # 2. Кофейня, латте-арт, бариста и напитки (ДО посуды/керамики!)
            "капучин", "латте", "кофе", "эспрессо", "барист", "круассан",
            # 3. Породы животных и питомцы
            "корги", "шпиц", "померан", "сиба", "хаски", "овчарк", "щенок", "щенк", "собак",
            "кот", "кошк", "котик", "котен", "котён",
            # 4. Гастрономия, блюда и стейки
            "стейк", "рибай", "шеф", "кулинар", "шаурм", "бургер", "пицц", "суши", "ролл",
            # 5. Десерты и выпечка
            "синнабон", "булочк", "печень", "торт", "ганаш", "чизкейк", "кулич", "пасх", "десерт", "пекарн",
            # 6. Флористика
            "флорист", "букет", "пион", "эвкалипт", "цвет",
            # 7. IT-ночь, терминал, мегаполис
            "терминал", "ide", "ночн", "ночь", "ночью", "мегаполис", "небоскреб", "высотк", "балкон",
            # 8. Посуда и керамика (ТОЛЬКО если это не кофе)
            "гончар", "глинян", "фарфор", "посуд", "керамик",
            # 9. Наружная реклама и постеры
            "постер", "плакат", "вывеск", "типографик", "билборд", "лайтбокс",
            # 10. Электроника и инженерия
            "esp32", "esp-32", "плата", "arduino", "микроконтроллер", "чип", "электроник",
            # 11. Общие бизнес-сферы
            "детейлинг", "стоматолог", "недвижим", "блокнот", "конспект", "постель",
            "разработчик", "программист", "it", "saas", "martech"
        ]
        effective_niche_key = None
        for k in domain_priority:
            if k in topic_lower:
                effective_niche_key = k
                break
        if not effective_niche_key:
            for k in domain_priority:
                if k in niche_lower:
                    effective_niche_key = k
                    break

        niche_en = cls.NICHE_EN_MAP.get(effective_niche_key, "professional commercial environment") if effective_niche_key else "professional commercial environment"

        # =========================================================================
        # ПИЛАР 1: АУТЕНТИЧНЫЙ МИР И СФЕРА ДЕЯТЕЛЬНОСТИ (Niche World-Building)
        # При перегенерации (var > 0) интерьер, окружение и реквизит циклически меняются!
        # =========================================================================
        niche_environments = {
            "martech": [
                {"setting": "sleek contemporary tech startup headquarters with glass partition walls and panoramic city skyline view", "props": "ultra-thin laptop with glowing analytics dashboard, minimal glass table, modern architectural daylight"},
                {"setting": "modern sunlit open-plan digital innovation lab with minimalist Scandinavian oak desks", "props": "sleek monitors displaying real-time AI conversion charts, potted indoor plants, bright productive ambiance"},
                {"setting": "futuristic executive tech boardroom at golden hour with floor-to-ceiling panoramic glass", "props": "clean aluminum tablet, modern data visualization, elite tech prestige and growth"},
                {"setting": "bright creative IT workspace with warm ambient pendant lighting and whiteboards", "props": "ergonomic workstation, high-tech SaaS dashboards, breakthrough clarity and success"}
            ],
            "it": [
                {"setting": "modern high-tech software engineering office with polished wooden desk and black gooseneck desk lamp casting a warm focused pool of light", "props": "sleek silver laptop, stack of black notebooks with silver pen, smartphone beside printed charts, white ceramic coffee mug, natural daylight from glass partitions in background"},
                {"setting": "contemporary tech office corner, warm beige fabric floor lamp casting soft ambient shadows against beige wall", "props": "black laptop, smartphone on wooden table, deep contemplation atmosphere"},
                {"setting": "executive analytical workstation with ergonomic black mesh chair", "props": "large curved monitor displaying glowing orange and white dynamic data charts, warm circular desk lamp creating dramatic ambient glow"},
                {"setting": "dimly lit late-night corporate tech office with floor-to-ceiling glass windows", "props": "silver laptop on desk, whiteboard with handwritten charts and sticky notes in soft background, cool blue-gray ambient tones"}
            ],
            "религия": [
                {"setting": "majestic historic cathedral interior with towering stone arches, golden gilded altar details, soft sunbeams filtering through ancient stained glass windows", "props": "glowing beeswax candles in soft chiaroscuro, natural linen cloth, delicate incense haze, tranquil sacred stillness"},
                {"setting": "bright sunlit artisan monastery kitchen courtyard with natural morning daylight, rustic carved wooden table", "props": "fresh spring pussy willow branches, hand-woven natural linen napkin, warm soft window illumination"},
                {"setting": "intimate atmospheric evening chapel with warm glowing candle bokeh and rich architectural textures", "props": "aged brass candlestick, delicate embroidered tablecloth, timeless serenity"},
                {"setting": "festive spring celebration table by an arched stone window overlooking morning sky", "props": "natural terracotta dishware, dried floral accents, peaceful reverent warmth"}
            ],
            "животные": [
                {"setting": "cozy sunlit living room with natural herringbone hardwood floor and soft textured cream knit throw blanket", "props": "delicate dust motes floating in golden afternoon sunbeams, pure domestic comfort"},
                {"setting": "warm sun-drenched living room window nook with natural linen curtains", "props": "soft woven blanket, indoor green plants in background bokeh, peaceful relaxation"},
                {"setting": "modern minimalist living space with light oak flooring and warm rug", "props": "afternoon sunlight patches, serene cozy home haven"},
                {"setting": "warm rustic living room with fireplace hearth", "props": "textured knitted wool blanket, cozy crackling warmth, ultimate comfort"}
            ],
            "зоо": [
                {"setting": "cozy sunlit living room with natural herringbone hardwood floor and soft textured cream knit throw blanket", "props": "delicate dust motes floating in golden afternoon sunbeams, pure domestic comfort"},
                {"setting": "warm sun-drenched living room window nook with natural linen curtains", "props": "soft woven blanket, indoor green plants in background bokeh, peaceful relaxation"},
                {"setting": "modern minimalist living space with light oak flooring and warm rug", "props": "afternoon sunlight patches, serene cozy home haven"},
                {"setting": "warm rustic living room with fireplace hearth", "props": "textured knitted wool blanket, cozy crackling warmth, ultimate comfort"}
            ],
            "кофейня": [
                {"setting": "sunlit rustic specialty craft coffee shop, polished vintage oak counter, soft morning street view in background bokeh", "props": "artisan ceramic cup, delicate rising fragrant steam, roasted coffee bean jar, warm brass accents"},
                {"setting": "minimalist luxury travertine marble counter with clean porcelain ware and fresh botanical eucalyptus", "props": "crisp morning studio daylight, glossy espresso machine reflection, refined modern aesthetic"},
                {"setting": "charming Parisian outdoor cafe bistro table with dark wrought iron accents in golden morning sun", "props": "crumbled buttery croissant flakes, fresh daily newspaper, warm European morning atmosphere"},
                {"setting": "warm atmospheric coffee roastery studio with burlap coffee sacks and glowing pendant lights", "props": "vintage brass coffee scale, roasted beans scattering, rich tactile aroma"}
            ],
            "пекарня": [
                {"setting": "traditional European rustic market stall covered by cream-colored canvas awning, brick building and open field in background under overcast sky", "props": "draped deep green cloth, abundant display of artisanal cheese wheels with white rinds, crumbly wedges, ripe red tomatoes in baskets, wooden crates overflowing with crusty sourdough baguettes"},
                {"setting": "cozy artisan food hall market stall with rustic exposed wooden beams and warm pendant lights", "props": "wooden cutting boards with artisanal cheeses, glass jars of honey and fruit preserves with handwritten labels, fresh chives, linen runner, small chalkboard price tags"},
                {"setting": "artisan French pastry boutique, warm marble countertop with scattered fine flour dust and toasted almond flakes", "props": "flaky golden crust, fresh spring berry garnish, vintage baker's wooden paddle in soft focus"},
                {"setting": "dimly lit professional gourmet restaurant kitchen with dark wooden shelves of wine bottles", "props": "chef knife with black handle slicing deep-red meat on rustic wooden board, stack of clean white ceramic plates, stainless steel pot in Rembrandt chiaroscuro"}
            ],
            "десерт": [
                {"setting": "artisan pastry workshop with dark slate slab and rustic wooden accents", "props": "glossy molten chocolate ganache cascading over layered cake, ripe halved strawberries, fine dark chocolate curls"},
                {"setting": "rustic bakery table covered with textured frayed beige linen runner", "props": "golden-brown cinnamon rolls on circular wooden board, whole dark star anise pods, whole cinnamon sticks, powdered sugar dusting"},
                {"setting": "cozy gourmet bakery packaging counter with natural kraft paper and brown ribbon", "props": "gourmet cookie gift box with crinkled parchment paper, assorted chocolate chunk and walnut cookies"},
                {"setting": "weathered wooden table with rich natural grain and knots", "props": "circular bark-edged wooden serving board, freshly baked chocolate chip cookies, steaming ceramic mug of hot coffee with delicate vapor curls"}
            ],
            "постер": [
                {"setting": "modern urban interior with weathered red brick wall and natural mortar lines", "props": "minimalist dark framed poster with sharp dark-gray typography on white, warm overhead spotlight, natural wood door trim"},
                {"setting": "classical architectural gallery arcade with stone arches and high vaulted ceiling", "props": "hanging circular illuminated lightbox sign with warm golden backlighting, classical stone pillars"},
                {"setting": "corner street facade of a multi-story contemporary concrete and glass building", "props": "massive architectural outdoor billboard, clean sky background, bold high-contrast graphic branding"},
                {"setting": "industrial modern loft staircase with dark steel risers and steps", "props": "crisp white typography stenciled on metal steps, directional side lighting, tactile raw steel texture"}
            ],
            "электроника": [
                {"setting": "clean high-tech electronics engineering laboratory, professional blue anti-static silicone soldering mat", "props": "precision tweezers, fine copper circuit traces, gold-plated header pins, micro-components in crisp macro focus"},
                {"setting": "modern minimalist R&D wooden workbench with glowing digital oscilloscope and schematic blueprints in soft focus", "props": "braided USB cables, precision multimeter probes, crisp engineering lighting"},
                {"setting": "top-down architectural tech workspace with anodized aluminum plates and brass precision calipers", "props": "clean circuit board layout, microchip silicon reflections, high-precision layout"},
                {"setting": "atmospheric prototyping studio with soft ambient amber and cyan LED edge illumination", "props": "breadboards, neatly organized jumper wires, cutting-edge innovation atmosphere"}
            ],
            "детейлинг": [
                {"setting": "pristine modern luxury auto detailing studio, glowing linear ceiling LED strip lights reflecting on deep paintwork", "props": "mirror-like gloss, hydrophobic micro water beads, ultra-plush microfiber towel in soft background"},
                {"setting": "high-end showroom floor at golden hour, polished epoxy reflective floor", "props": "dramatic rim lighting on car curves, flawless metallic paint depth, pristine prestige"},
                {"setting": "clean engineering tuning bay with professional modular tool cabinets in blurred background", "props": "ceramic coating applicator block, crisp reflection of overhead studio softbox"},
                {"setting": "outdoor scenic mountain lookout at golden sunset, clean asphalt reflection", "props": "warm evening sun flare, glistening clean aerodynamic bodywork"}
            ],
            "стоматология": [
                {"setting": "ultramodern sunlit aesthetic dental clinic, calm reassuring atmosphere with warm travertine marble and glass accents", "props": "flawless hygiene, soft diffused glare-free illumination, pure comfort and relief"},
                {"setting": "luxury dental wellness studio with floor-to-ceiling panoramic window and indoor bamboo garden", "props": "warm natural daylight, comfortable ergonomical setting, genuine peace of mind"},
                {"setting": "bright minimalist consultation office with contemporary Scandinavian wood finishes", "props": "crystal clear smile models, calming natural aroma, high-end medical excellence"},
                {"setting": "spacious private aesthetic room with soft warm indirect architectural lighting", "props": "pristine comfort, soothing atmosphere, trust and care"}
            ],
            "недвижимость": [
                {"setting": "spacious sun-drenched newly renovated open-plan living room with floor-to-ceiling panoramic windows overlooking evening sky", "props": "designer minimalist furniture, warm architectural ambient lighting, the feeling of dream home security"},
                {"setting": "contemporary luxury kitchen and dining area with monolithic quartz island and designer pendant lights", "props": "fresh fruit bowl, sunbeams piercing the room, elite architectural lifestyle"},
                {"setting": "airy sunlit master bedroom with herringbone oak flooring and sheer linen curtains fluttering in breeze", "props": "crisp white bedding, warm morning sunlight, serene sanctuary"},
                {"setting": "panoramic sunset terrace lounge with comfortable designer armchairs overlooking vibrant city lights", "props": "warm twilight sky, ambient recessed deck lighting, prestige and triumph"}
            ],
            "цвет": [
                {"setting": "entrance of a modern flower boutique with weathered red brick wall, textured white mortar, and dark wooden doorway", "props": "massive overflowing wicker basket packed with pink peonies, magenta dahlias, peach carnations, baby's breath, cascading green foliage, wet reflective concrete pavement"},
                {"setting": "picturesque cobblestone street corner with historic architecture in soft overcast daylight", "props": "large natural wicker basket overflowing with crisp white daisies and lush green foliage, beige trench coat and boots aesthetic"},
                {"setting": "sunlit Parisian floral boutique with rustic wooden worktables and arched European windows", "props": "fresh dewy pink peonies, eucalyptus stems, galvanized metal flower buckets, garden shears and ribbon rolls in soft focus"},
                {"setting": "modern minimalist floral atelier with concrete surfaces and clean glass vases", "props": "exquisite white hydrangeas and garden roses, soft natural window daylight, botanical elegance"}
            ],
            "посуд": [
                {"setting": "elegant sunlit artisanal ceramic and tableware boutique with warm open oak display shelves", "props": "handcrafted matte ceramic bowls, delicate bone porcelain plates, organic textured earthenware in soft warm ambient light"},
                {"setting": "minimalist Scandinavian tableware showroom with travertine stone pedestals", "props": "fine porcelain tea set with subtle glaze cracks, linen tablecloth in soft bokeh, timeless craftsmanship"},
                {"setting": "warm luxury porcelain gallery with soft directional gallery spotlights", "props": "exquisite bone china teacups, glazed ceramic vases, elegant refined lifestyle aesthetic"},
                {"setting": "charming European artisan tableware boutique counter with natural morning daylight", "props": "stacked handcrafted ceramic dinnerware, wooden serving spoons, pure tactile authenticity"}
            ],
            "ритейл": [
                {"setting": "modern cozy specialty grocery store with exposed brick wall, black metal shelving and hanging pendant filament bulbs", "props": "dark speckled granite checkout counter, touchscreen POS register, snacks in neat packaging, small potted green plant in metallic pot"},
                {"setting": "contemporary boutique checkout area with warm wooden accents and soft overhead spotlighting", "props": "branded canvas tote bag, organic snack packages on counter, friendly service atmosphere"},
                {"setting": "artisan concept store with warm oak display tables and minimalist signage", "props": "handcrafted goods with minimalist labels, receipt printer, warm inviting customer experience"},
                {"setting": "sunlit specialty gourmet market counter with glass display cases", "props": "freshly packaged artisan goods, chalkboard menu board, warm inviting light"}
            ],
            "бьюти": [
                {"setting": "modern sunlit beauty salon with warm travertine surfaces and fresh botanical accents", "props": "soft indirect lighting, clean mirrors, luxurious calm atmosphere"},
                {"setting": "cozy aesthetic studio with warm neutral beige background bokeh", "props": "textured cream chunky-knit fabric, delicate dried botanicals, soft ambient glow"},
                {"setting": "chic minimalist aesthetic salon with soft daylight", "props": "warm oak table, delicate linen cloth, refined modern elegance"},
                {"setting": "editorial studio setting with dramatic key lighting and deep shadow falloff", "props": "warm amber ambient accents, high-contrast textures, rich depth"}
            ],
            "маникюр": [
                {"setting": "cozy aesthetic nail studio with textured cream chunky-knit fabric in foreground", "props": "delicate dried autumn maple leaves, soft neutral beige background bokeh"},
                {"setting": "warm ambient studio lounge with soft circular golden bokeh lights", "props": "warm ceramic cup, soft textured knitwear, warm intimate glow"},
                {"setting": "minimalist luxury nail bar with warm oak surface and soft diffused daylight", "props": "ribbed knit sweater sleeve cuff, rich tactile textures"},
                {"setting": "chic modern beauty salon with soft indirect lighting", "props": "natural linen cloth, delicate seasonal accents, elegant ambiance"}
            ]
        }

        # Выбираем пул окружений по нише или дефолтный
        env_pool = None
        for k, pool in niche_environments.items():
            if k in niche_lower or k in topic_lower:
                env_pool = pool
                break

        if routing and hasattr(routing, "visual_anchor") and routing.visual_anchor:
            va = routing.visual_anchor
            niche_universe = {
                "setting": va.environment_preset.replace("_", " "),
                "props": va.crossover_props or "authentic natural details"
            }
        elif env_pool:
            niche_universe = env_pool[var]
        else:
            default_variations = [
                {"setting": f"aesthetic contemporary {niche_en} setting", "props": "tactile authentic materials and natural atmospheric depth"},
                {"setting": f"bright minimalist sunlit {niche_en} environment with warm wood accents", "props": "clean architectural lines, fresh botanical touches, soft natural lighting"},
                {"setting": f"warm atmospheric {niche_en} studio with soft evening ambient glow and rich textures", "props": "subtle textured details, sophisticated depth"},
                {"setting": f"spacious Scandinavian loft {niche_en} with expansive windows and golden daylight", "props": "organic textures, breathable negative space, effortless elegance"}
            ]
            niche_universe = default_variations[var]

        # =========================================================================
        # 1. АНАЛИЗ СЮЖЕТА, ВЫБОР РАКУРСА И СВЕТОВОЙ СХЕМЫ (С динамической ротацией)
        # =========================================================================
        perspectives_culinary = ["culinary_macro_eyelevel", "culinary_flatlay_topdown", "culinary_45_slice", "bokeh_shallow"]
        lighting_rotation = ["high_key", "soft_diffused", "rim_backlight", "gobo_shadows"]
        color_rotation = ["warm_analogous", "muted_editorial", "teal_orange", "warm_analogous"]
        comp_rotation = ["golden_spiral", "symmetry", "rule_of_thirds", "leading_lines"]

        if any(w in topic_lower for w in ["вид сверху", "сверху", "flatlay", "флэтлей", "ракурс сверху"]):
            light_key = "soft_diffused"
            color_key = "warm_analogous"
            comp_key = "symmetry"
            persp_key = "culinary_flatlay_topdown"
        elif any(w in topic_lower for w in ["торт", "пирог", "кусочек", "срез", "разрез", "начинк", "слои", "трюфель", "чизкейк"]):
            light_key = lighting_rotation[var]
            color_key = color_rotation[var]
            comp_key = comp_rotation[var]
            persp_key = "culinary_45_slice" if var % 2 == 0 else "culinary_macro_eyelevel"
        elif any(w in topic_lower for w in ["кулич", "пасх", "куличи", "панеттоне", "кекс", "капкейк"]):
            # При перегенерации кулича чередуем ракурсы: макро 30° -> flatlay 90° -> 45° срез
            persp_key = perspectives_culinary[var]
            light_key = lighting_rotation[var]
            color_key = color_rotation[var]
            comp_key = comp_rotation[var]
        elif "закат" in topic_lower or "пляж" in topic_lower or "вечер" in topic_lower:
            light_key = "rim_backlight"
            color_key = "teal_orange"
            comp_key = "rule_of_thirds"
            persp_key = "bokeh_shallow"
        elif "неон" in topic_lower or "приват" in topic_lower or "клуб" in topic_lower or "бар" in topic_lower:
            light_key = "low_key"
            color_key = "complementary"
            comp_key = "negative_space"
            persp_key = "candid_eye_level"
        elif "массаж" in topic_lower or "spa" in topic_lower or "спа" in topic_lower or "камн" in topic_lower:
            light_key = "soft_diffused"
            color_key = "warm_analogous"
            comp_key = "framing"
            persp_key = "bokeh_shallow"
        elif any(w in niche_lower for w in ["martech", "маркетинг", "saas", "it", "ии"]) or any(w in topic_lower for w in ["martech", "маркетинг", "saas", "ии-платформ", "автоматизац", "генеративн", "нейросеть"]):
            light_key = lighting_rotation[var]
            color_key = "muted_editorial" if var % 2 == 0 else "teal_orange"
            comp_key = comp_rotation[var]
            persp_key = "candid_eye_level" if var % 2 == 0 else "bokeh_shallow"
        elif any(w in topic_lower for w in ["маникюр", "ногти", "гель-лак", "ногот", "nail", "manicure", "педикюр"]):
            light_key = "soft_diffused" if var % 2 == 0 else "warm_pendant"
            color_key = "warm_analogous"
            comp_key = "rule_of_thirds"
            persp_key = "macro_nail_close_up"
        elif any(w in topic_lower for w in ["десерт", "ролл", "выпечк", "кофе", "еда", "огурец", "плата", "esp", "электроник", "микроконтроллер", "турбин", "инструмент", "ювелир", "кольц", "косметик", "крем"]):
            light_key = lighting_rotation[var]
            color_key = color_rotation[var]
            comp_key = comp_rotation[var]
            persp_key = "tabletop_commercial" if var % 2 == 0 else "culinary_macro_eyelevel"
        elif any(w in topic_lower for w in ["флаг", "архитектур", "спорт", "фитнес"]):
            light_key = "rim_backlight"
            color_key = "teal_orange"
            comp_key = "triangles"
            persp_key = "low_angle_heroic"
        else:
            light_key = lighting_rotation[var]
            color_key = color_rotation[var]
            comp_key = comp_rotation[var]
            persp_key = "candid_eye_level" if var % 2 == 0 else "bokeh_shallow"

        # =========================================================================
        # ПИЛАР 2: РОЛЬ ПРОДУКТА И АРКА ЗРИТЕЛЯ (Product as Hero / Catalyst)
        # Приоритет отдан максимально специфичным предметным сущностям и макро-деталям
        # =========================================================================
        from skills.visual_knowledge_researcher import VisualKnowledgeResearcher
        visual_spec = VisualKnowledgeResearcher.research_visual_spec_sync(topic)

        holiday_aesthetic = InternalCalendarEngine.get_instance().get_holiday_aesthetic(topic, niche) if InternalCalendarEngine else None

        if any(w in topic_lower for w in ["маникюр", "ногти", "гель-лак", "нейл", "ногот", "педикюр", "nail", "manicure"]):
            curr_season = InternalCalendarEngine.get_instance().cached_context.get("season", "Осень") if InternalCalendarEngine else "Осень"
            seasonal_anchor = InternalCalendarEngine.get_instance().get_seasonal_tactile_anchor("beauty") if InternalCalendarEngine else {}

            if any(w in topic_lower for w in ["сапфир", "синий", "navy", "синем", "голубой"]):
                color_desc = "deep glossy sapphire-navy gel polish with delicate gold leaf foil accent flakes"
                lipstick_color = "matching deep berry-fuchsia"
            elif any(w in topic_lower for w in ["бордо", "марсал", "вишн", "burgundy"]):
                color_desc = "rich glossy deep burgundy wine gel polish with subtle mirror shine"
                lipstick_color = "matching matte burgundy"
            elif any(w in topic_lower for w in ["шоколад", "кофе", "brown", "коричнев"]):
                color_desc = "rich glossy warm chocolate-brown and creamy off-white tones with delicate hand-painted maple leaf art"
                lipstick_color = "warm nude-chocolate"
            elif any(w in topic_lower for w in ["фукси", "розов", "fuchsia", "pink"]):
                color_desc = "vibrant glossy fuchsia gel polish with high-shine mirror finish"
                lipstick_color = "bold matte fuchsia"
            elif any(w in topic_lower for w in ["нюд", "беж", "пастел", "nude", "френч", "french"]):
                color_desc = "natural French manicure with clean white tips and pale glossy base"
                lipstick_color = "delicate natural nude"
            elif any(w in topic_lower for w in ["терракот", "оранж", "карамел"]):
                color_desc = "warm autumn terracotta and caramel gloss finish with delicate botanical micro-line art"
                lipstick_color = "warm terracotta"
            else:
                color_desc = "rich elegant glossy gel polish with flawless mirror reflection and pristine cuticles"
                lipstick_color = "matching matte velvet"

            shape_desc = "soft square with rounded tips" if any(w in topic_lower for w in ["квадрат", "square"]) else "long elegant almond-shaped"

            # Сезонный и Праздничный физический якорь
            if holiday_aesthetic and holiday_aesthetic.get("hero_beauty") and holiday_aesthetic.get("match_type") == "keyword":
                seasonal_pose = holiday_aesthetic["hero_beauty"]
            elif curr_season == "Зима":
                seasonal_pose = f"macro close-up photography of elegantly manicured female hands in cozy cream knit sweater sleeves gently holding a rustic handmade snowball with glistening melting ice crystals, showcasing pristine {shape_desc} nails with {color_desc}, razor-sharp focus on glossy nail plates and neat cuticles, soft winter bokeh"
            elif curr_season == "Осень":
                seasonal_pose = f"close-up shot of an elegantly manicured hand with {shape_desc} nails featuring a cohesive autumnal theme, alternating rich deep brown base and creamy beige background with delicate hand-painted maple leaves in orange and amber with fine vein textures, {seasonal_anchor.get('prop', 'delicate ceramic vase with dried maple leaves in background')}"
            elif curr_season == "Весна":
                seasonal_pose = f"macro beauty photography of slender hands with {shape_desc} nails with {color_desc} delicately holding fresh dewy pussy willow branches with soft velvety buds, crisp morning studio daylight"
            else:
                seasonal_pose = f"macro commercial shot of manicured hand with {shape_desc} nails with {color_desc} resting on sunlit warm travertine stone surface with delicate palm leaf shadow play"

            nail_poses = [
                # Вариация 0: Diagonal Organic Framing (Эталонный Pinterest-архетип: диагональ, лист слева, микро-глиттер, акцент в углу)
                f"close-up diagonal commercial beauty shot of a hand with slender well-manicured fingers gently curved in a relaxed natural pose, showcasing fingernails in {shape_desc} shape with {color_desc}, middle finger featuring a delicate fine glitter dusting catching the light with subtle sparkle, natural soft human skin texture with faint lines and creases around knuckles and fingertips, hand positioned slightly diagonally across frame with thumb and pinky slightly out of focus, in the foreground to the left a vibrant green leaf with serrated edges and glossy surface partially frames the shot, background softly blurred off-white surface with faint circular indentation and a thin curved line suggesting modern ceramic decor, with a subtle sliver of bright warm yellow accent in the upper right corner",
                # Вариация 1: Editorial Hand-to-Face (Рука у лица, помада в тон, кольцо с сердцем)
                f"close-up beauty editorial portrait of a woman with luminous skin, lips painted in {lipstick_color} lipstick accentuating natural texture, her hand with {shape_desc} nails in {color_desc} resting gently against lower cheek and jawline, fingers slightly curved toward lips, delicate silver ring with an openwork heart adorning her ring finger, soft neutral gradient bokeh",
                # Вариация 2: In-Action Process (Мастер наносит кистью топ/лак, полотенце, решетка вытяжки)
                f"macro shot of a skilled manicurist's hands delicately applying a translucent glossy layer to a client's fingernail using a fine precision brush, manicurist's left hand holding client's index finger steady while right hand maneuvers brush with precision, client's hand resting on a soft plush white towel draped over a metal nail dust extractor tray with a grid pattern, showcasing {shape_desc} nails with {color_desc}, transparent bottle and nail file in soft blurred background",
                # Вариация 3: Сезонный / Праздничный предметный якорь
                seasonal_pose,
                # Вариация 4: Встречные руки сверху и снизу кадра (Взаимная симметрия)
                f"editorial beauty photography of two manicured hands entering the frame from opposite top and bottom angles with fingers fanned out in parallel symmetry meeting in center, ribbed sweater sleeves framing the frame from above and below, showcasing pristine {shape_desc} nails with {color_desc}",
                # Вариация 5: Классический лайфстайл (ладони скрещены на свитере)
                f"extreme macro close-up photography of slender well-manicured female hands gently crossed over a soft cream knit sweater, {shape_desc} shaped nails with {color_desc}, razor-sharp focus on pristine cuticles and smooth nail plates, natural skin texture with visible pores, no full person visible"
            ]
            subject = nail_poses[var % len(nail_poses)]
            environment = f"warm aesthetic studio background in soft creamy bokeh, {seasonal_anchor.get('bg_accent', 'beautiful textured knitwear in soft focus')}"
            persp_key = "diagonal_organic_framing" if var % 2 == 0 else "macro_nail_close_up"

        # 1.5. ПРАЗДНИКИ И ТЕМАТИЧЕСКИЕ ИНФОПОВОДЫ (МАСЛЕНИЦА, ПАСХА, НОВЫЙ ГОД, 8 МАРТА, 14 ФЕВРАЛЯ, ХЭЛЛОУИН, СПАС И ДР.)
        elif holiday_aesthetic and (
            holiday_aesthetic.get("match_type") == "keyword" or
            any(w in topic_lower for w in ["маслениц", "блин", "сырн", "пасх", "кулич", "верб", "новый год", "рождеств", "8 март", "мимоз", "валентин", "хэллоуин", "тыква", "спас", "соты", "праздник", "праздничн"])
        ):
            subject = holiday_aesthetic["hero_tabletop"]
            environment = holiday_aesthetic["background"]
            persp_key = "tabletop_commercial"

        # 2. КОФЕЙНЯ, КАПУЧИНО, ЛАТТЕ-АРТ (РУКИ, ЧАШКА, ПАР, КРЕМА 40-60%)
        elif any(w in topic_lower for w in ["кофе", "капучин", "латте", "эспрессо", "раф", "флэт", "круассан", "coffee", "cappuccino", "latte", "croissant"]):
            latte_art = "intricate swan pattern latte art" if any(w in topic_lower for w in ["лебед", "swan"]) else ("intricate rosetta latte art" if any(w in topic_lower for w in ["розетт", "rosetta"]) else "silky velvety microfoam latte art")
            table_desc = "rustic dark oak table" if any(w in topic_lower for w in ["дуб", "дерев", "стол", "oak", "wood"]) else "minimalist wooden cafe table"
            pastry_desc = ", accompanied by a fresh golden-brown flaky French butter croissant on a textured linen napkin with visible buttery layers" if any(w in topic_lower for w in ["круассан", "croissant", "выпечк"]) else ""
            cup_desc = "handcrafted matte ceramic sage-green or earthy cup" if any(w in topic_lower for w in ["керамик", "чашк", "кружк", "cup", "ceramic"]) else "artisan ceramic cup"

            coffee_archetypes = [
                # Вариация 0: Diagonal Organic Framing (Диагональная подача, лист кофе/растения слева, срез салфетки в углу)
                f"close-up diagonal commercial tabletop photo of an artisan {cup_desc} with {latte_art} and a contrasting dark espresso rim resting on a smooth off-white travertine surface, in the foreground to the left a vibrant glossy green leaf with serrated edges partially frames the shot in soft blur, subtle sliver of warm golden-yellow natural linen in the upper right corner, soft natural diffused window daylight, delicate wisps of rising steam",
                # Вариация 1: Руки греются об чашку (эмоция уюта)
                f"candid close-up lifestyle photo of female hands in cozy knitted sweater sleeves gently cupping a warm {cup_desc} with both palms to warm up, {latte_art} with contrasting dark espresso rim, whisper of translucent warm vapor rising, on a {table_desc}",
                # Вариация 2: Хват за ручку (момент дегустации)
                f"candid side-angle photo of a clean hand holding the {cup_desc} by its handle lifting it slightly above ceramic saucer{pastry_desc}, glossy espresso crema and microfoam, subtle translucent heat shimmer rising, morning sunlight on {table_desc}",
                # Вариация 3: Стол без людей (предметный вид: крема 40-60% или ровный арт)
                f"macro commercial tabletop photography of a steaming {cup_desc} with golden-brown crema and microfoam covering 50% of surface, placed on a {table_desc} beside roasted coffee beans and a ceramic saucer, subtle translucent heat shimmer"
            ]
            subject = coffee_archetypes[var % len(coffee_archetypes)]
            environment = "cozy sunlit specialty craft coffee shop, warm morning sunbeams streaming through window, soft golden bokeh in background"
            persp_key = "diagonal_organic_framing" if var % 2 == 0 else "culinary_macro_eyelevel"

        # 3. КУЛИНАРИЯ: ШЕФ-ПОВАР, СТЕЙК, МЯСНОЙ БУТИК (ПРАВИЛЬНЫЙ ХВАТ, ШПАГАТ, ОВОЩИ-ГРИЛЬ)
        elif any(w in topic_lower for w in ["стейк", "рибай", "мясо", "steak", "ribeye", "bbq", "барбекю", "мясн"]) or (any(w in topic_lower for w in ["шеф", "повар", "chef"]) and any(w in topic_lower for w in ["кухн", "кулинар", "нарез", "жар", "блюд"])):
            garlic_and_herbs = "a caramelized charred roasted garlic bulb with golden edges, fresh rosemary sprig, and crunchy Maldon sea salt crystals on aged dark walnut board"
            steak_archetypes = [
                # Вариация 0: Хват повара (claw grip) и нарезка под 45°
                f"a professional master chef's hands in action, left hand firmly securing the resting steak in a professional claw grip, right hand slicing a prime ribeye steak against the grain at 45 degrees with a sharp Japanese knife on an aged dark walnut board, {garlic_and_herbs}, tender juicy pink medium-rare center with resting meat juices glistening, subtle translucent culinary heat shimmer",
                # Вариация 1: Крафтовая упаковка / Мясной бутик (шпагат, пергамент, овощи с прогарками от решетки)
                "candid culinary photography of a raw marbled prime beef steak resting on crinkled brown butcher kraft paper, loosely tied with natural rustic jute cooking twine with a partially unspooled twine spool on the side, accompanied by colorful grilled vegetables with distinct dark charred grill marks — blistered cherry tomatoes, roasted corn wheels and zucchini slices, with scattered coarse peppercorns and roasted garlic cloves on a dark butcher table",
                # Вариация 2: Макро-срез сочных медальонов и ресторанная подача
                f"extreme macro eye-level culinary photography of carved juicy medium-rare ribeye steak medallions laid out neatly on a dark slate board, pink marbled interior texture, glistening natural meat juices pooling, sprinkled with flaky Maldon salt and roasted garlic cloves, {garlic_and_herbs}"
            ]
            subject = steak_archetypes[var % len(steak_archetypes)]
            environment = "dimly lit professional gourmet restaurant open kitchen or artisan butcher workshop, warm dramatic Rembrandt chiaroscuro lighting, stainless steel accents and wine bottles in deep atmospheric bokeh"
            persp_key = "culinary_macro_eyelevel" if var % 2 == 0 else "culinary_45_slice"

        # 4. IT / РАЗРАБОТЧИК / КОМАНДА / DEVPULSE (КОМАНДА, ДВА МОНИТОРА, ПАР ОТ КОФЕ, ВЗГЛЯД В ЭКРАН)
        elif any(w in topic_lower for w in ["команд", "team", "стартап", "startup", "devpulse", "ucust"]) and any(w in niche_lower or w in topic_lower for w in ["it", "saas", "martech", "бизнес", "разработк", "маркетинг"]):
            team_archetypes = [
                # Вариация 0: Архитектор за двумя мониторами, взгляд строго на код, пар от кофе
                "a focused software architect in a dark charcoal crewneck sweater seated at modern desk with dual high-resolution matte monitors displaying glowing AI data telemetry and real-time backend architecture diagrams, eyes intently locked and reading code directly on the screen, steaming white ceramic coffee mug in foreground emitting delicate translucent curls of rising steam, candid side-angle profile, authentic human skin texture, unedited RAW look",
                # Вариация 1: Инженер за рабочим местом с двумя мониторами и направленным светом
                "a focused software developer working at modern desk with dual matte frameless monitors displaying dark-theme IDE code editor with real syntax highlighting, eyes concentrated directly on the display panel, warm desk lamp illuminating the desk surface without screen glare, steaming ceramic mug, clean cable management",
                # Вариация 2: POV разработчика (руки на клавиатуре, два экрана, глубина офиса)
                "first-person POV over-the-shoulder shot of hands typing on a sleek low-profile mechanical keyboard in front of dual widescreen monitors running data parsing pipelines and code terminal, blurred modern open-space tech office with warm ambient lights in background",
                # Вариация 3: Контрастная пара коллег (девушка тимлид + разработчик у двух экранов)
                "two distinct colleagues collaborating in a sunlit tech loft in front of dual monitors: a female product lead with wavy auburn hair in a beige knit cardigan pointing at real-time metrics on screen, and a male backend engineer in glasses looking intently at the monitor panel, distinct unique facial features, natural realistic skin"
            ]
            subject = team_archetypes[var % len(team_archetypes)]
            environment = "modern tech open-space loft office, warm ambient interior lighting, exposed brick and glass partitions in soft bokeh"
            light_key = "dual_office"
            color_key = "teal_orange"
            persp_key = "candid_eye_level"
        elif any(w in topic_lower for w in ["разработчик", "программист", "инженер", "кодер", "developer", "tech developer"]) or any(w in topic_lower for w in ["терминал", "ide", "архитектур"]) or (any(w in topic_lower for w in ["ночь", "ночью", "ночн", "мегаполис", "небоскреб"]) and any(w in niche_lower for w in ["it", "saas", "martech", "бизнес", "разработк"])):
            if any(w in topic_lower for w in ["ночь", "ночью", "ночн", "дожд", "мегаполис", "небоскреб", "панорам", "терминал", "ide", "темн"]):
                subject = "a focused software developer in dark clothing working late at night, seen from side angle focused on dual high-resolution matte monitors displaying real syntax-highlighted code in dark-theme IDE, terminal command logs and telemetry metrics, typing on a sleek low-profile keyboard beside a matte ceramic coffee mug"
                environment = "contemporary high-rise office with panoramic floor-to-ceiling glass windows overlooking a dark rainy illuminated nocturnal metropolis with glowing skyscraper lights and traffic reflections, soft cool cyan and amber rim lighting on aluminum laptop"
                light_key = "low_key"
                color_key = "teal_orange"
                persp_key = "bokeh_shallow"
            else:
                it_archetypes = [
                    "a focused young tech specialist in denim jacket typing intently on a sleek silver laptop displaying clean IDE interface, warm desk lamp directed downward onto wooden desk surface",
                    "a contemplative tech architect in clear glasses in deep analytical thought, seated at oak desk with laptop and code terminal under warm ambient lighting",
                    "a professional software engineer seated in ergonomic mesh chair, looking at curved monitor with glowing data graphs and code structure, clean desk setup",
                    "a dedicated engineer at modern desk, laptop and whiteboard with architecture diagram in background"
                ]
                subject = it_archetypes[var % len(it_archetypes)]
                environment = f"{niche_universe['setting']}, {niche_universe['props']}"

        # 5. ЖИВОТНЫЕ: КОШКИ
        elif any(w in topic_lower for w in ["кот", "кошк", "котик", "котен", "котён", "cat", "kitten"]):
            cat_archetypes = [
                "macro eye-level pet portrait of an adorable ginger tabby kitten with vibrant orange stripes and luminous blue-green eyes, stretching playfully in a warm diagonal sunbeam across a rustic wooden floor",
                "high-angle top-down macro shot of a tiny fluffy gray and white kitten lying curled on a soft ivory knit blanket, gazing directly up at the camera with wide curious amber eyes",
                "sleek black cat with glossy midnight fur and striking golden-yellow eyes, nestled comfortably on a cozy cream-toned textured fleece blanket in warm ambient lighting",
                "charming fluffy black cat with luminous emerald eyes, sitting on a wooden desk with a tiny pink tongue peeking out in a playful blep expression beside soft warm lamplight"
            ]
            if any(w in topic_lower for w in ["черн", "black"]):
                subject = cat_archetypes[2] if var % 2 == 0 else cat_archetypes[3]
            elif any(w in topic_lower for w in ["рыж", "ginger", "orange"]):
                subject = cat_archetypes[0]
            elif any(w in topic_lower for w in ["сер", "gray", "grey", "бел", "white"]):
                subject = cat_archetypes[1]
            else:
                subject = cat_archetypes[var % len(cat_archetypes)]
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"

        # 6. ЖИВОТНЫЕ: СОБАКИ, ЩЕНКИ И КОРГИ (3 РАЗНЫХ РАКУРСА И ПОЗЫ)
        elif any(w in topic_lower for w in ["собак", "щенок", "щенк", "корги", "шпиц", "померан", "сиба", "хаски", "овчарк"]) or any(re.search(rf'\b{w}\b', topic_lower) for w in ["пес", "пёс", "dog", "puppy"]):
            blanket_desc = "sitting on a soft cream chunky-knit blanket in golden afternoon sunbeams" if any(w in topic_lower for w in ["плед", "одеял", "вязаном", "blanket", "rug"]) else "sitting on a textured light oak floor in warm sunlight"
            
            corgi_variations = [
                # Вариация 0: Портрет крупно (наклон головы, выразительные глаза)
                "an adorable Welsh Corgi puppy with golden-red and white fur, upright rounded fox-like ears, cute curious head tilt, large expressive dark amber eyes, sitting comfortably on a soft cream chunky-knit blanket in warm morning sunbeams, razor-sharp eye focus and individual whisker details",
                # Вариация 1: Вид сверху / Top-down (щенок лежит на спине/боку на пледе)
                "high-angle top-down commercial pet photo of a playful Corgi puppy lying on its back on a thick knit blanket with paws up, joyful happy expression, soft sunlight patterns across the room",
                # Вариация 2: Ракурс от пола (Ground-level dynamic)
                "low ground-level action photo of a Corgi puppy stretching forward playfully on a light oak floor, sniffing toward camera, shallow depth of field with cozy room background in warm bokeh"
            ]
            
            dog_archetypes = [
                f"a fluffy, golden-furred puppy with soft long light golden fur, {blanket_desc}, ultra-detailed soft lifelike fur catching natural backlighting",
                corgi_variations[var % len(corgi_variations)],
                f"a fluffy cream-colored Pomeranian puppy with curious dark eyes, {blanket_desc}, playful expression",
                f"a neat red Shiba Inu with alert triangular ears and bright dark eyes, standing on light oak hardwood floor in golden afternoon light",
                f"a striking Siberian Husky puppy with piercing ice-blue eyes and thick silver-gray coat, {blanket_desc}",
                f"a loyal German Shepherd with rich black and tan coat, resting peacefully on lush green grass in soft golden hour light with alert intelligent gaze"
            ]
            if any(w in topic_lower for w in ["корги", "corgi"]):
                subject = corgi_variations[var % len(corgi_variations)]
            elif any(w in topic_lower for w in ["померан", "шпиц", "pomeranian", "spitz"]):
                subject = dog_archetypes[2]
            elif any(w in topic_lower for w in ["сиба", "shiba"]):
                subject = dog_archetypes[3]
            elif any(w in topic_lower for w in ["хаски", "husky"]):
                subject = dog_archetypes[4]
            elif any(w in topic_lower for w in ["овчарк", "shepherd"]):
                subject = dog_archetypes[5]
            elif any(w in topic_lower for w in ["щенок", "щенк", "puppy"]):
                subject = corgi_variations[var % len(corgi_variations)] if any(w in topic_lower for w in ["корги"]) else dog_archetypes[0]
            else:
                subject = dog_archetypes[var % len(dog_archetypes)]
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"

        # 7. ФЛОРИСТИКА (ПРИЛАВОК, ВРУЧЕНИЕ ЗРИТЕЛЮ POV, УЛЫБКА, БЕЗ НОУТБУКОВ)
        elif any(w in topic_lower for w in ["флорист", "девушка-флорист", "букет", "пион", "эвкалипт", "разнообрази", "однообрази", "авторский букет", "композици", "цветочн", "цветы", "далии", "гортензи"]):
            florist_archetypes = [
                # Вариация 0: POV вручение букета зрителю у прилавка с улыбкой
                "first-person POV candid photo of a friendly smiling female florist in a linen apron behind a rustic wooden flower shop counter, warmly extending and handing over a lavish bespoke bouquet of soft-pink peonies, white ranunculus, peach roses and silver eucalyptus directly toward the viewer, warm genuine welcoming smile",
                # Вариация 1: Процесс создания букета за верстаком
                "candid side-angle photo of an artisan florist in linen apron at a wooden workbench, carefully tying a silk ribbon around fresh flower stems, surrounded by garden shears, craft paper rolls and scattered dewy rose petals, warm sunlit flower boutique interior",
                # Вариация 2: Макро-натюрморт букета на мраморной витрине
                "close-up macro 45-degree angle photography of a breathtaking multi-flower artisan bouquet on a marble shop counter, individual fresh water droplets on delicate pink peony petals, blurred aesthetic flower boutique in soft golden background bokeh",
                # Вариация 3: Корзина с цветами
                "a cheerful florist holding a massive, overflowing woven wicker basket centered in frame with palms supporting the base, packed with diverse fresh blooms, layered pink peonies, white hydrangeas, magenta dahlias, chamomile, and lush eucalyptus foliage"
            ]
            subject = florist_archetypes[var % len(florist_archetypes)]
            environment = "bright sunlit artisan flower boutique, shelves with glass vases, fresh botanicals, warm morning light streaming through windows"

        # 8. ДЕСЕРТЫ И ВЫПЕЧКА (ПЕРЕМЕННАЯ ПОСУДА, РАЗРЕЗ С НАЧИНКОЙ, АСИММЕТРИЯ ПОЛИВАНИЯ)
        elif any(w in topic_lower for w in ["синнабон", "булочк", "кориц", "cinnamon", "rolls", "roll"]):
            subject = "three golden-brown artisan cinnamon rolls with perfectly spiraled glossy surfaces dusted generously with fine powdered sugar on a rustic circular wooden cutting board, accompanied by dark brown whole star anise pods, whole cinnamon sticks, and scattered brown sugar crystals, with a small creamy glaze bowl in background"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["печень", "печеньк", "кукис", "cookie", "cookies"]):
            cookie_archetypes = [
                "a generous pile of freshly baked golden-brown chocolate chip cookies with melted dark chocolate chunks on a rustic circular wooden serving board with rough natural bark edge, beside a steaming ceramic mug of coffee emitting delicate wisps of steam",
                "a rustic kraft paper gift box lined with crinkled parchment paper, filled with an assortment of freshly baked gourmet cookies studded with melted dark chocolate chunks and chopped walnuts, tied with natural jute twine",
                "macro eye-level shot of freshly baked chewy cookies on a marble pastry counter, with chocolate chips glistening and scattered cocoa nibs in soft focus"
            ]
            subject = cookie_archetypes[var % len(cookie_archetypes)]
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["торт", "ганаш", "шоколадн", "чизкейк", "пирог", "срез", "разрез", "начинк", "десерт", "cake", "cheesecake", "ganache", "dessert"]):
            seasonal_anchor = InternalCalendarEngine.get_instance().get_seasonal_tactile_anchor("horeca") if InternalCalendarEngine else {}
            cake_archetypes = [
                # Вариация 0: Multi-Tiered Pedestal Showcase (Чизкейк на ножке + противень с фланами и капкейками + трайфлы)
                "a rich decadent cheesecake with a smooth creamy white interior and crumbly graham cracker crust on a white ceramic pedestal cake stand, surface generously drizzled with glossy dark chocolate cascading down in thick ribbons, crowned with fresh red strawberries, blueberries, raspberries and delicate edible micro-flowers; in the foreground, a rectangular metal tray holds small round caramel flan cups with whipped cream dollops and chocolate cupcakes with piped swirl frosting; surrounded by chocolate brownies and transparent cups with layered chocolate mousse and brownie pieces on a dark textured slate countertop, warm directional key light from upper-left",
                # Вариация 1: Dynamic High-Speed Levitation Freeze-Frame (Левитация двух кусков торта, струя меда, парящие ягоды и крошки)
                "a dynamic high-speed freeze-frame capturing two slices of layered vanilla cake suspended in mid-air frozen in the dramatic moment of separation with thick creamy piped frosting, bottom slice adorned with berries and drizzled with glossy amber honey cascading in slow-motion streams pooling into powdered sugar on a dark countertop, cake crumbs and powdered sugar suspended in the air frozen mid-fall in radial pattern with floating strawberries and blueberries in zero-g, dark modern chef kitchen with stainless steel oven in soft bokeh",
                # Вариация 2: Разрез с начинкой на фарфоре (демонстрация слоев)
                f"luxurious gourmet artisanal cake on a vintage white porcelain plate with gold rim, with a cleanly cut appetizing single slice placed beside the cake revealing rich moist sponge layers, creamy mousse filling and glossy fruit confit cross-section, dessert fork resting on linen napkin, {seasonal_anchor.get('prop', 'whole star anise and cinnamon sticks')}",
                # Вариация 3: Процесс глазирования (асимметричные подтеки, огибающие ягоды)
                "gourmet artisanal multi-layered chocolate fudge cake on a dark slate board, rich dark chocolate glaze being poured smoothly from a ceramic pitcher corner, asymmetrical luscious glossy drips naturally cascading and deflecting around whole fresh ripe strawberries, delicate chocolate shavings on top, culinary action shot"
            ]
            subject = cake_archetypes[var % len(cake_archetypes)]
            environment = f"cozy dimly lit gourmet restaurant kitchen or artisan pastry boutique, {seasonal_anchor.get('bg_accent', 'dark slate countertop and warm ambient cafe bokeh')}"
            persp_key = "culinary_macro_eyelevel" if var % 2 == 0 else "culinary_45_slice"
        elif any(w in topic_lower for w in ["сыр", "сыроварн", "фермер", "рынок", "ярмарк", "сырные"]):
            subject = "a cheerful artisan seller wearing a beige knitted sweater and dark apron behind a rustic stall display of soft-ripened cheese wheels with white rinds, crumbly wedges, and crusty sourdough baguettes"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["касса", "магазин", "ритейл", "покупк", "продукты", "супермаркет"]):
            subject = "a friendly cashier in a black short-sleeved shirt and apron operating a black touchscreen POS cash register across a dark speckled counter, candid store interaction"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["балкон", "ночн", "небоскреб", "высотк", "сити", "balcony", "cityscape", "night city"]):
            subject = "a person seated on a modern high-rise balcony with a glass railing, hands typing on an open silver laptop displaying code lines, overlooking a sprawling illuminated nocturnal city skyline with glowing skyscrapers and street traffic bokeh below"
            environment = "modern evening balcony overlooking illuminated high-rise metropolis, cool night sky with warm glowing building windows"
        elif any(w in topic_lower for w in ["постель", "кровать", "одеял", "простын", "bed", "bedroom", "sheets", "linen"]):
            subject = "an open sleek silver laptop resting on rumpled cream-colored linen bedsheets beside a ceramic mug of hot tea and an open paperback book, bathed in soft golden morning sunlight streaming through sheer curtains"
            environment = "cozy sunlit bedroom with natural linen textures, morning sunbeams, peaceful relaxing atmosphere"
        elif any(w in topic_lower for w in ["блокнот", "конспект", "тетрадь", "учеб", "студент", "flatlay desk", "канцеляр"]):
            subject = "a neat top-down flatlay of a wooden study desk featuring an open spiral notebook with crisp handwritten ink notes and diagrams, a pair of classic tortoiseshell round glasses, a matte ceramic coffee cup with latte art, and a small potted green succulent"
            environment = "sunlit organized study workspace, natural oak desk surface, soft morning daylight, crisp educational aesthetic"
        elif any(w in topic_lower for w in ["постер", "плакат", "вывеск", "баннер", "билборд", "типографик", "надпись", "лайтбокс", "poster", "lightbox", "billboard", "signage"]):
            ooh_archetypes = [
                "a sleek minimalist framed poster mounted on a textured red-brown brick wall with visible mortar lines, featuring bold clean dark-gray typography against a crisp white background, with soft diffused overhead spotlighting and a light beige wooden door trim on the side",
                "an illuminated minimalist circular black metal lightbox sign hanging from a classical arched stone ceiling arcade, with warm golden backlighting highlighting subtle architectural stone textures",
                "a large clean architectural billboard mounted on the corner facade of a modern multi-story concrete and glass building against a clear blue sky, showing high-contrast minimalist graphic design",
                "bold motivational typography stenciled in crisp white paint across dark metallic industrial staircase risers, leading upward with dramatic directional side lighting and tactile metal textures"
            ]
            subject = ooh_archetypes[var % len(ooh_archetypes)]
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["посуд", "фарфор", "гончар", "глинян"]) or (any(w in topic_lower for w in ["керамик", "чаш", "блюд"]) and not any(w in topic_lower for w in ["кофе", "капучин", "латте", "чай", "маникюр", "ногти"])):
            subject = "an artisan ceramist wearing a casual long-sleeved shirt under an apron, holding a handcrafted bone porcelain cup in hands, distinct individual fingers, authentic tactile grip"
            environment = "Sunlit artisanal ceramic and tableware boutique, open oak display shelves"
        elif any(w in topic_lower for w in ["кожанк", "косух", "рок", "байкер", "тату", "biker", "leather jacket"]):
            subject = "a charismatic young woman in a textured black leather biker jacket with silver snaps and interlocking chain necklaces, candid expressive face, solid matte dark background"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["свитер", "осень", "парк", "уют", "скамейк", "autumn", "knitwear", "cozy"]):
            subject = "a young woman in an oversized cream cable-knit sweater and straight-leg denim jeans, sitting casually on a weathered wooden park bench with scattered autumn leaves in golden hour"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["человек", "основател", "фаундер", "девушк", "парен", "мужчин", "женщин", "портрет", "лицо"]):
            subject = "a confident young professional wearing modest casual clothes with genuine relaxed expression, looking into camera"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif "плата" in topic_lower or "esp32" in topic_lower or "esp-32" in topic_lower or "ардуино" in topic_lower or "arduino" in topic_lower or "микроконтроллер" in topic_lower or "чип" in topic_lower:
            subject = visual_spec.get("visual_description", "extreme macro tabletop product photography of genuine ESP-32 development board with straight rigid gold square male header pins, rectangular metal RF shield engraved with ESP-32 logo, matte black FR-4 PCB, copper circuit traces, USB Type-C port")
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif "массаж" in topic_lower or "камн" in topic_lower:
            subject = visual_spec.get("visual_description", "serene relaxing hot stone back massage SPA treatment, smooth black basalt stones placed along spine, aromatic botanical oils glistening")
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["купальник", "бикини", "стринги", "нижнее белье", "swimwear", "lingerie"]):
            garment_desc = visual_spec.get("visual_description", "elegant stylish minimalist swimwear")
            if "пляж" in topic_lower or "закат" in topic_lower:
                subject = f"athletic graceful young female model posing naturally, wearing {garment_desc}"
                environment = "breathtaking golden hour ocean shoreline, gentle turquoise waves in soft background bokeh, warm sea breeze"
            else:
                subject = f"captivating charismatic female model posing with poise and elegance, wearing {garment_desc}"
                environment = "moody luxury penthouse lounge with soft neon ambient reflections, subtle velvet textures, cinematic depth"
        elif any(w in topic_lower for w in ["пасочниц", "формы для выпечки", "бумажные формы", "формочки для кулич"]):
            subject = "set of premium pleated brown cellulose Panettone and Easter Kulich paper baking molds with gold filigree and traditional carved wooden paskha pyramid mold on baker table"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["вид сверху", "flatlay", "флэтлей"]):
            subject = "centered top-down flatlay of artisanal Easter Kulich on a minimalist warm ceramic plate, glossy pastel pink or snowy-white glaze dome garnished with freeze-dried strawberry crumbles and soft mini marshmallows"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in topic_lower for w in ["кулич", "пасх", "куличи", "пасхальн", "освящен"]):
            subject = "tall cylindrical golden-brown artisanal Easter Kulich brioche cake baked in a pleated brown Panettone paper mold with floral print, crowned with a thick glossy white royal icing glaze, decorated with emerald green pistachio sponge moss crumble and pastel sugar candy eggs, eye-level macro depth with background pastries in creamy bokeh"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif "кофе" in topic_lower or "эфиопи" in topic_lower or "капучин" in topic_lower:
            subject = "artisanal ceramic cup of creamy cappuccino with intricate latte art, fresh ripe peach slice and delicate white jasmine flowers on saucer, gentle rising steam"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif "крем" in topic_lower or "сыворотк" in topic_lower or "помад" in topic_lower or "блеск для губ" in topic_lower or "косметик" in topic_lower:
            subject = visual_spec.get("visual_description", "luxury commercial cosmetic product display")
            environment = "minimalist luxury travertine marble stone podium, delicate fresh water droplets, soft botanical accents in blurred background, clean studio aesthetic"
        elif "турбин" in topic_lower or "gt2871" in topic_lower or "койловер" in topic_lower or "перфоратор" in topic_lower or "шуруповерт" in topic_lower or "инструмент" in topic_lower:
            subject = visual_spec.get("visual_description", "precision tabletop commercial photograph of professional engineering component")
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        elif any(w in niche_lower for w in ["martech", "маркетинг", "saas", "it", "ии"]) or any(w in topic_lower for w in ["martech", "маркетинг", "saas", "ии-платформ", "автоматизац", "генеративн", "нейросеть"]):
            subject = "sleek modern workspace with an open ultra-thin laptop displaying a glowing clean AI marketing automation dashboard with real-time conversion growth graphs, creative preview cards, and automated campaign metrics in sharp focus"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"
        else:
            raw_vis = visual_spec.get("visual_description")
            subject = f"{raw_vis}" if raw_vis and raw_vis != topic else f"authentic commercial scene representing {niche_en}"
            environment = f"{niche_universe['setting']}, {niche_universe['props']}"

        # =========================================================================
        # ПИЛАР 3: ВНУТРЕННЯЯ ИСТОРИЯ И РЕКВИЗИТ КАК ЭКСПОЗИЦИЯ (Implied Narrative)
        # =========================================================================
        lighting = cls.LIGHTING_SCHEMES[light_key]
        color_scheme = cls.COLOR_HARMONIES[color_key]
        composition = cls.COMPOSITION_GEOMETRIES[comp_key]
        perspective = cls.PERSPECTIVES[persp_key]

        colors_str = f"Brand palette accents: {', '.join(brand_colors)}. " if brand_colors else ""

        # Дифференцируем текстурные дескрипторы: кожа для людей, фактура материала для предметов/еды/плат/животных
        non_human_terms = [
            "плата", "esp32", "esp-32", "arduino", "чип", "десерт", "торт", "синнабон", "булочк",
            "печень", "ролл", "выпечк", "стейк", "турбин", "перфоратор", "кот", "кошк", "котик",
            "котен", "собак", "щенок", "щенк", "корги", "шпиц", "померан", "сиба", "хаски",
            "овчарк", "постер", "плакат", "вывеск", "типографик", "билборд", "флэтлей", "flatlay",
            "блокнот", "конспект", "тетрадь", "блин", "блинчик", "кулич", "пасх", "яйц", "соты",
            "мед", "мёд", "пирог", "натюрморт", "still life", "tabletop", "bouquet", "букет", "цветы"
        ]
        
        # Строгая регулярная проверка человеческих персон с учетом границ слов
        human_regex = r"\b(человек\w*|девушк\w*|модел\w*|парен\w*|мужчин\w*|женщин\w*|портрет\w*|мастер\w*|доктор\w*|врач\w*|тренер\w*|студент\w*|барист\w*|юрист\w*|основател\w*|фаундер\w*|разработчик\w*|программист\w*|инженер\w*|маникюр\w*|ногт\w*|man|men|woman|women|person|people|model|portrait|doctor|barista|founder|florist|developer|engineer|male|female|fingers)\b"
        has_human_term = bool(re.search(human_regex, f"{topic_lower} {subject.lower()}"))
        has_non_human_term = any(w in topic_lower or w in subject.lower() for w in non_human_terms)

        # Если сцена - бьюти/маникюр, руки признаются частью человека
        if any(w in topic_lower or w in subject.lower() for w in ["маникюр", "ногти", "ногт", "nail", "manicure"]):
            is_human_scene = True
        else:
            is_human_scene = has_human_term and not has_non_human_term
        
        if is_human_scene:
            is_group = any(w in topic_lower or w in subject.lower() for w in ["team", "group", "engineers", "developers", "people", "команд", "разработчик", "инженер", "люди", "коллег"])
            group_diversity = "(heterogeneous distinct individual facial features:1.25), (diverse unique face shapes and contrasting hairstyles:1.25), distinct non-identical people, " if is_group else ""
            texture_desc = (
                f"{group_diversity}(subsurface scattering, authentic real skin texture:1.25), (visible micro skin pores:1.2), subtle natural skin blemishes, "
                "uneven natural skin tone, (35mm RAW film grain, ISO 400:1.15), fine individual hair strands, "
                "natural non-plastic skin, subtle facial asymmetry, authentic human gaze intently locked on screen, unedited analog photography, zero cgi, zero digital art, zero anime"
            )
            # Направленный свет с глубокими микротенями для проявления текстуры
            if light_key in {"high_key", "soft_diffused", "rembrandt"}:
                lighting_desc = "Dramatic directional side lighting, deep micro-shadows"
            else:
                lighting_desc = lighting

            is_full_body = any(w in topic_lower for w in ["полный рост", "во весь рост", "full body", "standing", "ростовой", "в полный рост"])
            is_action_hands = any(w in topic_lower or w in subject.lower() for w in ["маникюр", "ногти", "nail", "manicure", "держит", "руки", "пайк", "осциллограф", "инструмент", "букет", "пион", "чашк", "кружк", "holding", "hands", "soldering", "workbench", "bouquet", "cup", "mug"])

            optics_extra = ""
            if any(w in topic_lower or w in subject.lower() for w in ["маникюр", "ногти", "nail", "manicure", "ногот"]):
                optics_extra = "distinct anatomically correct 5 slender fingers with neat natural cuticles, perfectly shaped smooth nail plates, clean separation between fingers, "
            elif is_action_hands:
                optics_extra = "distinct clean separation between fingers and held objects, anatomically correct 5 fingers with clear knuckles, natural hand grasp, "
            elif is_full_body:
                optics_extra = "sharp full-body frame, crisp clothing fabric texture, "

            # Физический материализованный якорь переднего плана (СТРОГАЯ ИЗОЛЯЦИЯ ПО НИШАМ)
            if "leaf with serrated edges" in subject.lower() or persp_key == "diagonal_organic_framing":
                foreground_anchor = "(vibrant green leaf with serrated edges and glossy surface in extreme blurred foreground framing the shot from the left:1.25)"
            elif any(w in topic_lower or w in subject.lower() for w in ["корги", "щенок", "щенк", "собак", "кошк", "котен", "питомц", "puppy", "kitten"]) or any(re.search(rf'\b{w}\b', topic_lower) or re.search(rf'\b{w}\b', subject.lower()) for w in ["кот", "коты", "dog", "cat", "пес", "пёс"]):
                foreground_anchor = "(blurred edge of cozy knit blanket in extreme foreground:1.2)"
            elif any(w in topic_lower or w in subject.lower() for w in ["маникюр", "ногти", "гель-лак", "нейл", "ногот", "nail", "manicure"]):
                foreground_anchor = "(blurred edge of soft knitwear sleeve in extreme foreground:1.2)"
            elif any(w in topic_lower or w in subject.lower() for w in ["кофе", "капучин", "латте", "эспрессо", "круассан", "coffee", "cappuccino", "croissant"]):
                foreground_anchor = "(blurred edge of rustic ceramic saucer with gentle rising steam in extreme foreground:1.2)"
            elif any(w in topic_lower or w in subject.lower() for w in ["стейк", "рибай", "шеф", "повар", "мясо", "steak", "ribeye", "кулинар"]):
                foreground_anchor = "(blurred wine glass stem and edge of walnut board in extreme foreground:1.2)"
            elif any(w in topic_lower or w in subject.lower() for w in ["разработчик", "программист", "терминал", "ide", "ноутбук", "клавиатур", "developer", "команд", "startup", "devpulse"]):
                foreground_anchor = "(blurred edge of modern desk and steaming ceramic mug with delicate rising translucent vapor in extreme foreground:1.25)"
            elif any(w in topic_lower or w in subject.lower() for w in ["десерт", "торт", "мусс", "пирожн", "чизкейк", "выпечк", "синнабон", "dessert", "pastry", "cake"]):
                foreground_anchor = "(blurred vintage dessert fork and linen napkin in extreme foreground:1.2)"
            elif any(w in topic_lower or w in subject.lower() for w in ["букет", "пион", "флорист", "цвет"]):
                foreground_anchor = "(blurred dewy flower petal and craft twine in extreme foreground:1.2)"
            elif any(w in topic_lower or w in subject.lower() for w in ["плата", "esp32", "пайк", "электроник"]):
                foreground_anchor = "(blurred precision tweezers and wire spool in extreme foreground:1.2)"
            else:
                foreground_anchor = "(blurred foreground edge in extreme foreground:1.1)"

            # Механизм контролируемой энтропии (Controlled Variance)
            domain = "general"
            if any(k in niche_lower or k in topic_lower for k in ["martech", "маркетинг", "saas", "it", "ии", "разработ", "программист", "инженер", "tech"]):
                domain = "tech"
            elif any(k in niche_lower or k in topic_lower for k in ["кофе", "ресторан", "пекарн", "кондитер", "десерт", "стейк", "кулинар", "сыр", "еда"]):
                domain = "horeca"
            elif any(k in niche_lower or k in topic_lower for k in ["бьюти", "маникюр", "ногти", "салон", "косметик", "spa", "спа"]):
                domain = "beauty"

            cur_surface = ControlledVarianceEngine.get_surface(domain, var)
            cur_bg = ControlledVarianceEngine.get_background(domain, var)
            if InternalCalendarEngine:
                cur_light = InternalCalendarEngine.get_instance().get_visual_lighting_anchor(topic, environment)
            else:
                cur_light = ControlledVarianceEngine.get_lighting(var)
            cur_optics = ControlledVarianceEngine.get_camera_optics(var)

            # RAG Brand Identity injection
            rag_brand_anchors = ""
            if brand_props:
                if isinstance(brand_props, list):
                    rag_brand_anchors = f", featuring {', '.join(brand_props)}"
                elif isinstance(brand_props, str):
                    rag_brand_anchors = f", featuring {brand_props}"

            color_rhyme = CinematicAestheticCore.resolve_color_rhyme(topic, niche, var)
            full_prompt = CinematicAestheticCore.build_master_analog_prompt(
                subject=subject,
                environment=environment,
                surface=cur_surface,
                background=cur_bg,
                foreground_anchor=foreground_anchor,
                camera_optics=cur_optics,
                lighting_anchor=cur_light,
                color_rhyme=color_rhyme,
                is_human=True,
                rag_brand_anchors=rag_brand_anchors,
                optics_extra=optics_extra
            )
        else:
            # Механизм контролируемой энтропии (Controlled Variance)
            domain = "general"
            if any(k in niche_lower or k in topic_lower for k in ["martech", "маркетинг", "saas", "it", "ии", "разработ", "программист", "инженер", "tech"]):
                domain = "tech"
            elif any(k in niche_lower or k in topic_lower for k in ["кофе", "ресторан", "пекарн", "кондитер", "десерт", "стейк", "кулинар", "сыр", "еда"]):
                domain = "horeca"
            elif any(k in niche_lower or k in topic_lower for k in ["бьюти", "маникюр", "ногти", "салон", "косметик", "spa", "спа"]):
                domain = "beauty"

            if holiday_aesthetic and (holiday_aesthetic.get("match_type") == "keyword" or any(w in topic_lower for w in ["маслениц", "блин", "сырн", "пасх", "кулич", "верб", "новый год", "рождеств", "8 март", "мимоз", "валентин", "хэллоуин", "тыква", "спас", "соты", "праздник"])):
                cur_surface = holiday_aesthetic["surface"]
                cur_bg = holiday_aesthetic["background"]
                cur_light = holiday_aesthetic["window_lighting"]
                foreground_anchor = holiday_aesthetic["foreground_anchor"]
                palette_choice = holiday_aesthetic.get("palette_key", "terracotta")
            else:
                cur_surface = ControlledVarianceEngine.get_surface(domain, var)
                cur_bg = ControlledVarianceEngine.get_background(domain, var)
                if InternalCalendarEngine:
                    cur_light = InternalCalendarEngine.get_instance().get_visual_lighting_anchor(topic, environment)
                else:
                    cur_light = ControlledVarianceEngine.get_lighting(var)
                palette_choice = niche

            cur_optics = ControlledVarianceEngine.get_camera_optics(var)

            # RAG Brand Identity injection
            rag_brand_anchors = ""
            if brand_props:
                if isinstance(brand_props, list):
                    rag_brand_anchors = f", featuring {', '.join(brand_props)}"
                elif isinstance(brand_props, str):
                    rag_brand_anchors = f", featuring {brand_props}"

            # Физический материализованный якорь переднего плана (если не переопределен праздником)
            if not (holiday_aesthetic and holiday_aesthetic.get("match_type") == "keyword"):
                if "leaf with serrated edges" in subject.lower() or persp_key == "diagonal_organic_framing":
                    foreground_anchor = "(vibrant green leaf with serrated edges and glossy surface in extreme blurred foreground framing the shot from the left:1.25)"
                elif any(w in topic_lower or w in subject.lower() for w in ["корги", "щенок", "щенк", "собак", "кошк", "котен", "питомц", "puppy", "kitten"]) or any(re.search(rf'\b{w}\b', topic_lower) or re.search(rf'\b{w}\b', subject.lower()) for w in ["кот", "коты", "dog", "cat", "пес", "пёс"]):
                    foreground_anchor = "(blurred edge of cozy knit blanket in extreme foreground:1.2)"
                elif any(w in topic_lower or w in subject.lower() for w in ["маникюр", "ногти", "гель-лак", "нейл", "ногот", "nail", "manicure"]):
                    foreground_anchor = "(blurred edge of soft knitwear sleeve in extreme foreground:1.2)"
                elif any(w in topic_lower or w in subject.lower() for w in ["кофе", "капучин", "латте", "эспрессо", "круассан", "coffee", "cappuccino", "croissant"]):
                    foreground_anchor = "(blurred edge of rustic ceramic saucer in extreme foreground:1.2)"
                elif any(w in topic_lower or w in subject.lower() for w in ["стейк", "рибай", "шеф", "повар", "мясо", "steak", "ribeye", "кулинар"]):
                    foreground_anchor = "(blurred wine glass stem and edge of walnut board in extreme foreground:1.2)"
                elif any(w in topic_lower or w in subject.lower() for w in ["разработчик", "программист", "терминал", "ide", "ноутбук", "клавиатур", "developer", "команд", "startup", "devpulse"]):
                    foreground_anchor = "(blurred edge of modern desk and steaming ceramic mug in extreme foreground:1.2)"
                elif any(w in topic_lower or w in subject.lower() for w in ["десерт", "торт", "мусс", "пирожн", "чизкейк", "выпечк", "синнабон", "dessert", "pastry", "cake"]):
                    foreground_anchor = "(blurred vintage dessert fork and linen napkin in extreme foreground:1.2)"
                elif any(w in topic_lower or w in subject.lower() for w in ["букет", "пион", "флорист", "цвет"]):
                    foreground_anchor = "(blurred dewy flower petal and craft twine in extreme foreground:1.2)"
                elif any(w in topic_lower or w in subject.lower() for w in ["плата", "esp32", "пайк", "электроник"]):
                    foreground_anchor = "(blurred precision tweezers and wire spool in extreme foreground:1.2)"
                else:
                    foreground_anchor = "(blurred foreground edge in extreme foreground:1.1)"

            color_rhyme = CinematicAestheticCore.resolve_color_rhyme(topic, palette_choice, var)
            full_prompt = CinematicAestheticCore.build_master_analog_prompt(
                subject=subject,
                environment=environment,
                surface=cur_surface,
                background=cur_bg,
                foreground_anchor=foreground_anchor,
                camera_optics=cur_optics,
                lighting_anchor=cur_light,
                color_rhyme=color_rhyme,
                is_human=False,
                rag_brand_anchors=rag_brand_anchors,
                optics_extra=""
            )

        if is_human_scene:
            scene_type = "human"
        elif any(w in topic_lower for w in ["постер", "вывеск", "плакат", "баннер", "надпись", "текст", "лого", "sign", "poster", "billboard"]):
            scene_type = "text"
        elif any(w in topic_lower or w in niche_lower for w in ["кофе", "десерт", "стейк", "кулинар", "еда", "блюдо", "товар", "продукт", "крем", "плата", "esp32"]):
            scene_type = "product"
        else:
            scene_type = "general"

        sampling_config = QwenPromptAssembler.get_sampling_config(scene_type)
        qwen_negative = QwenPromptAssembler.get_negative_prompt(scene_type)

        return {
            "prompt": full_prompt,
            "negative_prompt": qwen_negative,
            "sampling_config": sampling_config,
            "lighting_scheme": light_key,
            "color_harmony": color_key,
            "composition": comp_key,
            "perspective": persp_key,
            "scene_type": scene_type
        }


try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger("photo_generator_skill")


class PhotoGeneratorSkill:
    """
    Автономный ИИ-фотограф для SMM.
    - Динамический Prompt Engineering под нишу бизнеса (3-Pillar Narrative Engine)
    - Поддержка соотношений сторон: 1:1 (Квадрат), 4:5 (Портрет), 16:9 (Баннер), 9:16 (Stories)
    - Интеграция с ComfyUI / SDXL / Diffusers / Local Visual Engine
    """

    ASPECT_RATIOS = {
        "1:1": (1024, 1024),
        "4:5": (896, 1152),
        "16:9": (1360, 768),
        "9:16": (768, 1360),
        "3:4": (896, 1216),
        "4:3": (1216, 896)
    }

    UPSCALED_RESOLUTIONS = {
        "1:1": (1536, 1536),
        "9:16": (1080, 1920),
        "16:9": (1920, 1080),
        "4:5": (1344, 1728)
    }

    NICHE_PRESETS = {
        "религия": {
            "subject": "majestic historic cathedral sanctuary with towering carved stone arches, golden gilded altar details, glowing beeswax candles, soft ethereal sunbeams filtering through ancient stained glass windows",
            "environment": "sacred historic sanctuary, timeless spiritual tranquility, marble floor reflecting candle glow, authentic cultural heritage atmosphere",
            "lighting": "warm golden candle glow, ethereal sunbeams through stained glass, gentle chiaroscuro highlights",
            "camera": "Cinematic 35mm architectural perspective, peaceful reverence and awe, Hasselblad color science, photorealistic"
        },
        "животные": {
            "subject": "adorable healthy domestic tabby cat resting peacefully on a warm wooden floor in a sunny spot next to a soft woven blanket, calm content expression",
            "environment": "cozy warm sunlit Scandinavian-style home living room, potted green plants, peaceful domestic haven",
            "lighting": "soft diffused morning window sunlight, gentle golden room ambient, natural warmth",
            "camera": "Eye-level macro pet photography, shallow depth of field, sharp tactile fur details, authentic UGC warmth"
        },
        "электроника": {
            "subject": "compact ESP-32 microcontroller board with dual-in-line gold header pins, CP2102 chip and USB Type-C port, extreme macro product shot",
            "environment": "clean high-tech electronics engineering workbench, blue anti-static silicone soldering mat, precision tweezers in soft background bokeh",
            "lighting": "high-key precision studio lighting, crisp metallic highlights on solder pads",
            "camera": "Macro tabletop lens, crisp copper circuit traces, tactile electronic engineering photography"
        },
        "кофейня": {
            "subject": "smiling friendly barista leaning over rustic wooden counter, gently handing a steaming artisanal ceramic cup of cappuccino with delicate latte art directly toward viewer",
            "environment": "cozy local craft coffee shop, large sunlit window with soft floating dust motes, relaxed warm background",
            "lighting": "natural soft ambient morning daylight from window, warm gentle golden tones, realistic room shadows",
            "camera": "Cinematic 35mm film look, natural handheld eye-level angle, candid smartphone photo, unedited Apple ProRAW look, emotional warmth"
        },
        "ресторан": {
            "subject": "passionate focused chef in dark apron using precision tweezers to place delicate garnish onto gourmet signature dish in warm open kitchen",
            "environment": "warm inviting bistro with ambient dining room in soft bokeh, polished glassware, fine dining atmosphere",
            "lighting": "warm golden spotlight on culinary masterpiece, soft candle and ambient dining glow",
            "camera": "Cinematic 35mm photography, natural tabletop angle, candid culinary passion, realistic foodie storytelling"
        },
        "красота": {
            "subject": "radiant client with a genuine glowing smile looking into sunlit salon mirror admiring fresh stylish hair and makeup, caring stylist smiling proudly behind her",
            "environment": "sunlit modern beauty salon, marble vanity shelf, delicate green eucalyptus in soft background",
            "lighting": "bright clean natural morning daylight, soft diffused window glow, fresh organic radiance",
            "camera": "Cinematic lifestyle beauty shot, authentic UGC texture, genuine emotion of confidence and self-love"
        },
        "it": {
            "subject": "focused passionate developer or founder leaning back with a relieved happy smile after successful project milestone, laptop on desk with clean editor",
            "environment": "bright minimalist home office or loft coworking, indoor potted plant, cozy ambient desk setup",
            "lighting": "natural ambient daylight from nearby window, soft warm desk lamp accent",
            "camera": "Cinematic desk point-of-view, authentic candid tech lifestyle photo, unedited RAW look, genuine human accomplishment"
        },
        "фитнес": {
            "subject": "dedicated athlete taking a deep breath of triumph after an intense workout in modern loft gym, holding water bottle with sunlight highlighting determination",
            "environment": "modern spacious gym, motivational athletic loft environment, wooden bench",
            "lighting": "warm golden morning sunbeams piercing through high gym windows, dramatic authentic highlights",
            "camera": "Dynamic candid smartphone angle, authentic workout lifestyle photo, raw emotion of self-overcoming"
        },
        "авто": {
            "subject": "skilled detailing specialist in black gloves gently running fingertips across mirror-like glossy hood of sports car, admiring flawless reflection",
            "environment": "clean modern workshop with soft LED strip lighting, reflections on glossy paint",
            "lighting": "natural golden hour light, realistic reflections on paint, dramatic workshop contrasts",
            "camera": "Cinematic automotive photography, candid automotive enthusiast passion, authentic craftsmanship"
        },
        "недвижимость": {
            "subject": "happy young homeowner sitting comfortably on warm hardwood floor of airy sunlit living room with coffee mug, gazing out panoramic window at city sunset",
            "environment": "modern newly finished apartment interior, floor-to-ceiling panoramic windows, potted plant nearby",
            "lighting": "bright warm afternoon sunbeams, airy room daylight, golden sunset glow",
            "camera": "Cinematic wide architectural photography, authentic new home celebration, pure happiness and safety"
        },
        "одежда": {
            "subject": "stylish woman in front of warm boutique mirror playfully adjusting collar of chic elegant coat with confident joyful smile",
            "environment": "bright aesthetic boutique dressing area, minimalist aesthetic clothing rack in soft background",
            "lighting": "soft natural window light, subtle room shadows, true fabric colors",
            "camera": "Casual candid mirror photo, authentic fashion UGC aesthetic, delight in personal style"
        },
        "медицина": {
            "subject": "caring friendly doctor in clean white coat having warm empathetic conversation with smiling relieved patient, genuine trust and safety",
            "environment": "bright modern consultation room with wood and green plant accents, welcoming atmosphere",
            "lighting": "soft bright diffused natural light, calm trustworthy and reassuring atmosphere",
            "camera": "Natural eye-level perspective, authentic candid healthcare photo, relief and care"
        },
        "ремонт": {
            "subject": "architect and proud homeowner standing together in finished open-plan room looking at blueprints with genuine satisfaction and pride",
            "environment": "spacious newly renovated living room, warm hardwood flooring, designer lighting",
            "lighting": "bright warm natural window daylight, gentle realistic interior shadows",
            "camera": "Wide angle lens, authentic interior design storytelling photo, crisp architectural details"
        },
        "образование": {
            "subject": "focused inspired student in headphones experiencing breakthrough moment of excitement while taking notes next to laptop by sunny window",
            "environment": "bright modern library or student coworking corner, organized learning space",
            "lighting": "natural sunny window light, soft warm ambiance, inspiring study mood",
            "camera": "Tabletop angle, authentic study lifestyle photo, intellectual growth and ambition"
        },
        "туризм": {
            "subject": "traveler wrapped in cozy blanket holding steaming mug of tea sitting on edge of wooden glamping deck watching golden sunrise over misty mountains",
            "environment": "scenic mountain or lake view at golden hour, breathtaking tranquil nature background",
            "lighting": "warm golden sunrise glow, soft mountain atmosphere, peaceful awe and tranquility",
            "camera": "Wide scenic view, authentic travel photography, natural rich colors, deep emotional peace"
        },
        "юриспруденция": {
            "subject": "two business partners firmly shaking hands across modern conference table at sunset after signing crucial contract, mutual respect and relief",
            "environment": "bright contemporary law firm or consulting office, large panoramic window with city view",
            "lighting": "crisp natural office daylight, warm golden hour accents, trustworthy and authoritative",
            "camera": "Professional desk perspective, authentic corporate lifestyle storytelling photo, confidence and success"
        },
        "праздник": {
            "subject": "cheerful professional team or person raising a warm toast or smiling genuinely in celebration by sunlit window with festive seasonal accent",
            "environment": "warm sunlit modern office, cheerful inspiring celebratory atmosphere",
            "lighting": "warm golden daylight, soft festive background bokeh",
            "camera": "Authentic candid commercial photo, shallow depth of field, genuine celebration and connection"
        },
        "флаг": {
            "subject": "focused professional in elegant silhouette standing at lower right looking up in awe, colossal majestic Russian tricolor flag fluttering grandly and powerfully on towering flagpole dominating upper sky",
            "environment": "modern high-rise glass office by panoramic window, dramatic glowing golden sunset sky and clouds",
            "lighting": "warm golden sunbeams through clouds, brilliant golden rim lighting on silhouette, soft window reflections",
            "camera": "Heroic dramatic low-angle upward perspective (shot from below looking up), cinematic 35mm film masterpiece, monumental scale and grandeur"
        },
        "услуги": {
            "subject": "passionate dedicated professional deeply engaged in their craft at modern sunlit workstation, genuine focus, pride and mastery",
            "environment": "sunlit contemporary creative workspace or bright meeting room, productive human atmosphere",
            "lighting": "natural window daylight, soft warm room ambient, golden highlights",
            "camera": "Casual tabletop angle, authentic business lifestyle storytelling photo"
        },
        "рынок": {
            "subject": "rustic weathered wooden market crate overflowing with vibrant ripe red tomatoes and crisp fresh herbs, dewdrops glistening in morning sun",
            "environment": "authentic bustling organic farmers market with natural canvas awnings, warm rustic atmosphere",
            "lighting": "golden morning sunshine streaming through market stalls, rich natural warmth",
            "camera": "Top-down / angled tabletop commercial food photography, crisp appetizing textures, shallow depth of field"
        },
        "приват": {
            "subject": "captivating charismatic creator in subtle ambient neon and candlelight, striking aesthetic silhouette, confident playful gaze",
            "environment": "stylish moody modern penthouse lounge or aesthetic cozy studio room with velvet textures",
            "lighting": "moody cinematic rim lighting, warm candle glow, subtle deep shadows and atmospheric highlights",
            "camera": "Cinematic 35mm portrait, intimate artistic depth of field"
        }
    }

    DEFAULT_NEGATIVE_PROMPT = (
        "volumetric fog, cinematic haze, floating dust motes, cyan and orange contrast lighting, cyberpunk neon, plastic skin, "
        "multiple people staring at screen, unnatural forced smiles, CGI, 3D render, oversaturated, dark basement, cluttered desk, artificial blue lighting, "
        "(flat lighting, HDR, softbox, even illumination, lifted shadows, studio fill light:1.35), "
        "(tone mapping, washed out blacks, washed out shadows, aggressive shadow recovery:1.3), "
        "(fake chroma key blur, abrupt cut-and-paste background, cardboard cutout look, computational fake blur:1.3), "
        "(cartoon:1.4), (anime:1.4), (digital painting:1.35), (digital illustration:1.35), (concept art:1.3), (stylized:1.35), (smooth render:1.35), "
        "(looking away from screen:1.3), (wandering gaze:1.3), (cross-eyed:1.25), (unfocused eyes:1.25), "
        "(identical faces:1.4), (cloned faces:1.4), (twin faces:1.35), (duplicate people:1.3), (same face syndrome:1.35), (cloned facial features:1.35), "
        "(extra fingers, mutated joints, fused fingers:1.3), (deformed knuckles, missing phalanges, melting fingers, hand-object fusion:1.25), (stems penetrating through fingers, objects melting into hands:1.2), "
        "(dense smoke, thick steam plumes, vape smoke overlay, opaque white smoke, cigarette smoke:1.3), "
        "(lamp pointed directly at screen, screen glare, financial stock trading charts on screens, sad depressed expression in retail:1.25), "
        "(yarn ball in food or restaurant, mechanical keyboard in bakery or food, out of place objects:1.25), "
        "(identical cloned drips, symmetrical plastic icing drips, artificial repetitive patterns:1.2), "
        "bare shoulders, sideboob, bare back, bare arms, naked under apron, open-back, halter top, cleavage, exposed skin, bare chest, shirtless, half-naked, unclothed, revealing clothing, deep neckline, bare midriff, lingerie, swimsuit, bikini, underwear, suggestive, erotic, "
        "100-megapixel Hasselblad, Hasselblad H6D, 8k resolution, 4k, photorealistic, clean editorial, commercial retouching, "
        "crisp specular highlights, artificial global color filter, golden ratio overlay, diagram overlay, "
        "fused fingers, extra digits, missing fingers, malformed hands, fingers melting into objects, blurred hands, phantom fingers, mutated hands, "
        "computational photography blur, fake depth of field, synthetic bokeh, flat background, "
        "thick plastic hair, helmet hair, perfect grooming, CGI hair, hair clumps, stylized clay hair, "
        "Unreal Engine 5, octane render, digital painting, video game protagonist, hero shot, flawless, 3D render, "
        "airbrushed, plastic, smooth skin, overly retouched, wax, porcelain skin, perfect skin, "
        "smartphone, phone screen, holding smartphone, camera UI, viewfinder, bezel, device mockup, "
        "spiral lines, golden spiral overlay, graphic circle lines, diagram, geometric curves, grid overlay, "
        "staged studio photoshoot, heavy artificial studio strobes, studio softboxes, "
        "bright pink blush, intense rosy cheeks, sunburn, clown makeup, painted blush, rosacea, unnatural cheek redness, "
        "plastic chest skin, airbrushed body, blurry decollete, smooth plastic skin, airbrushed face, "
        "sharp detailed background, background noise, high-frequency background grain, floating objects, deformed furniture, deformed wall sockets, disconnected wires, "
        "gibberish text, misspelled letters, blurry typography, double letters, deformed writing, "
        "nsfw, nude, naked, explicit, bad anatomy, deformed fingers, extra limbs, blurry face, bad eyes, "
        "low quality, oversaturated, plastic 3d render, watermark, text, signature"
    )

    def __init__(self, output_dir: Optional[str] = None):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_dir = output_dir or os.path.normpath(os.path.join(base_dir, "..", "output", "photos"))
        os.makedirs(self.output_dir, exist_ok=True)

    def create_smm_prompt(
        self,
        topic: str,
        niche: str = "Общий бизнес",
        aspect_ratio: str = "1:1",
        brand_colors: Optional[List[str]] = None,
        style: str = "candid_iphone",
        custom_prompt: Optional[str] = None,
        variation_index: int = 0,
        routing: Optional[Any] = None,
        brand_props: Optional[List[str]] = None,
        brand_profile: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Составляет высокохудожественный промпт для ComfyUI через CinematographyDirector с учетом номера перегенерации,
        Controlled Variance и RAG Brand Identity.
        """
        if custom_prompt and len(custom_prompt.strip()) > 30 and not custom_prompt.startswith("Authentic candid photo of a small tech") and not custom_prompt.startswith("Cinematic emotional culinary"):
            positive_prompt = custom_prompt
        else:
            cinematic_res = CinematographyDirector.compose_cinematic_prompt(
                topic=topic,
                niche=niche,
                brand_colors=brand_colors,
                variation_index=variation_index,
                routing=routing,
                brand_props=brand_props,
                brand_profile=brand_profile
            )
            positive_prompt = cinematic_res["prompt"]

        dimensions = self.ASPECT_RATIOS.get(aspect_ratio, self.ASPECT_RATIOS["1:1"])

        print(f"\n[PhotoGeneratorSkill] 📸 Сформирован промпт для ComfyUI (Ниша: {niche}, Вариация: {variation_index}):\n  👉 {positive_prompt}\n")

        return {
            "positive_prompt": positive_prompt,
            "negative_prompt": self.DEFAULT_NEGATIVE_PROMPT,
            "aspect_ratio": aspect_ratio,
            "width": dimensions[0],
            "height": dimensions[1],
            "niche": niche,
            "topic": topic,
            "variation_index": variation_index
        }

    def _get_font(self, size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """
        Кроссплатформенный загрузчик шрифтов с гарантированной поддержкой кириллицы.
        """
        bundled_font = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "fonts", "brand_font.ttf")
        )
        font_candidates = [
            bundled_font,
            "C:/Windows/Fonts/segoeui.ttf" if not bold else "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arial.ttf" if not bold else "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibri.ttf" if not bold else "C:/Windows/Fonts/calibrib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            "arial.ttf"
        ]

        for path in font_candidates:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    async def generate_photo(
        self,
        topic: str,
        niche: str = "Бизнес",
        aspect_ratio: str = "1:1",
        brand_colors: Optional[List[str]] = None,
        style: str = "photorealistic",
        company_name: str = "UCust",
        attachments: Optional[List[Any]] = None,
        custom_prompt: Optional[str] = None,
        variation_index: int = 0,
        routing: Optional[Any] = None,
        brand_props: Optional[List[str]] = None,
        brand_profile: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Полный цикл генерации профессиональной SMM фотографии и коммерческого визуала (с поддержкой перегенерации).
        """
        prompt_data = self.create_smm_prompt(
            topic=topic,
            niche=niche,
            aspect_ratio=aspect_ratio,
            brand_colors=brand_colors,
            style=style,
            variation_index=variation_index,
            routing=routing,
            brand_props=brand_props,
            brand_profile=brand_profile
        )
        if custom_prompt and len(custom_prompt.strip()) > 30:
            prompt_data["positive_prompt"] = custom_prompt
            print(f"[PhotoGeneratorSkill] 🎯 Использован пользовательский кастомный промпт:\n  👉 {custom_prompt}\n")

        photo_id = f"photo_{uuid.uuid4().hex[:10]}"
        filename = f"{photo_id}.jpg"
        file_path = os.path.join(self.output_dir, filename)

        rendered_via_comfy = False
        # 1. Попытка рендера через ComfyUI API / CLI runner (Realism 2.0)
        try:
            from skills.comfy_cli_runner import ComfyCLIRunner
            comfy_runner = ComfyCLIRunner(output_dir=self.output_dir)
            if await comfy_runner.ensure_server_online():
                has_images = bool(attachments and len(attachments) > 0)
                mode_str = "Edit Mode (True) с апскейлом референсов" if has_images else "Generation Mode (False) с нуля из шума"
                print(f"[PhotoGeneratorSkill] ⚡ ComfyUI (127.0.0.1:8188) онлайн — запуск Realism 2.0 воркфлоу ({mode_str})...")
                res_comfy = await comfy_runner.execute_workflow(
                    photo_prompt=prompt_data["positive_prompt"],
                    raw_topic=topic,
                    negative_prompt=prompt_data["negative_prompt"],
                    aspect_ratio=aspect_ratio,
                    attachments=attachments,
                    edit_mode=has_images
                )
                if res_comfy.get("photo_path") and os.path.exists(res_comfy["photo_path"]) and os.path.getsize(res_comfy["photo_path"]) > 100:
                    file_path = res_comfy["photo_path"]
                    filename = os.path.basename(file_path)
                    rendered_via_comfy = True
            else:
                print("[PhotoGeneratorSkill] ⚠️ Сервер ComfyUI оффлайн даже после автоперезапуска (127.0.0.1:8188 недоступен). Публикация будет выполнена без баннера.")
        except Exception as e:
            print(f"[PhotoGeneratorSkill] ⚠️ Ошибка вызова ComfyUI: {e}")
        # 2. Если ComfyUI не смог сгенерировать фото (оффлайн или ошибка) — НЕ создаем никаких 2D-баннеров!
        # Возвращаем статус no_image, чтобы пост вышел чистым текстом без искусственных картинок.
        if not rendered_via_comfy or not os.path.exists(file_path) or os.path.getsize(file_path) < 100:
            print("[PhotoGeneratorSkill] ℹ️ Фото не сгенерировано ComfyUI. Публикация будет выполнена в чистом текстовом формате без искусственных баннеров.")
            return {
                "status": "no_image",
                "photo_id": None,
                "filename": None,
                "image_url": None,
                "file_path": None,
                "positive_prompt": prompt_data["positive_prompt"],
                "negative_prompt": prompt_data["negative_prompt"],
                "aspect_ratio": aspect_ratio,
                "width": prompt_data["width"],
                "height": prompt_data["height"],
                "created_at": datetime.utcnow().isoformat()
            }

        # 3. Формирование публичного URL реального фото
        relative_url = f"/output/photos/{filename}"

        return {
            "status": "success",
            "photo_id": photo_id,
            "filename": filename,
            "image_url": relative_url,
            "file_path": file_path,
            "positive_prompt": prompt_data["positive_prompt"],
            "negative_prompt": prompt_data["negative_prompt"],
            "aspect_ratio": aspect_ratio,
            "width": prompt_data["width"],
            "height": prompt_data["height"],
            "created_at": datetime.utcnow().isoformat()
        }


__all__ = ["PhotoGeneratorSkill"]
