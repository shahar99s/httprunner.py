import json
import re
import time
from typing import Any, Dict, List, Text

from loguru import logger

import httpx

from httprunner import utils
from httprunner.exceptions import ValidationFailure
from httprunner.models import (
    Hooks,
    IStep,
    MethodEnum,
    StepResult,
    TRequest,
    TStep,
    VariablesMapping,
)
from httprunner.parser import build_url
from httprunner.response import ResponseObject
from httprunner.runner import ALLURE, HttpRunner


def call_hooks(hooks: Hooks, step_variables: VariablesMapping, hook_msg: Text) -> set:
    """call hook actions.

    Args:
        hooks (list): each hook in hooks list maybe in these formats:

            format1 (callable): call with step_variables dict.
                lambda v: do_something(v["response"])
            format2 (dict with callable): assignment with callable.
                {"var": lambda v: extract(v["response"])}

        step_variables: current step variables to call hook, include two special variables

            request: parsed request dict
            response: ResponseObject for current response

        hook_msg: setup/teardown request/workflow

    Returns:
        set: variable names assigned by dict-format hooks

    """
    logger.info(f"call hook actions: {hook_msg}")
    assigned = set()

    if not isinstance(hooks, List):
        logger.error(f"Invalid hooks format: {hooks}")
        return assigned

    for hook in hooks:
        if callable(hook):
            # callable hook
            logger.debug(f"call hook function: {hook}")
            hook(step_variables)
        elif isinstance(hook, Dict) and len(hook) == 1:
            # {"var": callable}
            var_name, hook_content = list(hook.items())[0]
            if callable(hook_content):
                hook_content_eval = hook_content(step_variables)
            else:
                logger.error(f"Hook value must be callable, got: {type(hook_content)}")
                continue
            logger.debug(
                f"call hook function: {hook_content}, got value: {hook_content_eval}"
            )
            logger.debug(f"assign variable: {var_name} = {hook_content_eval}")
            step_variables[var_name] = hook_content_eval
            assigned.add(var_name)
        else:
            logger.error(f"Invalid hook format: {hook}")

    return assigned


def pretty_format(v) -> str:
    if isinstance(v, dict):
        return json.dumps(v, indent=4, ensure_ascii=False)

    if isinstance(v, httpx.Headers):
        return json.dumps(dict(v.items()), indent=4, ensure_ascii=False)

    return repr(utils.omit_long_data(v))


def _resolve_dict_vars(d: Dict, variables: Dict) -> Dict:
    """Resolve callables and $-prefixed variable references in all values of a dict."""
    resolved = {}
    for k, v in d.items():
        if callable(v):
            resolved[k] = v(variables)
        elif isinstance(v, str) and v.startswith("$") and v[1:] in variables:
            resolved[k] = variables[v[1:]]
        else:
            resolved[k] = v
    return resolved


_EXPR_ACCESS = re.compile(r"""\.(\w+)|\[(['"])(.*?)\2\]""")


def _resolve_expr(expr: str, variables: Dict):
    """Resolve a dotted/bracket expression against step variables.

    Examples:
        response.body["direct_link"]
        response.json["response"]["file_info"]["filename"]
    """
    m = re.match(r"([a-zA-Z_]\w*)(.*)", expr)
    obj = variables[m.group(1)]
    for tok in _EXPR_ACCESS.finditer(m.group(2)):
        if tok.group(1):
            obj = getattr(obj, tok.group(1))
        else:
            obj = obj[tok.group(3)]
    return obj


