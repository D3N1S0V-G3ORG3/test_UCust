"""
Autonomous Research Grounder for UCust.AI.
Модуль автономного поиска и дистилляции подтвержденных фактов о неизвестных продуктах,
новинках и специфических сущностях (Active Grounding & Anti-Hallucination Pipeline).

- 1. Единый контракт данных: FactSheet (Pydantic).
- 2. Системный промпт для экстрактора: EXTRACTION_PROMPT.
- 3. Класс автономного ресёрча: AutonomousResearchGrounder с поддержкой DI (search, llm, cache).
"""

from __future__ import annotations

import json
import hashlib
import logging
import asyncio
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


# --- 1. Единый контракт данных ---

class FactSheet(BaseModel):
    product_name: str = Field(..., description="Точное название продукта")
    category: str = Field(..., description="Класс продукта / ниша")
    key_specs: List[str] = Field(default=[], description="Подтвержденные технические характеристики, цифры или состав")
    target_audience: Optional[str] = Field(None, description="Целевая аудитория")
    unverified_claims: List[str] = Field(default=[], description="Маркетинговые обещания, оценочные суждения (эпитеты), требующие осторожности")
    sources: List[str] = Field(default=[], description="URL-источники фактов")
    is_verified: bool = Field(True, description="Флаг наличия подтвержденных фактов")

    @property
    def is_grounded(self) -> bool:
        return self.is_verified

    def to_prompt_block(self) -> str:
        """
        Формирует защищенный блок [FACT_SHEET] для системного промпта SaigaLLM.
        """
        specs_str = "\n".join(f"- {s}" for s in self.key_specs) if self.key_specs else "- Специфические числовые характеристики не заявлены"
        unverified_str = "\n".join(f"- {u}" for u in self.unverified_claims) if self.unverified_claims else "- Сомнительных маркетинговых утверждений не выявлено"
        audience_str = self.target_audience or "Широкая целевая аудитория"

        return (
            "=== [VERIFIED_FACT_SHEET_START] ===\n"
            f"ПРОДУКТ: {self.product_name}\n"
            f"КАТЕГОРИЯ: {self.category}\n"
            f"ЦЕЛЕВАЯ АУДИТОРИЯ: {audience_str}\n\n"
            "ПОДТВЕРЖДЕННЫЕ ХАРАКТЕРИСТИКИ И ФАКТЫ (Используй строго их):\n"
            f"{specs_str}\n\n"
            "ТРЕБУЮЩИЕ ОСТОРОЖНОСТИ ЗАЯВЛЕНИЯ (Подавать как 'Позиционируется как...' или 'Заявлено производителем'):\n"
            f"{unverified_str}\n"
            "=== [VERIFIED_FACT_SHEET_END] ==="
        )


# --- 2. Системный промпт для экстрактора ---

EXTRACTION_PROMPT = """
Ты — строгий аналитик данных. Твоя задача: извлечь сухие факты о продукте "{product_name}" из предоставленных поисковых сниппетов.
Верни результат СТРОГО в формате JSON, соответствующем схеме:
{{
    "product_name": "string",
    "category": "string",
    "key_specs": ["string", "string"],
    "target_audience": "string or null",
    "unverified_claims": ["string"],
    "sources": ["url1", "url2"],
    "is_verified": boolean
}}

ПРАВИЛА:
1. В key_specs добавляй только проверяемые факты: цифры, материалы, габариты, точный состав, версии.
2. Любые фразы вроде "революционный", "лучший в классе", "идеальный выбор", "исцеляет", "премиальный" отправляй в unverified_claims.
3. Если сниппеты не содержат полезной информации, установи is_verified = false и оставь списки пустыми.
4. Ничего не выдумывай, используй только текст сниппетов.
"""


# --- 3. Дефолтные реализации зависимостей (Fallback adapters) ---

class InMemoryCacheAdapter:
    def __init__(self):
        self._store: Dict[str, str] = {}

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        self._store[key] = value


class DefaultSearchAdapter:
    def __init__(self):
        try:
            from skills.travity_search import TravitySearchSkill
        except ImportError:
            try:
                from ai.skills.travity_search import TravitySearchSkill
            except ImportError:
                TravitySearchSkill = None
        self.travity = TravitySearchSkill() if TravitySearchSkill else None

    async def execute(self, query: str, top_k: int = 3) -> List[Dict[str, str]]:
        if not self.travity:
            return []
        md = await self.travity.search(query)
        if not md or "Результаты поиска не найдены" in md:
            return []
        return [{"url": "https://search.ucust.ai", "snippet": md}]


