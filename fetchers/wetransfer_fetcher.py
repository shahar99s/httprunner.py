import re
import os
import datetime
from typing import Dict
from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import Step, OptionalStep
from urllib.parse import urlparse


class WeTransferFetcherFactory:
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

    def __init__(self, link: str, password: str | None = None, headers: Dict[str, str] | None = None):
        self.link = link
        self.password = password
        self.headers = headers or {}

        if not (
            "wetransfer.com/downloads" in link
            or "we.tl/" in link
        ):
            raise ValueError("Error: No valid WeTransfer URL provided")


    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        """
        mode: "info" (only info_steps), "fetch" (full fetch_steps)
        """
        class WeTransferFetcher(BaseFetcher):
            NAME = "WeTransfer"
            BASE_URL = "https://wetransfer.com"

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

            def _is_within_download_limit(self, status: dict) -> bool:
                download_limit = status.get("download_limit")
                if download_limit is None:
                    return True
                return status["number_of_downloads"] < download_limit

            def _is_expired(self, status: dict) -> bool:
                expiry_date = datetime.datetime.fromisoformat(status["expires_at"].replace('Z', '+00:00'))
                current_date = datetime.datetime.now(datetime.timezone.utc)
                return current_date > expiry_date

            def is_downloadable(self, status: dict) -> bool:
                return status.get("state") == "downloadable" \
                    and status.get("deleted_at") is None \
                    and self._is_within_download_limit(status) \
                    and not self._is_expired(status)

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
                info_steps = [Step(
                    RunRequest("resolve short url")
                    .get(self.link)
                    .with_headers(**self.headers)
                    .teardown_hook("${get_url($response)}", "download_url")
                    .extract()
                    .with_jmespath("$download_url", "download_url")
                    .validate()
                    .assert_equal("status_code", 200)
                )]
            info_steps.extend([
                Step(
                    RunRequest("check transfer status")
                    .with_variables(
                        download_url="$download_url" if self._is_short_url() else self.link,
                        transfer_id="${parse_link_transfer_id($download_url)}",
                        security_hash="${parse_link_security_hash($download_url)}",
                        recipient_id="${parse_link_recipient_id($download_url)}",
                    )
                    .post("/api/v4/transfers/${transfer_id}/prepare-download")
                    .with_headers(**{**self.headers, "x-requested-with": "XMLHttpRequest"})
                    .with_json("${build_download_payload($security_hash, $recipient_id)}")
                    .teardown_hook("${parse_metadata($response)}", "metadata")
                    .teardown_hook("${extract_downloads_count($metadata)}", "downloads_count")
                    .teardown_hook("${is_downloadable($metadata)}", "downloadable")
                    .teardown_hook("${log_fetch_state($metadata, $downloads_count)}")
                    .extract()
                    .with_jmespath("$metadata", "metadata")
                    .with_jmespath("$downloads_count", "downloads_count")
                    .with_jmespath("$downloadable", "downloadable")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("$downloadable", True)
                ),
            ])
            fetch_steps = info_steps.copy()
            fetch_steps.extend([
                # NOTE: This step increases the downloads counter! Find how to bypass it
                OptionalStep(
                    RunRequest("create direct link")
                    .with_variables(
                        download_url="$download_url" if self._is_short_url() else self.link,
                        transfer_id="${parse_link_transfer_id($download_url)}",
                        security_hash="${parse_link_security_hash($download_url)}",
                        recipient_id="${parse_link_recipient_id($download_url)}",
                    )
                    .post("/api/v4/transfers/${transfer_id}/download")
                    .with_headers(**{**self.headers, "x-requested-with": "XMLHttpRequest"})
                    .with_json("${build_download_payload($security_hash, $recipient_id)}")
                    .extract()
                    .with_jmespath("body.direct_link", "direct_link")
                    .validate()
                    .assert_equal("status_code", 200)
                ).when(lambda step, vars: should_download(mode, vars.get("downloads_count"))),
                OptionalStep(
                    RunRequest("download")
                    .get("$direct_link")
                    .with_headers(**self.headers)
                    .teardown_hook("${save_file($response, $metadata)}")
                    .validate()
                    .assert_equal("status_code", 200)
                ).when(lambda step, vars: should_download(mode, vars.get("downloads_count")))
            ])
            teststeps = info_steps if mode == Mode.INFO else fetch_steps
        return WeTransferFetcher()