def run_step_request(runner: HttpRunner, step: TStep) -> StepResult:
    """run step: request"""
    step_result = StepResult(
        name=step.name,
        step_type="request",
        success=False,
    )
    start_time = time.time()

    # merge variables
    step_variables = runner.merge_step_variables(step.variables)
    step_variables["self"] = runner
    # resolve callables in step variables themselves
    for k, v in list(step_variables.items()):
        if callable(v):
            step_variables[k] = v(step_variables)

    request_dict = step.request.dict()

    # resolve callable or $-prefixed variable-reference URL
    if callable(step.request.url):
        request_dict["url"] = step.request.url(step_variables)
    elif (
        isinstance(step.request.url, str)
        and step.request.url.startswith("$")
        and step.request.url[1:] in step_variables
    ):
        request_dict["url"] = step_variables[step.request.url[1:]]

    # resolve callable JSON body
    if callable(step.request.req_json):
        try:
            request_dict["req_json"] = step.request.req_json(step_variables)
        except TypeError:
            request_dict["req_json"] = step.request.req_json()

    # resolve callables in params
    if request_dict.get("params"):
        request_dict["params"] = _resolve_dict_vars(request_dict["params"], step_variables)

    parsed_request_dict = request_dict

    request_headers = parsed_request_dict.pop("headers", {})
    # omit pseudo header names for HTTP/1, e.g. :authority, :method, :path, :scheme
    request_headers = {
        key: request_headers[key] for key in request_headers if not key.startswith(":")
    }
    # resolve callables in headers
    request_headers = _resolve_dict_vars(request_headers, step_variables)
    if runner.get_config().add_request_id:
        request_headers[
            "HRUN-Request-ID"
        ] = f"HRUN-{runner.case_id}-{str(int(time.time() * 1000))[-6:]}"
    parsed_request_dict["headers"] = request_headers

    step_variables["request"] = parsed_request_dict

    # setup hooks
    if step.setup_hooks:
        call_hooks(step.setup_hooks, step_variables, "setup request")

    # prepare arguments
    config = runner.get_config()
    method = parsed_request_dict.pop("method")
    url_path = parsed_request_dict.pop("url")
    url = build_url(config.base_url, url_path)
    parsed_request_dict["verify"] = config.verify
    parsed_request_dict["json"] = parsed_request_dict.pop("req_json", {})
    parsed_request_dict.pop("upload", None)  # handled separately by uploader
    # log request
    request_print = "====== request details ======\n"
    request_print += f"url: {url}\n"
    request_print += f"method: {method}\n"
    for k, v in parsed_request_dict.items():
        request_print += f"{k}: {pretty_format(v)}\n"

    logger.debug(request_print)
    if ALLURE is not None:
        ALLURE.attach(
            request_print,
            name="request details",
            attachment_type=ALLURE.attachment_type.TEXT,
        )
    resp = runner.session.request(method, url, **parsed_request_dict)

    # log response
    response_print = "====== response details ======\n"
    response_print += f"status_code: {resp.status_code}\n"
    response_print += f"headers: {pretty_format(resp.headers)}\n"

    response_headers = dict(resp.headers)
    content_type = response_headers.get("Content-Type", "")
    content_disposition = response_headers.get("Content-Disposition", "")

    try:
        resp_body = resp.json()
    except (json.JSONDecodeError, ValueError):
        if "attachment" in content_disposition.lower():
            resp_body = utils.format_response_body_for_log(
                resp.content, content_type, content_disposition
            )
        else:
            resp_body = utils.format_response_body_for_log(
                resp.text, content_type, content_disposition
            )

    response_print += f"body: {pretty_format(resp_body)}\n"
    logger.debug(response_print)
    if ALLURE is not None:
        ALLURE.attach(
            response_print,
            name="response details",
            attachment_type=ALLURE.attachment_type.TEXT,
        )
    resp_obj = ResponseObject(resp)
    step_variables["response"] = resp_obj

    # teardown hooks
    teardown_assigned = set()
    if step.teardown_hooks:
        teardown_assigned = call_hooks(step.teardown_hooks, step_variables, "teardown request")

    # extract
    extractors = step.extract
    extract_mapping = resp_obj.extract(extractors, step_variables)

    # auto-export variables assigned by teardown hooks
    for var_name in teardown_assigned:
        if var_name not in extract_mapping:
            extract_mapping[var_name] = step_variables[var_name]

    step_result.export_vars = extract_mapping

    variables_mapping = {**step_variables, **extract_mapping}

    # validate
    validators = step.validators
    try:
        resp_obj.validate(validators, variables_mapping)
        step_result.success = True
    except ValidationFailure:
        raise
    finally:
        session_data = runner.session.data
        session_data.success = step_result.success
        session_data.validators = resp_obj.validation_results

        # save step data
        step_result.data = session_data
        step_result.elapsed = time.time() - start_time

    return step_result


