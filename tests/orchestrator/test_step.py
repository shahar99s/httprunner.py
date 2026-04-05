import unittest
from unittest.mock import MagicMock

from httporchestrator.models import StepResult
from httporchestrator.step import OptionalStep, Step
from httporchestrator.step_request import ConditionalStep, RunRequest, call_hooks


class TestCallHooks(unittest.TestCase):
    def test_callable_hook_is_called(self):
        called = []
        hook = lambda v: called.append(v.get("x"))
        variables = {"x": 42}
        call_hooks([hook], variables, "test setup")
        self.assertEqual(called, [42])

    def test_dict_hook_assigns_variable(self):
        variables = {"x": 10}
        hook = {"result": lambda v: v["x"] * 2}
        call_hooks([hook], variables, "test setup")
        self.assertEqual(variables["result"], 20)

    def test_dict_hook_returns_assigned_names(self):
        variables = {}
        hook = {"my_var": lambda v: "hello"}
        assigned = call_hooks([hook], variables, "test")
        self.assertIn("my_var", assigned)

    def test_invalid_hook_format_skipped(self):
        variables = {}
        # Non-callable dict value — should log error and skip gracefully
        hook = {"bad": "not_callable"}
        assigned = call_hooks([hook], variables, "test")
        self.assertEqual(assigned, set())
        self.assertNotIn("bad", variables)

    def test_invalid_hooks_list_returns_empty(self):
        assigned = call_hooks("not_a_list", {}, "test")
        self.assertEqual(assigned, set())

    def test_multiple_hooks_all_run(self):
        log = []
        hooks = [
            lambda v: log.append("first"),
            lambda v: log.append("second"),
        ]
        call_hooks(hooks, {}, "test")
        self.assertEqual(log, ["first", "second"])


class TestRunRequestBuilder(unittest.TestCase):
    def test_http_methods_set_request(self):
        for method in ["get", "post", "put", "delete", "head", "options", "patch"]:
            step = getattr(RunRequest("step"), method)("/path")
            self.assertEqual(step.struct().request.method.value, method.upper())
            self.assertEqual(step.struct().request.url, "/path")

    def test_params(self):
        step = RunRequest("step").get("/path").params(a="1", b="2")
        self.assertEqual(step.struct().request.params, {"a": "1", "b": "2"})

    def test_headers(self):
        step = RunRequest("step").get("/path").headers(**{"X-Custom": "value"})
        self.assertEqual(step.struct().request.headers["X-Custom"], "value")

    def test_data(self):
        step = RunRequest("step").post("/path").data("raw body")
        self.assertEqual(step.struct().request.data, "raw body")

    def test_body_alias(self):
        step = RunRequest("step").post("/path").body("payload")
        self.assertEqual(step.struct().request.data, "payload")

    def test_json_body(self):
        step = RunRequest("step").post("/path").json({"key": "val"})
        self.assertEqual(step.struct().request.req_json, {"key": "val"})

    def test_timeout(self):
        step = RunRequest("step").get("/path").timeout(30.0)
        self.assertEqual(step.struct().request.timeout, 30.0)

    def test_cookies(self):
        step = RunRequest("step").get("/path").cookies(session="tok")
        self.assertEqual(step.struct().request.cookies["session"], "tok")

    def test_variables(self):
        step = RunRequest("step").get("/path").variables(foo="bar")
        self.assertEqual(step.struct().variables["foo"], "bar")

    def test_extractor(self):
        step = RunRequest("step").get("/path").extract().extractor("body.id", "item_id")
        self.assertEqual(step.struct().extract["item_id"], "body.id")

    def test_capture_alias(self):
        step = RunRequest("step").get("/path").capture("result", "body.result")
        self.assertEqual(step.struct().extract["result"], "body.result")

    def test_jmespath_alias(self):
        step = RunRequest("step").get("/path").jmespath("body.name", "name")
        self.assertEqual(step.struct().extract["name"], "body.name")

    def test_assert_method(self):
        step = RunRequest("step").get("/path").validate().assert_equal("status_code", 200)
        self.assertEqual(step.struct().validators, [{"equal": ["status_code", 200, ""]}])

    def test_expect_method(self):
        step = RunRequest("step").get("/path").expect("eq", "status_code", 200, "should be 200")
        self.assertEqual(step.struct().validators, [{"eq": ["status_code", 200, "should be 200"]}])

    def test_retry(self):
        step = RunRequest("step").get("/path").retry(3, 2)
        self.assertEqual(step.struct().retry_times, 3)
        self.assertEqual(step.struct().retry_interval, 2)

    def test_setup_hook(self):
        fn = lambda v: None
        step = RunRequest("step").get("/path").setup_hook(fn)
        self.assertIn(fn, step.struct().setup_hooks)

    def test_setup_hook_with_assign(self):
        fn = lambda v: "value"
        step = RunRequest("step").get("/path").setup_hook(fn, "my_var")
        self.assertIn({"my_var": fn}, step.struct().setup_hooks)

    def test_teardown_hook(self):
        fn = lambda v: None
        step = RunRequest("step").get("/path").teardown_hook(fn)
        self.assertIn(fn, step.struct().teardown_hooks)

    def test_name_and_type(self):
        step = RunRequest("my step").get("/path")
        self.assertEqual(step.name(), "my step")
        self.assertIn("request-", step.type())
        self.assertIn("GET", step.type())

    def test_type_before_http_method(self):
        step = RunRequest("no method")
        self.assertEqual(step.type(), "request")

    def test_unknown_attribute_raises(self):
        step = RunRequest("step").get("/path")
        with self.assertRaises(AttributeError):
            _ = step.not_a_real_attribute

    def test_assert_dynamic_attribute(self):
        # assert_* attributes create validator methods dynamically
        step = RunRequest("step").get("/path")
        fn = step.assert_length_equal
        self.assertTrue(callable(fn))


