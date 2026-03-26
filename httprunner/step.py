from typing import Callable, Union

from httprunner import HttpRunner
from httprunner.models import StepResult, TRequest, TStep, Workflow
from httprunner.step_request import RunRequest
from httprunner.step_workflow import StepRefWorkflow


class Step(object):
    def __init__(
        self,
        step: Union[
            RunRequest,
            StepRefWorkflow,
        ],
    ):
        self.__step = step

    @property
    def request(self) -> TRequest:
        return self.__step.struct().request

    @property
    def workflow(self) -> Workflow:
        return self.__step.struct().workflow

    @property
    def retry_times(self) -> int:
        return self.__step.struct().retry_times

    @property
    def retry_interval(self) -> int:
        return self.__step.struct().retry_interval

    def struct(self) -> TStep:
        return self.__step.struct()

    def name(self) -> str:
        return self.__step.name()

    def type(self) -> str:
        return self.__step.type()

    def run(self, runner: HttpRunner) -> StepResult:
        return self.__step.run(runner)


class OptionalStep(Step):
    """
    Wrap a step and only execute it when a condition is met.
    """

    def __init__(self, step: Step):
        super().__init__(step)
        self.__step = step
        self.__predicate: Callable[[dict], bool] = lambda _vars: True

    def when(self, predicate: Callable[[Step, dict], bool]) -> 'OptionalStep':
        self.__predicate = predicate
        return self

    def run(self, runner: HttpRunner) -> StepResult:
        step_variables = runner.merge_step_variables(self.__step.struct().variables)
        should_run = bool(self.__predicate(self, step_variables))
        if should_run:
            return self.__step.run(runner)
        step = self.__step.struct()
        result = StepResult(name=step.name, step_type=self.__step.type(), success=True)
        result.attachment = "skipped(optional)"
        return result
