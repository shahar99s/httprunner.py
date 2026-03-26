import re
from typing import Dict
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class DropboxTransferFetcherFactory:
    """
    has download notification: No
    has downloads count: No
    note: DocSend links are has viewing and downloading notifications
    """

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        return "dropbox.com" in parsed.netloc and (
            parsed.path.startswith("/t/")
            or parsed.path.startswith("/s/")
            or parsed.path.startswith("/l/scl/")
            or parsed.path.startswith("/scl/")
        )

    def __init__(self, link: str, headers: Dict[str, str] | None = None):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid Dropbox Transfer URL provided")
        self.link = link
        self.headers = headers or {}

        parsed = urlparse(link)

        # Build the direct-download URL by setting dl=1
        qs = parse_qs(parsed.query)
        qs["dl"] = ["1"]
        self.direct_link = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))

        # Extract filename from URL path (e.g. /scl/fi/xxx/filename.ext?...)
        path_parts = parsed.path.rstrip("/").split("/")
        self.url_filename = None
        for part in reversed(path_parts):
            if "." in part and part != "fi":
                self.url_filename = part
                break

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        link = self.link
        direct_link = self.direct_link
        url_filename = self.url_filename
        request_headers = self.headers

        class DropboxTransferFetcher(BaseFetcher):
            NAME = "DropboxTransfer"
            BASE_URL = "https://www.dropbox.com"

            def log_fetch_state(self, metadata: dict, downloads_count: int | None):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filename": metadata.get("filename"),
                            "downloads_count": downloads_count,
                            "content_type": metadata.get("content_type"),
                            "state": metadata.get("state"),
                            "direct_link": metadata.get("direct_link"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def extract_metadata(self, response: ResponseObject) -> dict:
                """Extract metadata from HEAD response to the dl=1 URL."""
                disposition = response.headers.get("Content-Disposition", "")
                filename = url_filename
                if "filename=" in disposition:
                    # Handle both filename= and filename*=UTF-8''
                    m = re.search(r"filename\*?=(?:UTF-8'')?([^\s;]+)", disposition)
                    if m:
                        filename = m.group(1).strip('"')

                content_type = response.headers.get("Content-Type", "")
                content_length = response.headers.get("Content-Length")

                return {
                    "filename": filename,
                    "content_type": content_type,
                    "size": int(content_length) if content_length else None,
                    "direct_link": direct_link,
                    "state": "available" if response.status_code == 200 else "unavailable",
                    "url": link,
                }

            def extract_filename(self, metadata: dict) -> str:
                return metadata.get("filename") or url_filename or "dropbox-download.bin"

            def default_downloads_count(self) -> int | None:
                # Dropbox has no downloads count, defaulting to 1
                return 1

            def is_available(self, metadata: dict) -> bool:
                return metadata.get("state") == "available"

            info_steps = [
                Step(
                    RunRequest("get file metadata")
                    .head(direct_link)
                    .headers(**request_headers)
                    .teardown_callback("extract_metadata(response)", assign="metadata")
                    .teardown_callback("extract_filename(metadata)", assign="filename")
                    .teardown_callback("default_downloads_count()", assign="downloads_count")
                    .teardown_callback("is_available(metadata)", assign="available")
                    .teardown_callback("log_fetch_state(metadata, downloads_count)")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("available", True)
                )
            ]

            fetch_steps = info_steps.copy()
            fetch_steps.extend(
                [
                    OptionalStep(
                        RunRequest("download")
                        .get(direct_link)
                        .headers(**request_headers)
                        .teardown_callback("save_file(response, filename)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: should_download(mode, 1))
                ]
            )

            steps = info_steps if mode == Mode.INFO else fetch_steps

        return DropboxTransferFetcher()
