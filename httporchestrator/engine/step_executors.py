from __future__ import annotations

import time
from collections.abc import Mapping

from httporchestrator.engine.http_transport import send_request
from httporchestrator.engine.request_resolver import resolve_request_data
from httporchestrator.exceptions import ParameterError, ValidationFailure
from httporchestrator.models import StepResult
from httporchestrator.recording_models import RequestMetrics, RequestSession
from httporchestrator.request_step import ConditionalStep, RepeatableStep, RequestStep
from httporchestrator.response import Response
from httporchestrator.workflow_step import CallFlow


def describe_step_type(step) -> str:
    if isinstance(step, RequestStep):
        return f"request-{step.require_method().value}"
    if isinstance(step, CallFlow):
        return "flow"
    if isinstance(step, ConditionalStep):
        return describe_step_type(step.step)
    if isinstance(step, RepeatableStep):
        return "repeat"
    raise RuntimeError(f"unsupported step type: {type(step)!r}")


def _require_mapping_updates(updates, hook_name: str) -> dict:
    if updates is None:
        return {}
    if not isinstance(updates, Mapping):
        raise ParameterError(f"{hook_name} must return a mapping or None, got {type(updates).__name__}")
    return dict(updates)


class RequestExecutor:
    step_type = RequestStep

    def __init__(self, exchange_recorder, workflow_logger):
        self._exchange_recorder = exchange_recorder
        self._workflow_logger = workflow_logger

    def _run_assertions(self, request: RequestStep, response: Response, state: dict) -> list[dict]:
        results = []
        for assertion in request.assertions:
            try:
                outcome = assertion.fn(response, state)
                passed = outcome is not False
                if not passed:
                    raise ValidationFailure(assertion.message or f"assertion failed for step '{request.name}'")
                results.append({"message": assertion.message, "result": "pass"})
            except ValidationFailure:
                results.append({"message": assertion.message, "result": "fail"})
                raise
            except Exception as exc:
                results.append({"message": assertion.message or str(exc), "result": "fail"})
                raise ValidationFailure(assertion.message or str(exc)) from exc
        return results

    def execute(self, request: RequestStep, context, engine) -> StepResult:
        start_time = time.time()
        step_result = StepResult(name=request.name, step_type=describe_step_type(request), success=False)
        response = None
        response_list = []

        try:
            state = context.build_state_snapshot(request.state_values)
            for before in request.before_hooks:
                updates = _require_mapping_updates(before(state), "prepare")
                if updates:
                    state.update(updates)

            request_data = resolve_request_data(request, context, state)
            method = request_data.pop("method")
            self._workflow_logger.log_request(
                method,
                request_data["url"],
                request_data,
                log_details=context.flow.log_details,
            )
            response, response_time_ms = send_request(context, method, request_data)
            self._workflow_logger.log_response(response, response_time_ms, log_details=context.flow.log_details)

            response_object = Response(response)
            state["response"] = response_object

            state_updates = {}
            for capture in request.captures:
                value = capture.fn(response_object, state)
                state[capture.name] = value
                state_updates[capture.name] = value

            for after in request.after_hooks:
                updates = _require_mapping_updates(after(response_object, state), "after")
                if updates:
                    state.update(updates)
                    state_updates.update(updates)

            check_results = self._run_assertions(request, response_object, state)
            response_list = response.history + [response]
            content_size = int(dict(response.headers).get("content-length") or 0)
            try:
                elapsed_ms = response.elapsed.total_seconds() * 1000.0 if response.elapsed else response_time_ms
            except RuntimeError:
                elapsed_ms = response_time_ms

            step_result.data = RequestSession(
                success=True,
                req_resps=[
                    self._exchange_recorder.capture(item, log_details=context.flow.log_details)
                    for item in response_list
                ],
                stat=RequestMetrics(
                    response_time_ms=response_time_ms,
                    elapsed_ms=elapsed_ms,
                    content_size=content_size,
                ),
                checks=check_results,
            )
            step_result.success = True
            step_result.state_updates = state_updates
            step_result.content_size = content_size
            step_result.elapsed = time.time() - start_time
            self._workflow_logger.log_state_updates(step_result.state_updates, context.flow.log_details)
            return step_result
        finally:
            if response is not None:
                response_list = response_list or (response.history + [response])
                for item in response_list:
                    try:
                        item.close()
                    except Exception:
                        pass


class CallFlowExecutor:
    step_type = CallFlow

    def __init__(self, workflow_logger):
        self._workflow_logger = workflow_logger

    def execute(self, step: CallFlow, context, engine) -> StepResult:
        child_flow = step.require_flow()
        child_run = engine.run(
            child_flow,
            client=context.client,
            case_id=context.case_id,
            referenced=True,
            initial_state=context.build_state_snapshot(step.state_values),
            export_names=list(step.exports) or None,
            flow_name=step.flow_name or step.name,
        )
        result = StepResult(
            name=step.name,
            step_type="flow",
            success=child_run.success,
            data=child_run.step_results,
            state_updates=dict(child_run.exported),
        )
        self._workflow_logger.log_state_updates(result.state_updates, context.flow.log_details)
        return result


class ConditionalStepExecutor:
    step_type = ConditionalStep

    def __init__(self, workflow_logger):
        self._workflow_logger = workflow_logger

    def execute(self, step: ConditionalStep, context, engine) -> StepResult:
        if bool(step.predicate(context.build_state_snapshot())):
            return engine.execute_nested_step(step.step, context)

        self._workflow_logger.log_skipped_step(step.name)
        return StepResult(
            name=step.name,
            step_type=describe_step_type(step.step),
            success=True,
            attachment="skipped(when)",
        )


class RepeatableStepExecutor:
    step_type = RepeatableStep

    def execute(self, step: RepeatableStep, context, engine) -> StepResult:
        child_results = []
        state_updates = {}

        while bool(step.predicate(context.build_state_snapshot())):
            child_result = engine.execute_nested_step(step.step, context)
            context.apply_step_result(child_result)
            child_results.append(child_result)
            state_updates.update(child_result.state_updates)

        return StepResult(
            name=step.name,
            step_type="repeat",
            success=True,
            data=child_results,
            state_updates=state_updates,
        )
