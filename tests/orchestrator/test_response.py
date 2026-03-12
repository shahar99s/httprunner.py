import httpx

from httporchestrator import Response


def test_response_wraps_json_response():
    raw = httpx.Response(200, json={"name": "demo"}, request=httpx.Request("GET", "https://example.com"))
    response = Response(raw)

    assert response.status_code == 200
    assert response.json() == {"name": "demo"}
    assert response.body == {"name": "demo"}
    assert response.url == raw.url


def test_response_wraps_binary_response():
    raw = httpx.Response(200, content=b"abc", request=httpx.Request("GET", "https://example.com"))
    response = Response(raw)

    assert response.content == b"abc"
    assert response.body == b"abc"
