from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from httporchestrator.exceptions import ParameterError
from httporchestrator.models import (
    Assertion,
    CaptureAction,
    HandleHook,
    MethodEnum,
    PredicateHook,
    PrepareHook,
    RetryPolicy,
    VariablesMapping,
)


def _merge_mapping(current: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    merged.update(updates)
    return merged


@dataclass(frozen=True)
class RequestStep:
    name: str
    method: MethodEnum | None = None
    url: Any = ""
    params_values: VariablesMapping = field(default_factory=dict)
    header_values: VariablesMapping = field(default_factory=dict)
    cookie_values: VariablesMapping = field(default_factory=dict)
    body_value: Any = None
    json_value: Any = None
    timeout_seconds: float = 120.0
    follow_redirects: bool = True
    state_values: VariablesMapping = field(default_factory=dict)
    before_hooks: tuple[PrepareHook, ...] = ()
    captures: tuple[CaptureAction, ...] = ()
    after_hooks: tuple[HandleHook, ...] = ()
    assertions: tuple[Assertion, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    def _with_method(self, method: MethodEnum, url: Any) -> "RequestStep":
        return replace(self, method=method, url=url)

    def get(self, url: Any) -> "RequestStep":
        return self._with_method(MethodEnum.GET, url)

    def post(self, url: Any) -> "RequestStep":
        return self._with_method(MethodEnum.POST, url)

    def put(self, url: Any) -> "RequestStep":
        return self._with_method(MethodEnum.PUT, url)

    def head(self, url: Any) -> "RequestStep":
        return self._with_method(MethodEnum.HEAD, url)

    def delete(self, url: Any) -> "RequestStep":
        return self._with_method(MethodEnum.DELETE, url)

    def options(self, url: Any) -> "RequestStep":
        return self._with_method(MethodEnum.OPTIONS, url)

    def patch(self, url: Any) -> "RequestStep":
        return self._with_method(MethodEnum.PATCH, url)

    def state(self, values: VariablesMapping | None = None, /, **kwargs) -> "RequestStep":
        updates = dict(values or {})
        updates.update(kwargs)
        return replace(self, state_values=_merge_mapping(self.state_values, updates))

    def params(self, **params) -> "RequestStep":
        return replace(self, params_values=_merge_mapping(self.params_values, params))

    def headers(self, **headers) -> "RequestStep":
        return replace(self, header_values=_merge_mapping(self.header_values, headers))

    def cookies(self, **cookies) -> "RequestStep":
        return replace(self, cookie_values=_merge_mapping(self.cookie_values, cookies))

    def data(self, data: Any) -> "RequestStep":
        return replace(self, body_value=data)

    def body(self, data: Any) -> "RequestStep":
        return self.data(data)

    def json(self, req_json: Any) -> "RequestStep":
        return replace(self, json_value=req_json)

    def timeout(self, timeout: float) -> "RequestStep":
        return replace(self, timeout_seconds=timeout)

    def allow_redirects(self, allow_redirects: bool) -> "RequestStep":
        return replace(self, follow_redirects=allow_redirects)

    def before(self, fn: PrepareHook) -> "RequestStep":
        return replace(self, before_hooks=self.before_hooks + (fn,))

    def capture(self, name: str, fn) -> "RequestStep":
        return replace(self, captures=self.captures + (CaptureAction(name=name, fn=fn),))

    def after(self, fn: HandleHook) -> "RequestStep":
        return replace(self, after_hooks=self.after_hooks + (fn,))

    def check(self, fn, message: str = "") -> "RequestStep":
        return replace(self, assertions=self.assertions + (Assertion(fn=fn, message=message),))

    def retry(
        self,
        times: int,
        interval: float,
        retry_on: tuple[type[BaseException], ...] = (),
    ) -> "RequestStep":
        return replace(
            self,
            retry_policy=RetryPolicy(times=times, interval=interval, retry_on=retry_on),
        )

    def require_method(self) -> MethodEnum:
        if self.method is None:
            raise ParameterError(f"request '{self.name}' has no HTTP method configured")
        return self.method


@dataclass(frozen=True)
class ConditionalStep:
    step: object
    predicate: PredicateHook = lambda _state: True

    @property
    def name(self) -> str:
        return getattr(self.step, "name", "when")

    def run_when(self, predicate: PredicateHook) -> "ConditionalStep":
        return replace(self, predicate=predicate)


@dataclass(frozen=True)
class RepeatableStep:
    step: object
    predicate: PredicateHook = lambda _state: True

    @property
    def name(self) -> str:
        return getattr(self.step, "name", "repeat")

    def run_while(self, predicate: PredicateHook) -> "RepeatableStep":
        return replace(self, predicate=predicate)
