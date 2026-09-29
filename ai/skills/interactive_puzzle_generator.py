"""
InteractivePuzzleGenerator — Модуль создания интерактивных каруселей-пазлов (Mix & Match Cryptex) для Telegram в UCust AI.

Функционал:
1. Сценарный конструктор согласованных промптов с фиксированной оптикой (35° tilt, 50/85mm, Centered X=50%, Grounding Anchor).
2. Precision Image Slicer: Бесшовная нарезка сгенерированных мастер-кадров на 4 горизонтальных слоя (Y: 0-22%, 22-44%, 44-76%, 76-100%).
3. Scrambler: Стартовая перетасовка слоев для создания вирусного интерактивного вызова в Telegram.
4. Экспорт медиагрупп и генерация интерактивного HTML-превью для тестирования.
"""

from __future__ import annotations

import os
import uuid
import logging
from dataclasses import dataclass, field
try:
    from PIL import Image
except ImportError:
    Image = None

logger = logging.getLogger("InteractivePuzzleGenerator")

# Стандартные относительные границы швов по высоте (Y-координаты от 0.0 до 1.0)
DEFAULT_SEAM_RATIOS: List[Tuple[float, float]] = [
    (0.00, 0.22),  # Слой 1: Фон / Окружение / Торс / Верхняя атмосфера
    (0.22, 0.44),  # Слой 2: Крышка / Латте-арт / Пенка / Верхняя часть объекта
    (0.44, 0.76),  # Слой 3: Тело объекта / Стакан / Рука / Хват / Текстура
    (0.76, 1.00),  # Слой 4: Базовый якорь / Опорный стол / Падающая тень
]


@dataclass
class PuzzlePreset:
    """Шаблон интерактивного пазла под нишу."""
    niche: str
    title: str
    cta_hook: str
    layer_descriptions: List[str]
    master_scenes: List[Dict[str, str]]


