from httporchestrator import Flow, RequestStep


def test_flow_keeps_runtime_options_and_exports():
    flow = (
        Flow(
            name="demo",
            base_url="https://example.com",
            verify=True,
            log_details=False,
            add_request_id=False,
            steps=(RequestStep("load").get("/items"),),
        )
        .state(foo="bar")
        .export(["foo"])
    )

    assert flow.name == "demo"
    assert flow.base_url == "https://example.com"
    assert flow.verify is True
    assert flow.log_details is False
    assert flow.add_request_id is False
    assert flow.state_values == {"foo": "bar"}
    assert flow.exports == ("foo",)


def test_flow_helpers_return_new_instances():
    original = Flow(name="demo")
    updated = original.state({"foo": "bar"}).export(["foo"]).with_steps((RequestStep("load").get("/items"),))

    assert original.state_values == {}
    assert original.exports == ()
    assert original.steps == ()
    assert updated.state_values == {"foo": "bar"}
    assert updated.exports == ("foo",)
    assert len(updated.steps) == 1