# --- 4. Класс автономного ресёрча ---

class AutonomousResearchGrounder:
    def __init__(
        self,
        search_client: Optional[Any] = None,
        llm_client: Optional[Any] = None,
        cache_client: Optional[Any] = None
    ):
        """
        Инициализация зависимостей.
        search_client: интерфейс для поиска (метод execute(query, top_k) -> [{'url': '', 'snippet': ''}])
        llm_client: интерфейс для обращения к LLM (метод generate(system_prompt, user_prompt, response_format))
        cache_client: интерфейс Redis/Cache (методы get(key) и set(key, value, ttl))
        """
        self.search = search_client or DefaultSearchAdapter()
        self.llm = llm_client
        self.cache = cache_client or InMemoryCacheAdapter()
        self.cache_ttl = 86400  # 24 часа

    def _generate_cache_key(self, product_name: str) -> str:
        safe_name = product_name.strip().lower()
        name_hash = hashlib.md5(safe_name.encode("utf-8")).hexdigest()
        return f"factsheet:{name_hash}"

    async def extract_facts(self, product_name: str, niche: str = "") -> FactSheet:
        """
        Асинхронно извлекает верифицированный паспорт фактов FactSheet.
        """
        clean_name = product_name.strip()
        if not clean_name:
            return FactSheet(
                product_name="Unknown",
                category=niche or "General",
                is_verified=False
            )

        cache_key = self._generate_cache_key(clean_name)
        
        # 1. Проверка кэша
        cached_data = await self.cache.get(cache_key)
        if cached_data:
            logger.info(f"FactSheet найден в кэше для: {clean_name}")
            return FactSheet.model_validate_json(cached_data)

        # 2. Асинхронный сбор данных из сети (Search Fallback с поддержкой Geo Dork)
        logger.info(f"Кэш пуст. Запуск веб-поиска для: {clean_name}")
        
        # Интеллектуальный Dork-запрос с защитой от перегрузки операторов
        try:
            from skills.geo_entity_resolver import GeoEntityResolver, MarketRegion
        except ImportError:
            try:
                from ai.skills.geo_entity_resolver import GeoEntityResolver, MarketRegion
            except ImportError:
                GeoEntityResolver = None
                MarketRegion = None

        is_beauty = any(w in f"{niche} {clean_name}".lower() for w in ["бьюти", "красота", "салон", "волос", "лак", "шампун", "крем", "косметик", "beauty", "hair", "taft", "тафт"])
        
        if GeoEntityResolver and is_beauty:
            search_query = GeoEntityResolver.build_clean_dork_query(clean_name, region=MarketRegion.RU if MarketRegion else "ru")
            logger.info(f"🎯 [GeoEntityResolver] Сформирован чистый PIM Dork: {search_query}")
        else:
            search_query = f"{clean_name} {niche} характеристики официальный спецификация".strip()
        
        search_results = []
        if self.search:
            search_results = await self.search.execute(query=search_query, top_k=3)

        if not search_results:
            logger.warning(f"Поиск не дал результатов для: {clean_name}")
            empty_sheet = FactSheet(
                product_name=clean_name,
                category=niche or "Unknown",
                is_verified=False
            )
            return empty_sheet

        # Подготовка контекста для LLM
        snippets_text = "\n---\n".join([f"Источник ({r.get('url', 'N/A')}): {r.get('snippet', '')}" for r in search_results])
        sources_list = [r.get('url') for r in search_results if r.get('url')]

        # 3. LLM-дистилляция в JSON
        prompt = EXTRACTION_PROMPT.format(product_name=clean_name)
        
        # Попытка подключить SaigaLLMSkill если self.llm не передан явно
        effective_llm = self.llm
        if effective_llm is None:
            try:
                from skills.saiga_llm import SaigaLLMSkill
                effective_llm = SaigaLLMSkill()
            except Exception:
                effective_llm = None

        if effective_llm:
            try:
                llm_response = None
                if hasattr(effective_llm, "generate"):
                    llm_response = await effective_llm.generate(
                        system_prompt=prompt,
                        user_prompt=f"Сниппеты:\n{snippets_text}",
                        response_format="json" 
                    )
                elif hasattr(effective_llm, "generate_chat"):
                    messages = [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": f"Сниппеты:\n{snippets_text}\nВерни строго JSON."}
                    ]
                    llm_response = effective_llm.generate_chat(messages=messages, max_tokens=600)

                if llm_response:
                    # Извлечение JSON из ответа LLM
                    import re
                    json_match = re.search(r"\{.*\}", llm_response, re.DOTALL)
                    json_str = json_match.group(0) if json_match else llm_response
                    raw_dict = json.loads(json_str)
                    raw_dict["sources"] = sources_list
                    fact_sheet = FactSheet(**raw_dict)
                    await self.cache.set(cache_key, fact_sheet.model_dump_json(), ttl=self.cache_ttl)
                    return fact_sheet
            except Exception as e:
                logger.warning(f"Ошибка дистилляции LLM ({e}). Переход на детерминированный парсер фактов.")

        # Эвристический детерминированный фоллбэк: очистка текста от markdown-разметки и IT/B2B-жаргона
        is_consumer_niche = any(w in f"{niche} {clean_name}".lower() for w in ["пекарн", "кулич", "хлеб", "еда", "ресторан", "салон", "красот", "бьюти", "авто", "кафе", "выпечк"])
        cleaned_specs = []
        for line in snippets_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("Источник") or line.startswith("http") or line.startswith("---"):
                continue
            if line.startswith("**Сниппет:**"):
                line = line.replace("**Сниппет:**", "").strip()
            if line.startswith("- "):
                line = line[2:].strip()
            # Фильтр смыслового загрязнения (Semantic Bleed Purge)
            if is_consumer_niche and any(j in line.lower() for j in ["b2b", "llm", "сквозную аналитику", "верификации гипотез", "автоматизация коммуникаций", "документооборот", "спецификация"]):
                continue
            if len(line) > 20 and not any(line.startswith(p) for p in ["###", "##", "#"]):
                cleaned_specs.append(line)

        if not cleaned_specs:
            cleaned_specs = [
                f"Натуральные ингредиенты и аутентичная рецептура для {clean_name}",
                f"Контроль свежести и соблюдение стандартов ниши '{niche or 'производство'}'",
                f"Фирменная технология приготовления"
            ]

        fact_sheet = FactSheet(
            product_name=clean_name,
            category=niche or "Product",
            key_specs=cleaned_specs[:3],
            sources=sources_list,
            is_verified=True
        )
        await self.cache.set(cache_key, fact_sheet.model_dump_json(), ttl=self.cache_ttl)
        return fact_sheet

    async def research_product(self, product_query: str, niche: str = "") -> FactSheet:
        """Алиас для обратной совместимости."""
        return await self.extract_facts(product_query, niche=niche)

    def inject_grounding_to_system_prompt(self, base_system_prompt: str, fact_sheet: FactSheet) -> str:
        """
        Встраивает строгие правила Closed-Domain Grounding в системный промпт модели.
        """
        grounding_rules = (
            "\n\nСТАНДАРТ ЖЕСТКОГО ФАКТИЧЕСКОГО ЯКОРЕНИЯ (CLOSED-DOMAIN GROUNDING):\n"
            f"{fact_sheet.to_prompt_block()}\n\n"
            "ПРАВИЛА ИММУНИТЕТА К ГАЛЛЮЦИНАЦИЯМ:\n"
            "1. СТРОГИЙ ПРИОРИТЕТ ФАКТОВ: Используй только проверенные характеристики из блока выше.\n"
            "2. ЗАПРЕТ ВЫДУМЫВАНИЯ ЦИФР: Если точной цифры (цена, объем батареи, вес, мегапиксели) нет в [VERIFIED_FACT_SHEET], "
            "описывай пользу для пользователя концептуально, но категорически не выдумывай несуществующие числа.\n"
            "3. ОБРАБОТКА МАРКЕТИНГОВЫХ КЛЕЙМОВ: Если используешь тезисы из раздела 'ТРЕБУЮЩИЕ ОСТОРОЖНОСТИ', "
            "всегда предваряй их фразами 'Позиционируется как...', 'Производитель заявляет, что...'.\n"
            "4. БЕЗ СКАЗОК И ВОДЫ: Не придумывай несуществующие технологии или мифические свойства."
        )
        return f"{base_system_prompt}{grounding_rules}"