PUZZLE_PRESETS: Dict[str, PuzzlePreset] = {
    "coffee": PuzzlePreset(
        niche="Specialty Coffee",
        title="Кофейный конструктор настроения (Mix & Match)",
        cta_hook="Свайпай ряды и собери свой идеальный (или самый безумный) кофейный муд на сегодня! Скидывай скриншот в комменты 👇",
        layer_descriptions=[
            "Слой 1 (Фон/Персонаж): Атмосфера кофейни и бариста",
            "Слой 2 (Верх): Крышка, латте-арт или трубочка",
            "Слой 3 (Тело): Тип стакана/кружки и хват руки",
            "Слой 4 (Якорь): Деревянный стол и падающие тени"
        ],
        master_scenes=[
            {
                "name": "classic_togo",
                "layer1": "barista in a black artisan canvas apron with subtle brass pins in a warm sunlit coffee shop background in soft bokeh",
                "layer2": "emerald green premium coffee cup lid with drinking spout",
                "layer3": "emerald green craft paper coffee cup held gently by a hand with clean manicured nails",
                "layer4": "round solid oak counter table with soft directional morning shadows"
            },
            {
                "name": "artisan_latte",
                "layer1": "cozy warm coffee roastery with wooden shelves and glowing amber tungsten lights in soft bokeh",
                "layer2": "open wide cup mouth showcasing intricate swan latte art on silky microfoam crema",
                "layer3": "vintage ceramic speckled beige pottery mug with a cozy rounded handle",
                "layer4": "round solid oak counter table with soft warm side shadows"
            },
            {
                "name": "retro_absurd",
                "layer1": "vintage cozy retro coffee nook with hanging green plants and warm ambient daylight",
                "layer2": "black coffee with golden crema ring and a diagonal retro straw touching the upper edge",
                "layer3": "silver metallic Soviet folding camping cup held firmly by fingers",
                "layer4": "round solid oak counter table with soft contact shadows"
            },
            {
                "name": "modern_iced",
                "layer1": "minimalist scandinavian glass atelier cafe with soft morning window light in creamy bokeh",
                "layer2": "mountain of whipped cream with golden caramel drizzle and cinnamon dust",
                "layer3": "double-walled transparent glass cup revealing layered iced latte and espresso swirl",
                "layer4": "round solid oak counter table with crisp morning ray shadows"
            }
        ]
    ),
    "beauty": PuzzlePreset(
        niche="Beauty & Nail Art",
        title="Нейл-конструктор образа (Nail Art Slicer)",
        cta_hook="Собери весенний сет под свое настроение за 3 свайпа! Какой вариант получился у тебя?",
        layer_descriptions=[
            "Слой 1: Манжет свитера и атмосфера",
            "Слой 2: Кончики ногтей и дизайн",
            "Слой 3: Форма ногтей и фаланговые кольца",
            "Слой 4: Ладонь и шелковая текстура"
        ],
        master_scenes=[
            {
                "name": "minimal_glitter",
                "layer1": "cozy ribbed cashmere knit sweater cuff in soft oatmeal beige tone",
                "layer2": "short elegant fingernail tips dusted with micro-fine champagne glitter catching the light",
                "layer3": "slender fingers in a relaxed natural pose with delicate gold knuckle ring",
                "layer4": "resting on cream silk drape and matte travertine stone pedestal"
            },
            {
                "name": "satin_pearl",
                "layer1": "soft cream alpaca wool cardigan sleeve with warm morning rim light",
                "layer2": "glossy satin-finish pearl chrome tips reflecting subtle iridescent glow",
                "layer3": "gentle almond-shaped nails in soft taupe nude shade",
                "layer4": "resting on cream silk drape and natural light beige marble"
            },
            {
                "name": "chocolate_french",
                "layer1": "dark chocolate brown textured wool blazer sleeve in soft aesthetic focus",
                "layer2": "ultra-thin minimalist deep espresso french manicure tips",
                "layer3": "natural short rounded nails with smooth skin texture",
                "layer4": "resting on cream silk drape and minimalist ceramic surface"
            }
        ]
    ),
    "legal": PuzzlePreset(
        niche="Legal & Corporate Law",
        title="Анатомия безупречной сделки (Legal Shield Architecture)",
        cta_hook="Из каких уровней складывается правовая неуязвимость бизнеса? Свайпайте слои и оцените баланс защищенности вашей компании. Напишите в комментариях, какой аспект сейчас в приоритете 👇",
        layer_descriptions=[
            "Слой 1 (Top/Статус): Окружение, партнер бюро и атмосфера",
            "Слой 2 (Документ): Прошитый договор M&A, аудит или заключение",
            "Слой 3 (Атрибут): Перьевая ручка Montblanc, печать, кожаная папка",
            "Слой 4 (Якорь): Стол из мореного дуба и латунные часы"
        ],
        master_scenes=[
            {
                "name": "ma_deal_shield",
                "layer1": "senior partner in tailored dark navy wool suit standing in a private law library with leather-bound legal folios in soft warm bokeh",
                "layer2": "thick bound corporate M&A agreement on premium parchment with red wax seal and embossed crest",
                "layer3": "classic black Montblanc Meisterstuck fountain pen held gently by an executive hand with gold cufflinks",
                "layer4": "massive aged bog oak table with subtle reflections and antique brass desk clock"
            },
            {
                "name": "tax_due_diligence",
                "layer1": "modern panoramic glass-walled executive conference room in Moscow-City with soft natural corporate daylight",
                "layer2": "official tax audit and risk assessment dossier with clean minimalist infographics and notarized stamp",
                "layer3": "rich burgundy calfskin leather document holder with golden brass clasp",
                "layer4": "polished dark emerald marble tabletop with refined geometric shadow lines"
            },
            {
                "name": "court_litigation",
                "layer1": "solemn legal chambers with dark walnut wood wall paneling and warm ambient lighting",
                "layer2": "official arbitration court settlement brief with embossed judicial stamp",
                "layer3": "heavy polished solid brass advocate seal and signet ring on finger",
                "layer4": "solid walnut table with polished lacquer finish and subtle leather blotter"
            }
        ]
    ),
    "banking": PuzzlePreset(
        niche="Private Banking & Wealth Management",
        title="Архитектура инвестиционного портфеля (Portfolio Balance Slicer)",
        cta_hook="В управлении капиталом решает гармония базы, ликвидности и активов роста. Прокрутите слои и соберите ваш целевой профиль на 2026 год. Какая стратегия ближе вам?",
        layer_descriptions=[
            "Слой 1 (Горизонт): Панорамный финансовый центр / Кабинет",
            "Слой 2 (Класс активов): Физическое золото, облигации, фонды",
            "Слой 3 (Инструмент): Металлическая карта Private Banking / Хронограф",
            "Слой 4 (Опора/База): Гранитный или мраморный постамент"
        ],
        master_scenes=[
            {
                "name": "conservative_gold",
                "layer1": "panoramic floor-to-ceiling glass window overlooking a sunny financial skyline in soft high-end bokeh",
                "layer2": "cast 999.9 physical fine gold bullion bar resting on dark navy velvet fabric",
                "layer3": "sleek heavy matte black metal Private Banking credit card held between fingers with platinum ring",
                "layer4": "honed black granite pedestal with crisp directional morning light"
            },
            {
                "name": "balanced_bonds",
                "layer1": "quiet private wealth management office with soft ambient wood textures and discreet Bloomberg terminal glow",
                "layer2": "structured premium sovereign bond certificates on textured cream security paper",
                "layer3": "luxury Swiss mechanical chronograph watch with alligator leather strap on executive wrist",
                "layer4": "solid Burmese teak wooden desk with warm natural grain and soft ambient shadow"
            },
            {
                "name": "growth_tech_equity",
                "layer1": "architectural penthouse terrace with clean minimalist concrete lines and morning sunrise light",
                "layer2": "holographic venture equity portfolio certificate in a minimalist carbon frame",
                "layer3": "brushed titanium biometric digital wealth key held steadily by hand",
                "layer4": "flawless white Italian Carrara marble surface with subtle grey veining"
            }
        ]
    )
}


