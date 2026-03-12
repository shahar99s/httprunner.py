import json
from http.cookies import SimpleCookie

import httpx
from loguru import logger

from httporchestrator.recording_models import RequestData, RequestResponseRecord, ResponseData
from httporchestrator.utils import format_response_body_for_log, lower_dict_keys


def _model_dump(data) -> dict:
    if hasattr(data, "model_dump"):
        return data.model_dump()
    return data.dict()


def _log_record(data, label: str):
    """Log a RequestData or ResponseData in debug mode."""
    lines = [f"\n{'=' * 20} {label} details {'=' * 20}"]
    for key, value in _model_dump(data).items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, indent=4, ensure_ascii=False)
        lines.append(f"{key:<8} : {value}")
    logger.debug("\n".join(lines))


def _parse_request_cookies(headers: dict) -> dict:
    cookie_header = headers.get("cookie", "")
    if not cookie_header:
        return {}
    parsed = SimpleCookie()
    parsed.load(cookie_header)
    return {k: m.value for k, m in parsed.items()}


def _parse_request_body(response: httpx.Response, headers: dict):
    try:
        raw = response.request.content
    except httpx.RequestNotRead:
        return None

    content_type = lower_dict_keys(headers).get("content-type", "")
    if "multipart/form-data" in content_type:
        return "upload file stream (OMITTED)"

    try:
        return json.loads(raw)
    except (ValueError, TypeError, UnicodeDecodeError):
        return raw


def _is_head_response(response: httpx.Response) -> bool:
    return response.request.method.upper() == "HEAD"


def _parse_response_body(response: httpx.Response, headers: dict):
    if _is_head_response(response):
        return None

    content_type = lower_dict_keys(headers).get("content-type", "")
    content_disposition = lower_dict_keys(headers).get("content-disposition", "")

    try:
        return response.json()
    except ValueError:
        raw = response.content if ("image" in content_type or "attachment" in content_disposition) else response.text
        return format_response_body_for_log(raw, content_type, content_disposition)


class ExchangeRecorder:
    def capture(self, response: httpx.Response, log_details: bool = True) -> RequestResponseRecord:
        request_headers = dict(response.request.headers)
        request_data = RequestData(
            method=response.request.method,
            url=str(response.request.url),
            headers=request_headers,
            cookies=_parse_request_cookies(request_headers),
            body=_parse_request_body(response, request_headers),
        )
        if log_details:
            _log_record(request_data, "request")

        response_headers = dict(response.headers)
        lower_headers = lower_dict_keys(response_headers)
        content_type = lower_headers.get("content-type", "")
        response_body = _parse_response_body(response, response_headers)

        response_data = ResponseData(
            status_code=response.status_code,
            cookies=dict(response.cookies) if response.cookies else {},
            encoding=response.encoding,
            headers=response_headers,
            content_type=content_type,
            body=response_body,
        )
        if log_details:
            _log_record(response_data, "response")

        return RequestResponseRecord(request=request_data, response=response_data)


def capture_http_exchange(response: httpx.Response, log_details: bool = True) -> RequestResponseRecord:
    """Capture a normalized request/response record from a single httpx response."""
    return ExchangeRecorder().capture(response, log_details=log_details)
