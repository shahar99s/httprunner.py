import unittest

import requests

from httprunner.parser import Parser
from httprunner.response import ResponseObject, uniform_validator
from httprunner.utils import HTTP_BIN_URL


class TestResponse(unittest.TestCase):
    def setUp(self) -> None:
        # create a dummy response-like object to avoid network calls
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
        parser = Parser(
            functions_mapping={"get_name": lambda: "name", "get_num": lambda x: x}
        )
        self.resp_obj = ResponseObject(resp, parser)

    def test_extract(self):
        variables_mapping = {"body": "body"}
        extract_mapping = self.resp_obj.extract(
            {
                "var_1": "body.locations[0]",
                "var_2": "body.locations[3].name",
                "var_3": "$body.locations[3].name",
                "var_4": "$body.locations[3].${get_name()}",
            },
            variables_mapping=variables_mapping,
        )
        self.assertEqual(extract_mapping["var_1"], {"name": "Seattle", "state": "WA"})
        self.assertEqual(extract_mapping["var_2"], "Olympia")
        self.assertEqual(extract_mapping["var_3"], "Olympia")
        self.assertEqual(extract_mapping["var_4"], "Olympia")

    def test_validate(self):
        self.resp_obj.validate(
            [
                {"eq": ["body.locations[0].name", "Seattle"]},
                {"eq": ["body.locations[0]", {"name": "Seattle", "state": "WA"}]},
            ],
        )

    def test_validate_variables(self):
        variables_mapping = {"index": 1, "var_empty": ""}
        self.resp_obj.validate(
            [
                {"eq": ["body.locations[$index].name", "New York"]},
                {"eq": ["$var_empty", ""]},
            ],
            variables_mapping=variables_mapping,
        )

    def test_validate_functions(self):
        variables_mapping = {"index": 1}
        self.resp_obj.validate(
            [
                {"eq": ["${get_num(0)}", 0]},
                {"eq": ["${get_num($index)}", 1]},
            ],
            variables_mapping=variables_mapping,
        )

    def test_uniform_validator(self):
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
            self.assertEqual(uniform_validator(validator), expected)

    def test_extract_with_non_string_value(self):
        # register a parser function that returns a non-string (dict)
        self.resp_obj.parser.functions_mapping["return_obj"] = lambda: {"foo": 123}
        mapping = self.resp_obj.extract({"out": "${return_obj()}"})
        self.assertIsInstance(mapping["out"], dict)
        self.assertEqual(mapping["out"], {"foo": 123})

    def test_validate_non_string_check_item(self):
        # parser returns dict, should be passed through to comparator
        self.resp_obj.parser.functions_mapping["return_obj"] = lambda: {"foo": 123}
        # using equality against same dict should pass
        self.resp_obj.validate([
            {"eq": ["${return_obj()}", {"foo": 123}]},
        ])