@dataclass
class PuzzleDecision:
    """Решение оценщика триггеров: уместен ли интерактивный пазл."""
    should_use_puzzle: bool
    relevance_score: float  # от 0.0 до 1.0
    recommended_preset: str
    situation_type: str
    rationale: str
    suggested_cta: str
    optimal_time_window: str


class PuzzleTriggerEvaluator:
    """
    Интеллектуальный оценщик уместности интерактивного пазл-поста.
    Анализирует нишу, день недели, время, цели кампании и метрики вовлечения.
    """

    NICHE_MAPPING = {
        "coffee": ["кофе", "кофейня", "specialty coffee", "кофейный", "кафе", "cafe", "бариста", "horeca", "чай", "пекарня"],
        "beauty": ["ногти", "маникюр", "бьюти", "beauty", "салон красоты", "nail", "нейл", "косметика", "стилист", "spa", "спа"],
        "legal": ["юрист", "юриспруденция", "адвокат", "право", "legal", "law", "m&a", "налоги", "консалтинг", "нотариус", "арбитраж"],
        "banking": ["банк", "banking", "инвестиции", "private banking", "финансы", "капитал", "wealth", "управление активами", "фонд", "крипто"]
    }

    @classmethod
    def resolve_preset(cls, niche_input: str) -> str:
        """Определяет подходящий пресет по текстовому описанию ниши."""
        niche_lower = (niche_input or "").lower()
        for preset_key, keywords in cls.NICHE_MAPPING.items():
            if any(kw in niche_lower for kw in keywords):
                return preset_key
        return "coffee"  # Дефолтный универсальный пресет

    @classmethod
    def evaluate(
        cls,
        company_name: str,
        niche: str,
        post_goal: Optional[str] = None,
        day_of_week: Optional[int] = None,
        hour: Optional[int] = None,
        recent_engagement_drop: bool = False
    ) -> PuzzleDecision:
        """
        Анализирует контекст и выносит вердикт о целесообразности публикации пазла.
        
        Параметры:
        - day_of_week: 0=Понедельник, 1=Вторник, ..., 4=Пятница, 5=Суббота, 6=Воскресенье.
        - hour: Час публикации (0-23).
        - recent_engagement_drop: Флаг падения охватов за последние дни.
        """
        from datetime import datetime
        now = datetime.now()
        dow = day_of_week if day_of_week is not None else now.weekday()
        current_hour = hour if hour is not None else now.hour
        goal = (post_goal or "").lower()

        preset_key = cls.resolve_preset(niche)
        preset = PUZZLE_PRESETS[preset_key]

        score = 0.5  # Базовая релевантность
        situation = "standard_interactive"
        rationale_parts = []

        # 1. Анализ целей кампании
        if "engagement" in goal or "boost" in goal or "вовлеч" in goal or recent_engagement_drop:
            score += 0.35
            situation = "engagement_resuscitation"
            rationale_parts.append("Необходим алгоритмический буст охватов и оживление комментариев (Dwell Time 60+ сек).")
        elif "launch" in goal or "menu" in goal or "меню" in goal or "новинк" in goal or "коллекци" in goal:
            score += 0.30
            situation = "product_lineup_showcase"
            rationale_parts.append("Презентация вариативности нового меню/линейки через игровой конструктор.")
        elif "b2b" in goal or "expert" in goal or "эксперт" in goal or preset_key in ("legal", "banking"):
            score += 0.25
            situation = "b2b_authority_explainer"
            rationale_parts.append("Демонстрация фундаментальности и многоуровневой структуры услуг (экспертный статус).")
        elif "choice" in goal or "выбор" in goal or "рулетк" in goal:
            score += 0.25
            situation = "choice_paralysis_remover"
            rationale_parts.append("Снятие барьера выбора у клиента через геймифицированную рулетку образов.")

        # 2. Календарные и временные триггеры
        if dow == 0 and 7 <= current_hour <= 11:
            score += 0.20
            situation = "monday_morning_mood"
            rationale_parts.append("Утро понедельника: аудитории требуется легкий бодрящий интерактив ('Муд недели').")
            time_window = "08:00 - 10:30 (Утренний пик)"
        elif dow == 4 and 15 <= current_hour <= 20:
            score += 0.15
            situation = "friday_evening_chill"
            rationale_parts.append("Вечер пятницы: расслабленный развлекательный контент перед выходными.")
            time_window = "16:30 - 19:30 (Пятничный релакс)"
        elif dow in (5, 6):
            score += 0.10
            situation = "weekend_lifestyle"
            rationale_parts.append("Выходной день: пользователи дольше листают визуальный эстетичный контент.")
            time_window = "11:00 - 15:00 (Дневной уикенд)"
        else:
            time_window = "12:00 - 14:00 (Обеденный прайм-тайм)"

        # Нормализация скора
        final_score = min(1.0, round(score, 2))
        should_use = final_score >= 0.65

        rationale = " ".join(rationale_parts) if rationale_parts else "Стандартная ротация визуальных форматов для поддержания вовлеченности."

        return PuzzleDecision(
            should_use_puzzle=should_use,
            relevance_score=final_score,
            recommended_preset=preset_key,
            situation_type=situation,
            rationale=rationale,
            suggested_cta=preset.cta_hook,
            optimal_time_window=time_window
        )


