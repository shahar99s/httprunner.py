import base64
import re
from html import unescape
from typing import Dict
from urllib.parse import parse_qs, quote, urlparse

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, should_download
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class SmashFetcherFactory:
    """
    has download notification: Determined from transfer.notification
    has downloads count: No
    note: Tested for free users only.
          Download is skipped when transfer has download notifications enabled.
    """

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        normalized_path = parsed.path.rstrip("/")
        return "fromsmash.com" in parsed.netloc and normalized_path not in {"", "/"}

    def __init__(self_factory, link: str, headers: Dict[str, str] | None = None):
        if not self_factory.is_relevant_url(link):
            raise ValueError("Error: No valid Smash URL provided")
        self_factory.link = link
        self_factory.headers = headers or {}

        parsed = urlparse(link)
        normalized_path = parsed.path.rstrip("/")

        query_params = parse_qs(parsed.query)
        self_factory.identity_token = query_params.get("e", [None])[0]
        self_factory.transfer_id = normalized_path.split("/")[-1]
        self_factory.target_id = f"{parsed.netloc}{normalized_path}"
        self_factory.encoded_target_id = quote(self_factory.target_id, safe="")

    def create(self_factory, mode: Mode = Mode.FETCH) -> BaseFetcher:
        class SmashFetcher(BaseFetcher):
            NAME = "Smash"
            BASE_URL = "https://fromsmash.com"

            def log_fetch_state(
                self,
                transfer_metadata: dict,
                files_metadata: dict,
                downloads_count: int | None,
            ):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filenames": list(files_metadata.keys()),
                            "downloads_count": downloads_count,
                            "transfer_size": transfer_metadata["transfer_size"],
                            "file_count": transfer_metadata.get("file_count"),
                            "state": transfer_metadata.get("state"),
                            "download_url": transfer_metadata.get("download_url"),
                            "has_download_notification": transfer_metadata.get("has_download_notification"),
                            "notification_safe": transfer_metadata.get("notification_safe"),
                            "notification_channels": transfer_metadata.get("notification_channels"),
                        },
                        "details": {
                            "transfer_metadata": transfer_metadata,
                            "files_metadata": files_metadata,
                        },
                    },
                )

            def _extract_page_text(self, response: ResponseObject) -> str:
                body = response.body
                if isinstance(body, bytes):
                    return body.decode("utf-8", errors="ignore")
                return str(body)

            def extract_region(self, response: ResponseObject) -> str:
                region = (response.json or {}).get("region")
                if not region:
                    raise ValueError("Error: Smash discovery region not found")
                return region

            def extract_account_token(self, response: ResponseObject) -> str:
                payload = response.json or {}
                account = payload.get("account") or payload.get("identity") or payload
                token = (account.get("token") or {}).get("token")
                if not token:
                    raise ValueError("Error: Smash anonymous account token not found")
                return token

            def extract_target(self, response: ResponseObject) -> dict:
                target = (response.json or {}).get("target") or {}
                if not target.get("target"):
                    raise ValueError("Error: Smash target resolution failed")
                return target

            def extract_transfer_region(self, target: dict) -> str:
                region = (target or {}).get("region")
                if not region:
                    raise ValueError("Error: Smash transfer region not found")
                return region

            def extract_transfer_id(self, target: dict) -> str:
                resolved_transfer_id = (target or {}).get("target")
                if not resolved_transfer_id:
                    raise ValueError("Error: Smash transfer id not found")
                return resolved_transfer_id

            def decode_identity_email(self, encoded_identity: str | None) -> str | None:
                if not encoded_identity:
                    return None

                normalized = encoded_identity.strip()
                padding = (-len(normalized)) % 4
                normalized = normalized + ("=" * padding)
                try:
                    return base64.b64decode(normalized).decode("utf-8")
                except Exception:
                    return None

            def extract_notification_channels(self, transfer: dict) -> list[str]:
                """Return list of enabled notification channel names."""
                notification = transfer.get("notification") or {}
                channels: list[str] = []
                for channel, config in notification.items():
                    if isinstance(config, dict) and config.get("enabled"):
                        channels.append(channel)
                return channels

            def extract_metadata(self, response: ResponseObject, target: dict) -> dict:
                transfer = response.json["transfer"]
                notification = transfer.get("notification")
                download_url = transfer.get("download")
                notification_channels = self.extract_notification_channels(transfer)
                has_download_notification = "download" in notification_channels
                return {
                    "transfer_id": target.get("target") or self_factory.transfer_id,
                    "transfer_name": transfer.get("title"),
                    "file_count": transfer.get("filesNumber"),
                    "region": target.get("region"),
                    "download_url": download_url,
                    "availability_start_date": transfer.get("availabilityStartDate"),
                    "availability_end_date": transfer.get("availabilityEndDate"),
                    "availability_duration": transfer.get("availabilityDuration"),
                    "created": transfer.get("created"),
                    "notification_channels": notification_channels,
                    "has_download_notification": has_download_notification,
                    "has_any_notification": bool(notification_channels),
                    "notification_safe": not notification_channels,
                    "identity_email": self.decode_identity_email(self_factory.identity_token),
                    "state": "available" if download_url else "unavailable",
                    "transfer_size": transfer.get("size"),
                    "url": self_factory.link,
                }

            def extract_files_metadata(self, response: ResponseObject, target: dict) -> dict:
                files = response.json["files"]
                return {file["name"]: {"size": file["size"]} for file in files}

            def extract_filename(self, files_metadata: dict) -> str:
                # TODO: Support multiple files in a transfer
                return list(files_metadata.keys())[0]

            def default_downloads_count(self) -> int | None:
                return None

            def extract_download_url(self, metadata: dict) -> str:
                download_url = metadata.get("download_url")
                if not download_url:
                    raise ValueError("Error: Smash download URL not found")
                return download_url

            def is_available(self, metadata: dict) -> bool:
                return metadata.get("state") == "available" and bool(metadata.get("download_url"))

            def __init__(self):
                super().__init__()
                info_steps = [
                    Step(
                        RunRequest("discover Smash public service endpoint")
                        .get("https://discovery.fromsmash.co/namespace/public/services")
                        .headers(**self_factory.headers)
                        .params(version="10-2019")
                        .teardown_callback("extract_region(response)", assign="region")
                        .validate()
                        .assert_equal("status_code", 200)
                    ),
                    Step(
                        RunRequest("create anonymous Smash account")
                        .post(lambda v: f"https://iam.{v['region']}.fromsmash.co/account")
                        .headers(**self_factory.headers)
                        .json({})
                        .teardown_callback("extract_account_token(response)", assign="account_token")
                        .validate()
                        .assert_equal("status_code", 201)
                    ),
                    Step(
                        RunRequest("resolve Smash transfer target")
                        .get(f"https://link.fromsmash.co/target/{self_factory.encoded_target_id}")
                        .headers(**self_factory.headers, Authorization="Bearer $account_token")
                        .params(version="10-2019")
                        .teardown_callback("extract_target(response)", assign="target")
                        .teardown_callback("extract_transfer_region(target)", assign="transfer_region")
                        .teardown_callback("extract_transfer_id(target)", assign="public_transfer_id")
                        .validate()
                        .assert_equal("status_code", 200)
                    ),
                    Step(
                        RunRequest("load Smash transfer preview")
                        .get(lambda v: f"https://transfer.{v['transfer_region']}.fromsmash.co/transfer/{v['public_transfer_id']}/preview")
                        .headers(**self_factory.headers, Authorization="Bearer $account_token")
                        .params(version="01-2024", e=self_factory.identity_token)
                        .teardown_callback("extract_metadata(response, target)", assign="transfer_metadata")
                        .teardown_callback("default_downloads_count()", assign="downloads_count")
                        .teardown_callback("extract_download_url(transfer_metadata)", assign="download_url")
                        .teardown_callback("is_available(transfer_metadata)", assign="available")
                        .validate()
                        .assert_equal("status_code", 200)
                    ),
                    Step(
                        RunRequest("load Smash transfer files preview")
                        .get(lambda v: f"https://transfer.{v['transfer_region']}.fromsmash.co/transfer/{v['public_transfer_id']}/files/preview")
                        .headers(**self_factory.headers, Authorization="Bearer $account_token")
                        .params(version="01-2024", e=self_factory.identity_token)
                        .teardown_callback("extract_files_metadata(response, target)", assign="files_metadata")
                        .teardown_callback("extract_filename(files_metadata)", assign="filename")
                        .teardown_callback("log_fetch_state(transfer_metadata, files_metadata, downloads_count)")
                        .validate()
                        .assert_equal("status_code", 200)
                        .assert_equal("available", True)
                    ),
                ]

                fetch_steps = info_steps.copy()
                fetch_steps.extend(
                    [
                        OptionalStep(
                            Step(
                                RunRequest("download")
                                .get("$download_url")
                                .headers(**self_factory.headers)
                                .teardown_callback("save_file(response, filename)")
                                .validate()
                                .assert_equal("status_code", 200)
                            )
                        ).when(
                            lambda step, vars: should_download(
                                mode,
                                # Only allow download when no notifications are configured.
                                # notification_safe is True when no notification channels are enabled.
                                1 if vars.get("transfer_metadata", {}).get("notification_safe", False) else None,
                            )
                        )
                    ]
                )

                self.steps = info_steps if mode == Mode.INFO else fetch_steps

        return SmashFetcher()
