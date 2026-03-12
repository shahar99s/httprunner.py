import unittest

from fetchers.wetransfer_fetcher import WeTransferFetcherFactory


def _scratch_step(fetcher, index):
    return fetcher.teststeps[index].struct().request


class TestWeTransferFetcherFactory(unittest.TestCase):
    def test_parsing_full_url_two_parts(self):
        factory = WeTransferFetcherFactory("https://wetransfer.com/downloads/TID/SEC")
        fetcher = factory.create()

        # variables seeded from the original link via the with_variables logic
        vars_map = fetcher.teststeps[1].struct().variables
        parser = fetcher.parser
        self.assertEqual(parser.parse_data(vars_map["security_hash"], {}), "SEC")
        self.assertEqual(parser.parse_data(vars_map["recipient_id"], {}), None)
        # the transfer_id is embedded in the post URL because the variable
        # substitution happened at step parsing time
        step_req = _scratch_step(fetcher, 1)
        # URL remains templated until execution
        self.assertEqual(step_req.url, "https://wetransfer.com/api/v4/transfers/${transfer_id}/download")
        # simulate runtime substitution to verify it resolves correctly
        self.assertEqual(
            fetcher.parser.parse_data(step_req.url, {}),
            "https://wetransfer.com/api/v4/transfers/TID/download",
        )

        # helper functions should also return expected results when invoked
        parser = fetcher.parser
        self.assertEqual(parser.parse_data("${parse_link_transfer_id()}", {}), "TID")
        self.assertEqual(parser.parse_data("${parse_link_security_hash()}", {}), "SEC")
        self.assertIsNone(parser.parse_data("${parse_link_recipient_id()}", {}))

        # the create direct link step still has the request-based setup hook
        setup_hooks = fetcher.teststeps[1].struct().setup_hooks
        self.assertEqual(setup_hooks, [{"transfer_id": "${get_transfer_id_from_request($request)}"}])

    def test_parsing_full_url_three_parts(self):
        factory = WeTransferFetcherFactory("https://wetransfer.com/downloads/TID/SEC/REC")
        fetcher = factory.create()
        vars_map = fetcher.teststeps[1].struct().variables
        self.assertEqual(vars_map["security_hash"], "SEC")
        self.assertEqual(vars_map["recipient_id"], "REC")

        parser = fetcher.parser
        self.assertEqual(parser.parse_data("${parse_link_transfer_id()}", {}), "TID")
        self.assertEqual(parser.parse_data("${parse_link_recipient_id()}", {}), "REC")

        step_req = _scratch_step(fetcher, 1)
        setup_hooks = fetcher.teststeps[1].struct().setup_hooks
        self.assertEqual(setup_hooks, [{"transfer_id": "${get_transfer_id_from_request($request)}"}])
        self.assertEqual(
            fetcher.parser.parse_data(setup_hooks[0]["transfer_id"], {"request": {"url": step_req.url}}),
            "TID",
        )

    def test_parsing_raw_id(self):
        factory = WeTransferFetcherFactory("ABC123")
        fetcher = factory.create()
        step_req = _scratch_step(fetcher, 1)
        # URL template remains unfilled until execution
        self.assertEqual(step_req.url, "https://wetransfer.com/api/v4/transfers/${transfer_id}/download")
        # evaluate at runtime
        self.assertEqual(fetcher.parser.parse_data(step_req.url, {}), "https://wetransfer.com/api/v4/transfers/ABC123/download")
        # nothing known up-front; only recipient_id is declared as None
        self.assertEqual(fetcher.teststeps[1].struct().variables, {"recipient_id": None})

    def test_short_url(self):
        factory = WeTransferFetcherFactory("https://we.tl/t-foo")

        fetcher = factory.create()
        step_req = _scratch_step(fetcher, 1)
        # id not known yet, URL should still use placeholder variable
        self.assertEqual(step_req.url, "https://wetransfer.com/api/v4/transfers/${transfer_id}/download")
        # the template value was supplied by the helper function
        self.assertEqual(fetcher.teststeps[1].struct().variables, {"transfer_id": "$transfer_id", "recipient_id": None})

        # hook still exists; evaluating it against the placeholder URL yields
        # an empty string until the optional resolver step populates the
        # variable.
        setup_hooks = fetcher.teststeps[1].struct().setup_hooks
        self.assertEqual(setup_hooks, [{"transfer_id": "${get_transfer_id_from_request($request)}"}])
        # with no transfer_id variable yet, the regex will capture the
        # literal placeholder rather than returning an empty string
        self.assertEqual(
            fetcher.parser.parse_data(setup_hooks[0]["transfer_id"], {"request": {"url": step_req.url}}),
            "$transfer_id",
        )

    def test_url_from_main_example(self):
        # ensure query parameters do not interfere with parsing and that
        # recipient_id is seeded so building the payload won't raise
        url = (
            "https://wetransfer.com/downloads/"
            "b1446cfa95a605d896ee821c7b76222f20260311083557/0626bd"
            "?t_exp=1773477358&t_lsid=978b789e-6348-4a88-a31f-5f4c19a65395"
        )
        factory = WeTransferFetcherFactory(url)

        fetcher = factory.create()
        vars_map = fetcher.teststeps[1].struct().variables
        parser = fetcher.parser
        self.assertEqual(parser.parse_data(vars_map["security_hash"], {}), "0626bd")
        self.assertEqual(parser.parse_data(vars_map["recipient_id"], {}), None)

    def test_invalid_url(self):
        with self.assertRaises(ValueError):
            WeTransferFetcherFactory("https://example.com/not")
        with self.assertRaises(ValueError):
            WeTransferFetcherFactory("@@@")


class TestMergeVariables(unittest.TestCase):
    def test_merge_skip_none(self):
        from httprunner.utils import merge_variables
        # when step provides None but session already has value, keep existing
        self.assertEqual(merge_variables({"foo": None}, {"foo": "bar"}), {"foo": "bar"})
        # when session has no value, None is preserved so parser sees a defined key
        self.assertEqual(merge_variables({"foo": None}, {}), {"foo": None})
