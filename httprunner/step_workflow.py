from typing import Callable, Text

from loguru import logger

from httprunner import exceptions
from httprunner.models import IStep, StepResult, TStep, WorkflowSummary
from httprunner.runner import HttpRunner
from httprunner.step_request import call_hooks


def run_step_workflow(runner: HttpRunner, step: TStep) -> StepResult:
    """run step: referenced workflow"""
    step_result = StepResult(name=step.name, step_type="workflow")
    step_variables = runner.merge_step_variables(step.variables)
    step_export = step.export

    # setup hooks
    if step.setup_hooks:
        call_hooks(step.setup_hooks, step_variables, "setup workflow")

    # step.workflow is a referenced workflow, e.g. RequestWithFunctions
    ref_case_runner = step.workflow()
    ref_case_runner.config._Config__name = step.name
    ref_case_runner.set_referenced().set_session(runner.session).set_case_id(
        runner.case_id
    ).variables(step_variables).export(step_export).run()

    # teardown hooks
    if step.teardown_hooks:
        call_hooks(step.teardown_hooks, step_variables, "teardown workflow")

    summary: WorkflowSummary = ref_case_runner.get_summary()
    step_result.data = summary.step_results  # list of step data
    step_result.export_vars = summary.in_out.export_vars
    step_result.success = summary.success

    if step_result.export_vars:
        logger.info(f"export variables: {step_result.export_vars}")

    return step_result


class StepRefWorkflow(IStep):
    def __init__(self, step: TStep):
        self.__step = step

    def teardown_hook(self, hook: Text, assign_var_name: Text = None) -> "StepRefWorkflow":
        if assign_var_name:
            self.__step.teardown_hooks.append({assign_var_name: hook})
        else:
            self.__step.teardown_hooks.append(hook)

        return self

    def teardown(self, hook: Text, assign_var_name: Text = None) -> "StepRefWorkflow":
        return self.teardown_hook(hook, assign_var_name)

    def teardown_callback(self, method_name: str, *var_names: str, assign: str = None) -> "StepRefWorkflow":
        def hook(v):
            return getattr(v["self"], method_name)(*[v[n] for n in var_names])

        return self.teardown_hook(hook, assign)

    def export(self, *var_name: Text) -> "StepRefWorkflow":
        self.__step.export.extend(var_name)
        return self

    def struct(self) -> TStep:
        return self.__step

    def name(self) -> Text:
        return self.__step.name

    def type(self) -> Text:
        return f"request-{self.__step.request.method}"

    def run(self, runner: HttpRunner):
        return run_step_workflow(runner, self.__step)


class RunWorkflow(object):
    def __init__(self, name: Text):
        self.__step = TStep(name=name)

    def variables(self, **variables) -> "RunWorkflow":
        self.__step.variables.update(variables)
        return self

    def retry(self, retry_times, retry_interval) -> "RunWorkflow":
        self.__step.retry_times = retry_times
        self.__step.retry_interval = retry_interval
        return self

    def setup_hook(self, hook: Text, assign_var_name: Text = None) -> "RunWorkflow":
        if assign_var_name:
            self.__step.setup_hooks.append({assign_var_name: hook})
        else:
            self.__step.setup_hooks.append(hook)

        return self

    def setup(self, hook: Text, assign_var_name: Text = None) -> "RunWorkflow":
        return self.setup_hook(hook, assign_var_name)

    def call(self, workflow: Callable) -> StepRefWorkflow:
        if issubclass(workflow, HttpRunner):
            self.__step.workflow = workflow
        else:
            raise exceptions.ParamsError(
                f"Invalid step referenced workflow: {workflow}"
            )

        return StepRefWorkflow(self.__step)
