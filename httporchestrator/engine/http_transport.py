import time

import httpx

from httporchestrator.engine.context import ExecutionContext


def send_request(context: ExecutionContext, method: str, request_data: dict) -> tuple[httpx.Response, float]:
    kwargs = dict(request_data)
    url = kwargs.pop("url")
    kwargs.setdefault("timeout", 120)
    if "allow_redirects" in kwargs:
        kwargs["follow_redirects"] = kwargs.pop("allow_redirects")
    kwargs.setdefault("follow_redirects", True)
    kwargs.pop("stream", None)

    cookies = kwargs.pop("cookies", None)
    if cookies:
        context.client.cookies.update(cookies)

    body = kwargs.pop("body", None)
    if body is not None:
        if isinstance(body, (bytes, str)):
            kwargs["content"] = body
        else:
            kwargs["data"] = body

    json_body = kwargs.pop("json_body", None)
    if json_body is not None:
        kwargs["json"] = json_body

    params = kwargs.get("params")
    if not params and params is not None:
        kwargs.pop("params")

    request_start = time.time()
    response = context.client.request(method, url, **kwargs)

    if method != "HEAD" and not response.is_stream_consumed:
        try:
            response.read()
        except Exception:
            pass

    response_time_ms = round((time.time() - request_start) * 1000, 2)
    return response, response_time_ms
