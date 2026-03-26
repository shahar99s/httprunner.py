from typing import Dict, Text, Any

from loguru import logger

from httprunner import exceptions
from httprunner.exceptions import ValidationFailure, ParamsError
from httprunner.models import VariablesMapping, Validators
from httprunner.parser import parse_string_value
from httprunner.builtin.comparators import COMPARATOR_MODELS, _run_comparator


def _traverse_path(obj: Any, expr: str) -> Any:
    """Traverse a dotted path with optional bracket indexing, e.g. 'body.items[0].name'."""
    for segment in expr.split("."):
        if "[" in segment:
            key, _, rest = segment.partition("[")
            idx = int(rest.rstrip("]"))
            if key:
                obj = obj[key] if isinstance(obj, dict) else getattr(obj, key)
            obj = obj[idx]
        elif isinstance(obj, dict):
            obj = obj[segment]
        elif isinstance(obj, list):
            obj = obj[int(segment)]
        else:
            obj = getattr(obj, segment)
    return obj


def get_uniform_comparator(comparator: Text):
    """convert comparator alias to uniform name"""
    _ALIASES = {
        "eq": "equal", "equals": "equal", "equal": "equal",
        "lt": "less_than", "less_than": "less_than",
        "le": "less_or_equals", "less_or_equals": "less_or_equals",
        "gt": "greater_than", "greater_than": "greater_than",
        "ge": "greater_or_equals", "greater_or_equals": "greater_or_equals",
        "ne": "not_equal", "not_equal": "not_equal",
        "str_eq": "string_equals", "string_equals": "string_equals",
        "len_eq": "length_equal", "length_equal": "length_equal",
        "len_gt": "length_greater_than", "length_greater_than": "length_greater_than",
        "len_ge": "length_greater_or_equals", "length_greater_or_equals": "length_greater_or_equals",
        "len_lt": "length_less_than", "length_less_than": "length_less_than",
        "len_le": "length_less_or_equals", "length_less_or_equals": "length_less_or_equals",
        "contains": "contains", "contained_by": "contained_by",
        "type_match": "type_match", "regex_match": "regex_match",
    }
    return _ALIASES.get(comparator, comparator)


def uniform_validator(validator):
    """unify validator

    Args:
        validator (dict): validator maybe in two formats:

            format1: this is kept for compatibility with the previous versions.
                {"check": "status_code", "comparator": "eq", "expect": 201, "message": "test"}
                {"check": "status_code", "assert": "eq", "expect": 201, "msg": "test"}
            format2: recommended new version, {assert: [check_item, expected_value, msg]}
                {'eq': ['status_code', 201, "test"]}

    Returns
        dict: validator info

            {
                "check": "status_code",
                "expect": 201,
                "assert": "equal",
                "message": "test
            }

    """
    if not isinstance(validator, dict):
        raise ParamsError(f"invalid validator: {validator}")

    if "check" in validator and "expect" in validator:
        # format1
        check_item = validator["check"]
        expect_value = validator["expect"]

        if "assert" in validator:
            comparator = validator.get("assert")
        else:
            comparator = validator.get("comparator", "eq")

        if "msg" in validator:
            message = validator.get("msg")
        else:
            message = validator.get("message", "")

    elif len(validator) == 1:
        # format2
        comparator = list(validator.keys())[0]
        compare_values = validator[comparator]

        if not isinstance(compare_values, list) or len(compare_values) not in [2, 3]:
            raise ParamsError(f"invalid validator: {validator}")

        check_item = compare_values[0]
        expect_value = compare_values[1]
        if len(compare_values) == 3:
            message = compare_values[2]
        else:
            # len(compare_values) == 2
            message = ""

    else:
        raise ParamsError(f"invalid validator: {validator}")

    # uniform comparator, e.g. lt => less_than, eq => equals
    assert_method = get_uniform_comparator(comparator)

    return {
        "check": check_item,
        "expect": expect_value,
        "assert": assert_method,
        "message": message,
    }


