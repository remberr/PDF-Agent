"""Provider USD / 1M token prices and a bounded, auditable holiday calendar.

Update this table and china_holidays.json together with source verification.
Unknown calendar years are never guessed during potential peak hours.
"""
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path


PRICING_SOURCE = 'https://api-docs.deepseek.com/quick_start/pricing/'
PRICING_VERIFIED_ON = '2026-10-18'
BEIJING = timezone(timedelta(hours=8))
PRICE_ENV_VARS = {
    'cache_hit': 'LLM_CACHE_HIT_COST_PER_1M_TOKENS',
    'cache_miss': 'LLM_CACHE_MISS_COST_PER_1M_TOKENS',
    'output': 'LLM_OUTPUT_COST_PER_1M_TOKENS',
}
MODEL_PRICING = {
    'deepseek-flash': {'cache_hit': .006, 'cache_miss': .30, 'output': 1.20},
    'deepseek-v4-pro': {'cache_hit': .044, 'cache_miss': 1.32, 'output': 3.96},
}
MODEL_ALIASES = {
    'deepseek-v4-flash': 'deepseek-flash',
    'deepseek-v4-flash-vision-exp': 'deepseek-flash',
    'deepseek-chat': 'deepseek-flash',
    'deepseek-reasoner': 'deepseek-flash',
}


@lru_cache(maxsize=1)
def _holiday_calendar():
    return json.loads(Path(__file__).with_name('china_holidays.json').read_text(encoding='utf-8'))['years']


def _is_peak_time(at):
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError('A timezone-aware call timestamp is required.')
    local = at.astimezone(BEIJING)
    minute = local.hour * 60 + local.minute
    if local.weekday() >= 5 or not (540 <= minute < 720 or 840 <= minute < 1080):
        return False
    year = _holiday_calendar().get(str(local.year))
    if not year or not year.get('source') or not year.get('breaks'):
        raise ValueError(f'Chinese public holiday calendar unavailable for {local.year}; update utils/china_holidays.json.')
    for start, end in year['breaks']:
        if date.fromisoformat(start) <= local.date() <= date.fromisoformat(end):
            return False
    return True


def _unavailable(reason):
    return dict(cache_hit=0.0, cache_miss=0.0, output=0.0,
                tier='unavailable', available=False, reason=reason)


def get_model_pricing(model, at=None):
    """Apply peak-rate overrides before selecting the Beijing billing tier.

    Environment variables always denote peak USD / 1M token prices. Neither
    complete nor partial overrides bypass the calendar or price unknown models.
    """
    configured = {}
    for key, env_name in PRICE_ENV_VARS.items():
        value = os.getenv(env_name)
        if value is None:
            continue
        try:
            price = float(value)
            if not math.isfinite(price) or price < 0:
                raise ValueError()
        except ValueError:
            return _unavailable(f'Invalid non-negative finite price in {env_name}.')
        configured[key] = price
    peak_prices = MODEL_PRICING.get(MODEL_ALIASES.get(model, model))
    if peak_prices is None:
        return _unavailable(f'No pricing configured for model {model}.')
    try:
        is_peak = _is_peak_time(at or datetime.now(timezone.utc))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _unavailable(str(exc))
    prices = {key: price * (1 if is_peak else .5) for key, price in (peak_prices | configured).items()}
    return prices | dict(tier=('peak' if is_peak else 'off_peak') + ('_configured' if configured else ''), available=True)
