from __future__ import annotations

import json
import os

from loguru import logger

from httporchestrator import utils
from httporchestrator.engine.context import ExecutionContext
from httporchestrator.utils import LOGGER_FORMAT

try:
    import allure

    ALLURE = allure
except ModuleNotFoundError:
    ALLURE = None


def _format_value(value) -> str:
    import httpx

    if isinstance(value, dict):
        return json.dumps(value, indent=4, ensure_ascii=False)
    if isinstance(value, httpx.Headers):
        return json.dumps(dict(value.items()), indent=4, ensure_ascii=False)
    return repr(utils.omit_long_data(value))


def _is_head_response(response) -> bool:
    request = getattr(response, "request", None)
    method = getattr(request, "method", "")
    return str(method).upper() == "HEAD"


class WorkflowLogger:
    def start_workflow(self, context: ExecutionContext) -> int | None:
        if context.log_path:
            os.makedirs(os.path.dirname(context.log_path), exist_ok=True)
        if ALLURE is not None and not context.referenced:
            ALLURE.dynamic.title(context.flow.name)
            ALLURE.dynamic.description(f"Workflow ID: {context.case_id}")

        logger.info(f"Start to run flow: {context.flow.name}, Flow ID: {context.case_id}")
        if not context.log_path:
            return None
        return logger.add(context.log_path, format=LOGGER_FORMAT, level="DEBUG")

    def finish_workflow(self, context: ExecutionContext, sink_id: int | None) -> None:
        if context.log_path:
            logger.info(f"generate flow log: {context.log_path}")
        if sink_id is not None:
            logger.remove(sink_id)
        if ALLURE is not None and context.log_path:
            ALLURE.attach.file(
                context.log_path,
                name="all log",
                attachment_type=ALLURE.attachment_type.TEXT,
            )

    def log_step_begin(self, step_name: str) -> None:
        logger.info(f"run step begin: {step_name} >>>>>>")

    def log_step_end(self, step_name: str) -> None:
        logger.info(f"run step end: {step_name} <<<<<<\n")

    def log_retry(self, step_name: str, index: int, retry_times: int, retry_interval: float) -> None:
        logger.warning(f"run step {step_name} failed, wait {retry_interval} sec and try again")
        logger.info(f"run step retry ({index + 1}/{retry_times} time): {step_name} >>>>>>")

    def log_request(self, method: str, url: str, request_data: dict, log_details: bool = True) -> None:
        if not log_details:
            return

        request_print = "====== request details ======\n"
        request_print += f"url: {url}\n"
        request_print += f"method: {method}\n"
        for key, value in request_data.items():
            request_print += f"{key}: {_format_value(value)}\n"
        logger.debug(request_print)
        if ALLURE is not None:
            ALLURE.attach(
                request_print,
                name="request details",
                attachment_type=ALLURE.attachment_type.TEXT,
            )

    def log_response(self, response, response_time_ms: float, log_details: bool = True) -> None:
        import httpx

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(str(exc))

        if not log_details:
            return

        if not response.is_error:
            content_size = int(dict(response.headers).get("content-length") or 0)
            logger.info(
                f"status_code: {response.status_code}, "
                f"response_time(ms): {response_time_ms} ms, "
                f"response_length: {content_size} bytes"
            )

        response_print = "====== response details ======\n"
        response_print += f"status_code: {response.status_code}\n"
        response_print += f"headers: {_format_value(response.headers)}\n"

        response_headers = dict(response.headers)
        content_type = response_headers.get("Content-Type", "")
        content_disposition = response_headers.get("Content-Disposition", "")

        if _is_head_response(response):
            body = "<omitted for HEAD request>"
        else:
            try:
                body = response.json()
            except (json.JSONDecodeError, ValueError):
                if "attachment" in content_disposition.lower():
                    body = utils.format_response_body_for_log(response.content, content_type, content_disposition)
                else:
                    body = utils.format_response_body_for_log(response.text, content_type, content_disposition)

        response_print += f"body: {_format_value(body)}\n"
        logger.debug(response_print)
        if ALLURE is not None:
            ALLURE.attach(
                response_print,
                name="response details",
                attachment_type=ALLURE.attachment_type.TEXT,
            )

    def log_state_updates(self, state_updates: dict, log_details: bool = True) -> None:
        if state_updates and log_details:
            logger.info(f"state updates: {state_updates}")

    def log_skipped_step(self, step_name: str) -> None:
        logger.warning(f"step '{step_name}' is skipped due to condition not met")
