# httporchestrator

`httporchestrator` is a small library for explicit multi-step HTTP flows with a single shared state.

## Public API

- `Flow` defines a flow.
- `RequestStep` defines one HTTP request step.
- `ConditionalStep` conditionally runs a step.
- `RepeatableStep` repeats a step run_while a predicate stays true.
- `CallFlow` runs another flow and exports selected state back to the parent.
- `Flow.run()` returns a `WorkflowRun`.

## Quick Start

```python
from httporchestrator import Flow, RequestStep

flow = Flow(
    name="echo test",
    base_url="https://postman-echo.com",
    steps=(
        RequestStep("load token")
        .get("/get")
        .params(foo="bar")
        .capture("saved_foo", lambda response, state: response.json()["args"]["foo"])
        .check(lambda response, state: response.status_code == 200, "request should succeed"),
        RequestStep("post extracted value")
        .post("/post")
        .json(lambda state: {"foo": state["saved_foo"]})
        .check(
            lambda response, state: response.json()["json"]["foo"] == "bar",
            "posted payload should contain the captured value",
        ),
    ),
).export(["saved_foo"])

run = flow.run()
assert run.success
assert run.exported["saved_foo"] == "bar"
```

## Step Phases

`RequestStep` steps execute in a fixed order:

1. Step-local `.state(...)` values are resolved against the current flow state.
2. `.before(fn)` callbacks can update request-time state.
3. RequestStep URL, headers, params, body, and JSON are resolved.
4. The HTTP request is sent.
5. `.capture(...)`, `.after(fn)`, `.after(fn)`, and `.check(...)` run in order.
6. The produced state updates are merged back into the flow state.

Callback contracts:

- `.before(fn)` takes `state` and must return a mapping or `None`.
- `.after(fn)` takes `response, state` and must return a mapping or `None`.
- `.capture(name, fn)` saves one named value into state.
- `.after(fn)` takes `response, state` and must return `None`.
- `.check(fn, message="")` raises `ValidationFailure` when the assertion returns `False` or throws.

## Nested and Conditional Flows

```python
from httporchestrator import CallFlow, Flow, RequestStep, ConditionalStep

child = Flow(
    name="health check",
    base_url="https://postman-echo.com",
    steps=(
        RequestStep("ping")
        .get("/get")
        .capture("ok", lambda response, state: response.status_code == 200)
        .check(lambda response, state: response.status_code == 200, "health check failed"),
    ),
).export(["ok"])

parent = Flow(
    name="parent",
    steps=(
        CallFlow("run health check").use(child, flow_name="nested health check").export("ok"),
        ConditionalStep(RequestStep("optional ping").get("https://postman-echo.com/get")).run_when(lambda state: state["ok"] is True),
    ),
).export(["ok"])
```

## Runtime Model

- `WorkflowRun.summary` contains the overall result.
- `WorkflowRun.session_variables` contains the final flow state.
- `WorkflowRun.exported` contains only the configured exported values.
- `StepResult.state_updates` contains the state written by that step.

## Fetchers

Use `create_fetcher()` for provider auto-detection:

```python
from fetchers.fetcher_registry import create_fetcher
from fetchers.utils import Mode

fetcher = create_fetcher(
    "https://wetransfer.com/downloads/TRANSFER_ID/SECURITY_HASH",
    mode=Mode.INFO,
)
run = fetcher.run()
print(run.summary.success)
```
