import unittest

from httporchestrator.exceptions import ParameterError, ValidationFailure
from httporchestrator.response import ResponseObject, normalize_comparator, normalize_validator


class TestResponse(unittest.TestCase):
    def setUp(self) -> None:
        class DummyCookies(dict):
            def get_dict(self):
                return dict(self)

        class DummyResp:
            def __init__(self):
                self.status_code = 200
                self.headers = {"Content-Type": "application/json"}
                self._json = {
                    "locations": [
                        {"name": "Seattle", "state": "WA"},
                        {"name": "New York", "state": "NY"},
                        {"name": "Bellevue", "state": "WA"},
                        {"name": "Olympia", "state": "WA"},
                    ]
                }
                self.cookies = DummyCookies({"session": "abc123"})
                self.content = b""
                self.url = "https://example.com/api"

            def json(self):
                return self._json

            @property
            def text(self):
                return str(self._json)

        resp = DummyResp()
        self.resp_obj = ResponseObject(resp)

    def test_extract(self):
        extract_mapping = self.resp_obj.extract(
            {
                "var_1": "body.locations[0]",
                "var_2": "body.locations[3].name",
            },
        )
        self.assertEqual(extract_mapping["var_1"], {"name": "Seattle", "state": "WA"})
        self.assertEqual(extract_mapping["var_2"], "Olympia")

    def test_extract_callable(self):
        extract_mapping = self.resp_obj.extract(
            {
                "var_1": lambda v: "extracted_value",
            },
        )
        self.assertEqual(extract_mapping["var_1"], "extracted_value")

    def test_extract_empty(self):
        self.assertEqual(self.resp_obj.extract({}), {})

    def test_jpath(self):
        self.assertEqual(self.resp_obj.jpath("body.locations[0].name"), "Seattle")
        self.assertEqual(self.resp_obj.jpath("status_code"), 200)

    def test_response_properties(self):
        self.assertEqual(self.resp_obj.status_code, 200)
        self.assertEqual(self.resp_obj.headers, {"Content-Type": "application/json"})
        self.assertEqual(self.resp_obj.cookies, {"session": "abc123"})
        self.assertIn("locations", str(self.resp_obj.text))
        self.assertEqual(self.resp_obj.url, "https://example.com/api")

    def test_resolve_path_unknown_root_with_attr(self):
        # For an attribute that the resp_obj itself has, fall through to getattr
        self.assertEqual(self.resp_obj._resolve_path("url"), "https://example.com/api")

    def test_resolve_path_invalid_raises(self):
        with self.assertRaises(ParameterError):
            self.resp_obj._resolve_path("body.locations[99].name")

    def test_validate(self):
        self.resp_obj.validate(
            [
                {"eq": ["body.locations[0].name", "Seattle"]},
                {"eq": ["body.locations[0]", {"name": "Seattle", "state": "WA"}]},
            ],
        )

    def test_validate_callable_check(self):
        self.resp_obj.validate(
            [
                {"eq": [lambda v: 200, 200]},
            ],
        )

    def test_validate_empty(self):
        # Should pass silently with no validators
        self.resp_obj.validate([])

    def test_validate_failure_raises(self):
        with self.assertRaises(ValidationFailure):
            self.resp_obj.validate([{"eq": ["status_code", 404]}])

    def test_validate_unknown_comparator_raises(self):
        with self.assertRaises(AssertionError):
            self.resp_obj.validate([{"nonexistent_cmp": ["status_code", 200]}])

    def test_validate_with_variables_mapping(self):
        # check_item resolved from variables_mapping when root key exists there
        self.resp_obj.validate(
            [{"eq": ["my_var", "hello"]}],
            variables_mapping={"my_var": "hello"},
        )

    def test_normalize_validator(self):
        validators = [
            {
                "check": "status_code",
                "comparator": "eq",
                "expect": 201,
                "message": "test",
            },
            {"check": "status_code", "assert": "eq", "expect": 201, "msg": "test"},
            {"eq": ["status_code", 201, "test"]},
        ]
        expected = {
            "check": "status_code",
            "assert": "equal",
            "expect": 201,
            "message": "test",
        }
        for validator in validators:
            self.assertEqual(normalize_validator(validator), expected)

    def test_normalize_validator_format2_no_message(self):
        result = normalize_validator({"eq": ["status_code", 200]})
        self.assertEqual(result["assert"], "equal")
        self.assertEqual(result["message"], "")

    def test_normalize_validator_invalid_raises(self):
        with self.assertRaises(ParameterError):
            normalize_validator("not_a_dict")

        with self.assertRaises(ParameterError):
            normalize_validator({"eq": "status_code"})  # value not a list

        with self.assertRaises(ParameterError):
            normalize_validator({"eq": ["status_code", 200], "gt": ["status_code", 0]})  # multiple keys


