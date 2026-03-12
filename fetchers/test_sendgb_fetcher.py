import pytest

from fetchers.sendgb_fetcher import SendgbFetcherFactory


def _scratch_step(fetcher, index):
    # helper to reach a step's request struct
    return fetcher.teststeps[index].struct().request


def test_invalid_url_raises():
    with pytest.raises(ValueError):
        SendgbFetcherFactory("https://example.com/not-sendgb")
    with pytest.raises(ValueError):
        SendgbFetcherFactory("not a url")


def test_id_extraction_and_step_templates():
    url = "https://sendgb.com/g4D2eAoOamH"
    factory = SendgbFetcherFactory(url)
    # id should be extracted correctly
    assert factory.id == "g4D2eAoOamH"
    # also support the upload/?utm_source= form
    factory2 = SendgbFetcherFactory("https://sendgb.com/upload/?utm_source=g4D2eAoOamH")
    assert factory2.id == "g4D2eAoOamH"

    fetcher = factory.create()
    # first step should point to the upload page with the id
    step0 = _scratch_step(fetcher, 0)
    assert step0.url == f"https://www.sendgb.com/upload/?utm_source={factory.id}"

    # after the initial fetch we expect the factory to seed variables
    vars_map = fetcher.teststeps[0].struct().variables
    # secret_code/file/private_id should be registered as template variables
    assert "secret_code" in vars_map
    assert "file" in vars_map
    assert "private_id" in vars_map

    # second step should build the download_one.php URL using the templates
    step1 = _scratch_step(fetcher, 1)
    assert "/src/download_one.php" in step1.url
    assert "$secret_code" in step1.url
    assert "$file" in step1.url
    assert "$private_id" in step1.url

    # third step should download from the variable direct_link
    step2 = _scratch_step(fetcher, 2)
    assert step2.url == "$direct_link"
