import base64
import json as json_mod
import re
from typing import Dict
from urllib.parse import parse_qs, urlparse

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class SendAnywhereFetcherFactory:
    """
    has download notification: No (web downloads don't trigger sender notification)
    has downloads count: Yes (download_count from key data API)
    """

    # Pattern to extract key from send-anywhere download paths
    KEY_PATTERN = re.compile(r"^/web/(?:downloads|s)/([A-Za-z0-9]+)")

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        if "send-anywhere.com" in parsed.netloc:
            return bool(cls.KEY_PATTERN.search(parsed.path))
        if parsed.netloc == "sendanywhe.re" and parsed.path not in {"", "/"}:
            return True
        if parsed.netloc == "mandrillapp.com" and "sendanywhe.re" in url:
            return cls._extract_key_from_tracking(url) is not None
        return False

    def __init__(self, link: str, headers: Dict[str, str] | None = None):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid Send Anywhere URL provided")
        self.link = link
        self.headers = headers or {}

        parsed = urlparse(link)

        # Direct send-anywhere.com link
        if "send-anywhere.com" in parsed.netloc:
            m = self.KEY_PATTERN.search(parsed.path)
            if m:
                self.key = m.group(1)
                self.resolved_url = f"https://send-anywhere.com/web/downloads/{self.key}"
                return

        # Short link: sendanywhe.re/{KEY}
        if parsed.netloc == "sendanywhe.re" and parsed.path not in {"", "/"}:
            self.key = parsed.path.strip("/")
            self.resolved_url = f"https://send-anywhere.com/web/downloads/{self.key}"
            return

        # Mandrillapp tracking link: decode base64 payload to find real URL
        if parsed.netloc == "mandrillapp.com" and "sendanywhe.re" in link:
            key = self._extract_key_from_tracking(link)
            if key:
                self.key = key
                self.resolved_url = f"https://send-anywhere.com/web/downloads/{self.key}"
                return

    @staticmethod
    def _extract_key_from_tracking(link: str) -> str | None:
        """Extract Send Anywhere key from mandrillapp tracking link."""
        parsed = urlparse(link)
        qs = parse_qs(parsed.query)
        p_values = qs.get("p", [])
        if not p_values:
            return None
        try:
            raw = p_values[0]
            # Fix missing base64 padding
            raw += "=" * (-len(raw) % 4)
            payload = json_mod.loads(base64.b64decode(raw))
            inner = json_mod.loads(payload.get("p", "{}"))
            url = inner.get("url", "")
            # url looks like "http://sendanywhe.re/6PH9Y9DT"
            return urlparse(url).path.strip("/") or None
        except Exception:
            return None

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        key = self.key
        resolved_url = self.resolved_url
        request_headers = self.headers

        class SendAnyWhereFetcher(BaseFetcher):
            NAME = "SendAnywhere"
            BASE_URL = "https://send-anywhere.com"

            def log_fetch_state(self, metadata: dict, downloads_count: int | None):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "key": key,
                            "file_count": metadata.get("file_count"),
                            "total_size": metadata.get("total_size"),
                            "downloads_count": downloads_count,
                            "state": metadata.get("state"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def extract_key_data(self, response: ResponseObject) -> dict:
                """Extract key metadata from /web/key/data response."""
                data = response.json or {}
                is_relay = isinstance(data.get("key"), str) and isinstance(data.get("server"), str)
                files = data.get("files") or []
                return {
                    "key": data.get("key", key),
                    "server": data.get("server"),
                    "link": data.get("link"),
                    "device_id": data.get("device_id"),
                    "created_time": data.get("created_time"),
                    "expires_time": data.get("expires_time"),
                    "download_count": data.get("download_count"),
                    "use_storage": data.get("use_storage"),
                    "is_relay": is_relay,
                    "files": files,
                    "file_uuids": [f.get("file_uuid") for f in files if f.get("file_uuid")],
                    "state": "available",
                    "url": resolved_url,
                }

            def extract_metadata(self, key_data: dict) -> dict:
                files = key_data.get("files") or []
                return {
                    "key": key_data.get("key", key),
                    "file_count": len(files) or None,
                    "total_size": None,
                    "downloads_count": key_data.get("download_count"),
                    "state": key_data.get("state", "available"),
                    "url": resolved_url,
                    "is_relay": key_data.get("is_relay"),
                }

            def extract_filename(self, key_data: dict) -> str:
                files = key_data.get("files") or []
                if files:
                    return files[0].get("file_path") or f"SendAnywhere-{key}"
                return f"SendAnywhere-{key}"

            def extract_file_uuids(self, key_data: dict) -> list:
                return key_data.get("file_uuids") or []

            def extract_downloads_count(self, key_data: dict) -> int | None:
                return key_data.get("download_count")

            def is_relay_key(self, key_data: dict) -> bool:
                return key_data.get("is_relay", False)

            def extract_weblink(self, response: ResponseObject) -> str:
                """Extract weblink (direct download URL) from /web/key/search response."""
                data = response.json or {}
                weblink = data.get("weblink", "")
                if not weblink:
                    raise ValueError("Error: No weblink in search response")
                return weblink

            def extract_s3_secret(self, response: ResponseObject) -> str:
                data = response.json or {}
                secret = data.get("secret_key", "")
                if not secret:
                    raise ValueError("Error: No secret_key in prepare response")
                return secret

            def extract_s3_download_url(self, response: ResponseObject) -> str:
                data = response.json or []
                if isinstance(data, list) and data:
                    return data[0].get("url", "")
                raise ValueError("Error: No download URL in response")

            info_steps = [
                Step(
                    RunRequest("register device")
                    .post("/web/device")
                    .json(
                        {
                            "os_type": "web",
                            "manufacturer": "Windows",
                            "model_number": "Chrome",
                            "app_version": "1.0.0",
                            "os_version": "10",
                            "device_language": "en-US",
                        }
                    )
                    .validate()
                    .assert_equal("status_code", 200)
                ),
                Step(
                    RunRequest("get key data")
                    .get(f"/web/key/data/{key}")
                    .params(includeFileList="true")
                    .teardown_callback("extract_key_data(response)", assign="key_data")
                    .teardown_callback("extract_metadata(key_data)", assign="metadata")
                    .teardown_callback("extract_downloads_count(key_data)", assign="downloads_count")
                    .teardown_callback("is_relay_key(key_data)", assign="is_relay")
                    .teardown_callback("extract_filename(key_data)", assign="filename")
                    .teardown_callback("extract_file_uuids(key_data)", assign="file_uuids")
                    .teardown_callback("log_fetch_state(metadata, downloads_count)")
                    .validate()
                    .assert_equal("status_code", 200)
                ),
            ]

            fetch_steps = info_steps.copy()
            fetch_steps.extend(
                [
                    # Relay key path: get weblink via search
                    OptionalStep(
                        RunRequest("get download link")
                        .post(f"/web/key/search/{key}")
                        .json({})
                        .teardown_callback("extract_weblink(response)", assign="download_url")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: vars.get("is_relay") is True),
                    # S3 key path: prepare download
                    OptionalStep(
                        RunRequest("prepare download")
                        .post(f"/web/key/download/prepare/{key}")
                        .json(lambda v: {"files": v["file_uuids"]})
                        .teardown_callback("extract_s3_secret(response)", assign="secret_key")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: vars.get("is_relay") is False),
                    # S3 key path: get download URL
                    OptionalStep(
                        RunRequest("get download URL")
                        .post(f"/web/key/download/url/{key}")
                        .json(lambda v: {"files": v["file_uuids"], "secret_key": v["secret_key"]})
                        .teardown_callback("extract_s3_download_url(response)", assign="download_url")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: vars.get("is_relay") is False),
                    # Download file (both paths)
                    OptionalStep(
                        RunRequest("download file")
                        .get("$download_url")
                        .teardown_callback("save_file(response, filename)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(lambda step, vars: vars.get("download_url") is not None),
                ]
            )

            steps = info_steps if mode == Mode.INFO else fetch_steps

        return SendAnyWhereFetcher()
