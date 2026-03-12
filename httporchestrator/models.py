from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Mapping

import httpx

VariablesMapping = Dict[str, Any]
Headers = Dict[str, str]
Cookies = Dict[str, str]

PrepareHook = Callable[[VariablesMapping], Mapping[str, Any] | None]
CaptureHook = Callable[[Any, VariablesMapping], Any]
HandleHook = Callable[[Any, VariablesMapping], Mapping[str, Any] | None]
EffectHook = Callable[[Any, VariablesMapping], None]
AssertHook = Callable[[Any, VariablesMapping], bool | None]
PredicateHook = Callable[[VariablesMapping], bool]


class MethodEnum(str, Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    PATCH = "PATCH"


@dataclass(frozen=True)
class RetryPolicy:
    times: int = 0
    interval: float = 0.0
    retry_on: tuple[type[BaseException], ...] = ()

    def should_retry(self, exc: BaseException) -> bool:
        retry_types = self.retry_on or (httpx.HTTPError,)
        return isinstance(exc, retry_types)


@dataclass(frozen=True)
class CaptureAction:
    name: str
    fn: CaptureHook


@dataclass(frozen=True)
class Assertion:
    fn: AssertHook
    message: str = ""


@dataclass
class WorkflowTiming:
    start_at: float = 0.0
    start_at_iso_format: str = ""
    duration: float = 0.0


@dataclass
class WorkflowIO:
    initial_state: VariablesMapping = field(default_factory=dict)
    exported: VariablesMapping = field(default_factory=dict)


@dataclass
class StepResult:
    name: str = ""
    step_type: str = ""
    success: bool = False
    data: Any = None
    elapsed: float = 0.0
    content_size: float = 0.0
    state_updates: VariablesMapping = field(default_factory=dict)
    attachment: str = ""


@dataclass
class WorkflowSummary:
    name: str
    success: bool
    case_id: str
    time: WorkflowTiming
    in_out: WorkflowIO = field(default_factory=WorkflowIO)
    log: str = ""
    step_results: list[StepResult] = field(default_factory=list)


@dataclass
class WorkflowRun:
    summary: WorkflowSummary
    step_results: list[StepResult] = field(default_factory=list)
    session_variables: VariablesMapping = field(default_factory=dict)
    exported: VariablesMapping = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.summary.success
