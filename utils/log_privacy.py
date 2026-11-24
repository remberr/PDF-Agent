"""Allowed diagnostic metadata for application logs."""
import math
import re

from utils.pricing import MODEL_ALIASES, MODEL_PRICING


EVENTS = frozenset("""
agent_graph_close_failed agent_lease_release_failed agent_node_finished agent_result_save_failed
agent_workflow_failed agent_workflow_finished agent_workflow_interrupted agent_workflow_started
collaboration_failed collaboration_fallback http_request_completed http_request_failed http_request_started
llm_budget_cancelled llm_budget_exhausted llm_budget_finished llm_budget_reserved llm_budget_settled
llm_call_cancelled llm_call_completed llm_call_failed llm_response_invalid llm_retry_scheduled
llm_retry_skipped memory_cache_hit memory_capacity_reached memory_invalidated memory_summary_fallback
model_output_repaired model_output_validation_failed pdf_index_failed pdf_indexed pdf_upload_skipped
planner_fallback scheduled_session_cleanup_failed session_cleanup_completed session_created session_deleted
specialist_failed vectorstore_delete_failed vectorstore_delete_rejected
""".split())
METRICS = frozenset("""
attempt attempt_number attempts_admitted cache_hit_rate cache_hit_tokens cache_miss_tokens
cache_unavailable_calls cache_usage_available chunk_count cost_committed_or_reserved_usd
cost_estimate_available cost_estimate_cny_available delay_seconds document_count duration_ms elapsed_ms
estimated_cost_cny estimated_cost_usd estimated_input_tokens estimated_total_cost_usd expired_sessions
file_size_bytes in_flight input_tokens input_tokens_committed_or_reserved known_cost_cny known_cost_usd
llm_calls loaded_pdf_count orphaned_vectorstores output_tokens output_tokens_committed_or_reserved
page_count question_length remaining_seconds reserved_estimated_cost_usd reserved_output_tokens
retry_number revision_count status_code token_usage_available total_tokens ttl_seconds unpriced_calls
unpriced_cny_calls unresolved_usage_attempts usage_available
""".split())
METHODS = frozenset({'GET', 'POST', 'DELETE', 'HEAD', 'OPTIONS', 'PATCH', 'PUT', 'OTHER'})
ROUTES = frozenset({
    '/', '/health', '/docs', '/docs/oauth2-redirect', '/redoc', '/openapi.json', '/assets/{path}',
    '/sessions', '/sessions/{session_id}', '/sessions/{session_id}/pdfs',
    '/sessions/{session_id}/ask', '/sessions/{session_id}/ask/stream', 'unmatched',
})
NODES = frozenset("""
planner source qa keyword summary compare specialist collaboration controller revision reviewer workflow
""".split())
OPERATIONS = NODES | {'cache_probe', 'evaluation_judge', 'memory_summary', 'pdf_answer', 'unspecified'}
MODELS = frozenset(MODEL_ALIASES) | frozenset(MODEL_PRICING)
STATES = frozenset({'available', 'unavailable', 'partial', 'no_calls', 'running', 'succeeded',
                    'degraded', 'failed', 'cancelled', 'skipped'})
PERSISTENCE = frozenset({'saved', 'failed', 'not_attempted', 'not_attempted_or_already_saved'})
REASONS = frozenset("""
call_limit calls client_disconnected connection cost_unavailable deadline duplicate_filename duplicate_keys
estimated_cost_usd graph_error input_token_limit input_tokens invalid_json invalid_session_id
invalid_model_output memory_invalidated model_unavailable non_json_constant output_length output_tokens
output_token_limit output_type outside_vectorstore_root provider_usage_over_budget rate_limit
request_closed save_failed schema_validation server_error server_wait_too_long transport_timeout
workflow_closed workflow_error cancelled empty_output storage_error
""".split()) | {f'http_{status}' for status in (408, 409, 429, *range(500, 600))}
PRICING_TIERS = frozenset({'peak', 'off_peak', 'peak_configured', 'off_peak_configured', 'unavailable'})
ARRAY_LABELS = {
    'planned_steps': NODES,
    'pricing_tiers': PRICING_TIERS,
    'repairs': {'outer_whitespace', 'bom', 'json_fence', 'step_whitespace', 'duplicate_steps'},
    'error_codes': {'extra_forbidden', 'bool_type', 'literal_error', 'missing', 'string_type',
                    'list_type', 'too_short', 'too_long', 'value_error', 'model_type',
                    'string_too_short', 'string_too_long', 'dict_type', 'model_attributes_type'},
}
LABELS = {
    'active_node': NODES, 'node': NODES, 'step': NODES, 'model': MODELS, 'operation': OPERATIONS,
    'method': METHODS, 'path': ROUTES, 'outcome': STATES, 'status': STATES,
    'generation_status': STATES, 'cache_status': STATES, 'cost_status': STATES,
    'persistence': PERSISTENCE, 'reason': REASONS, 'retry_reason': REASONS,
    'stop_reason': REASONS, 'cancel_reason': REASONS, 'currency': {'USD', 'CNY'},
    'pricing_tier': PRICING_TIERS,
    'pricing_cny_tier': PRICING_TIERS,
    'accounting': {'conservative_reservations_not_billed_usage'},
}
ERROR_TYPE = re.compile(r'[A-Z][A-Za-z0-9_]{0,39}')
SESSION_ROUTE = re.compile(r'/sessions/[^/]+(?P<suffix>/pdfs|/ask(?:/stream)?)?')


def http_log_route(path: str) -> str:
    path = path.rstrip('/') or '/'
    if path in ROUTES:
        return path
    if path.startswith('/assets/'):
        return '/assets/{path}'
    match = SESSION_ROUTE.fullmatch(path)
    if match:
        return '/sessions/{session_id}' + (match['suffix'] or '')
    return 'unmatched'


def _scalar_fields(fields: dict) -> dict:
    safe = {}
    for key, value in fields.items():
        if key in METRICS and (value is None or type(value) in (bool, int)
                               or (type(value) is float and math.isfinite(value))):
            safe[key] = value
        elif key in LABELS and (value is None or (type(value) is str and value in LABELS[key])):
            safe[key] = value
        elif key == 'error_type' and type(value) is str and ERROR_TYPE.fullmatch(value):
            safe[key] = value
        elif key in ARRAY_LABELS and isinstance(value, list):
            safe[key] = [item for item in value if isinstance(item, str) and item in ARRAY_LABELS[key]]
    return safe


def _usage_fields(usage: dict) -> dict:
    safe = _scalar_fields(usage)
    for field, names in (('by_model', MODELS), ('by_operation', OPERATIONS)):
        buckets = usage.get(field)
        if isinstance(buckets, dict):
            safe[field] = {name: _scalar_fields(bucket) for name, bucket in buckets.items()
                           if name in names and isinstance(bucket, dict)}
    return safe


def log_fields(fields: dict) -> dict:
    safe = _scalar_fields(fields)
    if isinstance(fields.get('usage'), dict):
        safe['usage'] = _usage_fields(fields['usage'])
    if isinstance(fields.get('execution'), dict):
        safe['execution'] = _scalar_fields(fields['execution'])
    return safe