class TestNormalizeComparator(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(normalize_comparator("eq"), "equal")
        self.assertEqual(normalize_comparator("lt"), "less_than")
        self.assertEqual(normalize_comparator("le"), "less_or_equals")
        self.assertEqual(normalize_comparator("gt"), "greater_than")
        self.assertEqual(normalize_comparator("ge"), "greater_or_equals")
        self.assertEqual(normalize_comparator("ne"), "not_equal")
        self.assertEqual(normalize_comparator("str_eq"), "string_equals")
        self.assertEqual(normalize_comparator("len_eq"), "length_equal")
        self.assertEqual(normalize_comparator("len_gt"), "length_greater_than")
        self.assertEqual(normalize_comparator("len_ge"), "length_greater_or_equals")
        self.assertEqual(normalize_comparator("len_lt"), "length_less_than")
        self.assertEqual(normalize_comparator("len_le"), "length_less_or_equals")

    def test_canonical_names_pass_through(self):
        self.assertEqual(normalize_comparator("equal"), "equal")
        self.assertEqual(normalize_comparator("contains"), "contains")
        self.assertEqual(normalize_comparator("regex_match"), "regex_match")

    def test_unknown_name_passes_through(self):
        self.assertEqual(normalize_comparator("my_custom_cmp"), "my_custom_cmp")



class TestResponse(unittest.TestCase):
    def setUp(self) -> None:
        class DummyCookies(dict):
            def get_dict(self):
                return dict(self)

        class DummyResp:
            def __init__(self):
                self.status_code = 200
                self.headers = {}
                self._json = {
                    "locations": [
                        {"name": "Seattle", "state": "WA"},
                        {"name": "New York", "state": "NY"},
                        {"name": "Bellevue", "state": "WA"},
                        {"name": "Olympia", "state": "WA"},
                    ]
                }
                self.cookies = DummyCookies()
                self.content = b""

            def json(self):
                return self._json

            @property
            def text(self):
                return str(self._json)

        resp = DummyResp()
        self.resp_obj = ResponseObject(resp)

    def test_extract(self):
        extract_mapping = self.resp_obj.extract(
            {
                "var_1": "body.locations[0]",
                "var_2": "body.locations[3].name",
            },
        )
        self.assertEqual(extract_mapping["var_1"], {"name": "Seattle", "state": "WA"})
        self.assertEqual(extract_mapping["var_2"], "Olympia")

    def test_extract_callable(self):
        extract_mapping = self.resp_obj.extract(
            {
                "var_1": lambda v: "extracted_value",
            },
        )
        self.assertEqual(extract_mapping["var_1"], "extracted_value")

    def test_jpath(self):
        self.assertEqual(self.resp_obj.jpath("body.locations[0].name"), "Seattle")
        self.assertEqual(self.resp_obj.jpath("status_code"), 200)

    def test_validate(self):
        self.resp_obj.validate(
            [
                {"eq": ["body.locations[0].name", "Seattle"]},
                {"eq": ["body.locations[0]", {"name": "Seattle", "state": "WA"}]},
            ],
        )

    def test_validate_callable_check(self):
        self.resp_obj.validate(
            [
                {"eq": [lambda v: 200, 200]},
            ],
        )

    def test_normalize_validator(self):
        validators = [
            {
                "check": "status_code",
                "comparator": "eq",
                "expect": 201,
                "message": "test",
            },
            {"check": "status_code", "assert": "eq", "expect": 201, "msg": "test"},
            {"eq": ["status_code", 201, "test"]},
        ]
        expected = {
            "check": "status_code",
            "assert": "equal",
            "expect": 201,
            "message": "test",
        }
        for validator in validators:
            self.assertEqual(normalize_validator(validator), expected)
