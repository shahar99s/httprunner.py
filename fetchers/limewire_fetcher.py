import re
from typing import Dict
from urllib.parse import urlparse

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class LimewireFetcherFactory:
    """
    has download notification: No
    has downloads count: Yes
    """

    URL_PATTERN = re.compile(r"limewire\.com/d/([0-9A-Za-z_-]+)")

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        netloc = parsed.netloc.lstrip("www.")
        return (netloc == "limewire.com" or netloc.endswith(".limewire.com")) and bool(
            cls.URL_PATTERN.search(url)
        )

    def __init__(self, link: str, headers: Dict[str, str] | None = None):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid Limewire URL provided")
        self.link = link
        self.headers = headers or {}

        match = self.URL_PATTERN.search(link)
        self.content_id = match.group(1)

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        content_id = self.content_id
        link = self.link
        request_headers = self.headers

        class LimewireFetcher(BaseFetcher):
            NAME = "Limewire"
            BASE_URL = "https://limewire.com"

            def log_fetch_state(self, metadata: dict, downloads_count: int | None):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "content_id": content_id,
                            "filename": metadata.get("filename"),
                            "size": metadata.get("size"),
                            "downloads_count": downloads_count,
                            "state": metadata.get("state"),
                            "file_url": metadata.get("file_url"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def extract_metadata(self, response: ResponseObject) -> dict:
                data = response.json or {}
                # The API may return the file name under 'file_name' or 'name' depending
                # on the content type (uploaded file vs. titled content).
                filename = data.get("file_name") or data.get("name") or f"limewire-{content_id}"
                file_url = data.get("file_url")
                # Determine availability: prefer an explicit 'status' field from the API;
                # fall back to treating the presence of a downloadable file_url as available.
                api_status = data.get("status")
                if api_status is not None:
                    state = "available" if api_status in ("active", "published", "available") else "unavailable"
                else:
                    state = "available" if file_url else "unavailable"
                return {
                    "id": data.get("id") or content_id,
                    "filename": filename,
                    "title": data.get("title"),
                    "size": data.get("size"),
                    "file_type": data.get("file_type"),
                    "file_url": file_url,
                    "downloads_count": data.get("downloads_count"),
                    "creator_id": data.get("creator_id"),
                    "created_at": data.get("created_at"),
                    "state": state,
                    "url": link,
                }

            def extract_downloads_count(self, metadata: dict) -> int | None:
                return metadata.get("downloads_count")

            def extract_filename(self, metadata: dict) -> str:
                return metadata.get("filename") or f"limewire-{content_id}"

            def extract_file_url(self, metadata: dict) -> str:
                file_url = metadata.get("file_url")
                if not file_url:
                    raise ValueError("Error: Limewire file download URL not found")
                return file_url

            def is_available(self, metadata: dict) -> bool:
                return metadata.get("state") == "available"

            info_steps = [
                Step(
                    RunRequest("get content metadata")
                    .get(f"/api/v1/content/{content_id}")
                    .headers(**request_headers)
                    .teardown_callback("extract_metadata(response)", assign="metadata")
                    .teardown_callback("extract_filename(metadata)", assign="filename")
                    .teardown_callback("extract_downloads_count(metadata)", assign="downloads_count")
                    .teardown_callback("extract_file_url(metadata)", assign="file_url")
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
                        .get("$file_url")
                        .headers(**request_headers)
                        .teardown_callback("save_file(response, filename)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: should_download(mode, vars.get("downloads_count")))
                ]
            )

            steps = info_steps if mode == Mode.INFO else fetch_steps

        return LimewireFetcher()
