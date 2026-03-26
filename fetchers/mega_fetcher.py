import base64
import json
import os
import re
import struct
from typing import Dict

from loguru import logger

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


def _a32_to_str(values) -> bytes:
    return struct.pack(f">{len(values)}I", *values)


def _str_to_a32(data: bytes):
    remainder = len(data) % 4
    if remainder:
        data += b"\0" * (4 - remainder)
    return struct.unpack(f">{len(data) // 4}I", data)


def _base64_url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _base64_to_a32(data: str):
    return _str_to_a32(_base64_url_decode(data))


def _decrypt_attr(attr: bytes, key):
    try:
        from Crypto.Cipher import AES
    except ImportError as exc:
        raise ImportError("Mega fetcher requires pycryptodome-compatible AES support at runtime.") from exc

    cipher = AES.new(_a32_to_str(key), AES.MODE_CBC, b"\0" * 16)
    decrypted = cipher.decrypt(attr).decode("latin-1").rstrip("\0")
    return json.loads(decrypted[4:]) if decrypted[:6] == 'MEGA{"' else False


class MegaFetcherFactory:
    """
    has download notification: No
    has downloads count: No
    note: Transfer.it isn't tested
    """

    URL_PATTERN = re.compile(
        r"https?://mega\.nz/(?:file/(?P<file_id>[A-Za-z0-9_-]+)#(?P<key>[A-Za-z0-9_-]+)|#!(?P<legacy_file_id>[A-Za-z0-9_-]+)!(?P<legacy_key>[A-Za-z0-9_-]+))"
    )

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        return bool(cls.URL_PATTERN.match(url))

    def __init__(self, link: str, headers: Dict[str, str] | None = None):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid Mega URL provided")
        self.link = link
        self.headers = headers or {}

        match = self.URL_PATTERN.match(link)
        self.file_id = match.group("file_id") or match.group("legacy_file_id")
        self.file_key = match.group("key") or match.group("legacy_key")

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        link = self.link
        headers = self.headers
        file_id = self.file_id
        public_file_key = self.file_key

        class MegaFetcher(BaseFetcher):
            NAME = "Mega"
            BASE_URL = "https://g.api.mega.co.nz"

            def log_fetch_state(self, metadata: dict, downloads_count: int):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filename": metadata.get("filename"),
                            "downloads_count": downloads_count,
                            "size": metadata.get("size"),
                            "url": metadata.get("url"),
                            "state": metadata.get("state"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def build_file_info_payload(self) -> list[dict]:
                return [{"a": "g", "g": 1, "p": file_id, "ssm": 1}]

            def extract_api_response(self, response: ResponseObject) -> dict:
                payload = response.json
                if isinstance(payload, list):
                    payload = payload[0]
                if isinstance(payload, int):
                    return {"error_code": payload}
                if not isinstance(payload, dict):
                    raise ValueError(f"Error: Unexpected Mega API payload: {payload}")
                return payload

            def _get_decrypted_file_key(self):
                decoded_file_key = _base64_to_a32(public_file_key)
                return (
                    decoded_file_key[0] ^ decoded_file_key[4],
                    decoded_file_key[1] ^ decoded_file_key[5],
                    decoded_file_key[2] ^ decoded_file_key[6],
                    decoded_file_key[3] ^ decoded_file_key[7],
                )

            def extract_filename(self, api_response: dict) -> str:
                if "at" not in api_response:
                    return f"{file_id}.bin"

                attrs = _decrypt_attr(
                    _base64_url_decode(api_response["at"]),
                    self._get_decrypted_file_key(),
                )
                if not attrs or not attrs.get("n"):
                    return f"{file_id}.bin"
                return attrs["n"]

            def extract_download_url(self, api_response: dict) -> str:
                return api_response.get("g")

            def extract_size(self, api_response: dict) -> int | None:
                return api_response.get("s")

            def default_downloads_count(self) -> int:
                return 1

            def is_available(self, api_response: dict) -> bool:
                return bool(
                    api_response.get("error_code") is None
                    and api_response.get("g")
                    and api_response.get("s") is not None
                )

            def extract_metadata(self, api_response: dict) -> dict:
                if api_response.get("error_code") is not None:
                    return {
                        "filename": f"{file_id}.bin",
                        "size": self.extract_size(api_response),
                        "url": link,
                        "state": "unavailable",
                        "error_code": api_response["error_code"],
                    }

                metadata = {
                    "filename": self.extract_filename(api_response),
                    "size": self.extract_size(api_response),
                    "url": link,
                    "state": "available" if self.is_available(api_response) else "unavailable",
                }
                return metadata

            def save_public_file(self, response: ResponseObject, fallback_filename: str) -> str:
                try:
                    from Crypto.Cipher import AES
                    from Crypto.Util import Counter
                except ImportError as exc:
                    raise ImportError("Mega fetcher requires pycryptodome-compatible AES support at runtime.") from exc

                parsed_file_key = _base64_to_a32(public_file_key)
                decrypted_key = self._get_decrypted_file_key()
                iv = parsed_file_key[4:6] + (0, 0)
                counter = Counter.new(128, initial_value=((iv[0] << 32) + iv[1]) << 64)
                decryptor = AES.new(_a32_to_str(decrypted_key), AES.MODE_CTR, counter=counter)
                decrypted_body = decryptor.decrypt(response.body)

                disposition = response.headers.get("Content-Disposition", "")
                resolved_name = fallback_filename
                if "filename=" in disposition:
                    resolved_name = disposition.split("filename=")[-1].strip('"')

                output_path = os.path.join(os.getcwd(), resolved_name)
                with open(output_path, "wb") as file_handle:
                    file_handle.write(decrypted_body)

                logger.success(
                    "[{}] downloaded file saved to {} ({} bytes)",
                    self.NAME,
                    output_path,
                    len(decrypted_body),
                )
                return output_path

            def __init__(self):
                super().__init__()
                info_steps = [
                    Step(
                        RunRequest("get file metadata")
                        .post("/cs")
                        .params(id=0)
                        .headers(**headers)
                        .json(self.build_file_info_payload)
                        .teardown_callback("extract_api_response(response)", assign="api_response")
                        .teardown_callback("extract_metadata(api_response)", assign="metadata")
                        .teardown_callback("extract_filename(api_response)", assign="filename")
                        .teardown_callback("extract_download_url(api_response)", assign="direct_link")
                        .teardown_callback("extract_size(api_response)", assign="size")
                        .teardown_callback("default_downloads_count()", assign="downloads_count")
                        .teardown_callback("is_available(api_response)", assign="available")
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
                            Step(
                                RunRequest("download")
                                .get("$direct_link")
                                .headers(**headers)
                                .teardown_callback("save_public_file(response, filename)")
                                .validate()
                                .assert_equal("status_code", 200)
                            )
                        ).when(lambda step, vars: should_download(mode, vars.get("downloads_count")))
                    ]
                )

                self.steps = info_steps if mode == Mode.INFO else fetch_steps

        return MegaFetcher()
