import pytest

from httporchestrator import CallFlow, ConditionalStep, Flow, RepeatableStep, RequestStep
from httporchestrator.exceptions import ParameterError


def test_request_builders_are_immutable_and_accumulate_callbacks():
    def before(state):
        return {"token": "abc"}

    def capture(response, state):
        return {"ok": True}

    def after(response, state):
        return {"saved": True}

    def assertion(response, state):
        return True

    step = (
        RequestStep("load item")
        .get("/items")
        .state(item_id=1)
        .before(before)
        .capture("result", capture)
        .after(after)
        .check(assertion, "should pass")
        .retry(2, 1)
    )

    assert step.name == "load item"
    assert step.method.value == "GET"
    assert step.url == "/items"
    assert step.state_values == {"item_id": 1}
    assert step.before_hooks == (before,)
    assert len(step.captures) == 1
    assert step.after_hooks == (after,)
    assert len(step.assertions) == 1
    assert step.retry_policy.times == 2
    assert step.retry_policy.interval == 1


def test_call_flow_requires_flow_instance():
    child = Flow(name="child")
    step = CallFlow("run child").use(child, flow_name="nested").export("token")

    assert step.flow is child
    assert step.flow_name == "nested"
    assert step.exports == ("token",)


def test_call_flow_rejects_non_flow():
    with pytest.raises(ParameterError):
        CallFlow("bad").use(object())


def test_when_wraps_inner_step():
    wrapped = ConditionalStep(RequestStep("maybe").get("/path")).run_when(lambda state: state.get("enabled") is True)

    assert wrapped.name == "maybe"
    assert wrapped.step.name == "maybe"


def test_repeat_wraps_inner_step():
    wrapped = RepeatableStep(RequestStep("loop").get("/path")).run_while(lambda state: state.get("enabled") is True)

    assert wrapped.name == "loop"
    assert wrapped.step.name == "loop"
