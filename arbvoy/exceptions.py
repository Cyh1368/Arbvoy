from __future__ import annotations


class ArbvoyError(Exception):
    pass


class ConfigError(ArbvoyError):
    pass


class FeedError(ArbvoyError):
    pass


class RiskError(ArbvoyError):
    pass


class StrategyParseError(ArbvoyError):
    pass