class RunRequest(IStep):
    def __init__(self, name: Text):
        self.__step = TStep(name=name)

    # --- IStep interface ---

    def struct(self) -> TStep:
        return self.__step

    def name(self) -> Text:
        return self.__step.name

    def type(self) -> Text:
        if self.__step.request:
            return f"request-{self.__step.request.method}"
        return "request"

    def run(self, runner: HttpRunner):
        return run_step_request(runner, self.__step)

    # --- RunRequest setup ---

    def variables(self, **variables) -> "RunRequest":
        self.__step.variables.update(variables)
        return self

    def retry(self, retry_times, retry_interval) -> "RunRequest":
        self.__step.retry_times = retry_times
        self.__step.retry_interval = retry_interval
        return self

    def setup_hook(self, hook, assign_var_name: Text = None) -> "RunRequest":
        if assign_var_name:
            self.__step.setup_hooks.append({assign_var_name: hook})
        else:
            self.__step.setup_hooks.append(hook)
        return self

    # --- HTTP methods ---

    def get(self, url) -> "RunRequest":
        self.__step.request = TRequest(method=MethodEnum.GET, url=url)
        return self

    def post(self, url) -> "RunRequest":
        self.__step.request = TRequest(method=MethodEnum.POST, url=url)
        return self

    def put(self, url) -> "RunRequest":
        self.__step.request = TRequest(method=MethodEnum.PUT, url=url)
        return self

    def head(self, url) -> "RunRequest":
        self.__step.request = TRequest(method=MethodEnum.HEAD, url=url)
        return self

    def delete(self, url) -> "RunRequest":
        self.__step.request = TRequest(method=MethodEnum.DELETE, url=url)
        return self

    def options(self, url) -> "RunRequest":
        self.__step.request = TRequest(method=MethodEnum.OPTIONS, url=url)
        return self

    def patch(self, url) -> "RunRequest":
        self.__step.request = TRequest(method=MethodEnum.PATCH, url=url)
        return self

    # --- Request options ---

    def params(self, **params) -> "RunRequest":
        self.__step.request.params.update(params)
        return self

    def headers(self, **headers) -> "RunRequest":
        self.__step.request.headers.update(headers)
        return self

    def cookies(self, **cookies) -> "RunRequest":
        self.__step.request.cookies.update(cookies)
        return self

    def data(self, data) -> "RunRequest":
        self.__step.request.data = data
        return self

    def body(self, data) -> "RunRequest":
        return self.data(data)

    def json(self, req_json) -> "RunRequest":
        self.__step.request.req_json = req_json
        return self

    def timeout(self, timeout: float) -> "RunRequest":
        self.__step.request.timeout = timeout
        return self

    def verify(self, verify: bool) -> "RunRequest":
        self.__step.request.verify = verify
        return self

    def allow_redirects(self, allow_redirects: bool) -> "RunRequest":
        self.__step.request.allow_redirects = allow_redirects
        return self

    def teardown_hook(self, hook, assign_var_name: Text = None) -> "RunRequest":
        if assign_var_name:
            self.__step.teardown_hooks.append({assign_var_name: hook})
        else:
            self.__step.teardown_hooks.append(hook)
        return self

    def teardown_callback(self, method_name: str, *var_names: str, assign: str = None) -> "RunRequest":
        """Post-request hook: call self.<method_name>(var1, var2, ...) or resolve an expression.

        Supports three formats:
            .teardown_callback("method(arg1, arg2)", assign="result")   # method call
            .teardown_callback("method", "arg1", "arg2", assign="result")  # legacy
            .teardown_callback("response.body['key']", assign="result")  # expression
        """
        if "(" in method_name:
            name, _, args_str = method_name.partition("(")
            args_str = args_str.rstrip(")")
            parsed_args = tuple(a.strip() for a in args_str.split(",") if a.strip()) if args_str.strip() else ()
            method_name = name
            var_names = parsed_args

            def hook(v):
                return getattr(v["self"], method_name)(*[v[n] for n in var_names])
        elif "." in method_name or "[" in method_name:
            expr = method_name

            def hook(v):
                return _resolve_expr(expr, v)
        else:
            def hook(v):
                return getattr(v["self"], method_name)(*[v[n] for n in var_names])

        return self.teardown_hook(hook, assign)

    # --- Extraction ---

    def extract(self) -> "RunRequest":
        return self

    def extractor(self, path_or_fn, var_name: Text) -> "RunRequest":
        """Register an extractor: path_or_fn is a dotted string path or a Python callable."""
        self.__step.extract[var_name] = path_or_fn
        return self

    def capture(self, var_name: Text, path_or_fn) -> "RunRequest":
        return self.extractor(path_or_fn, var_name)

    jmespath = extractor

    # --- Validation ---

    def validate(self) -> "RunRequest":
        return self

    def expect(
        self,
        comparator: Text,
        check_item,
        expected_value: Any,
        message: Text = "",
    ) -> "RunRequest":
        self.__step.validators.append({comparator: [check_item, expected_value, message]})
        return self

    def __getattr__(self, name: str):
        if name.startswith("assert_"):
            comparator = name[len("assert_"):]

            def _validator(
                check_item, expected_value: Any, message: Text = ""
            ) -> "RunRequest":
                self.__step.validators.append(
                    {comparator: [check_item, expected_value, message]}
                )
                return self

            return _validator
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
