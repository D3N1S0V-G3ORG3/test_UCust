# -*- coding: utf-8 -*-
"""
Facade for backward compatibility: delegates directly to unified ChannelFormattersFactory.
"""
from services.channel_formatters import (
    OKFormatter as OKPostFormatter,
    OKFormatter,
    ChannelFormattersFactory,
    TargetChannelEnum,
)

__all__ = ["OKPostFormatter", "OKFormatter", "ChannelFormattersFactory", "TargetChannelEnum"]
