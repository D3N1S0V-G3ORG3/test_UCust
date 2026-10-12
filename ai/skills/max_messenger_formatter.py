# -*- coding: utf-8 -*-
"""
Facade for backward compatibility: delegates directly to unified ChannelFormattersFactory.
"""
from services.channel_formatters import (
    MaxMessengerFormatter,
    ChannelFormattersFactory,
    TargetChannelEnum,
)

__all__ = ["MaxMessengerFormatter", "ChannelFormattersFactory", "TargetChannelEnum"]
