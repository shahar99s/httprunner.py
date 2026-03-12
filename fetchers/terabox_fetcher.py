from __future__ import annotations

import json
import re
from typing import Dict
from urllib.parse import parse_qs, unquote, urlparse

from loguru import logger

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode, format_size, format_timestamp, status_is, variable_is
from httporchestrator import ConditionalStep, RequestStep, Response


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookie_map: dict[str, str] = {}
    for pair in (cookie_header or "").split(";"):
        part = pair.strip()
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        cookie_map[key.strip()] = value.strip()
    return cookie_map


def merge_cookie_header(*cookie_headers: str) -> str:
    merged: dict[str, str] = {}
    for cookie_header in cookie_headers:
        merged.update(parse_cookie_header(cookie_header))
    return "; ".join(f"{key}={value}" for key, value in merged.items())


def has_cookie(cookie_header: str) -> bool:
    return bool(parse_cookie_header(cookie_header))


def cookies_from_response(response: Response) -> str:
    cookie_map = {key: value for key, value in response.cookies.items() if value}
    return "; ".join(f"{key}={value}" for key, value in cookie_map.items())


class TeraBoxFetcher(BaseFetcher):
    """
    has download notification: No
    has downloads count: No
    """

    NAME = "TeraBox"
    BASE_URL = ""
    VALID_HOSTS = {
        "www.terabox.com",
        "terabox.com",
        "1024terabox.com",
        "www.terabox.app",
        "terabox.app",
        "1024tera.com",
        "email.terabox.com",
    }
    JS_TOKEN_PATTERNS = (
        r'window\.jsToken\s*=\s*"([^"]+)"',
        r"window\.jsToken\s*=\s*'([^']+)'",
        r"fn%28%22([A-F0-9]+)%22%29",
        r"jsToken%22%3A%22([A-Fa-f0-9]+)%22",
        r'"jsToken"\s*:\s*"([^"]+)"',
    )
    BDSTOKEN_PATTERNS = (
        r'"bdstoken"\s*:\s*"([^"]+)"',
        r"bdstoken\s*[:=]\s*'([^']+)'",
        r'bdstoken\s*[:=]\s*"([^"]+)"',
    )

    @classmethod
    def is_relevant_url(cls, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return host in cls.VALID_HOSTS and (
            parsed.path.startswith("/s/") or (host == "email.terabox.com" and parsed.path.startswith("/c/"))
        )

    def __init__(
        self,
        link: str,
        headers: Dict[str, str] | None = None,
        email: str = "",
        password: str = "",
        *,
        mode: Mode = Mode.FETCH,
        log_details: bool = False,
    ):
        if not self.is_relevant_url(link):
            raise ValueError("Error: No valid TeraBox URL provided")

        self.link = link
        self.headers = headers or {}
        self.email = email.strip()
        self.password = password.strip()
        self.has_credentials = bool(self.email and self.password)
        self.initial_cookie = (self.headers.get("Cookie") or self.headers.get("cookie") or "").strip()
        self.base_headers = {key: value for key, value in self.headers.items() if key.lower() != "cookie"}
        self._browser_auth_cookie = ""

        super().__init__(mode=mode, log_details=log_details)

    def build_info_steps(self) -> list:
        return [
            RequestStep("load share page")
            .get(self.link)
            .headers(**self.base_headers)
            .before(lambda vars: self.prepare_share_page_request(vars))
            .after(lambda response, vars: self.extract_share_page_state(response, vars))
            .check(status_is(200), "expected 200 response")
            .check(variable_is("available", True), "expected share to be available"),
            RequestStep("load share metadata")
            .get(lambda vars: f"{vars['share_origin']}/api/shorturlinfo")
            .headers(
                **self.base_headers,
                Referer=lambda vars: vars["share_page_url"],
                Cookie=lambda vars: vars.get("auth_cookie", ""),
            )
            .params(
                app_id="250528",
                web="1",
                channel="dubox",
                clienttype="0",
                jsToken=lambda vars: vars["js_token"],
                shorturl=lambda vars: vars["shorturl"],
                root="1",
                scene="",
            )
            .after(lambda response, vars: self.extract_metadata_state(response, vars))
            .after(lambda _response, vars: self.log_fetch_state(vars["metadata"], vars["downloads_count"]))
            .check(status_is(200), "expected 200 response")
            .check(variable_is("available", True), "expected share to be available"),
        ]

    def build_fetch_steps(self) -> list:
        return [
            ConditionalStep(
                RequestStep("load guarded download link")
                .post(lambda vars: f"{vars['share_origin']}/share/download")
                .headers(
                    **self.base_headers,
                    Referer=lambda vars: vars["share_page_url"],
                    Cookie=lambda vars: vars.get("auth_cookie", ""),
                    **{"Content-Type": "application/x-www-form-urlencoded"},
                )
                .params(
                    scene="",
                    bdstoken=lambda vars: vars.get("bdstoken", ""),
                )
                .data(
                    lambda vars: {
                        "product": "share",
                        "uk": vars["download_request_state"]["uk"],
                        "shareid": vars["download_request_state"]["share_id"],
                        "primaryid": vars["download_request_state"]["share_id"],
                        "fid_list": vars["download_request_state"]["fid_list"],
                        "sign": vars["download_request_state"]["sign"],
                        "timestamp": vars["download_request_state"]["timestamp"],
                        "type": vars["download_request_state"]["type"],
                        "need_speed": vars["download_request_state"]["need_speed"],
                    }
                )
                .after(lambda response, vars: self.extract_guarded_download_state(response, vars))
                .check(status_is(200), "expected 200 response")
            ).run_when(lambda vars: vars.get("available") is True),
            ConditionalStep(
                RequestStep("load legacy download link")
                .get(lambda vars: f"{vars['share_origin']}/api/sharedownload")
                .headers(
                    **self.base_headers,
                    Referer=lambda vars: vars["share_page_url"],
                    Cookie=lambda vars: vars.get("auth_cookie", ""),
                )
                .params(
                    app_id="250528",
                    web="1",
                    channel="dubox",
                    clienttype="0",
                    jsToken=lambda vars: vars["js_token"],
                    shareid=lambda vars: vars["download_request_state"]["share_id"],
                    uk=lambda vars: vars["download_request_state"]["uk"],
                    sign=lambda vars: vars["download_request_state"]["sign"],
                    timestamp=lambda vars: vars["download_request_state"]["timestamp"],
                    fid_list=lambda vars: vars["download_request_state"]["fid_list"],
                    primaryid=lambda vars: vars["download_request_state"]["share_id"],
                    product="share",
                    nozip="0",
                    type="download",
                    extra=lambda vars: vars["download_request_state"]["extra"],
                )
                .after(lambda response, vars: self.extract_legacy_download_state(response, vars))
                .check(status_is(200), "expected 200 response")
                .check(lambda _response, vars: self.ensure_download_link_is_usable(vars))
            ).run_when(
                lambda vars: (
                    vars.get("available") is True and vars.get("download_status", {}).get("can_download") is not True
                )
            ),
            ConditionalStep(
                RequestStep("download")
                .get(lambda vars: vars["direct_link"])
                .headers(
                    **self.base_headers,
                    Referer=lambda vars: vars["share_page_url"],
                    Cookie=lambda vars: vars.get("auth_cookie", ""),
                )
                .after(
                    lambda response, vars: {
                        "direct_download_status_code": response.status_code,
                        **(self.save_file(response, vars["filename"]) or {}),
                    }
                )
                .check(lambda _response, vars: self.ensure_download_succeeded(vars))
            ).run_when(
                lambda vars: (
                    vars.get("available") is True and vars.get("download_status", {}).get("can_download") is True
                )
            ),
        ]

    def prepare_share_page_request(self, vars: dict) -> dict:
        auth_cookie = vars.get("auth_cookie", "") or self.initial_cookie
        if self.has_credentials:
            auth_cookie = merge_cookie_header(auth_cookie, self.get_authenticated_cookie())
        return {"auth_cookie": auth_cookie}

    def get_authenticated_cookie(self) -> str:
        if self._browser_auth_cookie:
            return self._browser_auth_cookie

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("TeraBox credentialed download requires Playwright, but it is not installed") from exc

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                page.goto(
                    "https://www.terabox.com/login",
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                page.fill("input.email-input", self.email)
                page.fill("input.pwd-input", self.password)
                page.locator("text=Login").click()
                page.wait_for_url("**/ai/**", timeout=60_000)
                page.wait_for_timeout(1_000)
            except PlaywrightTimeoutError as exc:
                raise RuntimeError("TeraBox browser login timed out") from exc
            finally:
                cookies = context.cookies()
                browser.close()

        auth_cookie = "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies if cookie.get("value"))
        if not has_cookie(auth_cookie) or "ndus=" not in auth_cookie:
            raise RuntimeError("TeraBox browser login did not yield an authenticated session cookie")

        self._browser_auth_cookie = auth_cookie
        logger.info("[TeraBox] authenticated browser session obtained")
        return auth_cookie

    def extract_share_page_state(self, response: Response, vars: dict) -> dict:
        final_url = str(response.url)
        parsed = urlparse(final_url)

        if parsed.path.startswith("/sharing/link"):
            surl = parse_qs(parsed.query).get("surl", [""])[0]
            shorturl = f"1{surl}" if surl else ""
        elif parsed.path.startswith("/s/"):
            shorturl = parsed.path.split("/s/")[1].rstrip("/")
            surl = shorturl[1:] if shorturl.startswith("1") else shorturl
            final_url = f"{parsed.scheme}://{parsed.netloc}/sharing/link?surl={surl}"
        else:
            raise ValueError(f"Error: Unable to resolve TeraBox share URL: {final_url}")

        auth_cookie = merge_cookie_header(vars.get("auth_cookie", ""), cookies_from_response(response))
        share_origin = f"{parsed.scheme}://{parsed.netloc}"

        return {
            "available": True,
            "auth_cookie": auth_cookie,
            "share_origin": share_origin,
            "share_page_url": final_url,
            "shorturl": shorturl,
            "surl": surl,
            "js_token": self.extract_js_token(response.text),
            "bdstoken": self.extract_bdstoken(response.text),
        }

    def extract_js_token(self, html: str) -> str:
        for pattern in self.JS_TOKEN_PATTERNS:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        raise ValueError("Error: TeraBox jsToken not found on share page")

    def extract_bdstoken(self, html: str) -> str:
        for pattern in self.BDSTOKEN_PATTERNS:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        return ""

    def extract_metadata_state(self, response: Response, vars: dict) -> dict:
        data = response.json() or {}
        if data.get("errno") != 0:
            raise ValueError(f"TeraBox API error: errno={data.get('errno')}, msg={data.get('errmsg')}")

        file_list = data.get("list") or []
        metadata = self.build_metadata(vars["shorturl"], data, file_list)

        return {
            "metadata": metadata,
            "filename": metadata.get("filename") or f"terabox-{vars['surl']}.bin",
            "downloads_count": None,
            "available": bool(file_list),
            "direct_link": None,
            "direct_download_status_code": None,
            "download_status": {"can_download": False, "reason": "not_requested"},
            "download_request_state": self.build_download_request_state(metadata),
        }

    def build_metadata(self, shorturl: str, data: dict, file_list: list) -> dict:
        if not file_list:
            return {
                "filename": None,
                "size": None,
                "size_bytes": None,
                "state": "empty",
                "url": self.link,
                "shorturl": shorturl,
            }

        item = file_list[0]
        upload_ts = int(item.get("server_ctime") or 0)
        share_ts = int(data.get("ctime") or 0)
        size_bytes = int(item.get("size") or 0)

        return {
            "filename": item.get("server_filename"),
            "size": format_size(size_bytes),
            "size_bytes": size_bytes,
            "md5": item.get("md5"),
            "fs_id": item.get("fs_id"),
            "category": item.get("category"),
            "is_dir": str(item.get("isdir")) == "1",
            "upload_date": format_timestamp(upload_ts * 1000 if upload_ts else None),
            "file_count": len(file_list),
            "title": item.get("server_filename") or data.get("title", "").strip("/"),
            "country": data.get("country"),
            "share_username": data.get("share_username"),
            "share_id": data.get("shareid"),
            "uk": data.get("uk"),
            "uk_str": data.get("uk_str"),
            "head_url": data.get("head_url"),
            "share_ctime": format_timestamp(share_ts * 1000 if share_ts else None),
            "expired_type": data.get("expiredtype"),
            "fcount": data.get("fcount"),
            "sign": data.get("sign"),
            "randsk": data.get("randsk"),
            "download_timestamp": int(data.get("timestamp") or 0),
            "preview_download_url": self.extract_preview_download_url(item),
            "cookie_auth": has_cookie(self.initial_cookie),
            "state": "available",
            "url": self.link,
            "shorturl": shorturl,
        }

    def extract_preview_download_url(self, item: dict) -> str | None:
        thumbs = item.get("thumbs") or {}
        for key in ("url3", "url2", "url1", "icon"):
            if thumbs.get(key):
                return thumbs[key]
        return None

    def build_download_request_state(self, metadata: dict) -> dict:
        fs_id = metadata.get("fs_id")
        return {
            "sign": metadata.get("sign") or "",
            "timestamp": int(metadata.get("download_timestamp") or 0),
            "share_id": int(metadata.get("share_id") or 0),
            "uk": int(metadata.get("uk") or 0),
            "fid_list": json.dumps([int(fs_id)]) if fs_id else "[]",
            "type": "dlink",
            "need_speed": 1,
            "extra": json.dumps({"sekey": unquote(metadata.get("randsk") or "")}, separators=(",", ":")),
        }

    def extract_guarded_download_state(self, response: Response, vars: dict) -> dict:
        return self.extract_download_state(response, vars, source="guarded")

    def extract_legacy_download_state(self, response: Response, vars: dict) -> dict:
        return self.extract_download_state(response, vars, source="legacy")

    def extract_download_state(self, response: Response, vars: dict, *, source: str) -> dict:
        payload = response.json() or {}
        dlink_value = payload.get("dlink")
        item = {}
        if isinstance(dlink_value, list):
            item = (dlink_value or [{}])[0]
            direct_link = item.get("dlink")
        elif isinstance(dlink_value, str):
            direct_link = dlink_value
        else:
            list_items = payload.get("list") or []
            item = (list_items or [{}])[0]
            direct_link = item.get("dlink")
        file_info = payload.get("file_info") or {}
        server_time = int(payload.get("server_time") or payload.get("timestamp") or 0)
        errno = payload.get("errno")
        dstime = self.extract_dstime(direct_link)
        link_is_stale = self.is_stale_direct_link(dstime, server_time)
        download_context = self.extract_download_context(item)

        can_download = bool(errno == 0 and direct_link and not link_is_stale)
        if errno != 0:
            reason = f"{source}_errno_{errno}"
        elif not direct_link:
            reason = f"{source}_missing_dlink"
        elif link_is_stale:
            reason = f"{source}_ready_but_stale"
        else:
            reason = f"{source}_ready"

        download_item = {
            "errno": errno,
            "errmsg": payload.get("errmsg"),
            "server_time": server_time,
            "request_id": payload.get("request_id"),
            "dlink": direct_link,
            "shorturl": vars["shorturl"],
            "item": item,
            "file_info": file_info,
            "context": download_context,
            "source": source,
        }
        download_status = {
            "can_download": can_download,
            "reason": reason,
            "errno": errno,
            "errmsg": payload.get("errmsg"),
            "server_time": server_time,
            "dstime": dstime,
            "time_skew_seconds": ((server_time - dstime) if (server_time and dstime) else None),
            "direct_link": direct_link,
            "context": download_context,
            "source": source,
        }

        metadata = dict(vars["metadata"])
        existing_attempts = dict(metadata.get("download_attempts") or {})
        existing_attempts[source] = {
            "errno": errno,
            "errmsg": payload.get("errmsg"),
            "server_time": server_time,
            "dstime": dstime,
            "direct_link": direct_link,
            "reason": reason,
        }
        metadata.update(
            {
                "download_errno": errno,
                "download_error": payload.get("errmsg"),
                "download_server_time": server_time,
                "download_dstime": dstime,
                "download_time_skew_seconds": ((server_time - dstime) if (server_time and dstime) else None),
                "download_state": reason,
                "download_url": direct_link,
                "download_context": download_context,
                "download_source": source,
                "download_attempts": existing_attempts,
            }
        )
        filename = file_info.get("filename") or metadata.get("filename") or vars["filename"]
        if filename:
            metadata["filename"] = filename

        return {
            "download_item": download_item,
            "download_status": download_status,
            "direct_link": direct_link,
            "metadata": metadata,
            "filename": filename,
        }

    def is_stale_direct_link(self, dstime: int | None, server_time: int | None) -> bool:
        return bool(dstime and server_time and dstime < server_time)

    def extract_download_context(self, item: dict) -> dict:
        raw_context = item.get("context")
        if not raw_context:
            return {}
        parsed = parse_qs(raw_context, keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def ensure_download_link_is_usable(self, vars: dict) -> bool:
        download_status = vars.get("download_status") or {}
        if download_status.get("can_download") is True:
            return True

        guarded_attempt = ((vars.get("metadata") or {}).get("download_attempts") or {}).get("guarded") or {}
        reason = download_status.get("reason") or "unknown"
        if guarded_attempt.get("errno") == 400310 and reason.endswith("_ready_but_stale"):
            raise ValueError("TeraBox download requires verify_v2, and the anonymous fallback dlink is already expired")
        raise ValueError(f"TeraBox did not return a usable direct download link ({reason})")

    def ensure_download_succeeded(self, vars: dict) -> bool:
        if vars.get("local_file_path"):
            return True
        status_code = vars.get("direct_download_status_code")
        raise ValueError(f"TeraBox direct download request failed (HTTP {status_code})")

    def extract_dstime(self, dlink: str | None) -> int | None:
        if not dlink:
            return None
        dstime_raw = (parse_qs(urlparse(dlink).query).get("dstime") or [None])[0]
        try:
            return int(dstime_raw) if dstime_raw else None
        except (TypeError, ValueError):
            return None

    def log_fetch_state(self, metadata: dict, downloads_count: int | None):
        self.log_json(
            "fetch snapshot",
            {
                "summary": {
                    "provider": self.NAME,
                    "filename": metadata.get("filename"),
                    "downloads_count": downloads_count,
                    "size": metadata.get("size") or format_size(metadata.get("size_bytes")),
                    "md5": metadata.get("md5"),
                    "upload_date": metadata.get("upload_date"),
                    "share_username": metadata.get("share_username"),
                    "share_id": metadata.get("share_id"),
                    "country": metadata.get("country"),
                    "state": metadata.get("state"),
                },
                "details": {"metadata": metadata},
            },
        )
