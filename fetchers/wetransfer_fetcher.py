import datetime
import os
import re
from typing import Dict
from urllib.parse import urlparse

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class WeTransferFetcherFactory:
    """
    has download notification: Yes, for the first download only
    has downloads count: Yes
    """

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        return "wetransfer.com/downloads" in url or "we.tl/" in url

    @staticmethod
    def _parse_downloads_url(url: str) -> dict:
        """Return ``{transfer_id, security_hash[, recipient_id]}`` for a
        full ``wetransfer.com/downloads/...`` link.
        """
        parsed_url = urlparse(url)
        path_params = parsed_url.path.rstrip("/").split("/")[2:]
        if len(path_params) == 2:
            return {"transfer_id": path_params[0], "security_hash": path_params[1]}
        elif len(path_params) == 3:
            # order is transfer_id, security_hash, recipient_id
            return {
                "transfer_id": path_params[0],
                "security_hash": path_params[1],
                "recipient_id": path_params[2],
            }
        else:
            raise ValueError(f"Error: Unable to parse WeTransfer downloads URL: {parsed_url}")

    def _is_short_url(self) -> bool:
        return "we.tl/" in self.link

    def __init__(
        self,
        link: str,
        password: str | None = None,
        headers: Dict[str, str] | None = None,
    ):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid WeTransfer URL provided")
        self.link = link
        self.password = password
        self.headers = headers or {}

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        """
        mode: "info" (only info_steps), "fetch" (full fetch_steps)
        """

        class WeTransferFetcher(BaseFetcher):
            NAME = "WeTransfer"
            BASE_URL = "https://wetransfer.com"

            def log_fetch_state(self, metadata: dict, downloads_count: int):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filename": metadata.get("recommended_filename"),
                            "downloads_count": downloads_count,
                            "upload_date": metadata.get("uploaded_at"),
                            "expires_at": metadata.get("expires_at"),
                            "size": metadata.get("size"),
                            "state": metadata.get("state"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def parse_link_transfer_id(self, link: str):
                return WeTransferFetcherFactory._parse_downloads_url(link).get("transfer_id")

            def parse_link_security_hash(self, link: str):
                return WeTransferFetcherFactory._parse_downloads_url(link).get("security_hash")

            def parse_link_recipient_id(self, link: str):
                return WeTransferFetcherFactory._parse_downloads_url(link).get("recipient_id")

            def get_url(self, response: ResponseObject) -> str:
                return response.url

            def parse_metadata(self, response: ResponseObject) -> dict:
                return {
                    "state": response.json.get("state"),
                    "uploaded_at": response.json.get("uploaded_at"),
                    "expires_at": response.json.get("expires_at"),
                    "deleted_at": response.json.get("deleted_at"),
                    "download_limit": response.json.get("download_limit"),
                    "number_of_downloads": response.json.get("number_of_downloads"),
                    "recommended_filename": response.json.get("recommended_filename"),
                    "size": response.json.get("size"),
                }

            def _is_within_download_limit(self, status: dict) -> bool:
                download_limit = status.get("download_limit")
                if download_limit is None:
                    return True
                return status["number_of_downloads"] < download_limit

            def _is_expired(self, status: dict) -> bool:
                expiry_date = datetime.datetime.fromisoformat(status["expires_at"].replace("Z", "+00:00"))
                current_date = datetime.datetime.now(datetime.timezone.utc)
                return current_date > expiry_date

            def is_downloadable(self, status: dict) -> bool:
                return (
                    status.get("state") == "downloadable"
                    and status.get("deleted_at") is None
                    and self._is_within_download_limit(status)
                    and not self._is_expired(status)
                )

            def extract_downloads_count(self, metadata: dict) -> int:
                return metadata.get("number_of_downloads") or 0

            @staticmethod
            def build_download_payload(security_hash: str, recipient_id: str = None) -> dict:
                payload = {"intent": "entire_transfer", "security_hash": security_hash}
                if recipient_id:
                    payload["recipient_id"] = recipient_id
                # password support (if needed)
                return payload

            @staticmethod
            def build_metadata_payload(security_hash: str):
                return {"security_hash": security_hash}

            info_steps = []
            fetch_steps = []
            if self._is_short_url():
                info_steps = [
                    Step(
                        RunRequest("resolve short url")
                        .get(self.link)
                        .headers(**self.headers)
                        .teardown_callback("get_url(response)", assign="download_url")
                        .validate()
                        .assert_equal("status_code", 200)
                    )
                ]
            info_steps.extend(
                [
                    Step(
                        RunRequest("check transfer status")
                        .variables(
                            download_url=(lambda v: v["download_url"]) if self._is_short_url() else self.link,
                        )
                        .setup_hook(lambda v: v.update({
                            "transfer_id": v["self"].parse_link_transfer_id(v["download_url"]),
                            "security_hash": v["self"].parse_link_security_hash(v["download_url"]),
                            "recipient_id": v["self"].parse_link_recipient_id(v["download_url"]),
                        }))
                        .post(lambda v: f"/api/v4/transfers/{v['transfer_id']}/prepare-download")
                        .headers(**{**self.headers, "x-requested-with": "XMLHttpRequest"})
                        .json(lambda v: v["self"].build_download_payload(v["security_hash"], v.get("recipient_id")))
                        .teardown_callback("parse_metadata(response)", assign="metadata")
                        .teardown_callback("extract_downloads_count(metadata)", assign="downloads_count")
                        .teardown_callback("is_downloadable(metadata)", assign="downloadable")
                        .teardown_callback("log_fetch_state(metadata, downloads_count)")
                        .validate()
                        .assert_equal("status_code", 200)
                        .assert_equal("downloadable", True)
                    ),
                ]
            )
            fetch_steps = info_steps.copy()
            fetch_steps.extend(
                [
                    # NOTE: This step increases the downloads counter! Find how to bypass it
                    OptionalStep(
                        RunRequest("create direct link")
                        .variables(
                            download_url=(lambda v: v["download_url"]) if self._is_short_url() else self.link,
                        )
                        .setup_hook(lambda v: v.update({
                            "transfer_id": v["self"].parse_link_transfer_id(v["download_url"]),
                            "security_hash": v["self"].parse_link_security_hash(v["download_url"]),
                            "recipient_id": v["self"].parse_link_recipient_id(v["download_url"]),
                        }))
                        .post(lambda v: f"/api/v4/transfers/{v['transfer_id']}/download")
                        .headers(**{**self.headers, "x-requested-with": "XMLHttpRequest"})
                        .json(lambda v: v["self"].build_download_payload(v["security_hash"], v.get("recipient_id")))
                        .teardown_callback("response.body['direct_link']", assign="direct_link")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                    OptionalStep(
                        RunRequest("download")
                        .get("$direct_link")
                        .headers(**self.headers)
                        .teardown_callback("save_file(response, metadata)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                ]
            )
            steps = info_steps if mode == Mode.INFO else fetch_steps

        return WeTransferFetcher()
