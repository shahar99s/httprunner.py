import os
from typing import Dict
from urllib.parse import urlparse

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step

class FilemailFetcherFactory:
    def __init__(
        self,
        link: str,
        password: str | None = None,
        headers: Dict[str, str] | None = None,
    ):
        self.link = link
        self.password = password
        self.headers = headers or {}

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        link = self.link
        password = self.password
        request_headers = {
            **self.headers,
            "x-api-source": "WebApp",
            "x-api-version": "2.0",
        }

        class FilemailFetcher(BaseFetcher):
            NAME = "Filemail"
            BASE_URL = "https://api.filemail.com"

            def log_fetch_state(
                self,
                metadata: dict,
                downloads_count=None,
                filename=None,
                primary_file=None,
                transfer=None,
            ):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filename": filename or (primary_file or {}).get("filename"),
                            "downloads_count": downloads_count,
                            "uploader_email": metadata.get("email") or metadata.get("from"),
                            "upload_date": transfer.get("created") if isinstance(transfer, dict) else None,
                            "expires_at": transfer.get("expires") if isinstance(transfer, dict) else None,
                            "size": metadata.get("size") or (primary_file or {}).get("filesize"),
                            "url": metadata.get("url"),
                        },
                        "details": {
                            "metadata": metadata,
                            "primary_file": primary_file,
                            "transfer": transfer,
                        },
                    },
                )

            def extract_downloads_count(self, metadata: dict) -> int:
                return metadata.get("number_of_downloads") or 0

            def build_lookup_payload(self) -> dict:
                payload = {"url": link}
                if password:
                    payload["password"] = password
                return payload

            def extract_data(self, response: ResponseObject) -> dict:
                data = response.json.get("data")
                if not data:
                    raise ValueError("Error: Filemail transfer data not found")
                return data

            def extract_metadata(self, response: ResponseObject) -> dict:
                data = self.extract_data(response)
                return {
                    "id": data.get("id"),
                    "url": data.get("url"),
                    "status": data.get("status"),
                    "subject": data.get("subject"),
                    "message": data.get("message"),
                    "size": data.get("size"),
                    "from": data.get("from"),
                    "number_of_files": data.get("numberoffiles"),
                    "number_of_downloads": data.get("numberofdownloads"),
                    "is_expired": data.get("isexpired"),
                    "password_protected": data.get("passwordprotected"),
                    "block_downloads": data.get("blockdownloads"),
                    "infected": data.get("infected"),
                    "compressed_file_url": data.get("compressedfileurl"),
                }

            def extract_primary_file(self, response: ResponseObject) -> dict:
                data = self.extract_data(response)
                files = data.get("files") or []
                if not files:
                    raise ValueError("Error: Filemail files metadata not found")
                return files[0]

            def extract_filename(self, response: ResponseObject) -> str:
                data = self.extract_data(response)
                number_of_files = data.get("numberoffiles") or 0
                if number_of_files > 1 and data.get("compressedfileurl"):
                    subject = data.get("subject") or data.get("id") or "filemail-transfer"
                    return f"{subject}.zip"

                primary_file = self.extract_primary_file(response)
                return primary_file.get("filename") or f"{data.get('id')}.bin"

            def extract_direct_link(self, response: ResponseObject) -> str:
                data = self.extract_data(response)
                number_of_files = data.get("numberoffiles") or 0

                if number_of_files > 1 and data.get("compressedfileurl"):
                    base_url = data["compressedfileurl"]
                else:
                    primary_file = self.extract_primary_file(response)
                    base_url = primary_file.get("downloadurl")

                if not base_url:
                    raise ValueError("Error: Filemail direct download URL not found")

                separator = "&" if "?" in base_url else "?"
                return f"{base_url}{separator}skipcheck=true&skipreg=true"

            def is_available(self, response: ResponseObject) -> bool:
                data = self.extract_data(response)
                return (
                    data.get("status") == "STATUS_COMPLETE"
                    and data.get("isexpired") is False
                    and data.get("blockdownloads") is False
                )

            info_steps = [
                Step(
                    RunRequest("resolve transfer")
                    .post("/transfer/find")
                    .with_headers(**request_headers)
                    .with_json("${build_lookup_payload()}")
                    .teardown_hook("${extract_data($response)}", "transfer")
                    .teardown_hook("${extract_metadata($response)}", "metadata")
                    .teardown_hook("${extract_primary_file($response)}", "primary_file")
                    .teardown_hook("${extract_filename($response)}", "filename")
                    .teardown_hook("${extract_direct_link($response)}", "direct_link")
                    .teardown_hook("${is_available($response)}", "available")
                    .teardown_hook("${extract_downloads_count($metadata)}", "downloads_count")
                    .teardown_hook("${log_fetch_state($metadata, $downloads_count, $filename, $primary_file, $transfer)}")
                    .extract()
                    .with_jmespath("$transfer", "transfer")
                    .with_jmespath("$metadata", "metadata")
                    .with_jmespath("$downloads_count", "downloads_count")
                    .with_jmespath("$primary_file", "primary_file")
                    .with_jmespath("$filename", "filename")
                    .with_jmespath("$direct_link", "direct_link")
                    .with_jmespath("$available", "available")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("$available", True)
                )
            ]
            fetch_steps = info_steps.copy()
            fetch_steps.extend([
                OptionalStep(
                    RunRequest("download")
                    .get("$direct_link")
                    .with_headers(**self.headers)
                    .teardown_hook("${save_file($response, $filename)}")
                    .validate()
                    .assert_equal("status_code", 200)
                ).when(lambda step, vars: should_download(mode, vars.get("downloads_count")))
            ])

            teststeps = info_steps if mode == Mode.INFO else fetch_steps

        return FilemailFetcher()