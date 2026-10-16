import sys
import os
import asyncio
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from collectors.telethon_collector import TelethonCollector
from core.orchestrator import UnifiedOrchestrator

async def test_telethon_collector_async():
    print("--- 1. Testing TelethonCollector.collect_async with real channel ---")
    collector = TelethonCollector()
    res = await collector.collect_async(channel="@testaipublisher", limit=5)
    payload = res.payload
    print(f"Collected channel: {payload.get('channel')}, mode: {payload.get('mode')}")
    print(f"Messages count: {len(payload.get('messages', []))}")
    assert payload.get("mode") in ["real", "real_web_preview"], f"Expected real mode, got {payload.get('mode')}"
    assert len(payload.get("messages", [])) > 0, "Expected non-empty messages"
    first_msg = payload["messages"][0]
    print(f"First post #{first_msg.get('id')}: {first_msg.get('text')[:100]}...")
    assert "[MOCK]" not in first_msg.get("text", ""), "Expected real text, got mock text"
    print("SUCCESS: test_telethon_collector_async passed!")

def test_telethon_collector_sync():
    print("\n--- 2. Testing TelethonCollector.collect (sync) with real channel ---")
    collector = TelethonCollector()
    res = collector.collect(channel="@testaipublisher", limit=3)
    payload = res.payload
    print(f"Collected channel: {payload.get('channel')}, mode: {payload.get('mode')}")
    assert payload.get("mode") in ["real", "real_web_preview"], f"Expected real mode, got {payload.get('mode')}"
    assert len(payload.get("messages", [])) > 0
    print("SUCCESS: test_telethon_collector_sync passed!")

async def test_orchestrator_parse_telegram():
    print("\n--- 3. Testing Orchestrator execute_task('parse_telegram') ---")
    orchestrator = UnifiedOrchestrator()
    res = await orchestrator.execute_task(
        task_type="parse_telegram",
        user_data={
            "channel": "@testaipublisher",
            "limit": 5,
            "include_media_vqa": False
        },
        session_id="test-parse-tg-session-123"
    )
    print(f"Orchestrator status: {res.get('status')}")
    print(f"Source: {res.get('source')}")
    data = res.get("data", {})
    print(f"Mode in data: {data.get('mode')}")
    print(f"Posts count: {len(data.get('messages', []))}")
    assert res.get("status") == "success", f"Expected success, got {res}"
    assert data.get("mode") in ["real", "real_web_preview"], f"Expected real mode in data, got {data.get('mode')}"
    assert len(data.get("messages", [])) > 0
    print("SUCCESS: test_orchestrator_parse_telegram passed!")

if __name__ == "__main__":
    asyncio.run(test_telethon_collector_async())
    test_telethon_collector_sync()
    asyncio.run(test_orchestrator_parse_telegram())
    print("\n🎉 ALL TELEGRAM COLLECTOR INTEGRATION TESTS PASSED!")