class ResponseObjectBase(object):
    def __init__(self, resp_obj):
        """initialize with a response object

        Args:
            resp_obj (instance): requests.Response instance

        """
        self.resp_obj = resp_obj
        self.validation_results: Dict = {}

    def jpath(self, expr: str) -> Any:
        """Convenience helper — resolve a dotted path against the response."""
        return self._resolve_path(expr)

    def extract(
        self,
        extractors: Dict[Text, Text],
        variables_mapping: VariablesMapping = None,
    ) -> Dict[Text, Any]:
        if not extractors:
            return {}

        variables_mapping = variables_mapping or {}
        extract_mapping = {}
        for key, field in extractors.items():
            if callable(field):
                field_value = field(variables_mapping)
            else:
                field_value = self._resolve_path(field)
            extract_mapping[key] = field_value

        logger.info(f"extract mapping: {extract_mapping}")
        return extract_mapping

    def _resolve_path(self, expr: Any) -> Any:
        """Resolve a dotted key path (e.g. 'body.args.foo', 'items[0].name') against the response object."""
        if not isinstance(expr, str):
            return expr
        try:
            return _traverse_path(self.resp_obj, expr)
        except (KeyError, IndexError, AttributeError, TypeError, ValueError) as ex:
            logger.error(
                f"failed to resolve path\n"
                f"expression: {expr}\n"
                f"data: {self.resp_obj}\n"
                f"exception: {ex}"
            )
            raise exceptions.ParamsError(f"failed to resolve path '{expr}': {ex}")

    def validate(
        self,
        validators: Validators,
        variables_mapping: VariablesMapping = None,
    ):
        variables_mapping = variables_mapping or {}
        self.validation_results = {}
        if not validators:
            return

        validate_pass = True
        failures = []

        for v in validators:
            if "validate_extractor" not in self.validation_results:
                self.validation_results["validate_extractor"] = []

            u_validator = uniform_validator(v)

            check_item = u_validator["check"]
            # callable check: call with variables dict to get check value
            if callable(check_item):
                check_value = check_item(variables_mapping)
            elif isinstance(check_item, str) and check_item:
                root_key = check_item.split(".")[0].split("[")[0]
                if root_key in variables_mapping:
                    check_value = _traverse_path(variables_mapping, check_item)
                else:
                    check_value = self._resolve_path(check_item)
            else:
                check_value = check_item

            assert_method = u_validator["assert"]

            expect_value = u_validator["expect"]

            message = u_validator["message"]

            validate_msg = f"assert {check_item} {assert_method} {expect_value}({type(expect_value).__name__})"

            validator_dict = {
                "comparator": assert_method,
                "check": check_item,
                "check_value": check_value,
                "expect": expect_value,
                "expect_value": expect_value,
                "message": message,
            }

            try:
                if assert_method in COMPARATOR_MODELS:
                    _run_comparator(assert_method, check_value, expect_value, message)
                else:
                    raise AssertionError(f"unknown comparator: {assert_method}")
                validate_msg += "\t==> pass"
                logger.info(validate_msg)
                validator_dict["check_result"] = "pass"
            except AssertionError as ex:
                validate_pass = False
                validator_dict["check_result"] = "fail"
                validate_msg += "\t==> fail"
                validate_msg += (
                    f"\n"
                    f"check_item: {check_item}\n"
                    f"check_value: {check_value}({type(check_value).__name__})\n"
                    f"assert_method: {assert_method}\n"
                    f"expect_value: {expect_value}({type(expect_value).__name__})"
                )
                message = str(ex)
                if message:
                    validate_msg += f"\nmessage: {message}"

                logger.error(validate_msg)
                failures.append(validate_msg)

            self.validation_results["validate_extractor"].append(validator_dict)

        if not validate_pass:
            failures_string = "\n".join(failures)
            raise ValidationFailure(failures_string)


class ResponseObject(ResponseObjectBase):
    def __getattr__(self, key):
        if key in ["json", "content", "body"]:
            try:
                value = self.resp_obj.json()
            except ValueError:
                value = self.resp_obj.content
        elif key == "cookies":
            value = dict(self.resp_obj.cookies)
        else:
            try:
                value = getattr(self.resp_obj, key)
            except AttributeError:
                err_msg = "ResponseObject does not have attribute: {}".format(key)
                logger.error(err_msg)
                raise exceptions.ParamsError(err_msg)

        self.__dict__[key] = value
        return value

    def _resolve_path(self, expr: Any) -> Any:
        """Resolve a dotted key path (e.g. 'body.args.foo', 'body.items[0].name') against the HTTP response."""
        if not isinstance(expr, str):
            return expr
        resp_obj_meta = {
            "status_code": self.status_code,
            "headers": self.headers,
            "cookies": self.cookies,
            "body": self.body,
        }
        root_key = expr.split(".")[0].split("[")[0]
        if root_key not in resp_obj_meta:
            if hasattr(self.resp_obj, expr):
                return getattr(self.resp_obj, expr)
            return expr
        try:
            return _traverse_path(resp_obj_meta, expr)
        except (KeyError, IndexError, AttributeError, TypeError, ValueError) as ex:
            logger.error(
                f"failed to resolve path\n"
                f"expression: {expr}\n"
                f"data: {resp_obj_meta}\n"
                f"exception: {ex}"
            )
            raise exceptions.ParamsError(f"failed to resolve path '{expr}': {ex}")
