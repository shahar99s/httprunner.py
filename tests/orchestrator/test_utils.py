import unittest
from pathlib import Path

try:
    import tomllib

    def _toml_loads(content):
        return tomllib.loads(content)

except ModuleNotFoundError:
    import toml

    def _toml_loads(content):
        return toml.loads(content)


from httporchestrator import __version__, utils
from httporchestrator.utils import merge_variables


class TestUtils(unittest.TestCase):
    def test_validators(self):
        from httporchestrator.comparators import COMPARATORS

        functions_mapping = COMPARATORS

        functions_mapping["equal"](None, None)
        functions_mapping["equal"](1, 1)
        functions_mapping["equal"]("abc", "abc")
        with self.assertRaises(AssertionError):
            functions_mapping["equal"]("123", 123)

        functions_mapping["less_than"](1, 2)
        functions_mapping["less_or_equals"](2, 2)

        functions_mapping["greater_than"](2, 1)
        functions_mapping["greater_or_equals"](2, 2)

        functions_mapping["not_equal"](123, "123")

        functions_mapping["length_equal"]("123", 3)
        with self.assertRaises(AssertionError):
            functions_mapping["length_equal"]("123", "3")
        with self.assertRaises(AssertionError):
            functions_mapping["length_equal"]("123", "abc")
        functions_mapping["length_greater_than"]("123", 2)
        functions_mapping["length_greater_or_equals"]("123", 3)

        functions_mapping["contains"]("123abc456", "3ab")
        functions_mapping["contains"](["1", "2"], "1")
        functions_mapping["contains"]({"a": 1, "b": 2}, "a")
        functions_mapping["contained_by"]("3ab", "123abc456")
        functions_mapping["contained_by"](0, [0, 200])

        functions_mapping["regex_match"]("123abc456", r"^123\w+456$")
        with self.assertRaises(AssertionError):
            functions_mapping["regex_match"]("123abc456", "^12b.*456$")

        functions_mapping["startswith"]("abc123", "ab")
        functions_mapping["startswith"]("123abc", 12)
        functions_mapping["startswith"](12345, 123)

        functions_mapping["endswith"]("abc123", 23)
        functions_mapping["endswith"]("123abc", "abc")
        functions_mapping["endswith"](12345, 45)

        functions_mapping["type_match"](580509390, int)
        functions_mapping["type_match"](580509390, "int")
        functions_mapping["type_match"]([], list)
        functions_mapping["type_match"]([], "list")
        functions_mapping["type_match"]([1], "list")
        functions_mapping["type_match"]({}, "dict")
        functions_mapping["type_match"]({"a": 1}, "dict")
        functions_mapping["type_match"](None, "None")
        functions_mapping["type_match"](None, "NoneType")
        functions_mapping["type_match"](None, None)

    def test_lower_dict_keys(self):
        request_dict = {
            "url": "http://127.0.0.1:5000",
            "METHOD": "POST",
            "Headers": {"Accept": "application/json", "User-Agent": "ios/9.3"},
        }
        new_request_dict = utils.lower_dict_keys(request_dict)
        self.assertIn("method", new_request_dict)
        self.assertIn("headers", new_request_dict)
        self.assertIn("Accept", new_request_dict["headers"])
        self.assertIn("User-Agent", new_request_dict["headers"])

        result = utils.lower_dict_keys("$default_request")
        self.assertEqual(result, "$default_request")

        result = utils.lower_dict_keys(None)
        self.assertIsNone(result)

    def test_override_config_variables(self):
        step_variables = {"base_url": "$base_url", "foo1": "bar1"}
        config_variables = {"base_url": "https://postman-echo.com", "foo1": "bar111"}
        self.assertEqual(
            merge_variables(step_variables, config_variables),
            {"base_url": "https://postman-echo.com", "foo1": "bar1"},
        )

    def test_missing_comparators(self):
        from httporchestrator.comparators import COMPARATORS

        functions_mapping = COMPARATORS

        # string_equals
        functions_mapping["string_equals"](123, "123")
        functions_mapping["string_equals"]("abc", "abc")
        with self.assertRaises(AssertionError):
            functions_mapping["string_equals"]("abc", "xyz")

        # length_less_than
        functions_mapping["length_less_than"]("ab", 3)
        with self.assertRaises(AssertionError):
            functions_mapping["length_less_than"]("abc", 3)
        with self.assertRaises(AssertionError):
            functions_mapping["length_less_than"]("ab", "3")

        # length_less_or_equals
        functions_mapping["length_less_or_equals"]("abc", 3)
        functions_mapping["length_less_or_equals"]("ab", 3)
        with self.assertRaises(AssertionError):
            functions_mapping["length_less_or_equals"]("abcd", 3)

    def test_run_comparator(self):
        from httporchestrator.comparators import run_comparator

        run_comparator("equal", 1, 1)
        run_comparator("not_equal", 1, 2)
        with self.assertRaises(AssertionError):
            run_comparator("equal", 1, 2)
        with self.assertRaises(ValueError):
            run_comparator("nonexistent_comparator", 1, 1)

    def test_comparator_failure_messages(self):
        from httporchestrator.comparators import COMPARATORS

        # type_match with unknown type string should raise ValueError
        with self.assertRaises(ValueError):
            COMPARATORS["type_match"](1, "UnknownType")

        # type_match with non-string, non-type, non-None raises ValueError
        with self.assertRaises(ValueError):
            COMPARATORS["type_match"](1, 42)

        # contains with unsupported check_value type
        with self.assertRaises(AssertionError):
            COMPARATORS["contains"](123, 1)

        # contained_by with unsupported expect_value type
        with self.assertRaises(AssertionError):
            COMPARATORS["contained_by"]("a", 123)

        # regex_match with non-string check_value
        with self.assertRaises(AssertionError):
            COMPARATORS["regex_match"](123, r"\d+")

    def test_omit_long_data(self):
        # short string untouched
        result = utils.omit_long_data("hello", omit_len=512)
        self.assertEqual(result, "hello")

        # long string is truncated
        long_str = "x" * 600
        result = utils.omit_long_data(long_str, omit_len=512)
        self.assertTrue(result.startswith("x" * 512))
        self.assertIn("OMITTED", result)
        self.assertEqual(len(result), 512 + len(" ... OMITTED 88 CHARACTORS ..."))

        # bytes truncated
        long_bytes = b"y" * 600
        result = utils.omit_long_data(long_bytes, omit_len=512)
        self.assertIsInstance(result, bytes)
        self.assertIn(b"OMITTED", result)

        # non-string/bytes returned as-is
        result = utils.omit_long_data({"key": "value"})
        self.assertEqual(result, {"key": "value"})
        result = utils.omit_long_data(42)
        self.assertEqual(result, 42)

    def test_format_response_body_for_log(self):
        # dict/list returned as-is
        self.assertEqual(utils.format_response_body_for_log({"a": 1}), {"a": 1})
        self.assertEqual(utils.format_response_body_for_log([1, 2]), [1, 2])

        # short string returned as-is
        self.assertEqual(utils.format_response_body_for_log("hello"), "hello")

        # long string is truncated
        long_str = "z" * 600
        result = utils.format_response_body_for_log(long_str)
        self.assertIn("OMITTED", result)

        # binary with text content-type decoded and truncated
        short_text_bytes = b"hello world"
        result = utils.format_response_body_for_log(short_text_bytes, content_type="text/plain")
        self.assertEqual(result, "hello world")

        # binary with attachment disposition → placeholder string
        binary_data = b"\x00\x01\x02\x03"
        result = utils.format_response_body_for_log(binary_data, content_type="image/png", content_disposition="attachment; filename=file.png")
        self.assertIn("binary content omitted", result)
        self.assertIn("4 bytes", result)

        # binary without text content-type → placeholder string
        result = utils.format_response_body_for_log(b"\x00\x01", content_type="application/octet-stream")
        self.assertIn("binary content omitted", result)

        # other types (int) returned as-is
        self.assertEqual(utils.format_response_body_for_log(None), None)

    def test_merge_variables_none_handling(self):
        # None in step vars does NOT override existing non-None in config vars
        result = merge_variables({"key": None}, {"key": "config_value"})
        self.assertEqual(result["key"], "config_value")

        # None IS preserved when key is absent from base
        result = merge_variables({"new_key": None}, {})
        self.assertIsNone(result["new_key"])

        # step var with non-None value overrides config
        result = merge_variables({"key": "step_value"}, {"key": "config_value"})
        self.assertEqual(result["key"], "step_value")

        # keys only in base are preserved
        result = merge_variables({"a": "1"}, {"b": "2"})
        self.assertEqual(result["a"], "1")
        self.assertEqual(result["b"], "2")

    def test_versions_are_in_sync(self):
        """Checks if the pyproject.toml and __version__ in __init__.py are in sync."""

        path = Path(__file__).resolve().parents[2] / "pyproject.toml"
        pyproject = _toml_loads(path.read_text(encoding="utf-8"))
        pyproject_version = pyproject["tool"]["poetry"]["version"]
        self.assertEqual(pyproject_version, __version__)
