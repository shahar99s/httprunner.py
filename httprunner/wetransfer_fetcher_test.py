import unittest

from fetchers.wetransfer_fetcher import WeTransferFetcherFactory


def _step_struct(fetcher, index):
    return fetcher.steps[index].struct()


class TestWeTransferFetcherFactory(unittest.TestCase):
    def test_parse_downloads_url_two_parts(self):
        parsed = WeTransferFetcherFactory._parse_downloads_url(
            "https://wetransfer.com/downloads/TID/SEC"
        )
        self.assertEqual(parsed["transfer_id"], "TID")
        self.assertEqual(parsed["security_hash"], "SEC")
        self.assertNotIn("recipient_id", parsed)

    def test_parse_downloads_url_three_parts(self):
        parsed = WeTransferFetcherFactory._parse_downloads_url(
            "https://wetransfer.com/downloads/TID/SEC/REC"
        )
        self.assertEqual(parsed["transfer_id"], "TID")
        self.assertEqual(parsed["security_hash"], "SEC")
        self.assertEqual(parsed["recipient_id"], "REC")

    def test_full_url_builds_callable_request_steps(self):
        url = "https://wetransfer.com/downloads/TID/SEC"
        fetcher = WeTransferFetcherFactory(url).create()

        status_step = _step_struct(fetcher, 0)
        self.assertEqual(status_step.name, "check transfer status")
        self.assertEqual(status_step.variables, {"download_url": url})
        self.assertTrue(callable(status_step.request.url))
        self.assertTrue(callable(status_step.request.req_json))
        self.assertEqual(len(status_step.setup_hooks), 1)

        vars_map = {"self": fetcher, "download_url": url}
        status_step.setup_hooks[0](vars_map)

        self.assertEqual(vars_map["transfer_id"], "TID")
        self.assertEqual(vars_map["security_hash"], "SEC")
        self.assertIsNone(vars_map["recipient_id"])
        self.assertEqual(
            status_step.request.url(vars_map),
            "/api/v4/transfers/TID/prepare-download",
        )
        self.assertEqual(
            status_step.request.req_json(vars_map),
            {"intent": "entire_transfer", "security_hash": "SEC"},
        )

        direct_link_step = _step_struct(fetcher, 1)
        self.assertEqual(direct_link_step.name, "create direct link")
        self.assertTrue(callable(direct_link_step.request.url))
        self.assertTrue(callable(direct_link_step.request.req_json))

    def test_full_url_three_parts_builds_payload_recipient(self):
        url = "https://wetransfer.com/downloads/TID/SEC/REC"
        fetcher = WeTransferFetcherFactory(url).create()
        status_step = _step_struct(fetcher, 0)

        vars_map = {"self": fetcher, "download_url": url}
        status_step.setup_hooks[0](vars_map)

        self.assertEqual(vars_map["transfer_id"], "TID")
        self.assertEqual(vars_map["security_hash"], "SEC")
        self.assertEqual(vars_map["recipient_id"], "REC")
        self.assertEqual(
            status_step.request.req_json(vars_map),
            {
                "intent": "entire_transfer",
                "security_hash": "SEC",
                "recipient_id": "REC",
            },
        )

    def test_short_url_inserts_resolver_step(self):
        url = "https://we.tl/t-foo"
        fetcher = WeTransferFetcherFactory(url).create()

        resolver_step = _step_struct(fetcher, 0)
        self.assertEqual(resolver_step.name, "resolve short url")
        self.assertEqual(resolver_step.request.url, url)
        step1_vars = _step_struct(fetcher, 1).variables
        self.assertIn("download_url", step1_vars)
        self.assertTrue(callable(step1_vars["download_url"]))

    def test_url_from_main_example_parses_security_hash(self):
        url = (
            "https://wetransfer.com/downloads/"
            "b1446cfa95a605d896ee821c7b76222f20260311083557/0626bd"
            "?t_exp=1773477358&t_lsid=978b789e-6348-4a88-a31f-5f4c19a65395"
        )
        fetcher = WeTransferFetcherFactory(url).create()
        status_step = _step_struct(fetcher, 0)
        vars_map = {"self": fetcher, "download_url": url}
        status_step.setup_hooks[0](vars_map)

        self.assertEqual(
            vars_map["transfer_id"],
            "b1446cfa95a605d896ee821c7b76222f20260311083557",
        )
        self.assertEqual(vars_map["security_hash"], "0626bd")
        self.assertIsNone(vars_map["recipient_id"])

    def test_invalid_url(self):
        with self.assertRaises(ValueError):
            WeTransferFetcherFactory("https://example.com/not")
        with self.assertRaises(ValueError):
            WeTransferFetcherFactory("@@@")


class TestMergeVariables(unittest.TestCase):
    def test_merge_skip_none(self):
        from httprunner.utils import merge_variables

        self.assertEqual(merge_variables({"foo": None}, {"foo": "bar"}), {"foo": "bar"})
        self.assertEqual(merge_variables({"foo": None}, {}), {"foo": None})
