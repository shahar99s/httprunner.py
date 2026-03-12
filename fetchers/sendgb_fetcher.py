import re
import os
import datetime
from typing import Dict
from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import Step, OptionalStep

class SendgbFetcherFactory:

    def __init__(self_factory, link: str, password: str | None = None, headers: Dict[str, str] | None = None):
        self_factory.link = link
        self_factory.password = password
        self_factory.headers = headers or {}

        match = re.search(r"(?:https?://)(?:www\.)?sendgb\.com/(?:upload/\?utm_source=)?([0-9a-zA-Z]+)", self_factory.link)
        if not match:
            raise ValueError("Error: Invalid SendGB URL provided")
        self_factory.id = match.group(1)

    def create(self_factory, mode: Mode = Mode.FETCH) -> BaseFetcher:
        """
        mode: "info" (only info_steps), "fetch" (full fetch_steps)
        """
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
                            "is_direct_download": metadata.get("direct_download"),
                            "deletion_date": metadata.get("deletion_date"),
                            "is_deleted": metadata.get("is_deleted"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def default_downloads_count(self) -> int | None:
                return None

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
                match = re.search(r'<div class="fw-bold">Deletion Date</div>\s*([0-9]{2}\.[0-9]{2}\.[0-9]{4})', response.text)
                return match.group(1)

            def extract_is_deleted(self, response: ResponseObject) -> str:
                deletion_date_str = self.extract_deletion_date(response)
                deletion_date = datetime.datetime.strptime(deletion_date_str, "%d.%m.%Y").date()
                current_date = datetime.datetime.now().date()
                return str(current_date > deletion_date)

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

            info_steps = [
                Step(
                    RunRequest("get upload page")
                    .get(f"/upload/?utm_source={self_factory.id}")
                    .with_headers(**self_factory.headers)
                    .teardown_hook("${default_downloads_count()}", "downloads_count")
                    .teardown_hook("${is_direct_download($response)}", "direct_download")
                    .teardown_hook("${extract_secret_code($response)}", "secret_code")
                    .teardown_hook("${extract_file_attr($response)}", "file")
                    .teardown_hook("${extract_private_id($response)}", "private_id")
                    .teardown_hook("${extract_is_deleted($response)}", "is_deleted")
                    .teardown_hook("${extract_metadata($response)}", "metadata")
                    .teardown_hook("${log_fetch_state($metadata, $downloads_count)}")
                    .teardown_hook("${save_if_direct($response, $direct_download)}")
                    .extract()
                    .with_jmespath("$downloads_count", "downloads_count")
                    .with_jmespath("$metadata", "metadata")
                    .with_jmespath("$secret_code", "secret_code")
                    .with_jmespath("$file", "file")
                    .with_jmespath("$private_id", "private_id")
                    .with_jmespath("$is_deleted", "is_deleted")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("$is_deleted", False)
                )
            ]
            fetch_steps = info_steps.copy()
            fetch_steps.extend([
                OptionalStep(
                    RunRequest("create direct link")
                    .get(f"/src/download_one.php?uploadId={self_factory.id}&sc=$secret_code&file=$file&private_id=$private_id")
                    .with_headers(**self_factory.headers)
                    .extract()
                    .with_jmespath("body.url", "direct_link")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("body.success", True)
                ).when(lambda step, vars: should_download(mode, vars.get("downloads_count")) and not vars.get("direct_download", False)),
                OptionalStep(
                    RunRequest("download")
                    .get("$direct_link")
                    .with_headers(**self_factory.headers)
                    .teardown_hook("${save_file_outer($response)}")
                    .validate()
                    .assert_equal("status_code", 200)
                ).when(lambda step, vars: should_download(mode, vars.get("downloads_count")) and not vars.get("direct_download", False)),
            ])

            teststeps = info_steps if mode == Mode.INFO else fetch_steps

        return SendgbFetcher()
