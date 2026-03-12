from types import SimpleNamespace

from httporchestrator.engine.http_transport import send_request


class FakeResponse:
    def __init__(self):
        self.is_stream_consumed = False
        self.read_calls = 0

    def read(self):
        self.read_calls += 1
        self.is_stream_consumed = True


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.cookies = {}

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def build_context(response):
    return SimpleNamespace(client=FakeClient(response))


def test_send_request_does_not_read_head_response():
    response = FakeResponse()
    context = build_context(response)

    send_request(
        context,
        "HEAD",
        {
            "url": "https://example.com/file",
            "headers": {},
            "params": {},
            "cookies": {},
        },
    )

    assert response.read_calls == 0


def test_send_request_reads_get_response():
    response = FakeResponse()
    context = build_context(response)

    send_request(
        context,
        "GET",
        {
            "url": "https://example.com/file",
            "headers": {},
            "params": {},
            "cookies": {},
        },
    )

    assert response.read_calls == 1
