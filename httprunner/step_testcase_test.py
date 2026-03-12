import unittest

from httprunner import Config
from httprunner.runner import HttpRunner
from httprunner.step_testcase import RunTestCase
from examples.postman_echo.request_methods.request_with_functions_test import (
    TestCaseRequestWithFunctions,
)


class InspectReferencedCase(HttpRunner):
    last_summary_name = None

    config = Config("original referenced testcase")
    teststeps = []

    def test_start(self, param=None):
        result = super().test_start(param)
        type(self).last_summary_name = self.get_summary().name
        return result


class TestRunTestCase(unittest.TestCase):
    def setUp(self):
        self.runner = TestCaseRequestWithFunctions()
        self.runner.test_start()

    def test_run_testcase_by_path(self):

        step_result = (
            RunTestCase("run referenced testcase")
            .call(TestCaseRequestWithFunctions)
            .run(self.runner)
        )
        self.assertTrue(step_result.success)
        self.assertEqual(step_result.name, "run referenced testcase")
        self.assertEqual(len(step_result.data), 3)
        self.assertEqual(step_result.data[0].name, "get with params")
        self.assertEqual(step_result.data[1].name, "post raw text")
        self.assertEqual(step_result.data[2].name, "post form data")

    def test_run_testcase_overrides_referenced_case_name(self):
        InspectReferencedCase.last_summary_name = None

        step_result = (
            RunTestCase("override referenced testcase name")
            .call(InspectReferencedCase)
            .run(self.runner)
        )

        self.assertTrue(step_result.success)
        self.assertEqual(
            InspectReferencedCase.last_summary_name,
            "override referenced testcase name",
        )
