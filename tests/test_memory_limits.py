import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch, Mock

from utils import memory
from utils.observability import observability_context, new_usage_tracker
from utils.llm_budget import RequestBudget, BudgetSettings, LLMBudgetExceeded


def history(text='older'):
    return [{'role':'user','content':text} for _ in range(12)]


class MemoryLimitsTests(unittest.TestCase):
    def setUp(self):
        memory._memory_cache.clear()
        if hasattr(memory,'_inflight'): memory._inflight.clear()

    def test_identical_text_is_never_shared_between_sessions(self):
        with patch('utils.memory.chat_with_deepseek',side_effect=['first','second']) as chat:
            for sid, expected in [('a','first'),('b','second')]:
                with observability_context(session_id=sid):
                    self.assertEqual(memory.build_llm_conversation_summary(history()),expected)
            memory.invalidate_memory('a')
            with observability_context(session_id='b'):
                self.assertEqual(memory.build_llm_conversation_summary(history()),'second')
        self.assertEqual(chat.call_count,2)

    def test_parallel_success_reuses_summary_without_duplicate_usage(self):
        from tests.test_llm_budget import response
        gate,entered,release=threading.Barrier(5),threading.Event(),threading.Event()
        trackers=[new_usage_tracker() for _ in range(4)]
        client=Mock()
        def answer(**kwargs): entered.set(); release.wait(3); return response()
        client.chat.completions.create.side_effect=answer
        def run(tracker):
            with observability_context(session_id='same',usage_tracker=tracker):
                gate.wait(timeout=3)
                return memory.build_llm_conversation_summary(history())
        with patch('utils.llm_client.get_deepseek_client',return_value=client),ThreadPoolExecutor(4) as pool:
            futures=[pool.submit(run,t) for t in trackers]
            try: gate.wait(timeout=3); self.assertTrue(entered.wait(2))
            finally: release.set()
            self.assertEqual([f.result(timeout=3) for f in futures],['answer']*4)
        self.assertEqual(client.chat.completions.create.call_count,1)
        self.assertEqual(sum(t.summary()['llm_calls'] for t in trackers),1)
        self.assertEqual(len(memory._inflight),0)

    def test_invalid_limits_fail_without_echoing_values_or_dispatching(self):
        from utils.memory_limits import load_memory_limits
        for name in ('MEMORY_CACHE_MAX_ENTRIES','MEMORY_HISTORY_MAX_BYTES','MEMORY_CACHE_TTL_SECONDS'):
            for value in ('0','-1','nan','inf','private-value'):
                with self.subTest(name=name,value=value),patch.dict(os.environ,{name:value}):
                    with self.assertRaises(ValueError) as caught: load_memory_limits()
                    self.assertNotIn('private-value',str(caught.exception))

    def test_unknown_session_does_not_reuse_global_cache(self):
        with patch('utils.memory.chat_with_deepseek',side_effect=['first','second']) as chat:
            self.assertEqual(memory.build_llm_conversation_summary(history()),'first')
            self.assertEqual(memory.build_llm_conversation_summary(history()),'second')
        self.assertEqual(chat.call_count,2)

    def test_cache_hit_logging_does_not_hold_global_index_lock(self):
        def log(*args,**kwargs): self.assertFalse(memory._memory_cache_lock.locked())
        with observability_context(session_id='a'),patch('utils.memory.chat_with_deepseek',return_value='summary'), \
                patch('utils.memory.log_event',side_effect=log):
            memory.build_llm_conversation_summary(history())
            self.assertEqual(memory.build_llm_conversation_summary(history()),'summary')

    def test_slow_summary_does_not_hold_global_lock_or_block_other_session(self):
        entered, release, fast_done = threading.Event(),threading.Event(),threading.Event()
        def answer(prompt,**kwargs):
            if 'slow-content' in prompt:
                entered.set(); self.assertTrue(release.wait(3)); return 'slow summary'
            fast_done.set(); return 'fast summary'
        def run(sid, text):
            with observability_context(session_id=sid,usage_tracker=new_usage_tracker()):
                return memory.build_llm_conversation_summary(history(text))
        with patch('utils.memory.chat_with_deepseek',side_effect=answer),ThreadPoolExecutor(2) as pool:
            slow=pool.submit(run,'a','slow-content')
            try:
                self.assertTrue(entered.wait(2))
                fast=pool.submit(run,'b','fast-content')
                self.assertTrue(fast_done.wait(.5),'Unrelated summary must complete while the first is blocked')
            finally: release.set()
            self.assertEqual(slow.result(timeout=3),'slow summary')
            self.assertEqual(fast.result(timeout=3),'fast summary')

    def test_cache_has_lru_capacity_expiration_and_invalidation(self):
        with patch.dict(os.environ,{'MEMORY_CACHE_MAX_ENTRIES':'2','MEMORY_CACHE_TTL_SECONDS':'1'}), \
                patch('utils.memory.monotonic',return_value=0), \
                patch('utils.memory.chat_with_deepseek',return_value='summary') as chat:
            for value in ['one','two','three']:
                with observability_context(session_id='a'):
                    memory.build_llm_conversation_summary(history(value))
            self.assertLessEqual(len(memory._memory_cache),2)
            with observability_context(session_id='a'):
                memory.build_llm_conversation_summary(history('one'))
            self.assertEqual(chat.call_count,4)
            with patch('utils.memory.monotonic',return_value=2),observability_context(session_id='a'):
                memory.build_llm_conversation_summary(history('one'))
            self.assertEqual(chat.call_count,5)
            memory.invalidate_memory('a')
            self.assertEqual(len(memory._memory_cache),0)

    def test_history_and_filename_inputs_and_summary_outputs_are_bounded(self):
        long=[{'role':'assistant','content':'历史'*10000}]*1000
        with patch('utils.memory.chat_with_deepseek',return_value='摘要'*10000) as chat:
            result=memory.build_memory(long,['文档'*1000+str(n) for n in range(1000)])
        self.assertLessEqual(len(chat.call_args.args[0].encode()),17000)
        self.assertLessEqual(len(memory.build_recent_memory(long).encode()),8000)
        self.assertLessEqual(len(result.encode()),16500)
        self.assertIn('bounded',result)

    def test_document_context_and_history_version_are_part_of_cache_identity(self):
        with observability_context(session_id='a'),patch('utils.memory.chat_with_deepseek',return_value='summary') as chat:
            memory.build_memory(history(),['one.pdf'])
            memory.build_memory(history(),['one.pdf'])
            memory.build_memory(history(),['two.pdf'])
            memory.build_memory(history('changed'),['two.pdf'])
        self.assertEqual(chat.call_count,3)

    def test_failed_assistant_output_is_excluded_from_summary_input(self):
        data=history()+[{'role':'assistant','content':'FAILED-PRIVATE-MARKER','execution':{'generation_status':'failed'}}]+history()
        with patch('utils.memory.chat_with_deepseek',return_value='summary') as chat:
            memory.build_memory(data)
        self.assertNotIn('FAILED-PRIVATE-MARKER',chat.call_args.args[0])

    def test_singleflight_charges_only_owner_usage_and_waiter_can_cancel(self):
        from tests.test_llm_budget import response
        entered,release=threading.Event(),threading.Event()
        owner,waiter=new_usage_tracker(),new_usage_tracker(RequestBudget(BudgetSettings(request_timeout_seconds=.06)))
        client=Mock()
        def answer(**kwargs):
            entered.set(); self.assertTrue(release.wait(3)); return response()
        client.chat.completions.create.side_effect=answer
        def run(tracker):
            with observability_context(session_id='same',usage_tracker=tracker):
                return memory.build_llm_conversation_summary(history())
        with patch('utils.llm_client.get_deepseek_client',return_value=client),ThreadPoolExecutor(2) as pool:
            first=pool.submit(run,owner)
            try:
                self.assertTrue(entered.wait(2))
                second=pool.submit(run,waiter)
                with self.assertRaises(LLMBudgetExceeded): second.result(timeout=2)
            finally: release.set()
            self.assertEqual(first.result(timeout=3),'answer')
        self.assertEqual(owner.summary()['llm_calls'],1)
        self.assertEqual(waiter.summary()['llm_calls'],0)
        self.assertEqual(client.chat.completions.create.call_count,1)

    def test_invalidation_during_inflight_prevents_stale_publication(self):
        entered,release=threading.Event(),threading.Event()
        def answer(*args,**kwargs): entered.set(); release.wait(3); return 'stale summary'
        def run():
            with observability_context(session_id='a'): return memory.build_llm_conversation_summary(history())
        with patch('utils.memory.chat_with_deepseek',side_effect=answer),ThreadPoolExecutor(1) as pool:
            future=pool.submit(run)
            try:
                self.assertTrue(entered.wait(2)); memory.invalidate_memory('a')
            finally: release.set()
            self.assertNotEqual(future.result(timeout=3),'stale summary')
        self.assertEqual(len(memory._memory_cache),0)

    def test_memory_fallback_marks_workflow_degraded_and_keeps_failed_call_usage(self):
        from tests.test_llm_budget import response
        from tests.test_error_privacy import make_session
        from app.services.agent_service import ask_pdf_agent
        from langchain_core.documents import Document
        store=Mock(); store.similarity_search.return_value=[Document(page_content='evidence',metadata={'source':'a.pdf','page':0})]
        session=make_session(store); session['messages']=history()
        client=Mock(); client.chat.completions.create.side_effect=[TimeoutError('private'),response()]
        with patch('utils.llm_client.get_deepseek_client',return_value=client),patch('app.services.agent_service.save_session'):
            result=ask_pdf_agent(session,'What is the conclusion?')
        self.assertEqual(result['answer'],'answer')
        self.assertEqual(result['execution']['status'],'degraded')
        self.assertEqual(result['usage']['llm_calls'],2)
        self.assertFalse(result['usage']['cost_estimate_available'])
        self.assertEqual(client.chat.completions.create.call_count,2)

    def test_cancelled_leader_always_removes_inflight_and_releases_waiters(self):
        import asyncio
        with observability_context(session_id='a'),patch('utils.memory.chat_with_deepseek',side_effect=asyncio.CancelledError()):
            with self.assertRaises(asyncio.CancelledError): memory.build_llm_conversation_summary(history())
        self.assertEqual(len(memory._inflight),0)
        self.assertEqual(len(memory._memory_cache),0)

    def test_inflight_capacity_degrades_without_dispatching_more_summaries(self):
        entered,release=threading.Event(),threading.Event()
        def answer(*args,**kwargs): entered.set(); release.wait(3); return 'summary'
        def run():
            with observability_context(session_id='a'): return memory.build_llm_conversation_summary(history())
        with patch.dict(os.environ,{'MEMORY_CACHE_MAX_ENTRIES':'1'}),patch('utils.memory.chat_with_deepseek',side_effect=answer) as chat,ThreadPoolExecutor(1) as pool:
            future=pool.submit(run)
            try:
                self.assertTrue(entered.wait(2))
                with observability_context(session_id='b'):
                    self.assertIn('unavailable',memory.build_llm_conversation_summary(history()))
                self.assertEqual(chat.call_count,1)
            finally: release.set()
            self.assertEqual(future.result(timeout=3),'summary')
