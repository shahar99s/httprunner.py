import os
import time
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Dict, List, Text

try:
    import allure

    ALLURE = allure
except ModuleNotFoundError:
    ALLURE = None

from loguru import logger

from httprunner.client import HttpSession
from httprunner.config import Config
from httprunner.exceptions import ParamsError, ValidationFailure
from httprunner.models import (
    StepResult,
    TConfig,
    WorkflowInOut,
    WorkflowSummary,
    WorkflowTime,
    VariablesMapping,
)
from httprunner.utils import LOGGER_FORMAT, merge_variables

# Module-level ContextVar for session variables — replaces the per-instance dict.
# Each workflow invocation (including nested referenced workflows) gets its own
# copy via contextvars.copy_context().run(), so step exports are automatically
# scoped without manual dict-copying.
_session_variables: ContextVar[VariablesMapping] = ContextVar(
    "session_variables", default={}
)


class HttpRunner(object):
    config: Config
    steps: List[object]  # list of Step

    session: HttpSession = None
    case_id: Text = ""
    root_dir: Text = ""

    __config: TConfig
    __export: List[Text] = []
    __step_results: List[StepResult] = []
    __is_referenced: bool = False
    __initial_session_variables: VariablesMapping = {}
    # snapshot of session variables after run completes (for get_summary/get_export)
    __final_session_variables: VariablesMapping = {}
    # time
    __start_at: float = 0
    __duration: float = 0
    # log
    __log_path: Text = ""

    @property
    def session_variables(self) -> VariablesMapping:
        return _session_variables.get()

    @session_variables.setter
    def session_variables(self, value: VariablesMapping):
        _session_variables.set(value)

    def __init(self):
        self.__config = self.config.struct()
        self.session_variables = dict(self.__initial_session_variables or {})
        self.__start_at = 0
        self.__duration = 0
        self.__is_referenced = self.__is_referenced or False

        self.case_id = self.case_id or str(uuid.uuid4())
        self.root_dir = self.root_dir or os.getcwd()
        self.__log_path = os.path.join(self.root_dir, "logs", f"{self.case_id}.run.log")

        self.__step_results = self.__step_results or []
        self.session = self.session or HttpSession()

    def set_session(self, session: HttpSession) -> "HttpRunner":
        self.session = session
        return self

    def get_config(self) -> TConfig:
        return self.__config

    def set_referenced(self) -> "HttpRunner":
        self.__is_referenced = True
        return self

    def set_case_id(self, case_id: Text) -> "HttpRunner":
        self.case_id = case_id
        return self

    def variables(self, variables: VariablesMapping) -> "HttpRunner":
        self.__initial_session_variables = dict(variables or {})
        self.session_variables = dict(self.__initial_session_variables)
        return self

    def export(self, export: List[Text]) -> "HttpRunner":
        self.__export = export
        return self

    def __parse_config(self, param: Dict = None) -> None:
        # merge config variables
        self.__config.variables.update(self.session_variables)
        if param:
            self.__config.variables.update(param)

    def get_export_variables(self) -> Dict:
        # override workflow export vars with step export
        export_var_names = self.__export or self.__config.export
        export_vars_mapping = {}
        # Use the snapshot saved at end of run (survives context exit)
        sv = self.__final_session_variables or self.session_variables
        for var_name in export_var_names:
            if var_name not in sv:
                raise ParamsError(
                    f"failed to export variable {var_name} from session variables {sv}"
                )

            export_vars_mapping[var_name] = sv[var_name]

        return export_vars_mapping

    def get_summary(self) -> WorkflowSummary:
        """get workflow result summary"""
        start_at_timestamp = self.__start_at
        start_at_iso_format = datetime.utcfromtimestamp(start_at_timestamp).isoformat()

        summary_success = True
        for step_result in self.__step_results:
            if not step_result.success:
                summary_success = False
                break

        return WorkflowSummary(
            name=self.__config.name,
            success=summary_success,
            case_id=self.case_id,
            time=WorkflowTime(
                start_at=self.__start_at,
                start_at_iso_format=start_at_iso_format,
                duration=self.__duration,
            ),
            in_out=WorkflowInOut(
                config_vars=self.__config.variables,
                export_vars=self.get_export_variables(),
            ),
            log=self.__log_path,
            step_results=self.__step_results,
        )

    def merge_step_variables(self, variables: VariablesMapping) -> VariablesMapping:
        # override variables
        # step variables > extracted variables from previous steps
        variables = merge_variables(variables, self.session_variables)
        # step variables > workflow config variables
        variables = merge_variables(variables, self.__config.variables)
        return variables

    def __run_step(self, step):
        """run step, step maybe any kind that implements IStep interface

        Args:
            step (Step): step

        """
        logger.info(f"run step begin: {step.name()} >>>>>>")

        # run step
        for i in range(step.retry_times + 1):
            try:
                if ALLURE is not None:
                    with ALLURE.step(f"step: {step.name()}"):
                        step_result: StepResult = step.run(self)
                else:
                    step_result: StepResult = step.run(self)
                break
            except ValidationFailure:
                if i == step.retry_times:
                    raise
                else:
                    logger.warning(
                        f"run step {step.name()} validation failed,wait {step.retry_interval} sec and try again"
                    )
                    time.sleep(step.retry_interval)
                    logger.info(
                        f"run step retry ({i + 1}/{step.retry_times} time): {step.name()} >>>>>>"
                    )

        # save extracted variables to session variables
        sv = self.session_variables
        sv.update(step_result.export_vars)
        self.session_variables = sv
        # update workflow summary
        self.__step_results.append(step_result)

        logger.info(f"run step end: {step.name()} <<<<<<\n")

    def run(self, param: Dict = None) -> "HttpRunner":
        """main entrance — runs inside a copy_context() so that ContextVar
        changes made by this workflow (and any nested referenced workflows)
        are isolated from the caller."""
        import contextvars

        ctx = contextvars.copy_context()
        return ctx.run(self._run_inner, param)

    def _run_inner(self, param: Dict = None) -> "HttpRunner":
        print("\n")
        self.__init()
        self.__parse_config(param)

        if ALLURE is not None and not self.__is_referenced:
            # update allure report meta
            ALLURE.dynamic.title(self.__config.name)
            ALLURE.dynamic.description(f"Workflow ID: {self.case_id}")

        logger.info(
            f"Start to run workflow: {self.__config.name}, Workflow ID: {self.case_id}"
        )

        logger.add(self.__log_path, format=LOGGER_FORMAT, level="DEBUG")
        self.__start_at = time.time()
        try:
            # run step in sequential order
            for step in self.steps:
                self.__run_step(step)
        finally:
            logger.info(f"generate workflow log: {self.__log_path}")
            if ALLURE is not None:
                ALLURE.attach.file(
                    self.__log_path,
                    name="all log",
                    attachment_type=ALLURE.attachment_type.TEXT,
                )

        self.__duration = time.time() - self.__start_at
        # Snapshot session variables so they survive the copy_context() exit
        self.__final_session_variables = dict(self.session_variables)
        return self
