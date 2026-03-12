import pytest

from fetchers.wetransfer_fetcher import WeTransferFetcherFactory


def _scratch_step(fetcher, index):
    # helper to reach a step's request struct
    return fetcher.teststeps[index].struct().request


def test_parsing_full_download_url_two_parts():
    url = "https://wetransfer.com/downloads/TID/SEC123"
    factory = WeTransferFetcherFactory(url)

    # parsing happens later in steps; just create to ensure no error

    fetcher = factory.create()
    # second step is "create direct link"
    step_req = _scratch_step(fetcher, 1)
    assert step_req.url == "https://wetransfer.com/api/v4/transfers/${transfer_id}/download"
    # when executed the template resolves correctly
    assert fetcher.parser.parse_data(step_req.url, {}) == "https://wetransfer.com/api/v4/transfers/TID/download"
    # because security_hash was known we should have seeded it as a template expression
    vars_map = fetcher.teststeps[1].struct().variables
    assert "security_hash" in vars_map
    assert fetcher.parser.parse_data(vars_map["security_hash"], {}) == "SEC123"
    # recipient_id not seeded
    assert "recipient_id" not in vars_map


def test_parsing_full_download_url_three_parts():
    url = "https://wetransfer.com/downloads/TID/SEC123/RECIPIENT"
    factory = WeTransferFetcherFactory(url)

    fetcher = factory.create()
    step_req = _scratch_step(fetcher, 1)
    assert step_req.url == "https://wetransfer.com/api/v4/transfers/TID/download"
    assert fetcher.teststeps[1].struct().variables["security_hash"] == "SEC123"
    assert fetcher.teststeps[1].struct().variables["recipient_id"] == "RECIPIENT"


def test_parsing_raw_id():
    factory = WeTransferFetcherFactory("JUSTID")

    fetcher = factory.create()
    step_req = _scratch_step(fetcher, 1)
    assert step_req.url == "https://wetransfer.com/api/v4/transfers/JUSTID/download"
    # transfer_id is deduced from the link by the helper function
    assert fetcher.teststeps[1].struct().variables.get("transfer_id") == "JUSTID"
    # no hash/recipient seeded
    assert "security_hash" not in fetcher.teststeps[1].struct().variables
    assert "recipient_id" not in fetcher.teststeps[1].struct().variables


def test_short_url_does_not_preseed():
    factory = WeTransferFetcherFactory("https://we.tl/t-XYZ")

    fetcher = factory.create()
    step_req = _scratch_step(fetcher, 1)
    # placeholder remains in URL
    assert step_req.url == "https://wetransfer.com/api/v4/transfers/$transfer_id/download"
    # only placeholder transfer_id variable is present (still unresolved)
    assert fetcher.teststeps[1].struct().variables.get("transfer_id") == "$transfer_id"


def test_invalid_url_raises():
    with pytest.raises(ValueError):
        WeTransferFetcherFactory("https://example.com/not-a-wetransfer")
    with pytest.raises(ValueError):
        WeTransferFetcherFactory("not valid !!!")


def test_status_step_structure():
    # ensure the prepare-download check step is configured correctly
    url = "https://wetransfer.com/downloads/TID/SEC123"
    factory = WeTransferFetcherFactory(url)
    fetcher = factory.create()

    # first step should be the status check
    step0 = fetcher.teststeps[0].struct()
    assert step0.name == "check transfer status"
    assert "/prepare-download" in step0.request.url

    # teardown hooks should assign boolean flags based on dict result
    hook_names = {list(h.keys())[0] for h in step0.teardown_hooks if isinstance(h, dict)}
    assert "downloadable" in hook_names
    assert "within_limit" in hook_names
    assert "not_expired" in hook_names

    # extraction mapping should include transfer_status and recommended_filename
    extract_map = step0.extract
    assert "transfer_status" in extract_map
    assert "recommended_filename" in extract_map


def test_parse_data_preserves_non_string():
    from httprunner.parser import Parser

    parser = Parser()
    # register a custom function that returns a dict
    parser.functions_mapping["return_dict"] = lambda: {"foo": 123}

    result = parser.parse_data("${return_dict()}")
    assert isinstance(result, dict)
    assert result["foo"] == 123


def test_call_hooks_assigns_non_string():
    from httprunner.step_request import call_hooks
    from httprunner.runner import HttpRunner
    from httprunner.parser import Parser

    runner = HttpRunner()
    runner.parser = Parser()
    # custom function returns list
    runner.parser.functions_mapping["make_list"] = lambda: [1, 2, 3]
    step_vars = {}
    call_hooks(runner, [{"out": "${make_list()}"}], step_vars, "test")
    assert isinstance(step_vars.get("out"), list)
    assert step_vars["out"] == [1, 2, 3]
