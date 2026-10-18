"""Merge UsageTracker summaries without losing model/operation or unknown costs."""
from utils.observability import empty_usage_summary


ADDITIVE_FIELDS = (
    'llm_calls', 'input_tokens', 'output_tokens', 'total_tokens',
    'cache_hit_tokens', 'cache_miss_tokens', 'duration_ms', 'elapsed_ms',
    'estimated_cost_usd', 'unpriced_calls',
)


def merge_usage(summaries):
    summaries = [summary for summary in summaries if summary]
    result = empty_usage_summary()
    for field in ADDITIVE_FIELDS:
        result[field] = round(sum(s.get(field, 0) for s in summaries), 10)
    result['known_cost_usd'] = result['estimated_cost_usd']
    result['cost_estimate_available'] = all(s.get('cost_estimate_available', True) for s in summaries)
    result['cost_status'] = 'available' if result['cost_estimate_available'] else 'unavailable'
    result['estimated_total_cost_usd'] = result['estimated_cost_usd'] if result['cost_estimate_available'] else None
    result['cache_hit_rate'] = round(result['cache_hit_tokens'] / result['input_tokens'], 4) if result['input_tokens'] else 0.0
    for field in ['pricing_tiers', 'pricing_warnings']:
        result[field] = sorted({value for s in summaries for value in s.get(field, [])})
    for field in ['by_model', 'by_operation']:
        keys = {key for s in summaries for key in s.get(field, {})}
        result[field] = {
            key: _merge_buckets([s[field][key] for s in summaries if key in s.get(field, {})])
            for key in sorted(keys)
        }
    return result


def _merge_buckets(buckets):
    result = {key: round(sum(b.get(key, 0) for b in buckets), 10) for key in ADDITIVE_FIELDS}
    result['known_cost_usd'] = result['estimated_cost_usd']
    result['cost_estimate_available'] = all(b.get('cost_estimate_available', True) for b in buckets)
    result['cost_status'] = 'available' if result['cost_estimate_available'] else 'unavailable'
    result['estimated_total_cost_usd'] = result['estimated_cost_usd'] if result['cost_estimate_available'] else None
    return result
