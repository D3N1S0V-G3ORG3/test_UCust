"""
Internal Calendar and Temporal Grounding Engine for UCust.AI.
"""
from __future__ import annotations
import os
import re
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
try:
    from collectors.event_holiday_collector import EventHolidayCollector
except ImportError:
    try:
        from ai.collectors.event_holiday_collector import EventHolidayCollector
    except ImportError:
        EventHolidayCollector = None

class InternalCalendarEngine:
    _instance: Optional[InternalCalendarEngine] = None

    DAY_PSYCHOLOGY = {
        0: {"name": "Понедельник", "vibe": "Фокус на целях, планирование недели, старт новых процессов, собранность"},
        1: {"name": "Вторник", "vibe": "Максимальная концентрация, разбор сложных задач и экспертные темы"},
        2: {"name": "Среда", "vibe": "Экватор недели, преодоление рутины, оптимизация, инструменты и автоматизация"},
        3: {"name": "Четверг", "vibe": "Практические результаты, кейсы, подготовка решений и сильных офферов"},
        4: {"name": "Пятница", "vibe": "Итоги недели, легкий тон, предвкушение выходных, специальные предложения и разгрузка"},
        5: {"name": "Суббота", "vibe": "Лайфстайл, отдых, семья, вдохновение, неформальное теплое общение"},
        6: {"name": "Воскресенье", "vibe": "Перезагрузка, мысли о будущем, спокойные размышления и подготовка к старту"}
    }

    SEASONS = {
        (3, 4, 5): {
            "season": "Весна",
            "lighting_mod": "fresh bright spring daylight with gentle floral warmth",
            "palette": "fresh emerald, warm ivory, soft floral tones",
            "narrative_focus": "обновление, свежий старт, весенний рост и пробуждение"
        },
        (6, 7, 8): {
            "season": "Лето",
            "lighting_mod": "vibrant warm summer daylight with crisp defined shadows",
            "palette": "golden sunlight, rich warm neutrals, vibrant accents",
            "narrative_focus": "высокий сезон, динамика, энергия, скорость и активность"
        },
        (9, 10, 11): {
            "season": "Осень",
            "lighting_mod": "subtle golden hour autumn daylight casting gentle organic room shadows",
            "palette": "amber, warm cognac, terracotta, cozy beige, dark walnut",
            "narrative_focus": "деловой сезон, сбор урожая результатов, масштабирование, уют и надежность"
        },
        (12, 1, 2): {
            "season": "Зима",
            "lighting_mod": "soft diffused winter window daylight with warm 3000K interior accent",
            "palette": "deep navy, graphite, warm amber light, cream wool",
            "narrative_focus": "итоги года, новогодние цели, надежность в холода, забота и тепло"
        }
    }

    TIME_OF_DAY_SLOTS = [
        (range(6, 11), {
            "phase": "Утро",
            "code": "morning",
            "vibe": "Утренний фокус, заряд энергии, чашка кофе, бодрость, старт рабочего дня раньше всех",
            "caring_subtext": "Мы уже на месте с первой чашкой кофе, всё настроили и готовы решать ваши задачи с самого утра.",
            "window_lighting": "gentle morning window daylight with soft angled sunbeams, subtle translucent coffee vapor, fresh crisp shadows",
            "indoor_lighting": "crisp focused morning task lighting with soft ambient room falloff, steaming ceramic mug, fresh energetic studio ambiance"
        }),
        (range(11, 17), {
            "phase": "День",
            "code": "afternoon",
            "vibe": "Деловая активность, решение задач, разбор процессов, высокая продуктивность и скорость",
            "caring_subtext": "В самом разгаре рабочего дня — держим руку на пульсе ваших проектов и процессов.",
            "window_lighting": "crisp clean neutral 5000K daylight from windows, balanced realistic micro-shadows, productive atmosphere",
            "indoor_lighting": "balanced neutral task illumination with clean micro-shadows, sharp product clarity, productive studio setting"
        }),
        (range(17, 22), {
            "phase": "Вечер",
            "code": "evening",
            "vibe": "Подведение итогов дня, завершение рабочих процессов, вечерний комфорт, искренняя забота",
            "caring_subtext": "Рабочий день подошел к концу, но мы еще здесь: перепроверяем детали и готовим всё к завтрашнему дню, чтобы вы могли спокойно отдыхать.",
            "window_lighting": "warm directional desk lamp contrasting with soft evening twilight and gentle blurred city skyline lights through window in background",
            "indoor_lighting": "warm focused 3000K desk lamp illuminating the work surface with soft organic light falloff into cozy background, delicate warm ambient room shadows, quiet focused evening studio atmosphere"
        }),
        (range(22, 24), {
            "phase": "Ночь",
            "code": "night",
            "vibe": "Глубокая концентрация, автономная работа 24/7, пока город спит",
            "caring_subtext": "Пока город спит, наши автономные алгоритмы и серверы работают на ваш бизнес 24/7.",
            "window_lighting": "low-key ambient lighting, glowing monitor telemetry, dark nocturnal city skyscraper lights bokeh outside panoramic window",
            "indoor_lighting": "intimate low-key directional task light illuminating subject with deep chiaroscuro shadows, glowing dark-mode screen telemetry, quiet nocturnal focus"
        }),
        (range(0, 6), {
            "phase": "Ночь",
            "code": "night",
            "vibe": "Глубокая концентрация, автономная работа 24/7, пока город спит",
            "caring_subtext": "Пока город спит, наши автономные алгоритмы и серверы работают на ваш бизнес 24/7.",
            "window_lighting": "low-key ambient lighting, glowing monitor telemetry, dark nocturnal city skyscraper lights bokeh outside panoramic window",
            "indoor_lighting": "intimate low-key directional task light illuminating subject with deep chiaroscuro shadows, glowing dark-mode screen telemetry, quiet nocturnal focus"
        })
    ]

    SEASONAL_TACTILE_PROPS = {
        "beauty": {
            "Зима": {
                "prop": "holding a rustic handmade snowball with glistening melting ice crystals in cozy cream knit sweater sleeves",
                "bg_accent": "warm 3000K fairy lights and frosted window patterns in soft background bokeh",
                "vibe_token": "cozy winter knitwear and crisp frosty ice crystals"
            },
            "Осень": {
                "prop": "delicate ceramic vase with dried amber and scarlet maple leaves in soft background bokeh",
                "bg_accent": "cozy textured chunky knit sweater sleeve framing the frame",
                "vibe_token": "warm autumn terracotta ambiance, cozy knitted wool"
            },
            "Весна": {
                "prop": "delicate dewy pussy willow branches with soft velvety buds and fresh cherry blossom petals",
                "bg_accent": "fresh linen runner and soft pastel botanical studio atmosphere",
                "vibe_token": "fresh spring floral renewal, dewy petals"
            },
            "Лето": {
                "prop": "sunlit warm travertine stone surface with delicate palm leaf shadow play and subtle gold ring accents",
                "bg_accent": "crystal clear chilled glass with condensation droplets in soft bokeh",
                "vibe_token": "radiant summer daylight, sun-kissed textures"
            }
        },
        "horeca": {
            "Зима": {
                "prop": "fine dusting of powdered sugar resembling fresh powdery snow, whole cinnamon sticks, star anise, and dense rising steam curls",
                "bg_accent": "dark slate countertop with powdered sugar scattering, rustic winter kitchen ambiance",
                "vibe_token": "festive winter spices, snowy powdered sugar dusting, steaming warmth"
            },
            "Осень": {
                "prop": "rustic dark walnut board with whole star anise pods, whole cinnamon sticks, dried orange wheels, and rich salted caramel drizzle",
                "bg_accent": "frayed natural beige linen runner, golden autumn maple leaves scattering in soft bokeh",
                "vibe_token": "spiced autumn caramel, dark walnut wood, star anise"
            },
            "Весна": {
                "prop": "delicate edible spring micro-blossoms and fresh dewy mint leaves, bright berry garnish on crisp linen",
                "bg_accent": "bright morning bistro daylight, pastel ceramic plateware",
                "vibe_token": "fresh spring botanical garnish, dewy mint, light artisan ceramics"
            },
            "Лето": {
                "prop": "glistening crystal-clear melting ice cubes, fresh citrus wheels with fine translucent micro-droplets, vibrant summer berries",
                "bg_accent": "sun-drenched outdoor terrace table with crisp defined shadows",
                "vibe_token": "refreshing summer citrus, melting ice, dewy fruit glaze"
            }
        },
        "detailing": {
            "Зима": {
                "prop": "pristine hydrophobic water and frost bead test on deep ceramic coated hood",
                "bg_accent": "warm 3000K studio softbox contrasting with frosty glass partitions in background",
                "vibe_token": "hydrophobic frost beads, ceramic coating protection against cold"
            },
            "Осень": {
                "prop": "mirror-like reflection of golden autumn foliage on flawless glossy metallic paintwork",
                "bg_accent": "warm low-angle golden hour rim light accentuating sharp body contours",
                "vibe_token": "autumn foliage reflection, warm golden hour gloss"
            },
            "Весна": {
                "prop": "crisp clean spring morning reflection on pristine metallic paintwork, spotless workshop floor",
                "bg_accent": "bright diffused daylight showing razor-sharp mirror gloss",
                "vibe_token": "spring renewal, flawless high-gloss clear coat"
            },
            "Лето": {
                "prop": "sharp directional summer sunburst flare accentuating deep multi-stage mirror finish and metallic flake depth",
                "bg_accent": "scenic asphalt lookout at sunset, pristine showroom reflection",
                "vibe_token": "brilliant summer sun flare, deep metallic flake clarity"
            }
        },
        "tech": {
            "Зима": {
                "prop": "steaming matte ceramic mug emitting delicate translucent vapor, warm ambient monitor glow, subtle string light bokeh in background",
                "bg_accent": "dimly lit late-night high-tech office with frosty city skyline through panoramic glass",
                "vibe_token": "winter late-night focus, steaming coffee vapor, cozy tech loft"
            },
            "Осень": {
                "prop": "warm amber desk illumination, ceramic mug of hot spiced espresso, cozy textured throw on ergonomic office chair",
                "bg_accent": "modern oak desk with falling golden leaves visible outside architectural window blinds",
                "vibe_token": "productive autumn business season, warm amber task lighting"
            },
            "Весна": {
                "prop": "fresh potted indoor succulent plant on minimalist desk, bright crisp spring daylight streaming across workspace",
                "bg_accent": "sunlit open-plan digital innovation lab with Scandinavian oak desks",
                "vibe_token": "spring innovation, clean tech minimalism, fresh energy"
            },
            "Лето": {
                "prop": "minimalist iced cold-brew glass with condensation droplets beside sleek aluminum laptop, bright productive daylight",
                "bg_accent": "modern glass-partitioned tech headquarters at golden afternoon",
                "vibe_token": "summer high-velocity growth, iced coffee, clean analytics"
            }
        },
        "general": {
            "Зима": {
                "prop": "cozy textured knitted blanket in foreground, delicate frost patterns in soft bokeh",
                "bg_accent": "warm 3000K interior glow contrasting with cool winter exterior",
                "vibe_token": "winter warmth, cozy tactile textures"
            },
            "Осень": {
                "prop": "warm ceramic cup, subtle dried autumn botanicals in minimalist ceramic vase",
                "bg_accent": "soft golden hour sunbeams casting gentle organic room shadows",
                "vibe_token": "autumn coziness, warm earthy neutrals"
            },
            "Весна": {
                "prop": "fresh botanical greenery, crisp morning daylight on natural textured surface",
                "bg_accent": "bright airy sunlit interior in soft creamy bokeh",
                "vibe_token": "spring freshness, soft natural daylight"
            },
            "Лето": {
                "prop": "vibrant natural daylight, crisp defined micro-shadows, warm stone surface",
                "bg_accent": "sunlit contemporary space with natural airy depth",
                "vibe_token": "summer energy, bright sunlit clarity"
            }
        }
    }

    HOLIDAY_AESTHETIC_SETS = {
        "maslenitsa": {
            "title": "Масленица (Блинная неделя)",
            "keywords": ["маслениц", "блин", "блинчик", "сырн", "масленичн", "maslenitsa", "blini", "pancake", "crepe"],
            "date_ranges": [(2, 15, 3, 20)],  # Примерный диапазон Масленицы (февраль-март)
            "hero_tabletop": (
                "a towering golden stack of delicate paper-thin Russian blini with lacy crisp edges, "
                "a melting dollop of creamy farm butter slowly cascading down the glistening golden sides, "
                "drizzled with glossy amber honey pooling onto a handcrafted ceramic plate, "
                "accompanied by a sheaf of golden ripe wheat sprigs, a half-emptied rustic glass carafe with rich whole farm milk, "
                "and a delicate dusting of unrefined flour artistically scattered across a textured dark wooden table"
            ),
            "hero_beauty": (
                "macro close-up photography of elegantly manicured hands with natural glossy nails gently holding a handcrafted ceramic teacup, "
                "resting beside a warm stack of golden lacy blini drizzled with honey, golden wheat sprigs and a rustic milk carafe in soft morning sunrise light"
            ),
            "surface": "rustic aged dark wooden table with delicate unrefined flour scatter and frayed linen runner",
            "background": "cozy rustic country kitchen with morning sunrise dawn daylight streaming through window in background, soft floating dust motes in sunbeams, ceramic jars in soft bokeh",
            "window_lighting": "soft morning sunrise dawn daylight streaming through window in background with warm angled sunbeams and glowing specular highlights",
            "foreground_anchor": "(delicate sheaf of golden wheat ears, half-emptied glass milk carafe, and light flour dusting in extreme blurred foreground:1.25)",
            "vibe_token": "traditional Maslenitsa feast, golden blini, melting farm butter, wheat ears, morning dawn sunrise",
            "palette_key": "terracotta"
        },
        "easter": {
            "title": "Пасха (Светлое Воскресение)",
            "keywords": ["пасх", "кулич", "пасхальн", "верб", "яйц", "easter", "kulich"],
            "date_ranges": [(4, 1, 5, 10)],  # Примерный диапазон Пасхи (апрель-май)
            "hero_tabletop": (
                "a tall artisanal traditional Easter Kulich bread crowned with thick glossy white meringue fondant glaze with slow-moving drips down its golden-brown crust, "
                "artfully decorated strictly on top with dried candied cranberries, crushed pistachios, and delicate micro-flakes of edible gold leaf, "
                "standing elegantly on a minimalist white ceramic pedestal cake stand, beside a small bowl of naturally dyed terracotta, sage-green, and pastel speckled Easter eggs on an organic linen runner, "
                "accompanied by a small ceramic vase with fresh fluffy pussy willow branches in soft background"
            ),
            "hero_beauty": (
                "macro beauty photography of slender female hands with delicate pastel-glazed nails gently cradling a naturally dyed pastel terracotta Easter egg, "
                "with fluffy velvet pussy willow branches, frayed natural linen runner, and a glazed mini kulich in soft creamy background bokeh with spring morning window light"
            ),
            "surface": "natural textured light oak table with a frayed beige organic linen runner",
            "background": "bright serene dining room with diffused morning spring window daylight, pussy willow vase and pastel ceramics in creamy soft bokeh",
            "window_lighting": "soft diffused morning spring window daylight with delicate airy sunbeams and gentle organic micro-shadows",
            "foreground_anchor": "(fluffy velvet pussy willow catkins and speckled pastel egg in extreme blurred foreground:1.25)",
            "vibe_token": "peaceful Easter morning, artisanal glazed kulich, dyed eggs in nest, fluffy pussy willow branches",
            "palette_key": "nude"
        },
        "new_year": {
            "title": "Новый год и Рождество",
            "keywords": ["новый год", "новогодн", "рождеств", "рождественск", "елка", "елочн", "christmas", "new year", "xmas"],
            "date_ranges": [(12, 15, 1, 15)],
            "hero_tabletop": (
                "a festive winter holiday setting with fresh fragrant pine and blue spruce branches adorned with delicate frosty snow crystals, "
                "whole cinnamon sticks, whole star anise pods, dried orange wheels, a handcrafted beeswax candle with a gentle flickering warm flame, "
                "steaming ceramic mugs emitting delicate curls of spice vapor, and warm 3000K fairy lights sparkling in deep bokeh"
            ),
            "hero_beauty": (
                "macro close-up photography of elegantly manicured hands in cozy cream knit sweater sleeves gently cupping a steaming ceramic mug or holding a rustic handmade snowball with glistening ice crystals, "
                "surrounded by fresh pine needles, cinnamon sticks, and magical twinkling fairy lights in soft focus"
            ),
            "surface": "dark rustic walnut table with fine powdered sugar dusting and pine needles",
            "background": "cozy festive holiday living room with warm 3000K fairy lights bokeh and soft winter twilight outside frosted window pane",
            "window_lighting": "warm 3000K interior candle and fairy light glow contrasting with cool winter twilight outside frosted window pane",
            "foreground_anchor": "(blurred pine needle sprig, star anise pod, and whole cinnamon stick in extreme foreground:1.25)",
            "vibe_token": "festive New Year Christmas warmth, pine needles, fairy lights bokeh, winter spices",
            "palette_key": "emerald"
        },
        "womens_day": {
            "title": "8 Марта (Международный женский день)",
            "keywords": ["8 март", "восьмое март", "женский день", "мимоз", "тюльпан"],
            "date_ranges": [(3, 1, 3, 10)],
            "hero_tabletop": (
                "a lush spring celebration arrangement featuring a vibrant bouquet of fluffy yellow mimosa blossoms with delicate powdery texture "
                "and pastel pink and cream tulips with sparkling fresh morning dewdrops, wrapped in natural crinkled craft paper and tied with raw silk ribbon, "
                "resting beside a delicate porcelain teacup on a crisp linen tablecloth under radiant morning sunbeams"
            ),
            "hero_beauty": (
                "macro beauty portrait of manicured hands with radiant glossy nails holding a delicate sprig of fluffy yellow mimosa and dewy tulip petal, "
                "soft luminous skin, natural spring daylight streaming through sheer white curtains in background"
            ),
            "surface": "crisp white and pastel linen runner on polished marble or light wood tabletop",
            "background": "bright airy sunlit room with sheer curtains floating in spring breeze, soft pastel floral bouquets in creamy bokeh",
            "window_lighting": "bright radiant spring morning window daylight with warm sunbeams and crisp fresh highlights",
            "foreground_anchor": "(soft blurred yellow mimosa blossom and dewy tulip petal in extreme foreground:1.25)",
            "vibe_token": "spring celebration 8 March, fluffy yellow mimosa, dewy tulips, raw silk ribbon, morning sunshine",
            "palette_key": "fuchsia"
        },
        "valentines": {
            "title": "14 Февраля (День всех влюбленных)",
            "keywords": ["14 феврал", "валентин", "влюблен", "романтик", "день святого валентина", "valentine"],
            "date_ranges": [(2, 10, 2, 16)],
            "hero_tabletop": (
                "an intimate romantic luxury setting featuring velvety deep crimson rose petals scattered across dark polished wood, "
                "two vintage crystal coupe glasses filled with effervescent champagne with rising micro-fizz bubbles, "
                "a plate of fresh plump strawberries dipped in glossy dark chocolate, and natural beeswax taper candles casting a warm intimate amber glow"
            ),
            "hero_beauty": (
                "macro beauty shot of slender female hands with crimson/berry nails resting gracefully beside vintage crystal champagne coupe and fresh velvet rose petals, "
                "delicate openwork ring, warm candlelight reflections in background"
            ),
            "surface": "dark polished mahogany or smoked mirror surface reflecting warm candlelight",
            "background": "moody romantic luxury lounge with warm candlelight glow and soft city twilight skyline bokeh outside window",
            "window_lighting": "warm intimate 2700K candlelight illumination with soft dramatic falloff into deep evening twilight shadows",
            "foreground_anchor": "(blurred vintage crystal coupe rim and deep crimson rose petal in extreme foreground:1.25)",
            "vibe_token": "romantic Valentine ambiance, velvet rose petals, champagne micro-fizz, warm candlelight",
            "palette_key": "burgundy"
        },
        "defenders": {
            "title": "23 Февраля (День защитника Отечества)",
            "keywords": ["23 феврал", "защитник", "отечеств", "мужской день"],
            "date_ranges": [(2, 20, 2, 25)],
            "hero_tabletop": (
                "a sophisticated masculine still life featuring handcrafted dark full-grain leather accessories, a brushed titanium timepiece, "
                "a double espresso with dense golden crema in a matte charcoal ceramic cup, and a vintage fountain pen on solid smoked oak"
            ),
            "hero_beauty": (
                "macro commercial shot of well-groomed hands with clean matte nails adjusting a luxury timepiece on smoked oak table under directional studio lighting"
            ),
            "surface": "solid smoked oak table with natural tactile wood grain",
            "background": "minimalist architectural loft with dark steel and concrete elements in moody soft bokeh",
            "window_lighting": "moody low-key 45-degree directional light with high contrast and deep natural chiaroscuro shadows",
            "foreground_anchor": "(blurred dark full-grain leather edge and smoked glass in extreme foreground:1.2)",
            "vibe_token": "brutal masculine elegance, dark leather, titanium, espresso crema, smoked oak",
            "palette_key": "sapphire"
        },
        "knowledge_day": {
            "title": "1 Сентября (День знаний)",
            "keywords": ["1 сентябр", "день знани", "первое сентябр", "школ", "знаний", "учебн"],
            "date_ranges": [(8, 25, 9, 5)],
            "hero_tabletop": (
                "a nostalgic academic autumn still life featuring a stack of vintage clothbound hardcover books with embossed spines, "
                "an elegant brass fountain pen, a crisp polished red garden apple with natural dewdrops, and a ceramic vase with autumn dahlias and asters, "
                "bathed in warm golden September afternoon sunlight streaming through a study window"
            ),
            "hero_beauty": (
                "macro beauty shot of manicured hands in cozy cardigan sleeve gently opening a vintage clothbound book with a brass bookmark, warm autumn sunlight on oak desk"
            ),
            "surface": "classic polished dark oak library desk with subtle natural patina",
            "background": "warm scholarly study or library interior with floor-to-ceiling bookshelves and soft autumn sunbeams in bokeh",
            "window_lighting": "warm golden September afternoon daylight streaming through large window casting long gentle room shadows",
            "foreground_anchor": "(soft blurred brass pen tip, book edge, and autumn dahlia petal in extreme foreground:1.2)",
            "vibe_token": "Knowledge Day September 1st, vintage books, brass pen, ripe apple, autumn flowers",
            "palette_key": "chocolate"
        },
        "halloween": {
            "title": "Хэллоуин / Самайн (Осенний урожай)",
            "keywords": ["хэллоуин", "halloween", "тыква", "тыкв", "самайн", "autumn harvest"],
            "date_ranges": [(10, 20, 11, 2)],
            "hero_tabletop": (
                "a moody rustic autumn harvest still life featuring heirloom ribbed butternut and mini white ghost pumpkins with matte velvety rind, "
                "dripping beeswax taper candles casting long warm dramatic shadows, dried wheat sheaves, autumn maple leaves, and aged dark wood"
            ),
            "hero_beauty": (
                "macro beauty photography of manicured dark terracotta nails resting gently on a textured velvet pumpkin with dripping beeswax candle in soft bokeh"
            ),
            "surface": "aged rustic dark wood plank surface with dried leaves and wax drops",
            "background": "moody dark rustic interior with glowing amber candlelight and mysterious soft shadow depth",
            "window_lighting": "moody low-key warm amber candle glow casting dramatic chiaroscuro shadows with cool nocturnal twilight in background",
            "foreground_anchor": "(blurred mini white pumpkin and flickering candle flame in extreme foreground:1.25)",
            "vibe_token": "mystical Halloween harvest, heirloom pumpkins, dripping beeswax, amber candlelight",
            "palette_key": "terracotta"
        },
        "spas": {
            "title": "Спас (Яблочный и Медовый Спас)",
            "keywords": ["спас", "яблочный спас", "медовый спас", "ореховый спас", "соты", "мед", "мёд"],
            "date_ranges": [(8, 10, 8, 30)],
            "hero_tabletop": (
                "a radiant rustic harvest still life featuring a freshly cut section of natural golden honeycomb with rich amber honey slowly dripping into a handcrafted terracotta bowl, "
                "surrounded by crisp ripe red garden apples with fresh dewdrops, cracked walnuts and hazelnuts in an artisan wooden dish, and golden ears of wheat on coarse natural linen"
            ),
            "hero_beauty": (
                "macro beauty shot of manicured hands holding a fresh dewy red garden apple beside dripping honeycomb and golden wheat stalks in radiant late-summer sunbeams"
            ),
            "surface": "rustic unvarnished pine table with coarse unbleached natural linen runner",
            "background": "sunlit country veranda with lush green garden foliage and golden hour sunbeams in soft creamy bokeh",
            "window_lighting": "radiant late-summer golden hour sunbeams casting warm glowing rim highlights and soft natural shadows",
            "foreground_anchor": "(glistening amber honey drizzle droplet, wheat ear, and apple leaf in extreme foreground:1.25)",
            "vibe_token": "traditional Spas harvest, dripping golden honeycomb, crisp apples, rustic wood",
            "palette_key": "chocolate"
        }
    }

    def __init__(self):
        self.collector = EventHolidayCollector() if EventHolidayCollector else None
        self.last_updated_date: Optional[date] = None
        self.cached_context: Dict[str, Any] = {}
        self.refresh()

    @classmethod
    def get_instance(cls) -> InternalCalendarEngine:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def refresh(self, target_dt: Optional[datetime] = None, force: bool = False) -> Dict[str, Any]:
        now = target_dt or datetime.now()
        today = now.date()
        hour = now.hour
        month, day, weekday = now.month, now.day, now.weekday()
        year = now.year

        season_info = next(v for k, v in self.SEASONS.items() if month in k)
        day_info = self.DAY_PSYCHOLOGY[weekday]
        time_info = next(info for r, info in self.TIME_OF_DAY_SLOTS if hour in r)

        today_events = []
        upcoming_events = []
        if self.collector:
            try:
                events_calendar = self.collector.get_calendar_events(country="Россия", city="Москва", niche="all", days_count=14)
                today_events = [e for e in events_calendar if e.get("date") == f"{month:02d}-{day:02d}"]
                upcoming_events = [e for e in events_calendar if e.get("date") != f"{month:02d}-{day:02d}"][:5]
            except Exception:
                pass

        self.last_updated_date = today
        self.cached_context = {
            "current_year": year,
            "current_time_str": now.strftime("%H:%M"),
            "current_date_str": now.strftime(f"%d.%m.{year}"),
            "formatted_date_ru": f"{day} {self._get_month_name_ru(month)} {year} года",
            "day_of_week": day_info["name"],
            "day_vibe": day_info["vibe"],
            "time_phase": time_info["phase"],
            "time_code": time_info["code"],
            "time_vibe": time_info["vibe"],
            "caring_subtext": time_info["caring_subtext"],
            "window_lighting": time_info["window_lighting"],
            "indoor_lighting": time_info["indoor_lighting"],
            "season": season_info["season"],
            "seasonal_lighting": season_info["lighting_mod"],
            "seasonal_palette": season_info["palette"],
            "seasonal_narrative": season_info["narrative_focus"],
            "today_holidays": today_events,
            "upcoming_holidays_14d": upcoming_events
        }
        return self.cached_context

    def get_holiday_aesthetic(self, topic: str = "", niche: str = "", target_dt: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """
        Определяет праздничную эстетику и тактильные предметные сеты по теме поста или текущей дате.
        """
        combined_text = f"{topic} {niche}".lower()
        now = target_dt or datetime.now()
        month, day = now.month, now.day

        # 1. Поиск по ключевым словам темы
        for h_key, h_data in self.HOLIDAY_AESTHETIC_SETS.items():
            if any(re.search(rf"\b{re.escape(kw)}", combined_text) for kw in h_data["keywords"]):
                return {**h_data, "holiday_key": h_key, "match_type": "keyword"}

        # 2. Поиск по дате календаря (если праздник выпадает на текущий период)
        for h_key, h_data in self.HOLIDAY_AESTHETIC_SETS.items():
            for (sm, sd, em, ed) in h_data.get("date_ranges", []):
                # Проверка попадания даты в диапазон
                if (sm == em and sm == month and sd <= day <= ed) or \
                   (sm != em and ((month == sm and day >= sd) or (month == em and day <= ed))):
                    return {**h_data, "holiday_key": h_key, "match_type": "calendar_date"}

        return None

    def get_seasonal_tactile_anchor(self, domain: str = "general", target_dt: Optional[datetime] = None) -> Dict[str, str]:
        ctx = self.refresh(target_dt=target_dt)
        season_name = ctx["season"]
        domain_dict = self.SEASONAL_TACTILE_PROPS.get(domain, self.SEASONAL_TACTILE_PROPS["general"])
        return domain_dict.get(season_name, domain_dict.get("Осень", {
            "prop": "warm organic ceramic mug and natural linen",
            "bg_accent": "soft ambient background bokeh",
            "vibe_token": "natural commercial elegance"
        }))

    def get_visual_lighting_anchor(self, topic: str = "", setting_desc: str = "", target_dt: Optional[datetime] = None) -> str:
        ctx = self.refresh(target_dt=target_dt)
        combined_text = f"{topic} {setting_desc}".lower()

        window_regex = r"\b(окн\w*|панорам\w*|балкон\w*|вид\s+на\s+город|скайлайн\w*|небоскреб\w*|витрин\w*|террас\w*|улиц\w*|фасад\w*|window\w*|panoramic|balcony|cityscape|skyline|outdoor)\b"
        has_window = bool(re.search(window_regex, combined_text))

        if has_window:
            return f"{ctx['window_lighting']}, {ctx['seasonal_lighting']}"
        else:
            return f"{ctx['indoor_lighting']}, {ctx['seasonal_lighting']}"

    def get_copywriting_temporal_prompt(self, target_dt: Optional[datetime] = None) -> str:
        ctx = self.refresh(target_dt=target_dt)
        holidays_today_str = ", ".join([h["title"] for h in ctx["today_holidays"]]) if ctx["today_holidays"] else "Обычный рабочий день"
        upcoming_str = "; ".join([f"{h['date']}: {h['title']}" for h in ctx["upcoming_holidays_14d"][:3]]) if ctx["upcoming_holidays_14d"] else "Плановые инфоповоды"

        return (
            f"ВРЕМЕННОЙ ЯКОРЬ И ЭМПАТИЯ КЛИЕНТА:\n"
            f"- Дата: {ctx['formatted_date_ru']} ({ctx['day_of_week']}), время публикации: {ctx['current_time_str']} ({ctx['time_phase']}).\n"
            f"- Сезонная фаза: {ctx['season']} ({ctx['seasonal_narrative']}).\n"
            f"- Психологический тон дня: {ctx['day_vibe']}.\n"
            f"- Подтекст времени суток (Забота о клиенте): {ctx['caring_subtext']}\n"
            f"- Праздники сегодня: {holidays_today_str}.\n"
            f"- Ближайшие инфоповоды (14 дней): {upcoming_str}.\n"
            f"ВАЖНО: Органично отрази в тональности текста время суток и день недели. Не используй банальные «Добрый вечер/день», транслируй заботу и вовлеченность через суть и контекст."
        )

    def _get_month_name_ru(self, m: int) -> str:
        names = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        return names[m - 1]

__all__ = ["InternalCalendarEngine"]
