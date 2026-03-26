"""
Built-in validate comparators using Pydantic.

Each comparator is modeled as a Pydantic validator that raises
``AssertionError`` on failure — keeping the same contract the rest of
the engine relies on.
"""

import re
from typing import Any, Text, Union

from pydantic import BaseModel, validator


class _Comparison(BaseModel):
    """Base comparison model. Subclasses add a validator on *check_value*.
    Fields are ordered so that expect_value and message are available in
    the validator's ``values`` dict when check_value is validated."""

    expect_value: Any
    message: Text = ""
    check_value: Any


# ---------------------------------------------------------------------------
# Equality
# ---------------------------------------------------------------------------

class EqualModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert v == values["expect_value"], values.get("message", "")
        return v


class NotEqualModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert v != values["expect_value"], values.get("message", "")
        return v


class StringEqualsModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert str(v) == str(values["expect_value"]), values.get("message", "")
        return v


# ---------------------------------------------------------------------------
# Numeric ordering
# ---------------------------------------------------------------------------

class GreaterThanModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert v > values["expect_value"], values.get("message", "")
        return v


class LessThanModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert v < values["expect_value"], values.get("message", "")
        return v


class GreaterOrEqualsModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert v >= values["expect_value"], values.get("message", "")
        return v


class LessOrEqualsModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert v <= values["expect_value"], values.get("message", "")
        return v


# ---------------------------------------------------------------------------
# Length checks
# ---------------------------------------------------------------------------

class LengthEqualModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert isinstance(values["expect_value"], int), "expect_value should be int type"
        assert len(v) == values["expect_value"], values.get("message", "")
        return v


class LengthGreaterThanModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert isinstance(values["expect_value"], (int, float)), "expect_value should be int/float type"
        assert len(v) > values["expect_value"], values.get("message", "")
        return v


class LengthGreaterOrEqualsModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert isinstance(values["expect_value"], (int, float)), "expect_value should be int/float type"
        assert len(v) >= values["expect_value"], values.get("message", "")
        return v


class LengthLessThanModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert isinstance(values["expect_value"], (int, float)), "expect_value should be int/float type"
        assert len(v) < values["expect_value"], values.get("message", "")
        return v


class LengthLessOrEqualsModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert isinstance(values["expect_value"], (int, float)), "expect_value should be int/float type"
        assert len(v) <= values["expect_value"], values.get("message", "")
        return v


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------

class ContainsModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert isinstance(v, (list, tuple, dict, str, bytes)), \
            "check_value should be list/tuple/dict/str/bytes type"
        assert values["expect_value"] in v, values.get("message", "")
        return v


class ContainedByModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert isinstance(values["expect_value"], (list, tuple, dict, str, bytes)), \
            "expect_value should be list/tuple/dict/str/bytes type"
        assert v in values["expect_value"], values.get("message", "")
        return v


# ---------------------------------------------------------------------------
# Type & regex
# ---------------------------------------------------------------------------

class TypeMatchModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        expect = values["expect_value"]
        if expect in ["None", "NoneType", None]:
            assert v is None, values.get("message", "")
        else:
            if isinstance(expect, type):
                target_type = expect
            elif isinstance(expect, str):
                import builtins
                target_type = getattr(builtins, expect, None)
                if target_type is None:
                    raise ValueError(expect)
            else:
                raise ValueError(expect)
            assert type(v) == target_type, values.get("message", "")
        return v


class RegexMatchModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        expect = values["expect_value"]
        assert isinstance(expect, str), "expect_value should be Text type"
        assert isinstance(v, str), "check_value should be Text type"
        assert re.match(expect, v), values.get("message", "")
        return v


class StartsWithModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert str(v).startswith(str(values["expect_value"])), values.get("message", "")
        return v


class EndsWithModel(_Comparison):
    @validator("check_value", always=True)
    def _validate(cls, v, values):
        assert str(v).endswith(str(values["expect_value"])), values.get("message", "")
        return v


# ---------------------------------------------------------------------------
# Registry: name → Pydantic model
# ---------------------------------------------------------------------------

COMPARATOR_MODELS = {
    "equal": EqualModel,
    "not_equal": NotEqualModel,
    "string_equals": StringEqualsModel,
    "greater_than": GreaterThanModel,
    "less_than": LessThanModel,
    "greater_or_equals": GreaterOrEqualsModel,
    "less_or_equals": LessOrEqualsModel,
    "length_equal": LengthEqualModel,
    "length_greater_than": LengthGreaterThanModel,
    "length_greater_or_equals": LengthGreaterOrEqualsModel,
    "length_less_than": LengthLessThanModel,
    "length_less_or_equals": LengthLessOrEqualsModel,
    "contains": ContainsModel,
    "contained_by": ContainedByModel,
    "type_match": TypeMatchModel,
    "regex_match": RegexMatchModel,
    "startswith": StartsWithModel,
    "endswith": EndsWithModel,
}


# ---------------------------------------------------------------------------
# Public function-style wrappers (backward-compatible call signature)
# ---------------------------------------------------------------------------

def _run_comparator(name: str, check_value: Any, expect_value: Any, message: Text = ""):
    """Instantiate the Pydantic model to trigger its validator."""
    model_cls = COMPARATOR_MODELS.get(name)
    if model_cls is None:
        raise ValueError(f"unknown comparator: {name}")
    try:
        model_cls(expect_value=expect_value, message=message, check_value=check_value)
    except AssertionError:
        raise
    except Exception as exc:
        # Pydantic may wrap assertion failures; preserve legacy comparator contract.
        raise AssertionError(str(exc)) from None


def equal(check_value, expect_value, message=""):
    _run_comparator("equal", check_value, expect_value, message)


def greater_than(check_value, expect_value, message=""):
    _run_comparator("greater_than", check_value, expect_value, message)


def less_than(check_value, expect_value, message=""):
    _run_comparator("less_than", check_value, expect_value, message)


def greater_or_equals(check_value, expect_value, message=""):
    _run_comparator("greater_or_equals", check_value, expect_value, message)


def less_or_equals(check_value, expect_value, message=""):
    _run_comparator("less_or_equals", check_value, expect_value, message)


def not_equal(check_value, expect_value, message=""):
    _run_comparator("not_equal", check_value, expect_value, message)


def string_equals(check_value, expect_value, message=""):
    _run_comparator("string_equals", check_value, expect_value, message)


def length_equal(check_value, expect_value, message=""):
    _run_comparator("length_equal", check_value, expect_value, message)


def length_greater_than(check_value, expect_value, message=""):
    _run_comparator("length_greater_than", check_value, expect_value, message)


def length_greater_or_equals(check_value, expect_value, message=""):
    _run_comparator("length_greater_or_equals", check_value, expect_value, message)


def length_less_than(check_value, expect_value, message=""):
    _run_comparator("length_less_than", check_value, expect_value, message)


def length_less_or_equals(check_value, expect_value, message=""):
    _run_comparator("length_less_or_equals", check_value, expect_value, message)


def contains(check_value, expect_value, message=""):
    _run_comparator("contains", check_value, expect_value, message)


def contained_by(check_value, expect_value, message=""):
    _run_comparator("contained_by", check_value, expect_value, message)


def type_match(check_value, expect_value, message=""):
    _run_comparator("type_match", check_value, expect_value, message)


def regex_match(check_value, expect_value, message=""):
    _run_comparator("regex_match", check_value, expect_value, message)


def startswith(check_value, expect_value, message=""):
    _run_comparator("startswith", check_value, expect_value, message)


def endswith(check_value, expect_value, message=""):
    _run_comparator("endswith", check_value, expect_value, message)