class InteractivePuzzleSlicer:
    """
    Высокоточный нарезчик изображений для интерактивных Telegram-каруселей.
    """

    def __init__(self, seam_ratios: Optional[List[Tuple[float, float]]] = None):
        self.seam_ratios = seam_ratios or DEFAULT_SEAM_RATIOS

    def slice_image(self, image: Image.Image) -> List[Image.Image]:
        """
        Разрезает одно мастер-изображение на горизонтальные полосы по заданным швам.
        """
        width, height = image.size
        slices: List[Image.Image] = []

        for top_ratio, bottom_ratio in self.seam_ratios:
            top_px = int(round(height * top_ratio))
            bottom_px = int(round(height * bottom_ratio))
            
            # Коррекция последней полосы во избежание потери нижних пикселей
            if bottom_ratio >= 0.999:
                bottom_px = height

            cropped = image.crop((0, top_px, width, bottom_px))
            slices.append(cropped)

        return slices

    def slice_batch(self, images: List[Image.Image]) -> List[List[Image.Image]]:
        """
        Разрезает список мастер-кадров и перегруппировывает их по слоям (Layer Albums).
        
        Возвращает матрицу `layers[layer_idx][variation_idx]`:
        - layers[0] = [Кадр1_Слой1, Кадр2_Слой1, Кадр3_Слой1, ...]
        - layers[1] = [Кадр1_Слой2, Кадр2_Слой2, Кадр3_Слой2, ...]
        - layers[2] = [Кадр1_Слой3, Кадр2_Слой3, Кадр3_Слой3, ...]
        - layers[3] = [Кадр1_Слой4, Кадр2_Слой4, Кадр3_Слой4, ...]
        """
        num_layers = len(self.seam_ratios)
        layer_pools: List[List[Image.Image]] = [[] for _ in range(num_layers)]

        for img in images:
            img_slices = self.slice_image(img)
            for layer_idx, slice_img in enumerate(img_slices):
                layer_pools[layer_idx].append(slice_img)

        return layer_pools

    def export_puzzle_package(
        self,
        layer_pools: List[List[Image.Image]],
        output_dir: str,
        prefix: str = "puzzle"
    ) -> Dict[str, Any]:
        """
        Сохраняет все нарезанные полосы в структурированную директорию и генерирует HTML-интерактив.
        """
        os.makedirs(output_dir, exist_ok=True)
        manifest: Dict[str, Any] = {
            "prefix": prefix,
            "num_layers": len(layer_pools),
            "layers": []
        }

        saved_files: List[List[str]] = []

        for layer_idx, pool in enumerate(layer_pools):
            layer_files: List[str] = []
            layer_dir = os.path.join(output_dir, f"layer_{layer_idx + 1}")
            os.makedirs(layer_dir, exist_ok=True)

            for var_idx, slice_img in enumerate(pool):
                filename = f"{prefix}_L{layer_idx + 1}_V{var_idx + 1}.jpg"
                file_path = os.path.join(layer_dir, filename)
                slice_img.save(file_path, "JPEG", quality=95)
                layer_files.append(file_path)

            saved_files.append(layer_files)
            manifest["layers"].append({
                "layer_index": layer_idx + 1,
                "variations_count": len(pool),
                "files": layer_files
            })

        # Генерация автономного HTML-симулятора Telegram-карусели
        html_path = os.path.join(output_dir, "telegram_puzzle_preview.html")
        self._generate_html_preview(saved_files, html_path)
        manifest["html_preview"] = html_path

        return manifest

    @classmethod
    def create_telegram_slot_machine_package(
        cls,
        image_paths: List[str],
        output_dir: str,
        num_rows: int = 4,
        target_slice_size: Tuple[int, int] = (1200, 300),
        scramble: bool = True,
        use_anatomical_seams: bool = True
    ) -> List[List[str]]:
        """
        Создает 4-этажный пакет альбомов для интерактивного Telegram Свайп-пазла:
        - Ряд 1 (Y: 0-22%): Атмосфера / Верх ветвей вербы / Окно (до верхушки кулича)
        - Ряд 2 (Y: 22-44%): Купол / Белоснежная глазурь / Разноцветная посыпка / Золото
        - Ряд 3 (Y: 44-72%): Форма для выпечки (капсула) / Капли глазури / Верхняя тарелка подставки
        - Ряд 4 (Y: 72-100%): Ножка подставки / Стол / Пиала с крашеными яйцами / Декор
        """
        if not Image:
            logger.error("PIL (Pillow) не установлен!")
            return []

        valid_paths = [p for p in image_paths if os.path.exists(p)]
        if not valid_paths:
            return []

        os.makedirs(output_dir, exist_ok=True)
        num_variations = len(valid_paths)

        # Открываем мастер-изображения и приводим к единому квадратному размеру (1200x1200)
        master_imgs = []
        square_dim = target_slice_size[0]  # 1200
        for p in valid_paths:
            with Image.open(p) as img:
                img_sq = ImageOps.fit(img, (square_dim, square_dim), Image.Resampling.LANCZOS)
                master_imgs.append(img_sq)

        target_w, target_h = target_slice_size

        # Анатомические швы по 4 уровням объекта
        if use_anatomical_seams and num_rows == 4:
            seams = [
                (0.00, 0.22),  # Ряд 1: Фон / Окно / Верба
                (0.22, 0.44),  # Ряд 2: Купол глазури / Посыпка
                (0.44, 0.72),  # Ряд 3: Тело кулича / Капсула / Верх подставки
                (0.72, 1.00)   # Ряд 4: Ножка подставки / Стол / Яйца
            ]
        else:
            seams = [(i / num_rows, (i + 1) / num_rows) for i in range(num_rows)]

        row_albums: List[List[str]] = [[] for _ in range(num_rows)]

        for v_idx, img_sq in enumerate(master_imgs):
            for r_idx, (top_r, bot_r) in enumerate(seams):
                top_y = int(round(square_dim * top_r))
                bottom_y = int(round(square_dim * bot_r))
                if bot_r >= 0.999:
                    bottom_y = square_dim

                cropped = img_sq.crop((0, top_y, square_dim, bottom_y))
                slice_resized = ImageOps.fit(cropped, (target_w, target_h), Image.Resampling.LANCZOS)

                slice_path = os.path.join(output_dir, f"row{r_idx + 1}_var{v_idx + 1}.jpg")
                slice_resized.save(slice_path, "JPEG", quality=95)
                row_albums[r_idx].append(os.path.abspath(slice_path))

        # Перетасовка (Scramble): сдвигаем стартовые позиции в каждом ряду
        if scramble and num_variations > 1:
            scrambled_albums: List[List[str]] = []
            for r_idx, album in enumerate(row_albums):
                shift = (r_idx + 1) % len(album)
                scrambled = album[shift:] + album[:shift]
                scrambled_albums.append(scrambled)
            return scrambled_albums

        return row_albums

    def _generate_html_preview(self, saved_files: List[List[str]], html_path: str):
        """Создает интерактивную HTML-страничку со свайпами и стрелками (точная копия Telegram)."""
        import json

        relative_files = []
        base_dir = os.path.dirname(html_path)
        for layer in saved_files:
            rel_layer = [os.path.relpath(f, base_dir).replace("\\", "/") for f in layer]
            relative_files.append(rel_layer)

        html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UCust AI: Telegram Interactive Puzzle Preview</title>
    <style>
        body {{
            background-color: #0f141c;
            color: #ffffff;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
            margin: 0;
        }}
        h2 {{
            color: #4fa4f3;
            margin-bottom: 5px;
        }}
        p.subtitle {{
            color: #8b98a5;
            font-size: 14px;
            margin-bottom: 20px;
        }}
        .tg-container {{
            width: 380px;
            background: #17212b;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            display: flex;
            flex-direction: column;
        }}
        .puzzle-viewport {{
            width: 100%;
            display: flex;
            flex-direction: column;
            gap: 1px;
            background: #0e1621;
        }}
        .puzzle-layer {{
            position: relative;
            width: 100%;
            overflow: hidden;
            user-select: none;
        }}
        .layer-slider {{
            display: flex;
            transition: transform 0.25s cubic-bezier(0.25, 1, 0.5, 1);
            width: 100%;
        }}
        .layer-slide {{
            min-width: 100%;
            max-width: 100%;
            display: flex;
        }}
        .layer-slide img {{
            width: 100%;
            height: auto;
            display: block;
        }}
        .nav-btn {{
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            background: rgba(0, 0, 0, 0.55);
            color: white;
            border: none;
            width: 28px;
            height: 28px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            opacity: 0.8;
            transition: opacity 0.2s, background 0.2s;
            z-index: 10;
        }}
        .nav-btn:hover {{
            opacity: 1;
            background: rgba(82, 136, 193, 0.85);
        }}
        .prev-btn {{ left: 8px; }}
        .next-btn {{ right: 8px; }}
        .dots {{
            position: absolute;
            bottom: 4px;
            left: 50%;
            transform: translateX(-50%);
            display: flex;
            gap: 4px;
            z-index: 10;
        }}
        .dot {{
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.4);
            transition: background 0.2s;
        }}
        .dot.active {{
            background: #ffffff;
            width: 7px;
        }}
        .caption {{
            padding: 12px 14px;
            font-size: 14px;
            line-height: 1.4;
            color: #f5f5f5;
        }}
        .caption .hook {{
            font-weight: bold;
            color: #64b5f6;
            margin-bottom: 6px;
        }}
        .stats {{
            padding: 0 14px 10px 14px;
            font-size: 11px;
            color: #6c7883;
            display: flex;
            justify-content: space-between;
        }}
    </style>
