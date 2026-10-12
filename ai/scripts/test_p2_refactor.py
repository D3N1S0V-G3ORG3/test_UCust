# File: ai/scripts/test_p2_refactor.py
"""
test_p2_refactor.py
Validation test suite for Phase P2 Refactoring:
1. Unified ChannelFormattersFactory (TG, VK, OK, MAX) & backward-compatibility imports
2. PublishingService integration with ChannelFormattersFactory
3. Celery single broker priority routing (custom, business, start)
4. Verification that removed obsolete components (queue_manager, rabbit worker, swarm runner) are eliminated
"""

import os
import sys
import asyncio

# Setup sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from schemas.pipeline_state import PipelineState, ContentFormatEnum
from services.channel_formatters import (
    ChannelFormattersFactory,
    TargetChannelEnum,
    FormattedPostResult,
    TelegramFormatter,
    VKFormatter,
    OKFormatter,
    MaxMessengerFormatter,
)
from services.publishing_service import PublishingService
from celery_tasks import (
    enqueue_pipeline_task,
    get_pipeline_task_status,
    get_celery_queue_stats,
    get_queue_for_tier,
    QUEUE_START,
    QUEUE_BUSINESS,
    QUEUE_CUSTOM,
)


async def test_phase_p2():
    print("=" * 65)
    print("🚀 TESTING PHASE P2 INFRASTRUCTURE & FORMATTERS FACTORY")
    print("=" * 65)

    sample_post = (
        "Запуск автономного ИИ-маркетинга для вашего бизнеса от «UCust AI» 🤖✨\n\n"
        "Команда ИИ-агентов освобождает до 15 часов в неделю предпринимателю.\n\n"
        "▫️ Автономная генерация постов и визуалов 24/7\n"
        "▫️ Встроенный ОТК аудит качества без галлюцинаций\n\n"
        "Специальное предложение: вместо 15000 ₽ всего 9900 ₽ при оплате за год!\n"
        "Промокод: UCUST2026\n"
        "Секретный бонус: скидка 50% на внедрение\n\n"
        "👉 Подробнее на https://ucust.ai или пишите в ЛС!"
    )

    # -------------------------------------------------------------
    # 1. Test ChannelFormattersFactory
    # -------------------------------------------------------------
    print("\n1. Testing ChannelFormattersFactory across all platforms...")

    # 1.1 Telegram Formatter
    tg_res = ChannelFormattersFactory.format(
        text=sample_post,
        target_channel=TargetChannelEnum.TELEGRAM,
        has_media=True,
        promo_code="UCUST2026",
    )
    assert isinstance(tg_res, FormattedPostResult)
    assert tg_res.channel == TargetChannelEnum.TELEGRAM
    assert "<b>" in tg_res.post_text or "<code>" in tg_res.post_text or "<s>" in tg_res.post_text
    print("   ✅ Telegram Formatter: OK")
    print(f"      Caption len: {len(tg_res.caption_text or '')} | Char count: {tg_res.char_count}")

    # 1.2 VK Formatter (First Comment Rule)
    vk_res = ChannelFormattersFactory.format(
        text=sample_post,
        target_channel=TargetChannelEnum.VK,
    )
    assert vk_res.channel == TargetChannelEnum.VK
    assert "<" not in vk_res.post_text and ">" not in vk_res.post_text  # All HTML stripped
    assert vk_res.first_comment is not None  # External link moved to first comment
    assert "https://ucust.ai" in vk_res.first_comment
    assert "https://ucust.ai" not in vk_res.post_text  # Organic reach protected
    print("   ✅ VK Formatter (First Comment Protection): OK")
    print(f"      Post snippet: {vk_res.post_text[:60]}...")
    print(f"      First comment: {vk_res.first_comment}")

    # 1.3 OK Formatter (Clean layout & Snippet URL)
    ok_res = ChannelFormattersFactory.format(
        text=sample_post,
        target_channel=TargetChannelEnum.OK,
    )
    assert ok_res.channel == TargetChannelEnum.OK
    assert "<" not in ok_res.post_text
    assert ok_res.snippet_url == "https://ucust.ai"
    print("   ✅ OK Formatter (Single Snippet Extraction): OK")
    print(f"      Snippet URL: {ok_res.snippet_url}")

    # 1.4 Max Messenger Formatter (Push Preview & Single CTA)
    max_res = ChannelFormattersFactory.format(
        text=sample_post,
        target_channel=TargetChannelEnum.MAX,
    )
    assert max_res.channel == TargetChannelEnum.MAX
    assert max_res.push_preview is not None
    assert len(max_res.push_preview) <= 70
    assert max_res.sms_fallback is not None
    print("   ✅ Max Messenger Formatter: OK")
    print(f"      Push preview (≤70 chars): '{max_res.push_preview}'")

    # 1.5 Test Backward-Compatibility Facades in skills/
    print("\n   Testing legacy facade re-exports in skills/:")
    from skills.telegram_rich_formatter import TelegramRichPostFormatter
    from skills.vk_rich_formatter import VKPostFormatter
    from skills.ok_rich_formatter import OKPostFormatter
    from skills.max_messenger_formatter import MaxMessengerFormatter as LegacyMaxFormatter

    assert TelegramRichPostFormatter is TelegramFormatter
    assert VKPostFormatter is VKFormatter
    assert OKPostFormatter is OKFormatter
    assert LegacyMaxFormatter is MaxMessengerFormatter
    print("     • skills.telegram_rich_formatter: ✅ Re-exported")
    print("     • skills.vk_rich_formatter:       ✅ Re-exported")
    print("     • skills.ok_rich_formatter:       ✅ Re-exported")
    print("     • skills.max_messenger_formatter: ✅ Re-exported")

    # -------------------------------------------------------------
    # 2. Test PublishingService Integration with Factory
    # -------------------------------------------------------------
    print("\n2. Testing PublishingService with ChannelFormattersFactory...")
    pub_svc = PublishingService(db_session=None, redis_cache=None, rag_pipeline=None)
    res_pub = await pub_svc.publish_post_content(
        text=sample_post,
        channel="@UcustAi",
        company_name="UCust AI",
    )
    assert res_pub.get("status") in ("success", "mock_success")
    print("   ✅ PublishingService formatted and processed post successfully!")

    # -------------------------------------------------------------
    # 3. Test Celery Queue Priority Infrastructure
    # -------------------------------------------------------------
    print("\n3. Testing Celery Priority Routing & Task Management...")
    
    # 3.1 Tier to Queue mapping
    q_start = get_queue_for_tier("start")
    q_biz = get_queue_for_tier("business")
    q_custom = get_queue_for_tier("custom")
    assert q_start == QUEUE_START
    assert q_biz == QUEUE_BUSINESS
    assert q_custom == QUEUE_CUSTOM
    print("   ✅ Queue Priority Mapping: start -> 'start', business -> 'business', custom -> 'custom'")

    # 3.2 Enqueue task via Celery helper
    task_info = enqueue_pipeline_task(
        task_type="generate_post",
        payload={"topic": "Тестовая генерация", "tier": "custom"},
        user_id="vip_user_42",
        tier="custom",
    )
    assert task_info.get("status") == "QUEUED"
    assert task_info.get("queue") == QUEUE_CUSTOM
    print(f"   ✅ Task successfully queued in '{task_info.get('queue')}' priority queue (Task ID: {task_info.get('task_id')})")

    # 3.3 Task status check
    status_info = get_pipeline_task_status(task_info["task_id"])
    assert "status" in status_info
    print(f"   ✅ Celery Task Status check: Status={status_info.get('status')}")

    # 3.4 Queue Stats
    stats = get_celery_queue_stats()
    assert "active_queues" in stats
    assert QUEUE_CUSTOM in stats["active_queues"]
    print(f"   ✅ Celery Queue Stats: Broker={stats.get('broker')}, Queues={stats.get('active_queues')}")

    # -------------------------------------------------------------
    # 4. Verify Elimination of Removed Obsolete Modules
    # -------------------------------------------------------------
    print("\n4. Verifying elimination of obsolete modules (Clean Architecture)...")
    
    try:
        import core.queue_manager  # type: ignore
        raise AssertionError("core.queue_manager still exists!")
    except ModuleNotFoundError:
        print("   ✅ core.queue_manager successfully REMOVED")

    try:
        import workers.content_generation_worker  # type: ignore
        raise AssertionError("workers.content_generation_worker still exists!")
    except ModuleNotFoundError:
        print("   ✅ workers.content_generation_worker successfully REMOVED")

    assert not os.path.exists(os.path.join(parent_dir, "infrastructure", "run_agents.py"))
    print("   ✅ infrastructure/run_agents.py successfully REMOVED")

    print("\n" + "=" * 65)
    print("🎉 ALL PHASE P2 TESTS PASSED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(test_phase_p2())
