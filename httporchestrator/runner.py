from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from httporchestrator.models import VariablesMapping, WorkflowRun


def _merge_mapping(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    merged.update(updates)
    return merged


@dataclass(frozen=True)
class Flow:
    name: str = "flow"
    base_url: str = ""
    steps: tuple[object, ...] = ()
    verify: bool = False
    log_details: bool = True
    add_request_id: bool = True
    state_values: VariablesMapping = field(default_factory=dict)
    exports: tuple[str, ...] = ()
    artifact_dir: str | None = None

    def with_name(self, name: str) -> "Flow":
        return replace(self, name=name)

    def state(self, values: VariablesMapping | None = None, /, **kwargs) -> "Flow":
        updates = dict(values or {})
        updates.update(kwargs)
        return replace(self, state_values=_merge_mapping(self.state_values, updates))

    def export(self, names: list[str] | tuple[str, ...]) -> "Flow":
        ordered = list(self.exports)
        for name in names:
            if name not in ordered:
                ordered.append(name)
        return replace(self, exports=tuple(ordered))

    def with_steps(self, steps: list[object] | tuple[object, ...]) -> "Flow":
        return replace(self, steps=tuple(steps))

    def with_artifact_dir(self, artifact_dir: str | None) -> "Flow":
        return replace(self, artifact_dir=artifact_dir)

    def run(
        self,
        inputs: dict[str, Any] | None = None,
        *,
        client=None,
        case_id: str | None = None,
    ) -> WorkflowRun:
        from httporchestrator.engine import default_workflow_engine

        return default_workflow_engine.run(self, inputs=inputs, client=client, case_id=case_id)
