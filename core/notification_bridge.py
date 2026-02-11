# File: core/notification_bridge.py | Module: notification_bridge | Part of: Intellectual Property Submission.
"""Notification bridge service for human-in-the-loop communication."""

from __future__ import annotations

from enum import Enum
from typing import Callable, Optional


class ApprovalDecision(str, Enum):
    """System-level decisions returned by the user approval channel."""

    APPROVED = "APPROVED"
    EDIT = "EDIT"
    REGENERATE = "REGENERATE"
    AWAITING_USER_ACTION = "AWAITING_USER_ACTION"


class NotificationBridge:
    """Service abstraction for notifying a user and collecting approval decisions."""

    # Step 1: Initialize notification transport with an optional callback adapter.
    def __init__(
        self,
        notifier: Optional[Callable[[str, Optional[str]], ApprovalDecision]] = None,
    ) -> None:
        self._notifier = notifier

    # Step 2: Dispatch a content-ready signal and return the current decision state.
    def notify_content_ready(self, post_content: str, image_url: Optional[str] = None) -> ApprovalDecision:
        if self._notifier is None:
            return ApprovalDecision.AWAITING_USER_ACTION

        decision = self._notifier(post_content, image_url)
        if isinstance(decision, ApprovalDecision):
            return decision

        try:
            return ApprovalDecision(str(decision))
        except ValueError:
            return ApprovalDecision.AWAITING_USER_ACTION


__all__ = ["ApprovalDecision", "NotificationBridge"]
