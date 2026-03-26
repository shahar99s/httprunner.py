import io
import os
import re
import zipfile
from typing import Dict
from urllib.parse import urlparse

from loguru import logger

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class TransferXLFetcherFactory:
    """
    has download notification: Yes, but only for the first download
    has downloads count: Yes
    """

    URL_PATTERN = re.compile(r"/download/([0-9A-Fa-f]{2}[a-zA-Z0-9]+)")

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        return "transferxl.com" in parsed.netloc and bool(cls.URL_PATTERN.search(parsed.path))

    def __init__(self, link: str, headers: Dict[str, str] | None = None):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid TransferXL URL provided")
        self.link = link
        self.headers = headers or {}

        parsed = urlparse(link)
        self.transfer_id = self.URL_PATTERN.search(parsed.path).group(1)

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        link = self.link
        transfer_id = self.transfer_id
        request_headers = self.headers

        class TransferXLFetcher(BaseFetcher):
            NAME = "TransferXL"
            BASE_URL = "https://api.transferxl.com/api/v2"

            def log_fetch_state(self, metadata: dict, downloads_count: int | None):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "transfer_id": transfer_id,
                            "filename": metadata.get("filename"),
                            "file_count": metadata.get("file_count"),
                            "size": metadata.get("size"),
                            "from_email": metadata.get("from_email"),
                            "to_email": metadata.get("to_email"),
                            "available_until": metadata.get("available_until"),
                            "downloads_count": downloads_count,
                            "state": metadata.get("state"),
                            "download_url": metadata.get("download_url"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def extract_metadata(self, response: ResponseObject) -> dict:
                data = response.json or {}
                files = data.get("files") or []
                primary_file = files[0] if files else {}
                status = data.get("status")
                result = data.get("result")

                return {
                    "id": data.get("id") or transfer_id,
                    "transfer_id": data.get("id") or transfer_id,
                    "share_url": data.get("shareUrl") or link,
                    "region": data.get("region"),
                    "download_url": data.get("url"),
                    "transfer": data.get("transfer"),
                    "message": data.get("message"),
                    "file_count": data.get("fileCount") or len(files),
                    "size": data.get("size"),
                    "from_email": data.get("from"),
                    "to_email": data.get("to_email"),
                    "status": status,
                    "type": data.get("type"),
                    "created_at": data.get("createdAt"),
                    "encrypted": data.get("encrypted"),
                    "is_pending": data.get("isPending"),
                    "available_until": data.get("availableUntil"),
                    "download_count": data.get("downloadCount"),
                    "files": files,
                    "filename": primary_file.get("name") or f"TransferXL-{transfer_id}.zip",
                    "primary_file": primary_file,
                    "state": "available" if result == "ok" and status == "AVAILABLE" else "unavailable",
                    "url": link,
                }

            def extract_downloads_count(self, metadata: dict) -> int | None:
                return metadata.get("download_count")

            def extract_filename(self, metadata: dict) -> str:
                return metadata.get("filename") or f"TransferXL-{transfer_id}.zip"

            def extract_direct_link(self, metadata: dict, response: ResponseObject) -> str:
                token = (response.json or {}).get("downloadToken")
                base_url = metadata.get("download_url")
                if not token or not base_url:
                    raise ValueError("Error: TransferXL download token not found")
                return f"{base_url}?downloadToken={token}"

            def is_available(self, metadata: dict) -> bool:
                return metadata.get("state") == "available"

            def save_file(self, response: object, fallback_filename: str) -> str:
                """Save file, extracting from ZIP if TransferXL wraps it."""
                path = super().save_file(response, fallback_filename)
                if not zipfile.is_zipfile(path):
                    return path
                with zipfile.ZipFile(path) as zf:
                    names = zf.namelist()
                    if len(names) != 1:
                        return path
                    inner_name = names[0]
                    inner_bytes = zf.read(inner_name)
                dest = os.path.join(os.path.dirname(path), os.path.basename(inner_name))
                with open(dest, "wb") as fh:
                    fh.write(inner_bytes)
                os.remove(path)
                logger.success(
                    "[{}] extracted {} from ZIP ({} bytes)",
                    self.NAME,
                    dest,
                    len(inner_bytes),
                )
                return dest

            info_steps = [
                Step(
                    RunRequest("load transfer metadata")
                    .get("/history/download")
                    .headers(**request_headers)
                    .params(shortUrl=transfer_id, perFilePendingStatus="true", language="en")
                    .teardown_callback("extract_metadata(response)", assign="metadata")
                    .teardown_callback("extract_filename(metadata)", assign="filename")
                    .teardown_callback("extract_downloads_count(metadata)", assign="downloads_count")
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
                        RunRequest("create download token")
                        .post("/download/getToken")
                        .headers(**request_headers)
                        .json({"shortUrl": transfer_id})
                        .teardown_callback("extract_direct_link(metadata, response)", assign="direct_link")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: (mode != Mode.INFO and vars.get("available") is True)),
                    OptionalStep(
                        RunRequest("download")
                        .get("$direct_link")
                        .headers(**request_headers)
                        .teardown_callback("save_file(response, filename)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: (mode != Mode.INFO and vars.get("available") is True)),
                ]
            )

            steps = info_steps if mode == Mode.INFO else fetch_steps

        return TransferXLFetcher()
