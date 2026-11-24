import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.test_error_privacy import make_app
from tests.session_access_fixtures import BROWSER_HEADERS


SID = 'a' * 32
BROWSER = BROWSER_HEADERS


class SessionAccessTests(unittest.TestCase):
    def test_rejected_multipart_never_reads_body(self):
        import anyio
        from starlette.types import Message

        async def run():
            sent: list[Message] = []
            async def receive():
                raise AssertionError('Unauthorized request read the multipart body')
            async def send(message):
                sent.append(message)
            await make_app()({
                'type': 'http', 'method': 'POST', 'path': f'/sessions/{SID}/pdfs',
                'headers': [(b'content-type', b'multipart/form-data; boundary=test')],
                'query_string': b'', 'scheme': 'https', 'http_version': '1.1',
            }, receive, send)
            self.assertEqual(sent[0]['status'], 404)

        anyio.run(run)

    def test_missing_credentials_rejected_before_body_parsing_or_snapshot(self):
        with TestClient(make_app()) as http, patch('app.api.routes.get_session') as lookup:
            for method, suffix in (
                ('GET', ''), ('DELETE', ''), ('POST', '/pdfs'),
                ('POST', '/ask'), ('POST', '/ask/stream'),
            ):
                with self.subTest(method=method, suffix=suffix):
                    response = http.request(method, f'/sessions/{SID}{suffix}', content=b'{',
                                            headers={'Content-Type': 'application/json'})
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response.json(), {'detail': 'Session not found.'})
                    self.assertEqual(response.headers.get('cache-control'), 'no-store')
            lookup.assert_not_called()

    def test_cross_origin_creation_is_rejected_before_store(self):
        with TestClient(make_app()) as http, patch('app.api.routes.create_owned_session') as create:
            for headers in (
                {}, {'X-PDF-Agent-Client': 'browser'},
                {**BROWSER, 'Origin': 'https://other.invalid'},
                {**BROWSER, 'Origin': 'null'},
                {**BROWSER, 'Origin': 'http://localhost:5173'},
                {**BROWSER, 'X-Session-Mode': 'bearer'},
            ):
                self.assertEqual(http.post('/sessions', headers=headers).status_code, 403)
            create.assert_not_called()

    def test_database_failure_never_opens_session(self):
        from sqlalchemy.exc import SQLAlchemyError
        from tests.session_access_fixtures import AUTH_HEADERS
        with TestClient(make_app()) as http, patch(
            'app.api.session_access.check_session_owner', side_effect=SQLAlchemyError('private error')
        ), patch('app.api.routes.get_session') as lookup:
            response = http.get(f'/sessions/{SID}', headers=AUTH_HEADERS)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('private error', response.text)
            lookup.assert_not_called()
