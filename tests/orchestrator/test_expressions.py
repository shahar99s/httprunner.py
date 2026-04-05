import unittest

from httporchestrator import expressions
from httporchestrator.exceptions import ParameterError


class TestParserBasic(unittest.TestCase):
    def test_build_url(self):
        url = expressions.build_url("https://postman-echo.com", "/get")
        self.assertEqual(url, "https://postman-echo.com/get")
        url = expressions.build_url("https://postman-echo.com", "get")
        self.assertEqual(url, "https://postman-echo.com/get")
        url = expressions.build_url("https://postman-echo.com/", "/get")
        self.assertEqual(url, "https://postman-echo.com/get")

        url = expressions.build_url("https://postman-echo.com/abc/", "/get?a=1&b=2")
        self.assertEqual(url, "https://postman-echo.com/abc/get?a=1&b=2")
        url = expressions.build_url("https://postman-echo.com/abc/", "get?a=1&b=2")
        self.assertEqual(url, "https://postman-echo.com/abc/get?a=1&b=2")

        # omit query string in base url
        url = expressions.build_url("https://postman-echo.com/abc?x=6&y=9", "/get?a=1&b=2")
        self.assertEqual(url, "https://postman-echo.com/abc/get?a=1&b=2")

        url = expressions.build_url("", "https://postman-echo.com/get")
        self.assertEqual(url, "https://postman-echo.com/get")

        # notice: step request url > config base url
        url = expressions.build_url("https://postman-echo.com", "https://httpbin.org/get")
        self.assertEqual(url, "https://httpbin.org/get")

    def test_build_url_missing_base_netloc(self):
        with self.assertRaises(ParameterError):
            expressions.build_url("not-a-url", "/path")

    def test_parse_string_value(self):
        self.assertEqual(expressions.parse_string_value("123"), 123)
        self.assertEqual(expressions.parse_string_value("12.3"), 12.3)
        self.assertEqual(expressions.parse_string_value("a123"), "a123")
        self.assertEqual(expressions.parse_string_value("$var"), "$var")
        self.assertEqual(expressions.parse_string_value("${func}"), "${func}")

    def test_traverse_path_dict(self):
        data = {"body": {"items": [{"name": "foo"}, {"name": "bar"}]}}
        self.assertEqual(expressions.traverse_path(data, "body.items[0].name"), "foo")
        self.assertEqual(expressions.traverse_path(data, "body.items[1].name"), "bar")
        self.assertEqual(expressions.traverse_path(data, "body"), {"items": [{"name": "foo"}, {"name": "bar"}]})

    def test_traverse_path_list_index(self):
        data = {"items": ["a", "b", "c"]}
        self.assertEqual(expressions.traverse_path(data, "items[2]"), "c")

    def test_traverse_path_attribute(self):
        class Obj:
            status_code = 200

        self.assertEqual(expressions.traverse_path(Obj(), "status_code"), 200)

    def test_resolve_expr(self):
        class Body:
            key = "value"

        class Resp:
            body = Body()
            json = {"file": {"name": "test.txt"}}

        variables = {"response": Resp()}
        self.assertEqual(expressions.resolve_expr("response.body.key", variables), "value")
        self.assertEqual(expressions.resolve_expr('response.json["file"]["name"]', variables), "test.txt")


if __name__ == "__main__":
    unittest.main()
