import httpx

from httporchestrator import Flow, RequestStep
from httporchestrator.engine.context import ExecutionContext
from httporchestrator.engine.request_resolver import build_url, resolve_request_data


def build_context(**flow_kwargs):
    flow = Flow(name="test", **flow_kwargs)
    return ExecutionContext.create(
        flow=flow,
        client=httpx.Client(),
        initial_state={"session_token": "session-123", **dict(flow.state_values)},
    )


def test_build_url_joins_relative_paths():
    assert build_url("https://example.com/api", "/users") == "https://example.com/api/users"


def test_resolve_request_supports_callables_and_request_id():
    context = build_context(base_url="https://example.com", state_values={"prefix": "Bearer"})
    step = (
        RequestStep("resolve")
        .state(token=lambda state: state["session_token"])
        .get(lambda state: f"/download/{state['token']}")
        .headers(Authorization=lambda state: f"{state['prefix']} {state['token']}")
        .params(limit=lambda state: 5)
        .json(lambda state: {"token": state["token"]})
    )

    state = context.build_state_snapshot(step.state_values)
    request_data = resolve_request_data(step, context, state)

    assert state["token"] == "session-123"
    assert request_data["url"] == "https://example.com/download/session-123"
    assert request_data["headers"]["Authorization"] == "Bearer session-123"
    assert request_data["params"]["limit"] == 5
    assert request_data["json_body"] == {"token": "session-123"}
    assert "HRUN-RequestStep-ID" in request_data["headers"]


def test_resolve_request_keeps_literal_strings_literal():
    context = build_context(base_url="https://example.com")
    step = RequestStep("literal").get("/items").headers(Authorization="$token")

    request_data = resolve_request_data(step, context, context.build_state_snapshot(step.state_values))

    assert request_data["headers"]["Authorization"] == "$token"


def test_build_url_keeps_absolute_url():
    assert build_url("https://example.com/api", "https://other.example/path") == "https://other.example/path"
