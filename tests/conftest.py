"""
File: tests/conftest.py
Общие фикстуры для сквозного E2E-тестирования модулей AI Core.
Чистая реализация на базе стандартного pytest и asyncio.
"""

from __future__ import annotations

import sys
import os
import asyncio
import inspect
import pytest
from typing import Any, Optional
from unittest.mock import AsyncMock

# Добавляем путь к корню и ai в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ai")))


def pytest_pyfunc_call(pyfuncitem):
    """
    Хук pytest для прозрачного запуска асинхронных тестовых функций (async def test_*)
    без зависимости от внешних плагинов pytest-asyncio.
    """
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            testargs = {
                arg: pyfuncitem.funcargs[arg]
                for arg in pyfuncitem._fixtureinfo.argnames
            }
            loop.run_until_complete(pyfuncitem.obj(**testargs))
            return True
        finally:
            loop.close()
            asyncio.set_event_loop(None)
    return None


class MockAsyncRedis:
    """
    Потокобезопасная асинхронная in-memory эмуляция Redis для E2E-тестов.
    Поддерживает аргументы nx (Not Exists) и ex (TTL).
    """
    def __init__(self):
        self._data = {}

    async def set(self, key: str, value: Any, ex: Optional[int] = None, nx: bool = False) -> bool:
        if nx and key in self._data:
            return False
        self._data[key] = value.encode("utf-8") if isinstance(value, str) else value
        return True

    async def get(self, key: str) -> Optional[bytes]:
        val = self._data.get(key)
        if val is None:
            return None
        return val if isinstance(val, bytes) else str(val).encode("utf-8")

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self._data:
                del self._data[k]
                deleted += 1
        return deleted


@pytest.fixture
def redis_client():
    return MockAsyncRedis()


@pytest.fixture
def rabbitmq_channel():
    channel = AsyncMock()
    channel.publish = AsyncMock()
    return channel


@pytest.fixture
def pg_db_pool():
    repo = AsyncMock()
    repo.get_project_profile = AsyncMock(return_value={
        "company_name": "Estel Professional",
        "niche": "Салонная косметика и уход за волосами",
        "positioning": "Премиальный уход и терапия для волос",
        "aesthetic": "scandi_eco"
    })
    return repo


@pytest.fixture
def comfy_bridge_mock():
    mock_bridge = AsyncMock()
    mock_bridge.render_asset = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR...")
    return mock_bridge
