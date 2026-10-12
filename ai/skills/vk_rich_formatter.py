# -*- coding: utf-8 -*-
"""
Facade for backward compatibility: delegates directly to unified ChannelFormattersFactory.
"""
from services.channel_formatters import (
    VKFormatter as VKPostFormatter,
    VKFormatter,
    ChannelFormattersFactory,
    TargetChannelEnum,
)

__all__ = ["VKPostFormatter", "VKFormatter", "ChannelFormattersFactory", "TargetChannelEnum"]