</head>
<body>
    <h2>🚀 UCust AI: Interactive Mix & Match Puzzle</h2>
    <p class="subtitle">Симуляция интерактивного Telegram-поста со свайпами и независимыми барабанами</p>

    <div class="tg-container">
        <div class="puzzle-viewport" id="puzzleViewport">
            <!-- Layers will be injected here -->
        </div>
        <div class="caption">
            <div class="hook">☕ Давайте поможем собрать идеальный кофейный муд!</div>
            <div>Листай стрелками или свайпай ряды влево/вправо. Напиши в комменты, какая комбинация получилась у тебя! 🚀</div>
        </div>
        <div class="stats">
            <span>👁 86.4K 16:45</span>
            <span>↗ 1.4K пересылок</span>
        </div>
    </div>

    <script>
        const layersData = {json.dumps(relative_files)};
        const viewport = document.getElementById('puzzleViewport');

        layersData.forEach((layerImages, layerIdx) => {{
            const layerEl = document.createElement('div');
            layerEl.className = 'puzzle-layer';

            const sliderEl = document.createElement('div');
            sliderEl.className = 'layer-slider';
            sliderEl.id = `slider_${{layerIdx}}`;

            layerImages.forEach(imgSrc => {{
                const slideEl = document.createElement('div');
                slideEl.className = 'layer-slide';
                const imgEl = document.createElement('img');
                imgEl.src = imgSrc;
                slideEl.appendChild(imgEl);
                sliderEl.appendChild(slideEl);
            }});

            layerEl.appendChild(sliderEl);

            if (layerImages.length > 1) {{
                const prevBtn = document.createElement('button');
                prevBtn.className = 'nav-btn prev-btn';
                prevBtn.innerHTML = '‹';
                prevBtn.onclick = () => moveSlide(layerIdx, -1);

                const nextBtn = document.createElement('button');
                nextBtn.className = 'nav-btn next-btn';
                nextBtn.innerHTML = '›';
                nextBtn.onclick = () => moveSlide(layerIdx, 1);

                const dotsContainer = document.createElement('div');
                dotsContainer.className = 'dots';
                dotsContainer.id = `dots_${{layerIdx}}`;

                layerImages.forEach((_, i) => {{
                    const dot = document.createElement('div');
                    dot.className = `dot ${{i === 0 ? 'active' : ''}}`;
                    dotsContainer.appendChild(dot);
                }});

                layerEl.appendChild(prevBtn);
                layerEl.appendChild(nextBtn);
                layerEl.appendChild(dotsContainer);
            }}

            viewport.appendChild(layerEl);
        }});

        const currentIndices = new Array(layersData.length).fill(0);

        function moveSlide(layerIdx, delta) {{
            const total = layersData[layerIdx].length;
            currentIndices[layerIdx] = (currentIndices[layerIdx] + delta + total) % total;
            const slider = document.getElementById(`slider_${{layerIdx}}`);
            slider.style.transform = `translateX(-${{currentIndices[layerIdx] * 100}}%)`;

            const dots = document.getElementById(`dots_${{layerIdx}}`).children;
            for (let i = 0; i < dots.length; i++) {{
                dots[i].className = `dot ${{i === currentIndices[layerIdx] ? 'active' : ''}}`;
            }}
        }}
    </script>
