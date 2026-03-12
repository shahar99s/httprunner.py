from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

from httporchestrator.engine.context import ExecutionContext
from httporchestrator.request_step import RequestStep


def resolve_value(value: Any, state: dict) -> Any:
    if callable(value):
        return value(state)
    return value


def resolve_mapping(mapping: dict, state: dict) -> dict:
    return {key: resolve_value(value, state) for key, value in dict(mapping).items()}


def build_url(base_url: str, step_url: str) -> str:
    parsed_step_url = urlparse(step_url)
    if parsed_step_url.scheme and parsed_step_url.netloc:
        return step_url

    if not base_url:
        return step_url

    parsed_base_url = urlparse(base_url)
    path = parsed_base_url.path.rstrip("/") + "/" + parsed_step_url.path.lstrip("/")
    return parsed_step_url._replace(
        scheme=parsed_base_url.scheme,
        netloc=parsed_base_url.netloc,
        path=path,
    ).geturl()


def resolve_request_data(
    request: RequestStep,
    context: ExecutionContext,
    state: dict,
) -> dict:
    method = request.require_method().value
    request_data = {
        "method": method,
        "url": build_url(context.flow.base_url, resolve_value(request.url, state)),
        "params": resolve_mapping(request.params_values, state),
        "headers": resolve_mapping(request.header_values, state),
        "cookies": resolve_mapping(request.cookie_values, state),
        "body": resolve_value(request.body_value, state),
        "json_body": resolve_value(request.json_value, state),
        "timeout": request.timeout_seconds,
        "allow_redirects": request.follow_redirects,
    }
    request_headers = {key: value for key, value in request_data["headers"].items() if not str(key).startswith(":")}
    if context.flow.add_request_id:
        request_headers["HRUN-RequestStep-ID"] = f"HRUN-{context.case_id}-{str(int(time.time() * 1000))[-6:]}"
    request_data["headers"] = request_headers
    return request_data