class TestTeardownCallback(unittest.TestCase):
    def test_method_call_format(self):
        """teardown_callback with method(arg) syntax assigns result via hook."""
        class FakeRunner:
            def get_value(self, x):
                return x * 2

        step = RunRequest("step").get("/path")
        step.teardown_callback("get_value(my_var)", assign="doubled")

        variables = {"self": FakeRunner(), "my_var": 5}
        hook_entry = step.struct().teardown_hooks[-1]
        self.assertIsInstance(hook_entry, dict)
        result = hook_entry["doubled"](variables)
        self.assertEqual(result, 10)

    def test_expression_format(self):
        """teardown_callback with dot/bracket expression resolves via resolve_expr."""
        class Body:
            name = "test"

        class Resp:
            body = Body()

        step = RunRequest("step").get("/path")
        step.teardown_callback("response.body.name", assign="file_name")

        variables = {"response": Resp()}
        hook_entry = step.struct().teardown_hooks[-1]
        result = hook_entry["file_name"](variables)
        self.assertEqual(result, "test")

    def test_legacy_format(self):
        """teardown_callback with method name + var_names uses legacy format."""
        class FakeRunner:
            def combine(self, a, b):
                return f"{a}-{b}"

        step = RunRequest("step").get("/path")
        step.teardown_callback("combine", "x", "y", assign="out")

        variables = {"self": FakeRunner(), "x": "hello", "y": "world"}
        hook_entry = step.struct().teardown_hooks[-1]
        result = hook_entry["out"](variables)
        self.assertEqual(result, "hello-world")


class TestStep(unittest.TestCase):
    def _make_step(self):
        return Step(RunRequest("inner step").get("/path"))

    def test_name(self):
        s = self._make_step()
        self.assertEqual(s.name(), "inner step")

    def test_type(self):
        s = self._make_step()
        self.assertIn("request-", s.type())
        self.assertIn("GET", s.type())

    def test_struct(self):
        s = self._make_step()
        data = s.struct()
        self.assertEqual(data.name, "inner step")

    def test_request_property(self):
        s = self._make_step()
        self.assertIsNotNone(s.request)
        self.assertEqual(s.request.url, "/path")

    def test_retry_properties(self):
        inner = RunRequest("r").get("/p").retry(2, 5)
        s = Step(inner)
        self.assertEqual(s.retry_times, 2)
        self.assertEqual(s.retry_interval, 5)


class TestConditionalStep(unittest.TestCase):
    def _make_mock_runner(self, variables=None):
        runner = MagicMock()
        runner.merge_step_variables.return_value = variables or {}
        return runner

    def test_runs_when_predicate_true(self):
        inner = MagicMock()
        inner.name.return_value = "my step"
        inner.type.return_value = "request-GET"
        mock_struct = MagicMock()
        mock_struct.name = "my step"
        mock_struct.variables = {}
        inner.struct.return_value = mock_struct
        expected_result = StepResult(name="my step", step_type="request-GET", success=True)
        inner.run.return_value = expected_result

        step = ConditionalStep(inner).when(lambda v: True)
        runner = self._make_mock_runner()
        result = step.run(runner)
        self.assertTrue(result.success)
        inner.run.assert_called_once_with(runner)

    def test_skips_when_predicate_false(self):
        inner = MagicMock()
        inner.name.return_value = "my step"
        inner.type.return_value = "request-GET"
        mock_struct = MagicMock()
        mock_struct.name = "my step"
        mock_struct.variables = {}
        inner.struct.return_value = mock_struct

        step = ConditionalStep(inner).when(lambda v: False)
        runner = self._make_mock_runner()
        result = step.run(runner)
        self.assertTrue(result.success)
        self.assertEqual(result.attachment, "skipped(optional)")
        inner.run.assert_not_called()

    def test_default_predicate_runs(self):
        inner = MagicMock()
        inner.name.return_value = "my step"
        inner.type.return_value = "request-GET"
        mock_struct = MagicMock()
        mock_struct.name = "my step"
        mock_struct.variables = {}
        inner.struct.return_value = mock_struct
        expected_result = StepResult(name="my step", step_type="request-GET", success=True)
        inner.run.return_value = expected_result

        step = ConditionalStep(inner)
        runner = self._make_mock_runner()
        step.run(runner)
        inner.run.assert_called_once()


class TestOptionalStep(unittest.TestCase):
    def _make_mock_runner(self, variables=None):
        runner = MagicMock()
        runner.merge_step_variables.return_value = variables or {}
        return runner

    def test_runs_when_predicate_true(self):
        inner = RunRequest("opt step").get("/path")
        mock_run = MagicMock(return_value=StepResult(name="opt step", step_type="request-GET", success=True))
        inner.run = mock_run

        step = OptionalStep(Step(inner))
        step.when(lambda v: True)
        runner = self._make_mock_runner()
        result = step.run(runner)
        self.assertTrue(result.success)

    def test_skips_when_predicate_false(self):
        inner = RunRequest("opt step").get("/path")

        step = OptionalStep(Step(inner))
        step.when(lambda v: False)
        runner = self._make_mock_runner()
        result = step.run(runner)
        self.assertTrue(result.success)
