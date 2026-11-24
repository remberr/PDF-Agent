"""Default unit discovery is offline; paid suites require explicit opt-in."""
import os

if not any(os.getenv(name) == '1' for name in (
    'PDF_AGENT_RUN_PAID_TESTS', 'PDF_AGENT_RUN_CACHE_API_TESTS',
)):
    os.environ['PDF_AGENT_DISABLE_LLM_API'] = '1'
