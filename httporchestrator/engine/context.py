from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import httpx

from httporchestrator.exceptions import ParameterError
from httporchestrator.models import (
    StepResult,
    VariablesMapping,
    WorkflowIO,
    WorkflowRun,
    WorkflowSummary,
    WorkflowTiming,
)

if TYPE_CHECKING:
    from httporchestrator.runner import Flow


def _resolve_value(value: Any, state: VariablesMapping) -> Any:
    if callable(value):
        return value(state)
    return value


@dataclass
class ExecutionContext:
    flow: "Flow"
    case_id: str
    client: httpx.Client
    referenced: bool = False
    export_names: list[str] | None = None
    log_path: str = ""
    initial_state: VariablesMapping = field(default_factory=dict)
    state: VariablesMapping = field(default_factory=dict)
    step_results: list[StepResult] = field(default_factory=list)
    start_at: float = 0.0
    duration: float = 0.0

    @classmethod
    def create(
        cls,
        flow: "Flow",
        client: httpx.Client,
        *,
        case_id: str | None = None,
        referenced: bool = False,
        export_names: list[str] | None = None,
        initial_state: VariablesMapping | None = None,
    ) -> "ExecutionContext":
        resolved_case_id = case_id or str(uuid.uuid4())
        artifact_dir = flow.artifact_dir
        log_path = ""
        if artifact_dir:
            log_path = os.path.join(artifact_dir, "logs", f"{resolved_case_id}.run.log")
        state = dict(initial_state or {})
        return cls(
            flow=flow,
            case_id=resolved_case_id,
            client=client,
            referenced=referenced,
            export_names=export_names,
            log_path=log_path,
            initial_state=dict(state),
            state=state,
        )

    def build_state_snapshot(self, state_values: VariablesMapping | None = None) -> VariablesMapping:
        snapshot = dict(self.state)
        for key, value in dict(state_values or {}).items():
            snapshot[key] = _resolve_value(value, snapshot)
        return snapshot

    def apply_step_result(self, step_result: StepResult) -> None:
        self.state.update(step_result.state_updates)

    def record_step_result(self, step_result: StepResult) -> None:
        self.apply_step_result(step_result)
        self.step_results.append(step_result)

    def collect_exported_variables(self) -> VariablesMapping:
        export_names = self.export_names if self.export_names is not None else list(self.flow.exports)
        export_mapping = {}
        for name in export_names:
            if name not in self.state:
                raise ParameterError(f"failed to export '{name}' from state {self.state}")
            export_mapping[name] = self.state[name]
        return export_mapping

    def create_summary(self) -> WorkflowSummary:
        start_at_iso = datetime.utcfromtimestamp(self.start_at).isoformat() if self.start_at else ""
        return WorkflowSummary(
            name=self.flow.name,
            success=all(result.success for result in self.step_results),
            case_id=self.case_id,
            time=WorkflowTiming(
                start_at=self.start_at,
                start_at_iso_format=start_at_iso,
                duration=self.duration,
            ),
            in_out=WorkflowIO(
                initial_state=dict(self.initial_state),
                exported=self.collect_exported_variables(),
            ),
            log=self.log_path,
            step_results=list(self.step_results),
        )

    def create_run(self) -> WorkflowRun:
        summary = self.create_summary()
        return WorkflowRun(
            summary=summary,
            step_results=list(self.step_results),
            session_variables=dict(self.state),
            exported=dict(summary.in_out.exported),
        )