</body>
</html>
"""
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)


class CinematographyDirectorPuzzleExtension:
    """
    Расширение для CinematographyDirector: Составляет согласованный батч промптов
    для рендера 3-4 полноценных сцен с единым сидом, оптикой и физическим якорем.
    """

    @staticmethod
    def compose_puzzle_batch(niche_key: str = "coffee", company_name: str = "Specialty Coffee") -> List[str]:
        preset = PUZZLE_PRESETS.get(niche_key, PUZZLE_PRESETS["coffee"])
        prompts: List[str] = []

        if niche_key in ("legal", "banking"):
            base_analog_camera = (
                "Shot on Hasselblad H6D-100c, 85mm prime lens f/2.8, camera angled downwards at 35 degrees tilt, "
                "focus pinned precisely on the center vertical axis of executive documents and high-end materials, "
                "authentic 35mm RAW color photo with natural fine organic film grain Kodak Portra 400 ISO 400:1.15, "
                "soft corporate architectural daylight 5600K with deep rich contrast and subtle warm rim light, "
                "hyper-realistic physical textures of bog oak, calfskin leather, polished brass, and marble, zero CGI, zero 3D artifacts"
            )
            hero_prefix = f"High-end corporate editorial presentation for {company_name}."
        elif niche_key == "beauty":
            base_analog_camera = (
                "Shot on Hasselblad H6D-100c, 85mm macro prime lens f/2.8, camera angled downwards at 35 degrees tilt, "
                "focus pinned precisely on the center vertical axis of the hands and manicured nails, "
                "authentic 35mm RAW color photo with natural fine organic film grain Kodak Portra 400 ISO 400:1.15, "
                "soft morning sunrise window light 5600K, soft skin subsurface scattering, hyper-realistic physical materials, zero CGI"
            )
            hero_prefix = f"Luxury beauty and nail art editorial shot for {company_name}."
        else:
            base_analog_camera = (
                "Shot on Hasselblad H6D-100c, 85mm prime lens f/2.8, camera angled downwards at 35 degrees tilt, "
                "focus pinned precisely on the center vertical axis of the beverage and hand, "
                "authentic 35mm RAW color photo with natural fine organic film grain Kodak Portra 400 ISO 400:1.15, "
                "soft directional morning window daylight 5600K from upper left, hyper-realistic physical materials, "
                "subsurface scattering on skin, zero CGI, zero 3d render artifacts"
            )
            hero_prefix = f"Commercial hero shot of an artisan beverage presentation for {company_name}."

        for scene in preset.master_scenes:
            full_prompt = (
                f"{hero_prefix} "
                f"Top background layer shows {scene['layer1']}. "
                f"Upper middle section features {scene['layer2']}. "
                f"Center focal body features {scene['layer3']}. "
                f"Base grounding bottom layer rests firmly on {scene['layer4']}. "
                f"{base_analog_camera}."
            )
            prompts.append(full_prompt)

        return prompts
