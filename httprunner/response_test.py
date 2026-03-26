import unittest

from httprunner.response import ResponseObject, uniform_validator


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
