# -*- coding: utf-8 -*-
"""
Facade for backward compatibility: delegates directly to unified ChannelFormattersFactory.
"""
from services.channel_formatters import (
    TelegramFormatter as TelegramRichPostFormatter,
    TelegramFormatter,
    ChannelFormattersFactory,
    TargetChannelEnum,
)

__all__ = ["TelegramRichPostFormatter", "TelegramFormatter", "ChannelFormattersFactory", "TargetChannelEnum"]
