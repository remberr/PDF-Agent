"""Request/resource regressions; local generated PDFs, no models or live database."""
import asyncio
import io
import json
import tempfile
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi import HTTPException, UploadFile
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.api.routes import router
from tests.session_access_fixtures import AUTH_HEADERS, HTTP_SESSION_ID, accept_test_owner
from app.services import pdf_service


def pdf_bytes(pages=1, text="Useful evidence"):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                NameObject('/Subtype'): NameObject('/Type1'),
                                NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({
            NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 10 100 Td ({text}) Tj ET'.encode('ascii'))
        page[NameObject('/Contents')] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def session():
    return dict(session_id='test-session', loaded_pdfs=[], messages=[],
                vectorstore=None, document_count=0)


class RequestValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = FastAPI()
        app.include_router(router)
        self.enterContext(accept_test_owner())
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=AUTH_HEADERS)
        self.addAsyncCleanup(self.http.aclose)

    async def test_invalid_questions_rejected_before_session_lookup(self):
        for suffix in ('ask', 'ask/stream'):
            for question in ('   \n\t', 'x' * 100001):
                with self.subTest(suffix=suffix, size=len(question)), \
                        patch('app.api.routes.get_session', return_value=None) as lookup:
                    response = await self.http.post(f'/sessions/{HTTP_SESSION_ID}/{suffix}',
                                                    json={'question': question})
                    self.assertEqual(response.status_code, 422)
                    lookup.assert_not_called()

    async def test_file_count_rejected_before_indexing(self):
        with patch('app.api.routes.get_session', return_value=session()), \
                patch('app.api.routes.load_pdf_into_session', return_value=True) as index:
            response = await self.http.post(f'/sessions/{HTTP_SESSION_ID}/pdfs', files=[
                ('files', (f'{i}.pdf', b'pdf', 'application/pdf')) for i in range(101)])
        self.assertEqual(response.status_code, 413)
        index.assert_not_called()

    async def test_missing_filename_is_safe_client_error(self):
        with patch('app.api.routes.get_session', return_value=session()):
            response = await self.http.post(f'/sessions/{HTTP_SESSION_ID}/pdfs',
                                            files={'files': ('', b'pdf', 'application/pdf')})
        self.assertIn(response.status_code, (400, 422))

    async def test_question_is_trimmed_and_configured_limit_applies_to_both_apis(self):
        from app.input_limits import InputLimits
        from app.schemas.requests import AskRequest
        with patch('app.schemas.requests.get_input_limits', return_value=InputLimits(max_question_chars=4)):
            self.assertEqual(AskRequest(question='  test\n').question, 'test')
            for suffix in ('ask', 'ask/stream'):
                response = await self.http.post(f'/sessions/{HTTP_SESSION_ID}/{suffix}', json={'question': '12345'})
                self.assertEqual(response.status_code, 422)

    async def test_invalid_later_filename_does_not_index_first_file(self):
        with patch('app.api.routes.get_session', return_value=session()), \
                patch('app.api.routes.load_pdf_into_session', return_value=True) as index:
            response = await self.http.post(f'/sessions/{HTTP_SESSION_ID}/pdfs', files=[
                ('files', ('valid.pdf', pdf_bytes(), 'application/pdf')),
                ('files', ('bad.txt', b'invalid', 'text/plain'))])
        self.assertEqual(response.status_code, 400)
        index.assert_not_called()

    async def test_session_lookup_does_not_block_health(self):
        started, release = threading.Event(), threading.Event()
        def slow_lookup(_sid, *, owner):
            started.set()
            release.wait(3)
            return session()
        with patch('app.api.routes.get_session', side_effect=slow_lookup), \
                patch('app.api.routes.load_pdf_into_session', return_value=True):
            upload = asyncio.create_task(self.http.post(f'/sessions/{HTTP_SESSION_ID}/pdfs',
                files={'files': ('test.pdf', pdf_bytes(), 'application/pdf')}))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                health = await self.http.get('/health')
                self.assertEqual(health.status_code, 200)
                self.assertFalse(upload.done(), 'SQL lookup blocked the event loop until its timeout')
            finally:
                release.set()
                await upload


class UploadLimitsTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_during_copy_does_not_close_a_running_writer(self):
        entered, release = threading.Event(), threading.Event()
        paths = []
        factory = tempfile.NamedTemporaryFile
        @contextmanager
        def blocked_file(**kwargs):
            with factory(**kwargs) as file:
                paths.append(file.name)
                def write(block):
                    entered.set()
                    release.wait(4)
                    return file.write(block)
                yield SimpleNamespace(name=file.name, write=write)
        file = UploadFile(filename='test.pdf', file=io.BytesIO(pdf_bytes()))
        with patch('app.services.pdf_service.tempfile.NamedTemporaryFile', side_effect=blocked_file):
            task = asyncio.create_task(pdf_service.load_pdf_into_session(session(), file))
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
                self.assertTrue(Path(paths[0]).exists(), 'Cancellation removed a file still used by its writer')
                self.assertFalse(task.done())
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await file.close()
            self.assertFalse(Path(paths[0]).exists())

    async def test_all_file_sizes_checked_before_processing_with_unknown_size(self):
        from app.input_limits import InputLimits
        files = [UploadFile(filename='a.pdf', file=io.BytesIO(b'1234')),
                 UploadFile(filename='b.pdf', file=io.BytesIO(b'56789'))]
        try:
            with self.assertRaises(HTTPException) as caught:
                await pdf_service.validate_uploads(files, InputLimits(max_file_bytes=8, max_batch_bytes=8))
            self.assertEqual(caught.exception.status_code, 413)
            self.assertEqual(files[0].file.tell(), 0)
            with self.assertRaises(HTTPException):
                await pdf_service.validate_uploads(files, InputLimits(max_file_bytes=3))
        finally:
            for file in files:
                await file.close()

    async def test_real_pdf_limits_and_empty_corrupt_inputs_never_encode_or_write(self):
        from app.input_limits import InputLimits
        cases = [
            (pdf_bytes(), InputLimits(max_file_bytes=10), 413),
            (pdf_bytes(pages=2), InputLimits(max_pages=1), 413),
            (pdf_bytes(text='abcdef'), InputLimits(max_text_chars=5), 413),
            (pdf_bytes(text='a' * 3000), InputLimits(max_chunks=1), 413),
            (pdf_bytes(text=''), InputLimits(), 400),
            (pdf_bytes(pages=0), InputLimits(), 400),
            (b'not a pdf', InputLimits(), 400),
            (b'', InputLimits(), 400),
        ]
        for body, limits, expected in cases:
            with self.subTest(expected=expected, size=len(body)), tempfile.TemporaryDirectory() as directory:
                factory = tempfile.NamedTemporaryFile
                def temporary(**kwargs):
                    return factory(dir=directory, **kwargs)
                with patch('app.services.pdf_service.get_input_limits', return_value=limits), \
                        patch('app.services.pdf_service.tempfile.NamedTemporaryFile', side_effect=temporary), \
                        patch('app.services.pdf_service.get_bge_embeddings') as embeddings, \
                        patch('app.services.pdf_service.commit_document') as commit:
                    file = UploadFile(filename='test.pdf', file=io.BytesIO(body))
                    try:
                        with self.assertRaises(HTTPException) as caught:
                            await pdf_service.load_pdf_into_session(session(), file)
                        self.assertEqual(caught.exception.status_code, expected)
                        embeddings.assert_not_called()
                        commit.assert_not_called()
                        self.assertEqual(list(Path(directory).iterdir()), [])
                    finally:
                        await file.close()

    async def test_exact_page_text_chunk_and_byte_boundaries_accept_valid_pdf(self):
        from app.input_limits import InputLimits
        body = pdf_bytes(pages=2, text='alpha')
        limits = InputLimits(max_pages=2, max_text_chars=10, max_chunks=2,
                             max_file_bytes=len(body), max_batch_bytes=len(body))
        file = UploadFile(filename='paper.pdf', file=io.BytesIO(body))
        try:
            await pdf_service.validate_uploads([file], limits)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'paper.pdf'
                path.write_bytes(body)
                docs = pdf_service.parse_pdf_documents(path, 'paper.pdf', limits=limits)
            self.assertEqual([doc.page_content for doc in docs], ['alpha', 'alpha'])
            self.assertEqual([doc.metadata['page'] for doc in docs], [0, 1])
            self.assertTrue(all(doc.metadata['source'] == 'paper.pdf' for doc in docs))
        finally:
            await file.close()

    async def test_encrypted_pdf_is_safe_client_error_before_embedding(self):
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.encrypt('test-password')
        body = io.BytesIO()
        writer.write(body)
        file = UploadFile(filename='encrypted.pdf', file=io.BytesIO(body.getvalue()))
        try:
            with self.assertRaises(HTTPException) as caught:
                await pdf_service.load_pdf_into_session(session(), file)
            self.assertEqual(caught.exception.status_code, 400)
            self.assertNotIn('test-password', str(caught.exception))
        finally:
            await file.close()

    async def test_cancelled_worker_holds_slot_and_file_until_exit_and_skips_commit(self):
        from app.input_limits import get_upload_admission
        admission = get_upload_admission()
        started, release = threading.Event(), threading.Event()
        paths = []
        real_parser = pdf_service.parse_pdf_documents
        def blocked_parser(path, name, **kwargs):
            paths.append(path)
            started.set()
            release.wait(4)
            return real_parser(path, name, **kwargs)
        first = UploadFile(filename='test.pdf', file=io.BytesIO(pdf_bytes()))
        second = UploadFile(filename='second.pdf', file=io.BytesIO(pdf_bytes()))
        with patch('app.services.pdf_service.parse_pdf_documents', side_effect=blocked_parser), \
                patch('app.services.pdf_service.get_bge_embeddings') as embeddings, \
                patch('app.services.pdf_service.commit_document') as commit:
            task = asyncio.create_task(pdf_service.load_pdf_into_session(session(), first))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()  # Repeated cancellation must not release a running worker.
                await asyncio.sleep(0)
                self.assertTrue(Path(paths[0]).exists())
                with self.assertRaises(HTTPException) as caught:
                    await pdf_service.load_pdf_into_session(session(), second)
                self.assertEqual(caught.exception.status_code, 429)
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await first.close()
                await second.close()
            self.assertFalse(Path(paths[0]).exists())
            embeddings.assert_not_called()
            commit.assert_not_called()
        with admission.slot():  # Capacity is reusable after actual worker exit.
            pass


class BodyLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_production_middleware_keeps_cors_and_request_id_on_early_rejection(self):
        from app.input_limits import get_input_limits
        from app.main import app
        cors = next(item for item in app.user_middleware if item.cls.__name__ == 'CORSMiddleware')
        allowed = cors.kwargs['allow_origins']
        origin = allowed[0] if allowed else 'http://localhost:5173'
        expected_origin = allowed[0] if allowed else None
        if origin == '*':
            origin = 'http://localhost:5173'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=AUTH_HEADERS) as http:
            with patch('app.api.routes.get_session') as lookup:
                response = await http.post('/sessions/test/pdfs', content=b'', headers={
                    'Origin': origin,
                    'Content-Length': str(get_input_limits().max_upload_body_bytes + 1),
                    'X-Request-ID': 'input-limit-rejection',
                })
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), expected_origin)
            self.assertEqual(response.headers['X-Request-ID'], 'input-limit-rejection')
            lookup.assert_not_called()

    async def test_valid_unicode_questions_accept_json_surrogate_pair_escapes(self):
        from app.input_limits import InputLimits, InputLimitsMiddleware
        limits = InputLimits(max_question_chars=1000)
        app = FastAPI()
        app.include_router(router)
        app.add_middleware(InputLimitsMiddleware, limits=limits)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=AUTH_HEADERS) as http:
            with accept_test_owner(), patch('app.schemas.requests.get_input_limits', return_value=limits), \
                    patch('app.api.routes.get_session', return_value=None) as lookup:
                response = await http.post(f'/sessions/{HTTP_SESSION_ID}/ask',
                    content=json.dumps({'question': '\U0001f600' * 1000}, ensure_ascii=True),
                    headers={'Content-Type': 'application/json'})
            self.assertEqual(response.status_code, 404, 'Valid question must reach normal session validation')
            lookup.assert_called_once()

    async def test_body_timeout_does_not_become_an_sse_generation_timeout(self):
        from app.input_limits import InputLimits, InputLimitsMiddleware
        messages = []
        reads = 0
        async def receive():
            nonlocal reads
            reads += 1
            if reads == 1:
                return {'type': 'http.request', 'body': b'{}', 'more_body': False}
            await asyncio.sleep(0.03)
            return {'type': 'http.disconnect'}
        async def send(message):
            messages.append(message)
        async def downstream(scope, receive, send):
            await receive()
            self.assertEqual((await receive())['type'], 'http.disconnect')
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
        middleware = InputLimitsMiddleware(downstream,
            limits=InputLimits(body_idle_seconds=0.01, max_body_seconds=0.02))
        await middleware({'type': 'http', 'method': 'POST', 'path': '/sessions/test/ask/stream',
                          'headers': []}, receive, send)
        self.assertEqual(messages[0]['status'], 200)

    async def test_stalled_and_dripping_bodies_timeout_and_release_admission(self):
        from app.input_limits import InputLimits, InputLimitsMiddleware
        for dripping in (False, True):
            with self.subTest(dripping=dripping):
                limits = InputLimits(body_idle_seconds=0.03 if not dripping else 1,
                                     max_body_seconds=0.05)
                async def downstream(scope, receive, send):
                    while (await receive()).get('more_body', False):
                        pass
                middleware = InputLimitsMiddleware(downstream, limits=limits)
                messages = []
                async def receive():
                    await asyncio.sleep(0.02 if dripping else 5)
                    return {'type': 'http.request', 'body': b'x', 'more_body': True}
                async def send(message):
                    messages.append(message)
                scope = {'type': 'http', 'method': 'POST', 'path': '/sessions/test/pdfs', 'headers': []}
                await middleware(scope, receive, send)
                self.assertEqual(messages[0]['status'], 408)
                with middleware.admission.slot():
                    pass

    async def test_question_admission_bounds_json_and_sse_before_reading_body(self):
        from app.input_limits import InputLimitsMiddleware, ProcessingAdmission
        entered, release = asyncio.Event(), asyncio.Event()
        async def downstream(scope, receive, send):
            entered.set()
            await release.wait()
        middleware = InputLimitsMiddleware(downstream)
        middleware.question_admission = ProcessingAdmission(1)
        async def receive():
            self.fail('Rejected questions must not read their body')
        messages = []
        async def send(message):
            messages.append(message)
        scope = {'type': 'http', 'method': 'POST', 'path': '/sessions/test/ask/stream', 'headers': []}
        task = asyncio.create_task(middleware(scope, receive, send))
        await entered.wait()
        try:
            await middleware(dict(scope, path='/sessions/test/ask'), receive, send)
            self.assertEqual(messages[0]['status'], 429)
            self.assertIn((b'retry-after', b'1'), messages[0]['headers'])
        finally:
            release.set()
            await task

    async def test_question_body_limit_covers_missing_or_incorrect_content_length(self):
        from app.input_limits import InputLimits, InputLimitsMiddleware
        limits = InputLimits(max_question_chars=1)
        async def downstream(scope, receive, send):
            await receive()
            self.fail('Oversized JSON was delivered to the application')
        middleware = InputLimitsMiddleware(downstream, limits=limits)
        for headers in ([], [(b'content-length', b'1')]):
            messages = []
            async def receive():
                return {'type': 'http.request', 'body': b'x' * (limits.max_question_body_bytes + 1)}
            async def send(message):
                messages.append(message)
            await middleware({'type': 'http', 'method': 'POST', 'path': '/sessions/test/ask',
                              'headers': headers}, receive, send)
            self.assertEqual(messages[0]['status'], 413)

    async def test_stream_limit_closes_partially_spooled_multipart_files(self):
        from app.input_limits import InputLimits, InputLimitsMiddleware
        limits = InputLimits(max_batch_bytes=8)
        app = FastAPI()
        app.include_router(router)
        app.add_middleware(InputLimitsMiddleware, limits=limits)
        files = []
        factory = tempfile.SpooledTemporaryFile
        def tracked_file(*args, **kwargs):
            file = factory(*args, **kwargs)
            files.append(file)
            return file
        async def body():
            yield b'--b\r\nContent-Disposition: form-data; name="files"; filename="a.pdf"\r\n\r\npdf'
            yield b'x' * limits.max_upload_body_bytes
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test', headers=AUTH_HEADERS) as http:
            with accept_test_owner(), patch('starlette.formparsers.SpooledTemporaryFile', side_effect=tracked_file), \
                    patch('app.api.routes.get_session') as lookup:
                response = await http.post(f'/sessions/{HTTP_SESSION_ID}/pdfs', content=body(),
                                           headers={'Content-Type': 'multipart/form-data; boundary=b'})
            self.assertEqual(response.status_code, 413)
            lookup.assert_not_called()
        self.assertTrue(files)
        self.assertTrue(all(file.closed for file in files))

    async def test_declared_and_streamed_body_limit_reject_before_downstream_work(self):
        from app.input_limits import InputLimits, InputLimitsMiddleware
        limits = InputLimits(max_batch_bytes=8)
        cap = limits.max_upload_body_bytes
        for declared in (True, False):
            messages, reached = [], []
            async def downstream(scope, receive, send):
                while (await receive()).get('more_body', False):
                    pass
                reached.append(True)
            middleware = InputLimitsMiddleware(downstream, limits=limits)
            packets = iter([{'type': 'http.request', 'body': b'x' * cap, 'more_body': True},
                            {'type': 'http.request', 'body': b'x', 'more_body': False}])
            async def receive():
                return next(packets)
            async def send(message):
                messages.append(message)
            scope = {'type': 'http', 'method': 'POST', 'path': '/sessions/test/pdfs',
                     'headers': [(b'content-length', str(cap + 1).encode())] if declared else []}
            await middleware(scope, receive, send)
            self.assertEqual(messages[0]['status'], 413)
            self.assertEqual(reached, [])

    async def test_busy_upload_does_not_read_body_and_does_not_block_health(self):
        from app.input_limits import InputLimitsMiddleware
        entered, release = asyncio.Event(), asyncio.Event()
        async def downstream(scope, receive, send):
            if scope['path'].endswith('/pdfs'):
                entered.set()
                await release.wait()
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})
        middleware = InputLimitsMiddleware(downstream)
        async def receive():
            self.fail('Busy upload must not start reading the request')
        async def send(_message):
            pass
        scope = {'type': 'http', 'method': 'POST', 'path': '/sessions/test/pdfs', 'headers': []}
        task = asyncio.create_task(middleware(scope, receive, send))
        await entered.wait()
        messages = []
        async def capture(message):
            messages.append(message)
        try:
            await middleware(scope, receive, capture)
            self.assertEqual(messages[0]['status'], 429)
            await middleware(dict(scope, method='GET', path='/health'), receive, send)
        finally:
            release.set()
            await task


class LimitsConfigurationTests(unittest.TestCase):
    def test_invalid_configuration_fails_explicitly_without_echoing_values(self):
        from app.input_limits import load_input_limits
        for value in ('0', '-1', 'NaN', '1.5', 'secret-test-value'):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                load_input_limits({'PDF_AGENT_MAX_PDF_PAGES': value})
            self.assertNotIn(value, str(caught.exception))


if __name__ == '__main__':
    unittest.main()
