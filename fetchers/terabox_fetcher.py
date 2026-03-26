import datetime
import json
import os
import re
from http.cookies import SimpleCookie
from typing import Dict
from urllib.parse import parse_qs, urlparse

from loguru import logger

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode
from httprunner import RunRequest
from httprunner.response import ResponseObject
from httprunner.step import OptionalStep, Step


class TeraBoxFetcherFactory:
    """
    has download notification: No
    has downloads count: No
    """

    VALID_HOSTS = {
        "www.terabox.com",
        "terabox.com",
        "1024terabox.com",
        "www.terabox.app",
        "terabox.app",
        "1024tera.com",
    }

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc in cls.VALID_HOSTS and parsed.path.startswith("/s/")

    def __init__(self, link: str, headers: Dict[str, str] | None = None):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid TeraBox URL provided")
        self.link = link
        self.headers = headers or {}

        parsed = urlparse(link)

        self.shorturl = parsed.path.split("/s/")[1].rstrip("/")
        self.surl = self.shorturl[1:] if self.shorturl.startswith("1") else self.shorturl

    def create(self, mode: Mode = Mode.FETCH) -> BaseFetcher:
        surl = self.surl
        shorturl = self.shorturl
        link = self.link
        request_headers = dict(self.headers)
        auth_cookie = (
            request_headers.get("Cookie") or os.getenv("TERABOX_COOKIE", "") or os.getenv("TERABOX_COOKIE_HEADER", "")
        ).strip()
        if not auth_cookie:
            ndus = os.getenv("TERABOX_NDUS", "").strip()
            if ndus:
                auth_cookie = f"ndus={ndus}"
        if auth_cookie:
            request_headers["Cookie"] = auth_cookie

        raw_gateway_url = (
            os.getenv("TERABOX_GATEWAY_API2_URL")
            or os.getenv("TERABOX_GATEWAY_URL")
            or os.getenv("TERABOX_WORKER_URL")
            or ""
        ).strip()
        proxy_mode = "disabled"
        proxy_request_url = ""
        if raw_gateway_url:
            normalized_gateway_url = raw_gateway_url.rstrip("/")
            if os.getenv("TERABOX_GATEWAY_API2_URL"):
                proxy_mode = "api2"
                proxy_request_url = normalized_gateway_url
            elif "workers.dev" in normalized_gateway_url or os.getenv("TERABOX_WORKER_URL"):
                proxy_mode = "worker"
                proxy_request_url = normalized_gateway_url or raw_gateway_url
            else:
                proxy_mode = "api2"
                proxy_request_url = (
                    normalized_gateway_url
                    if normalized_gateway_url.endswith("/api2")
                    else f"{normalized_gateway_url}/api2"
                )
        share_page_path = f"/sharing/link?surl={surl}"
        sharedownload_headers = dict(request_headers)
        sharedownload_headers.setdefault("Referer", f"https://www.1024tera.com{share_page_path}")
        download_headers = dict(request_headers)
        download_headers.setdefault("Referer", f"https://www.1024tera.com{share_page_path}")
        proxy_headers = dict(request_headers)
        proxy_headers.setdefault("Accept", "application/json")

        class TeraBoxFetcher(BaseFetcher):
            NAME = "TeraBox"
            BASE_URL = "https://www.1024tera.com"

            def log_fetch_state(self, metadata: dict, downloads_count: int | None):
                self.log_json(
                    "fetch snapshot",
                    {
                        "summary": {
                            "provider": self.NAME,
                            "filename": metadata.get("filename"),
                            "downloads_count": downloads_count,
                            "size": metadata.get("size"),
                            "md5": metadata.get("md5"),
                            "upload_date": metadata.get("upload_date"),
                            "share_username": metadata.get("share_username"),
                            "share_id": metadata.get("share_id"),
                            "country": metadata.get("country"),
                            "state": metadata.get("state"),
                        },
                        "details": {
                            "metadata": metadata,
                        },
                    },
                )

            def extract_js_token(self, response: ResponseObject) -> str:
                body = response.text
                patterns = [
                    r'window\.jsToken\s*=\s*"([^"]+)"',
                    r"window\.jsToken\s*=\s*'([^']+)'",
                    r"fn%28%22([A-F0-9]+)%22%29",
                    r'jsToken%22%3A%22([A-Fa-f0-9]+)%22',
                    r'"jsToken"\s*:\s*"([^"]+)"',
                ]
                for pattern in patterns:
                    match = re.search(pattern, body)
                    if match:
                        return match.group(1)
                raise ValueError("Error: TeraBox jsToken not found on share page")

            def extract_cookies_from_response(self, response: ResponseObject) -> str:
                """Extract auth cookies (especially ndus) from Set-Cookie response headers."""
                set_cookie_headers = response.headers.get("Set-Cookie", "")
                if not set_cookie_headers:
                    return ""
                cookie_jar: dict[str, str] = {}
                # Handle both single string and list of Set-Cookie values
                cookie_lines = (
                    set_cookie_headers.split(",")
                    if isinstance(set_cookie_headers, str)
                    else list(set_cookie_headers)
                )
                for line in cookie_lines:
                    sc = SimpleCookie()
                    try:
                        sc.load(line.strip())
                    except Exception:
                        continue
                    for key, morsel in sc.items():
                        if morsel.value:
                            cookie_jar[key] = morsel.value
                if cookie_jar:
                    cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_jar.items())
                    logger.info("[TeraBox] extracted cookies from share page: {}", list(cookie_jar.keys()))
                    return cookie_str
                return ""

            def merge_cookies(self, existing_cookie: str, new_cookies: str) -> str:
                """Merge new cookies into existing cookie header, preferring new values."""
                if not new_cookies:
                    return existing_cookie
                if not existing_cookie:
                    return new_cookies
                merged: dict[str, str] = {}
                for pair in existing_cookie.split(";"):
                    pair = pair.strip()
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        merged[k.strip()] = v.strip()
                for pair in new_cookies.split(";"):
                    pair = pair.strip()
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        merged[k.strip()] = v.strip()
                return "; ".join(f"{k}={v}" for k, v in merged.items())

            def apply_extracted_cookies(self, response: ResponseObject) -> str:
                """Extract cookies from the share page and update request headers for subsequent calls."""
                new_cookies = self.extract_cookies_from_response(response)
                if new_cookies:
                    existing = request_headers.get("Cookie", "")
                    merged = self.merge_cookies(existing, new_cookies)
                    # Update all header dicts so subsequent steps use the cookies
                    for headers_dict in (request_headers, sharedownload_headers, download_headers):
                        headers_dict["Cookie"] = merged
                    return merged
                return request_headers.get("Cookie", "")

            def extract_file_list(self, response: ResponseObject) -> list:
                data = response.json
                if data.get("errno") != 0:
                    raise ValueError(f"TeraBox API error: errno={data.get('errno')}, msg={data.get('errmsg')}")
                return data.get("list") or []

            def extract_metadata(self, response: ResponseObject, file_list: list) -> dict:
                if not file_list:
                    return {
                        "filename": None,
                        "size": None,
                        "state": "empty",
                    }

                primary = file_list[0]
                data = response.json or {}
                upload_ts = int(primary.get("server_ctime") or 0)
                share_ts = int(data.get("ctime") or 0)
                return {
                    "filename": primary.get("server_filename"),
                    "size": int(primary.get("size") or 0),
                    "md5": primary.get("md5"),
                    "fs_id": primary.get("fs_id"),
                    "category": primary.get("category"),
                    "is_dir": primary.get("isdir") == "1",
                    "upload_date": (
                        datetime.datetime.fromtimestamp(upload_ts, tz=datetime.timezone.utc).isoformat()
                        if upload_ts
                        else None
                    ),
                    "file_count": len(file_list),
                    "title": primary.get("server_filename") or data.get("title", "").strip("/"),
                    "country": data.get("country"),
                    "share_username": data.get("share_username"),
                    "share_id": data.get("shareid"),
                    "uk": data.get("uk"),
                    "uk_str": data.get("uk_str"),
                    "head_url": data.get("head_url"),
                    "share_ctime": (
                        datetime.datetime.fromtimestamp(share_ts, tz=datetime.timezone.utc).isoformat()
                        if share_ts
                        else None
                    ),
                    "expired_type": data.get("expiredtype"),
                    "fcount": data.get("fcount"),
                    "sign": data.get("sign"),
                    "randsk": data.get("randsk"),
                    "download_timestamp": int(data.get("timestamp") or 0),
                    "thumbs": primary.get("thumbs") or {},
                    "cookie_auth": bool(request_headers.get("Cookie")),
                    "state": "available",
                    "url": link,
                }

            def extract_filename(self, metadata: dict) -> str:
                return metadata.get("filename") or f"terabox-{surl}.bin"

            def is_proxy_gateway_configured(self) -> bool:
                return bool(proxy_request_url)

            def default_downloads_count(self) -> int | None:
                # TeraBox API does not expose a download counter
                return None

            def is_available(self, file_list: list) -> bool:
                return len(file_list) > 0

            def get_download_sign(self, metadata: dict) -> str:
                return metadata.get("sign") or ""

            def get_download_timestamp(self, metadata: dict) -> int:
                return int(metadata.get("download_timestamp") or 0)

            def get_share_id(self, metadata: dict) -> int:
                return int(metadata.get("share_id") or 0)

            def get_share_uk(self, metadata: dict) -> int:
                return int(metadata.get("uk") or 0)

            def build_fid_list(self, metadata: dict) -> str:
                fs_id = metadata.get("fs_id")
                return json.dumps([int(fs_id)]) if fs_id else "[]"

            def build_download_extra(self, metadata: dict) -> str:
                return json.dumps({"sekey": metadata.get("randsk") or ""}, separators=(",", ":"))

            def extract_sharedownload_item(self, response: ResponseObject) -> dict:
                data = response.json or {}
                items = data.get("list") or []
                item = items[0] if items else {}
                return {
                    "errno": data.get("errno"),
                    "errmsg": data.get("errmsg"),
                    "server_time": int(data.get("server_time") or 0),
                    "request_id": data.get("request_id"),
                    "dlink": item.get("dlink"),
                    "item": item,
                }

            def extract_proxy_result(self, response: ResponseObject) -> dict:
                payload = response.json if isinstance(response.json, dict) else {}
                files = payload.get("files") or []
                item = files[0] if files else {}
                direct_link = (
                    item.get("direct_link") or item.get("download_link") or item.get("link") or item.get("dlink")
                )
                return {
                    "status_code": response.status_code,
                    "status": payload.get("status"),
                    "error": payload.get("error") or payload.get("message"),
                    "errno": payload.get("errno"),
                    "file": item,
                    "direct_link": direct_link,
                    "payload": payload,
                }

            def extract_worker_proxy_result(self, response: ResponseObject) -> dict:
                payload = response.json if isinstance(response.json, dict) else {}
                data = payload.get("data") or payload.get("upstream") or {}
                items = data.get("list") or []
                item = items[0] if items else {}
                direct_link = (
                    item.get("direct_link")
                    or item.get("download_link")
                    or item.get("link")
                    or item.get("dlink")
                    or data.get("dlink")
                )
                return {
                    "status_code": response.status_code,
                    "status": "success" if response.status_code == 200 and data.get("errno") == 0 else "error",
                    "error": payload.get("error") or payload.get("message") or payload.get("note"),
                    "errno": data.get("errno"),
                    "file": item,
                    "direct_link": direct_link,
                    "payload": payload,
                    "note": payload.get("note"),
                    "data": data,
                }

            def extract_proxy_download_status(self, proxy_result: dict) -> dict:
                if proxy_result.get("status_code") != 200:
                    return {
                        "can_download": False,
                        "reason": f"gateway_http_{proxy_result.get('status_code')}",
                        "errno": proxy_result.get("errno"),
                        "errmsg": proxy_result.get("error"),
                        "server_time": None,
                        "dstime": None,
                        "direct_link": None,
                        "source": "gateway",
                    }

                if proxy_result.get("status") != "success":
                    return {
                        "can_download": False,
                        "reason": "gateway_error",
                        "errno": proxy_result.get("errno"),
                        "errmsg": proxy_result.get("error"),
                        "server_time": None,
                        "dstime": None,
                        "direct_link": None,
                        "source": "gateway",
                    }

                direct_link = proxy_result.get("direct_link")
                if not direct_link:
                    return {
                        "can_download": False,
                        "reason": "gateway_missing_link",
                        "errno": proxy_result.get("errno"),
                        "errmsg": proxy_result.get("error"),
                        "server_time": None,
                        "dstime": None,
                        "direct_link": None,
                        "source": "gateway",
                    }

                return {
                    "can_download": True,
                    "reason": "gateway_ready",
                    "errno": proxy_result.get("errno"),
                    "errmsg": proxy_result.get("error"),
                    "server_time": None,
                    "dstime": None,
                    "direct_link": direct_link,
                    "source": "gateway",
                }

            def extract_proxy_direct_link(self, proxy_result: dict) -> str | None:
                return proxy_result.get("direct_link")

            def extract_direct_link(self, download_item: dict) -> str | None:
                return download_item.get("dlink")

            def extract_download_status(self, download_item: dict) -> dict:
                errno = download_item.get("errno")
                dlink = download_item.get("dlink")
                server_time = int(download_item.get("server_time") or 0)

                if errno != 0:
                    return {
                        "can_download": False,
                        "reason": f"sharedownload_errno_{errno}",
                        "errno": errno,
                        "errmsg": download_item.get("errmsg"),
                        "server_time": server_time,
                        "dstime": None,
                        "direct_link": None,
                    }

                if not dlink:
                    return {
                        "can_download": False,
                        "reason": "missing_dlink",
                        "errno": errno,
                        "errmsg": download_item.get("errmsg"),
                        "server_time": server_time,
                        "dstime": None,
                        "direct_link": None,
                    }

                query = parse_qs(urlparse(dlink).query)
                dstime_raw = (query.get("dstime") or [None])[0]
                try:
                    dstime = int(dstime_raw) if dstime_raw else None
                except (TypeError, ValueError):
                    dstime = None

                is_fresh = bool(dstime and server_time and dstime >= server_time)
                reason = "ready" if is_fresh else "expired_issued_link"
                return {
                    "can_download": is_fresh,
                    "reason": reason,
                    "errno": errno,
                    "errmsg": download_item.get("errmsg"),
                    "server_time": server_time,
                    "dstime": dstime,
                    "direct_link": dlink,
                }

            def extend_metadata_download(self, metadata: dict, download_item: dict, download_status: dict) -> dict:
                updated = dict(metadata)
                updated["download_errno"] = download_item.get("errno")
                updated["download_error"] = download_item.get("errmsg")
                updated["download_server_time"] = download_status.get("server_time")
                updated["download_dstime"] = download_status.get("dstime")
                updated["download_state"] = download_status.get("reason")
                updated["download_url"] = download_status.get("direct_link")
                updated["download_source"] = download_status.get("source") or "native"
                return updated

            def extend_metadata_proxy(self, metadata: dict, proxy_result: dict, download_status: dict) -> dict:
                updated = dict(metadata)
                file_info = proxy_result.get("file") or {}
                payload = proxy_result.get("payload") or {}
                updated["filename"] = file_info.get("filename") or updated.get("filename")
                updated["size"] = int(file_info.get("size_bytes") or updated.get("size") or 0)
                updated["fs_id"] = file_info.get("fs_id") or updated.get("fs_id")
                updated["thumbs"] = file_info.get("thumbnails") or updated.get("thumbs") or {}
                updated["download_errno"] = proxy_result.get("errno")
                updated["download_error"] = proxy_result.get("error")
                updated["download_server_time"] = None
                updated["download_dstime"] = None
                updated["download_state"] = download_status.get("reason")
                updated["download_url"] = download_status.get("direct_link")
                updated["download_source"] = download_status.get("source")
                updated["proxy_gateway"] = proxy_request_url
                updated["proxy_status"] = payload.get("status")
                if proxy_result.get("note"):
                    updated["proxy_note"] = proxy_result.get("note")
                return updated

            def log_download_negotiation(self, download_item: dict, download_status: dict):
                self.log_json(
                    "download negotiation",
                    {
                        "request": {
                            "shorturl": shorturl,
                            "cookie_auth": bool(request_headers.get("Cookie")),
                        },
                        "response": download_item,
                        "status": download_status,
                    },
                )

            def log_proxy_resolution(self, proxy_result: dict, download_status: dict):
                self.log_json(
                    "gateway resolution",
                    {
                        "request": {
                            "url": proxy_request_url,
                            "mode": proxy_mode,
                            "cookie_auth": bool(request_headers.get("Cookie")),
                        },
                        "response": proxy_result,
                        "status": download_status,
                    },
                )

            info_steps = [
                Step(
                    RunRequest("load share page")
                    .get(share_page_path)
                    .headers(**request_headers)
                    .teardown_callback("apply_extracted_cookies(response)", assign="auth_cookie")
                    .teardown_callback("extract_js_token(response)", assign="js_token")
                    .validate()
                    .assert_equal("status_code", 200)
                ),
                Step(
                    RunRequest("load share metadata")
                    .get("/api/shorturlinfo")
                    .headers(**request_headers)
                    .params(
                        app_id="250528",
                        web="1",
                        channel="dubox",
                        clienttype="0",
                        jsToken="$js_token",
                        shorturl=shorturl,
                        root="1",
                        scene="",
                    )
                    .teardown_callback("extract_file_list(response)", assign="file_list")
                    .teardown_callback("extract_metadata(response, file_list)", assign="metadata")
                    .teardown_callback("extract_filename(metadata)", assign="filename")
                    .teardown_callback("default_downloads_count()", assign="downloads_count")
                    .teardown_callback("is_available(file_list)", assign="available")
                    .teardown_callback("log_fetch_state(metadata, downloads_count)")
                    .validate()
                    .assert_equal("status_code", 200)
                    .assert_equal("available", True)
                ),
            ]

            fetch_steps = info_steps.copy()
            fetch_steps.extend(
                [
                    OptionalStep(
                        RunRequest("load gateway direct link")
                        .get(proxy_request_url or "https://invalid.local/api2")
                        .headers(**proxy_headers)
                        .params(url=link)
                        .teardown_callback("extract_proxy_result(response)", assign="proxy_result")
                        .teardown_callback("extract_proxy_direct_link(proxy_result)", assign="direct_link")
                        .teardown_callback("extract_proxy_download_status(proxy_result)", assign="download_status")
                        .teardown_callback("extend_metadata_proxy(metadata, proxy_result, download_status)", assign="metadata")
                        .teardown_callback("extract_filename(metadata)", assign="filename")
                        .teardown_callback("log_proxy_resolution(proxy_result, download_status)")
                    ).when(
                        lambda step, vars: (
                            mode != Mode.INFO and vars.get("available") is True and proxy_mode == "api2"
                        )
                    ),
                    OptionalStep(
                        RunRequest("load worker direct link")
                        .get(proxy_request_url or "https://invalid.local/")
                        .headers(**proxy_headers)
                        .params(mode="resolve", surl=surl, raw="1")
                        .teardown_callback("extract_worker_proxy_result(response)", assign="proxy_result")
                        .teardown_callback("extract_proxy_direct_link(proxy_result)", assign="direct_link")
                        .teardown_callback("extract_proxy_download_status(proxy_result)", assign="download_status")
                        .teardown_callback("extend_metadata_proxy(metadata, proxy_result, download_status)", assign="metadata")
                        .teardown_callback("extract_filename(metadata)", assign="filename")
                        .teardown_callback("log_proxy_resolution(proxy_result, download_status)")
                    ).when(
                        lambda step, vars: (
                            mode != Mode.INFO and vars.get("available") is True and proxy_mode == "worker"
                        )
                    ),
                    OptionalStep(
                        RunRequest("load shared download link")
                        .get("/api/sharedownload")
                        .setup_hook(lambda v: v.update({
                            "download_sign": v["self"].get_download_sign(v["metadata"]),
                            "download_timestamp": v["self"].get_download_timestamp(v["metadata"]),
                            "share_id": v["self"].get_share_id(v["metadata"]),
                            "share_uk": v["self"].get_share_uk(v["metadata"]),
                            "fid_list": v["self"].build_fid_list(v["metadata"]),
                            "download_extra": v["self"].build_download_extra(v["metadata"]),
                        }))
                        .headers(**sharedownload_headers)
                        .params(
                            app_id="250528",
                            web="1",
                            channel="dubox",
                            clienttype="0",
                            jsToken="$js_token",
                            shorturl=shorturl,
                            sign="$download_sign",
                            timestamp="$download_timestamp",
                            shareid="$share_id",
                            primaryid="$share_id",
                            uk="$share_uk",
                            fid_list="$fid_list",
                            product="share",
                            type="nolimit",
                            nozip="0",
                            extra="$download_extra",
                        )
                        .teardown_callback("extract_sharedownload_item(response)", assign="download_item")
                        .teardown_callback("extract_direct_link(download_item)", assign="direct_link")
                        .teardown_callback("extract_download_status(download_item)", assign="download_status")
                        .teardown_callback("extend_metadata_download(metadata, download_item, download_status)", assign="metadata")
                        .teardown_callback("log_download_negotiation(download_item, download_status)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(
                        lambda step, vars: (
                            mode != Mode.INFO
                            and vars.get("available") is True
                            and not bool((vars.get("download_status") or {}).get("can_download"))
                        )
                    ),
                    OptionalStep(
                        RunRequest("download")
                        .get("$direct_link")
                        .headers(**download_headers)
                        .teardown_callback("save_file(response, filename)")
                        .validate()
                        .assert_equal("status_code", 200)
                    ).when(
                        lambda step, vars: (
                            mode != Mode.INFO
                            and vars.get("available") is True
                            and bool(
                                (vars.get("download_status") or {}).get("can_download") and vars.get("direct_link")
                            )
                        )
                    ),
                ]
            )

            steps = info_steps if mode == Mode.INFO else fetch_steps

        return TeraBoxFetcher()
