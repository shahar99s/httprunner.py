from __future__ import annotations

import time

import httpx

from httporchestrator.engine.context import ExecutionContext
from httporchestrator.engine.step_executors import (
    CallFlowExecutor,
    ConditionalStepExecutor,
    RepeatableStepExecutor,
    RequestExecutor,
)
from httporchestrator.engine.workflow_logger import WorkflowLogger
from httporchestrator.models import RetryPolicy, StepResult, WorkflowRun
from httporchestrator.recording import ExchangeRecorder
from httporchestrator.runner import Flow


class WorkflowEngine:
    def __init__(self):
        self._exchange_recorder = ExchangeRecorder()
        self._workflow_logger = WorkflowLogger()
        self._executors = {}
        for executor in (
            RequestExecutor(self._exchange_recorder, self._workflow_logger),
            CallFlowExecutor(self._workflow_logger),
            ConditionalStepExecutor(self._workflow_logger),
            RepeatableStepExecutor(),
        ):
            self._executors[executor.step_type] = executor

    def run(
        self,
        flow: Flow,
        inputs: dict | None = None,
        *,
        client: httpx.Client | None = None,
        case_id: str | None = None,
        referenced: bool = False,
        initial_state: dict | None = None,
        export_names: list[str] | None = None,
        flow_name: str | None = None,
    ) -> WorkflowRun:
        context = self._execute(
            flow,
            inputs=inputs,
            client=client,
            case_id=case_id,
            referenced=referenced,
            initial_state=initial_state,
            export_names=export_names,
            flow_name=flow_name,
        )
        return context.create_run()

    def _execute(
        self,
        flow: Flow,
        *,
        inputs: dict | None = None,
        client: httpx.Client | None = None,
        case_id: str | None = None,
        referenced: bool = False,
        initial_state: dict | None = None,
        export_names: list[str] | None = None,
        flow_name: str | None = None,
    ) -> ExecutionContext:
        owned_client = client is None
        execution_client = client or httpx.Client(verify=flow.verify)
        resolved_flow = flow.with_name(flow_name) if flow_name else flow
        starting_state = dict(resolved_flow.state_values)
        starting_state.update(initial_state or {})
        starting_state.update(inputs or {})
        context = ExecutionContext.create(
            flow=resolved_flow,
            client=execution_client,
            case_id=case_id,
            referenced=referenced,
            export_names=export_names,
            initial_state=starting_state,
        )

        sink_id = self._workflow_logger.start_workflow(context)
        context.start_at = time.time()
        try:
            for step in resolved_flow.steps:
                context.record_step_result(self.execute_nested_step(step, context))
        finally:
            context.duration = time.time() - context.start_at
            self._workflow_logger.finish_workflow(context, sink_id)
            if owned_client:
                execution_client.close()

        return context

    def execute_nested_step(self, step, context: ExecutionContext) -> StepResult:
        step_name = getattr(step, "name", type(step).__name__)
        self._workflow_logger.log_step_begin(step_name)
        try:
            return self._execute_with_retry(step, context)
        finally:
            self._workflow_logger.log_step_end(step_name)

    def _execute_with_retry(self, step, context: ExecutionContext) -> StepResult:
        policy = getattr(step, "retry_policy", RetryPolicy())
        for index in range(policy.times + 1):
            try:
                executor = self._executors.get(type(step))
                if executor is None:
                    raise RuntimeError(f"unsupported step type: {type(step)!r}")
                return executor.execute(step, context, self)
            except Exception as exc:
                if index == policy.times or not policy.should_retry(exc):
                    raise
                self._workflow_logger.log_retry(
                    step_name=getattr(step, "name", type(step).__name__),
                    index=index,
                    retry_times=policy.times,
                    retry_interval=policy.interval,
                )
                time.sleep(policy.interval)
        raise RuntimeError("step execution did not return a result")


default_workflow_engine = WorkflowEngine()
