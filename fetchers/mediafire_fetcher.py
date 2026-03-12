import re
import os
from typing import Dict
from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class MediaFireFetcherFactory:
    def __init__(self, link: str, headers: Dict[str, str] | None = None):
        self.link = link
        self.headers = headers or {}
        result = re.search(r"mediafire\.com\/file\/(\w+)\/", self.link)
        if result == None and '.com' in self.link:
            raise ValueError('Error: No valid URL provided')
        elif result != None and len(result.groups()) > 0:
            self.file_key = result.group(1)
        else:
            self.file_key = self.link

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        """
        mode: Mode.INFO (only info_steps), Mode.FETCH (full fetch_steps)
        """
        class MediaFireFetcher(BaseFetcher):
            NAME = "MediaFire"
            BASE_URL = "https://mediafire.com"

            def log_fetch_state(self, metadata: dict, downloads_count: int):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filename": metadata.get("filename"),
                            "downloads_count": downloads_count,
                            "views_count": metadata.get("views") or metadata.get("view"),
                            "upload_date": metadata.get("created"),
                            "size": metadata.get("size"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def extract_metadata(self, response: ResponseObject) -> dict:
                return response.json["response"]["file_info"]

            def default_downloads_count(self) -> int:
                return 1

            def extract_direct_download_link(self, response: ResponseObject) -> str:
                for line in response.body.decode('utf-8').splitlines():
                    m = re.search(r'href="((http|https)://download[^\"]+)', line)
                    if m:
                        direct_download_link = m.groups()[0]
                        return direct_download_link
                raise ValueError('Error: No valid direct download link found')

            info_steps = [
                Step(
                    RunRequest("info")
                    .post("/api/1.5/file/get_info.php")
                    .with_headers(**self.headers)
                    .with_params(**{'recursive': 'yes', 'quick_key': self.file_key, 'response_format': 'json'})
                    .teardown_hook("${extract_metadata($response)}", "metadata")
                    .teardown_hook("${default_downloads_count()}", "downloads_count")
                    .teardown_hook("${log_fetch_state($metadata, $downloads_count)}")
                    .extract()
                    .with_jmespath("$metadata", "metadata")
                    .with_jmespath("body.response.file_info.filename", "filename")
                    .with_jmespath("$downloads_count", "downloads_count")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("body.response.file_info.password_protected", "no")
                    .assert_equal("body.response.file_info.permissions.read", "1")
                    .assert_equal("body.response.result", "Success")
                ),
            ]
            fetch_steps = info_steps.copy()
            fetch_steps.extend([
                OptionalStep(
                    RunRequest("get direct link")
                    .get("/file/{}".format(self.file_key))
                    .with_headers(**self.headers)
                    .teardown_hook("${extract_direct_download_link($response)}", "direct_download_link")
                    .extract()
                    .with_jmespath("$direct_download_link", "direct_download_link")
                    .validate()
                    .assert_equal("status_code", 200)
                ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                OptionalStep(
                    RunRequest("download link")
                    .get("$direct_download_link")
                    .with_headers(**self.headers)
                    .teardown_hook("${save_file($response, $filename)}")
                    .validate()
                    .assert_equal("status_code", 200)
                ).when(lambda step, vars: should_download(mode, vars.get("downloads_count")))
            ])
            teststeps = info_steps if mode == Mode.INFO else fetch_steps

        return MediaFireFetcher()
