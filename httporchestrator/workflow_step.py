from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from httporchestrator.exceptions import ParameterError
from httporchestrator.models import RetryPolicy, VariablesMapping
from httporchestrator.runner import Flow


def _merge_mapping(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    merged.update(updates)
    return merged


@dataclass(frozen=True)
class CallFlow:
    name: str
    flow: Flow | None = None
    flow_name: str | None = None
    state_values: VariablesMapping = field(default_factory=dict)
    exports: tuple[str, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    def use(self, flow: Flow, flow_name: str | None = None) -> "CallFlow":
        if not isinstance(flow, Flow):
            raise ParameterError(f"Invalid flow reference: {flow}")
        return replace(self, flow=flow, flow_name=flow_name)

    def state(self, values: VariablesMapping | None = None, /, **kwargs) -> "CallFlow":
        updates = dict(values or {})
        updates.update(kwargs)
        return replace(self, state_values=_merge_mapping(self.state_values, updates))

    def export(self, *names: str) -> "CallFlow":
        ordered = list(self.exports)
        for name in names:
            if name not in ordered:
                ordered.append(name)
        return replace(self, exports=tuple(ordered))

    def retry(
        self,
        times: int,
        interval: float,
        retry_on: tuple[type[BaseException], ...] = (),
    ) -> "CallFlow":
        return replace(
            self,
            retry_policy=RetryPolicy(times=times, interval=interval, retry_on=retry_on),
        )

    def require_flow(self) -> Flow:
        if self.flow is None:
            raise ParameterError(f"flow step '{self.name}' has no flow configured")
        return self.flow
