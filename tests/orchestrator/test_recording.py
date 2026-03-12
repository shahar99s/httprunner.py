import httpx

from httporchestrator.recording import capture_http_exchange


def test_capture_http_exchange_records_request_and_response():
    request = httpx.Request(
        "POST",
        "https://example.com/upload",
        content=b"payload",
        headers={"Cookie": "a=1"},
    )
    response = httpx.Response(
        201,
        json={"ok": True},
        request=request,
        headers={"Content-Type": "application/json"},
    )

    record = capture_http_exchange(response, log_details=False)

    assert record.request.method == "POST"
    assert record.request.url == "https://example.com/upload"
    assert record.request.cookies == {"a": "1"}
    assert record.response.status_code == 201
    assert record.response.body == {"ok": True}
