# File: ai/skills/mosaic_grid_composer.py
"""
MosaicGridComposer — Профессиональный инструмент сборки и разделения мозаик (2x2 Grid / Quadrants / Collage) для UCust AI.

Функции:
1. compose_2x2_grid: Объединяет 4 согласованных изображения в единый мастер-кадр 2x2 с опциональным разделителем (gap) или бесшовно.
2. create_quadrant_blend: Формирует сплит-мозаику из 4 разных сцен (Top-Left, Top-Right, Bottom-Left, Bottom-Right) вокруг единого центра.
3. split_2x2_quadrants: Нарезает квадратное изображение (1:1) на 4 квадранта для загрузки в соцсети.
"""

from __future__ import annotations

import os
import logging
from typing import List, Tuple, Optional
try:
    from PIL import Image, ImageDraw, ImageOps
except ImportError:
    Image = None

logger = logging.getLogger("MosaicGridComposer")


class MosaicGridComposer:
    """Утилита сборки и нарезки мозаичных композиций 2x2."""

    @staticmethod
    def compose_2x2_grid(
        image_paths: List[str],
        output_path: Optional[str] = None,
        target_size: Tuple[int, int] = (2048, 2048),
        gap: int = 0,
        gap_color: str = "#FFFFFF"
    ) -> Optional[str]:
        """
        Объединяет 4 изображения в квадратный коллаж 2x2.
        Порядок:
        [0: Top-Left ] [1: Top-Right   ]
        [2: Bottom-Left] [3: Bottom-Right]
        """
        if not Image:
            logger.error("PIL (Pillow) не установлен!")
            return None

        if len(image_paths) < 4:
            logger.warning(f"Ожидалось 4 изображения, получено {len(image_paths)}. Повторяем последние.")
            while len(image_paths) < 4:
                image_paths.append(image_paths[-1])

        try:
            total_w, total_h = target_size
            cell_w = (total_w - gap) // 2
            cell_h = (total_h - gap) // 2

            master = Image.new("RGB", (total_w, total_h), gap_color)

            positions = [
                (0, 0),                        # Top-Left
                (cell_w + gap, 0),             # Top-Right
                (0, cell_h + gap),             # Bottom-Left
                (cell_w + gap, cell_h + gap)   # Bottom-Right
            ]

            for idx, img_p in enumerate(image_paths[:4]):
                if not os.path.exists(img_p):
                    continue
                with Image.open(img_p) as img:
                    img_resized = ImageOps.fit(img, (cell_w, cell_h), Image.Resampling.LANCZOS)
                    master.paste(img_resized, positions[idx])

            if not output_path:
                out_dir = os.path.dirname(image_paths[0])
                base_name = os.path.splitext(os.path.basename(image_paths[0]))[0]
                output_path = os.path.join(out_dir, f"{base_name}_mosaic_2x2.jpg")

            master.save(output_path, "JPEG", quality=95)
            logger.info(f"✅ Мозаика 2x2 успешно создана: {output_path}")
            return output_path

        except Exception as err:
            logger.error(f"Ошибка создания мозаики 2x2: {err}")
            return None

    @staticmethod
    def create_quadrant_blend(
        image_paths: List[str],
        output_path: Optional[str] = None,
        target_size: Tuple[int, int] = (2048, 2048)
    ) -> Optional[str]:
        """
        Берёт из каждого из 4 изображений его соответствующий квадрант (TL, TR, BL, BR)
        и соединяет в одну цельную картину с единым объектом по центру и 4 разными углами интерьера.
        """
        if not Image or len(image_paths) < 4:
            return MosaicGridComposer.compose_2x2_grid(image_paths, output_path, target_size, gap=0)

        try:
            total_w, total_h = target_size
            half_w = total_w // 2
            half_h = total_h // 2

            master = Image.new("RGB", (total_w, total_h))

            # Квадранты (box: left, upper, right, lower)
            quadrant_boxes = [
                (0, 0, half_w, half_h),           # Top-Left
                (half_w, 0, total_w, half_h),     # Top-Right
                (0, half_h, half_w, total_h),     # Bottom-Left
                (half_w, half_h, total_w, total_h)# Bottom-Right
            ]

            for idx, img_p in enumerate(image_paths[:4]):
                if not os.path.exists(img_p):
                    continue
                with Image.open(img_p) as img:
                    img_sq = ImageOps.fit(img, (total_w, total_h), Image.Resampling.LANCZOS)
                    box = quadrant_boxes[idx]
                    crop_part = img_sq.crop(box)
                    master.paste(crop_part, box)

            if not output_path:
                out_dir = os.path.dirname(image_paths[0])
                base_name = os.path.splitext(os.path.basename(image_paths[0]))[0]
                output_path = os.path.join(out_dir, f"{base_name}_quadrant_blend.jpg")

            master.save(output_path, "JPEG", quality=95)
            logger.info(f"✅ Сплит-квадрант мозаика создана: {output_path}")
            return output_path

        except Exception as err:
            logger.error(f"Ошибка quadrant blend: {err}")
            return None

    @staticmethod
    def split_2x2_quadrants(
        image_path: str,
        output_dir: Optional[str] = None
    ) -> List[str]:
        """
        Разрезает 1 квадратный мастер-кадр на 4 квадранта (TL, TR, BL, BR) для раздельной публикации.
        """
        if not Image or not os.path.exists(image_path):
            return []

        try:
            if not output_dir:
                output_dir = os.path.dirname(image_path)
            base_name = os.path.splitext(os.path.basename(image_path))[0]

            with Image.open(image_path) as img:
                w, h = img.size
                half_w = w // 2
                half_h = h // 2

                quads = [
                    ("top_left", (0, 0, half_w, half_h)),
                    ("top_right", (half_w, 0, w, half_h)),
                    ("bottom_left", (0, half_h, half_w, h)),
                    ("bottom_right", (half_w, half_h, w, h)),
                ]

                results = []
                for name, box in quads:
                    crop_img = img.crop(box)
                    out_p = os.path.join(output_dir, f"{base_name}_{name}.jpg")
                    crop_img.save(out_p, "JPEG", quality=95)
                    results.append(os.path.abspath(out_p))

                return results
        except Exception as err:
            logger.error(f"Ошибка нарезки 2x2: {err}")
            return []
