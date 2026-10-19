"""Opt-in paid cache telemetry probe, not a retrieval/answer-quality benchmark."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep

from app.services.pdf_service import parse_pdf_documents
from utils.citations import format_docs_with_citations
from utils.deepseek_client import PDF_SYSTEM_PROMPT, build_pdf_prompt
from utils.llm_client import get_deepseek_client, get_deepseek_model
from utils.observability import new_usage_tracker, observability_context, record_llm_usage


def run_probe(pdf_path, *, page=3, attempts=3, delay_seconds=3, output=None, allow_paid_api=False):
    if not allow_paid_api:
        raise ValueError('Paid DeepSeek cache probe requires --allow-paid-api.')
    if not 2 <= attempts <= 5 or not 0 <= delay_seconds <= 30:
        raise ValueError('Use 2-5 attempts and a delay of 0-30 seconds.')
    pdf_path = Path(pdf_path)
    documents = parse_pdf_documents(pdf_path, pdf_path.name)
    if not 1 <= page <= len(documents):
        raise ValueError('Requested physical PDF page is out of range.')
    # A useful real page, without duplicated context or padding. No ground-truth
    # answers are supplied. This deliberately measures cache transport only.
    context = format_docs_with_citations([documents[page - 1]])
    prompt = build_pdf_prompt('Summarize the main point on this page in one brief sentence with a citation.',
                              context, loaded_pdfs=[pdf_path.name])
    messages = [{'role': 'system', 'content': PDF_SYSTEM_PROMPT}, {'role': 'user', 'content': prompt}]
    client = get_deepseek_client().with_options(max_retries=0, timeout=45)
    tracker = new_usage_tracker()
    report = {
        'mode': 'prompt-cache-probe',
        'model': get_deepseek_model(),
        'prompt_sha256': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest(),
        'pdf_sha256': hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        'physical_page': page,
        'attempts': attempts, 'delay_seconds': delay_seconds, 'max_output_tokens_per_call': 64,
        'calls': [],
        'limitations': 'Identical useful prompts; cache hits are provider-dependent and not guaranteed. '
                       'A zero hit count is an observation, not a failed transport assertion. '
                       'This is not end-to-end RAG evaluation or an answer-quality test.',
    }
    for number in range(1, attempts + 1):
        started_at = datetime.now(timezone.utc)
        started = perf_counter()
        status = 'succeeded'
        error_type = None
        try:
            response = client.chat.completions.create(model=report['model'], messages=messages,
                                                       temperature=0, max_tokens=64)
            usage = response.usage
            model = response.model or report['model']
        except Exception as exc:
            usage = getattr(exc, 'usage', None)
            model = report['model']
            status, error_type = 'failed', type(exc).__name__
        with observability_context(usage_tracker=tracker):
            normalized = record_llm_usage(model, 'cache_probe', usage,
                                          (perf_counter() - started) * 1000, at=started_at)
        call = dict(attempt=number, status=status, error_type=error_type, **normalized)
        report['calls'].append(call)
        report['summary'] = tracker.summary()
        report['observed_cache_hit'] = any(item['cache_usage_available'] and item['cache_hit_tokens'] > 0
                                           for item in report['calls'])
        if output is not None:
            path = Path(output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({key: call[key] for key in ('attempt', 'status', 'input_tokens', 'cache_hit_tokens',
                                                    'cache_miss_tokens', 'cache_hit_rate', 'cache_status')}), flush=True)
        if status == 'failed':
            # Do not spend further calls on a failed credential/transport setup.
            break
        if number < attempts:
            sleep(delay_seconds)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid-api', action='store_true')
    parser.add_argument('--pdf-path', required=True)
    parser.add_argument('--page', type=int, default=3)
    parser.add_argument('--attempts', type=int, default=3)
    parser.add_argument('--delay-seconds', type=float, default=3)
    parser.add_argument('--output', default='evaluation/reports/cache-probe.json')
    args = parser.parse_args(argv)
    report = run_probe(args.pdf_path, page=args.page, attempts=args.attempts, delay_seconds=args.delay_seconds,
                        output=args.output, allow_paid_api=args.allow_paid_api)
    return 0 if all(call['status'] == 'succeeded' and call['cache_usage_available']
                    for call in report['calls']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
