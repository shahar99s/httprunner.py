import datetime
import os
import re
from typing import Dict

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class SendgbFetcherFactory:
    """
    has download notification: Yes, for the first download only
    has downloads count: Yes
    """

    URL_PATTERN = re.compile(r"(?:https?://)(?:www\.)?sendgb\.com/(?:upload/\?utm_source=)?([0-9a-zA-Z]+)")

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        return bool(cls.URL_PATTERN.search(url))

    def __init__(
        self_factory,
        link: str,
        password: str | None = None,
        headers: Dict[str, str] | None = None,
    ):
        if not self_factory.is_relevant_url(link):
            raise ValueError("Error: Invalid SendGB URL provided")
        self_factory.link = link
        self_factory.password = password
        self_factory.headers = headers or {}

        match = self_factory.URL_PATTERN.search(self_factory.link)
        self_factory.id = match.group(1)

    def create(self_factory, mode: Mode = Mode.FETCH) -> BaseFetcher:
        class SendgbFetcher(BaseFetcher):
            NAME = "SendGB"
            BASE_URL = "https://www.sendgb.com"

            def log_fetch_state(self, metadata: dict, downloads_count: int):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "downloads_count": downloads_count,
                            "direct_download": metadata.get("direct_download"),
                            "expires_at": metadata.get("deletion_date"),
                            "state": metadata.get("is_deleted"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def default_downloads_count(self) -> int:
                return 1

            def save_file_outer(self, response: ResponseObject):
                disposition = response.headers.get("Content-Disposition", "")
                if "filename=" in disposition:
                    filename = disposition.split("filename=")[-1].strip('"')
                else:
                    filename = "downloaded"
                self.save_file(response, filename)

            def is_direct_download(self, response: ResponseObject) -> bool:
                return "content-disposition" in response.headers

            def extract_secret_code(self, response: ResponseObject) -> str | None:
                match = re.search(r'id="secret_code" value="([^"]*)"', response.text)
                return match.group(1)

            def extract_file_attr(self, response: ResponseObject) -> str | None:
                match = re.search(r'data-file="([^\"]+)"', response.text)
                return match.group(1)

            def extract_private_id(self, response: ResponseObject) -> str:
                match = re.search(r'data-private_id="([^\"]*)"', response.text)
                return match.group(1)

            def extract_deletion_date(self, response: ResponseObject) -> str | None:
                match = re.search(
                    r'<div class="fw-bold">Deletion Date</div>\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})',
                    response.text,
                )
                return match.group(1) if match else None

            def extract_is_deleted(self, response: ResponseObject) -> bool:
                deletion_date_str = self.extract_deletion_date(response)
                if deletion_date_str is None:
                    # No deletion date in the page — file is still available.
                    return False
                deletion_date = datetime.datetime.strptime(deletion_date_str, "%d.%m.%Y").date()
                current_date = datetime.datetime.now().date()
                return current_date > deletion_date

            def extract_metadata(self, response: ResponseObject) -> dict:
                return {
                    "id": self_factory.id,
                    "direct_download": self.is_direct_download(response),
                    "secret_code": self.extract_secret_code(response),
                    "file": self.extract_file_attr(response),
                    "private_id": self.extract_private_id(response),
                    "deletion_date": self.extract_deletion_date(response),
                    "is_deleted": self.extract_is_deleted(response),
                }

            def save_if_direct(self, response: ResponseObject, direct: bool):
                if direct and should_download(mode, 1):
                    self.save_file_outer(response)

            def __init__(self):
                super().__init__()
                info_steps = [
                    Step(
                        RunRequest("get upload page")
                        .get(f"/upload/?utm_source={self_factory.id}")
                        .headers(**self_factory.headers)
                        .teardown_callback("default_downloads_count()", assign="downloads_count")
                        .teardown_callback("is_direct_download(response)", assign="direct_download")
                        .teardown_callback("extract_secret_code(response)", assign="secret_code")
                        .teardown_callback("extract_file_attr(response)", assign="file")
                        .teardown_callback("extract_private_id(response)", assign="private_id")
                        .teardown_callback("extract_is_deleted(response)", assign="is_deleted")
                        .teardown_callback("extract_metadata(response)", assign="metadata")
                        .teardown_callback("log_fetch_state(metadata, downloads_count)")
                        .teardown_callback("save_if_direct(response, direct_download)")
                        .validate()
                        .assert_equal("status_code", 200)
                        .assert_equal("is_deleted", False)
                    )
                ]
                fetch_steps = info_steps.copy()
                fetch_steps.extend(
                    [
                        OptionalStep(
                            Step(
                                RunRequest("create direct link")
                                .get(
                                    lambda v: f"/src/download_one.php?uploadId={self_factory.id}&sc={v['secret_code']}&file={v['file']}&private_id={v['private_id']}"
                                )
                                .headers(**self_factory.headers)
                                .teardown_callback("response.body['url']", assign="direct_link")
                                .validate()
                                .assert_equal("status_code", 200)
                                .assert_equal("body.success", True)
                            )
                        ).when(
                            lambda step, vars: (
                                should_download(mode, vars.get("downloads_count"))
                                and not vars.get("direct_download", False)
                            )
                        ),
                        OptionalStep(
                            Step(
                                RunRequest("download")
                                .get("$direct_link")
                                .headers(**self_factory.headers)
                                .teardown_callback("save_file_outer(response)")
                                .validate()
                                .assert_equal("status_code", 200)
                            )
                        ).when(
                            lambda step, vars: (
                                should_download(mode, vars.get("downloads_count"))
                                and not vars.get("direct_download", False)
                            )
                        ),
                    ]
                )

                self.steps = info_steps if mode == Mode.INFO else fetch_steps

        return SendgbFetcher()
