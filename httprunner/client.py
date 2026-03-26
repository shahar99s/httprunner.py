import json
import time

import httpx
from loguru import logger

from httprunner.models import RequestData, ResponseData
from httprunner.models import SessionData, ReqRespData
from httprunner.utils import format_response_body_for_log, lower_dict_keys


def get_req_resp_record(resp_obj: httpx.Response) -> ReqRespData:
    """get request and response info from Response() object."""

    def log_print(req_or_resp, r_type):
        msg = f"\n================== {r_type} details ==================\n"
        for key, value in req_or_resp.dict().items():
            if isinstance(value, dict) or isinstance(value, list):
                value = json.dumps(value, indent=4, ensure_ascii=False)

            msg += "{:<8} : {}\n".format(key, value)
        logger.debug(msg)

    # record actual request info
    request_headers = dict(resp_obj.request.headers)
    request_cookies = dict(resp_obj.request.headers.get("cookie", ""))

    request_body = None
    try:
        request_body = resp_obj.request.content
    except httpx.RequestNotRead:
        pass
    if request_body is not None:
        try:
            request_body = json.loads(request_body)
        except json.JSONDecodeError:
            # str: a=1&b=2
            pass
        except UnicodeDecodeError:
            # bytes/bytearray: request body in protobuf
            pass
        except TypeError:
            # neither str nor bytes/bytearray, e.g. <MultipartEncoder>
            pass

        request_content_type = lower_dict_keys(request_headers).get("content-type")
        if request_content_type and "multipart/form-data" in request_content_type:
            # upload file type
            request_body = "upload file stream (OMITTED)"

    request_data = RequestData(
        method=resp_obj.request.method,
        url=str(resp_obj.request.url),
        headers=request_headers,
        cookies=request_cookies,
        body=request_body,
    )

    # log request details in debug mode
    log_print(request_data, "request")

    # record response info
    resp_headers = dict(resp_obj.headers)
    lower_resp_headers = lower_dict_keys(resp_headers)
    content_type = lower_resp_headers.get("content-type", "")

    content_disposition = lower_resp_headers.get("content-disposition", "")

    try:
        # try to record json data
        response_body = resp_obj.json()
    except ValueError:
        if "image" in content_type or "attachment" in content_disposition:
            response_body = format_response_body_for_log(
                resp_obj.content, content_type, content_disposition
            )
        else:
            # only record at most 512 text charactors
            resp_text = resp_obj.text
            response_body = format_response_body_for_log(
                resp_text, content_type, content_disposition
            )

    response_data = ResponseData(
        status_code=resp_obj.status_code,
        cookies=dict(resp_obj.cookies) if resp_obj.cookies else {},
        encoding=resp_obj.encoding,
        headers=resp_headers,
        content_type=content_type,
        body=response_body,
    )

    # log response details in debug mode
    log_print(response_data, "response")

    req_resp_data = ReqRespData(request=request_data, response=response_data)
    return req_resp_data


class HttpSession:
    """
    Class for performing HTTP requests and holding (session-) cookies between requests (in order
    to be able to log in and out of websites). Each request is logged so that HttpRunner can
    display statistics.

    Wraps httpx.Client to provide session-level cookie persistence and request/response logging.
    """

    def __init__(self):
        self._client = httpx.Client(verify=False)
        self.data = SessionData()

    def update_last_req_resp_record(self, resp_obj):
        """
        update request and response info from Response() object.
        """
        record = get_req_resp_record(resp_obj)
        if self.data.req_resps:
            self.data.req_resps[-1] = record
        else:
            self.data.req_resps.append(record)

    def _close_request_body(self, request_body):
        if request_body is None or not hasattr(request_body, "close"):
            return

        try:
            request_body.close()
        except Exception as ex:
            logger.debug(f"failed to close request body: {ex}")

    def request(self, method, url, name=None, **kwargs):
        """
        Constructs and sends an HTTP request via httpx.Client.
        Returns httpx.Response object.

        :param method: HTTP method (GET, POST, etc.)
        :param url: URL for the request.
        :param name: (optional) Placeholder for compatibility.
        :param params: (optional) Query parameters.
        :param data: (optional) Form data body.
        :param headers: (optional) HTTP headers.
        :param cookies: (optional) Cookies dict.
        :param json: (optional) JSON body.
        :param files: (optional) Upload files.
        :param auth: (optional) Auth tuple.
        :param timeout: (optional) Timeout in seconds (default 120).
        :param follow_redirects: (optional) Whether to follow redirects (default True).
        :param verify: (optional) SSL verification (mapped to client config).
        """
        self.data = SessionData()

        # timeout default to 120 seconds
        kwargs.setdefault("timeout", 120)

        # map requests-style kwargs to httpx equivalents
        if "allow_redirects" in kwargs:
            kwargs["follow_redirects"] = kwargs.pop("allow_redirects")
        kwargs.setdefault("follow_redirects", True)

        # httpx doesn't use 'stream' kwarg in the same way; remove it
        kwargs.pop("stream", None)

        # httpx uses 'verify' on the client, not per-request; remove it
        verify = kwargs.pop("verify", None)
        if verify is not None:
            self._client = httpx.Client(verify=verify)

        # map 'proxies' to httpx 'proxy' (single proxy)
        proxies = kwargs.pop("proxies", None)
        if proxies:
            proxy_url = proxies.get("https") or proxies.get("http") or proxies.get("all")
            if proxy_url:
                self._client = httpx.Client(verify=verify if verify is not None else False, proxy=proxy_url)

        # httpx: set per-request cookies on the client instead
        cookies = kwargs.pop("cookies", None)
        if cookies:
            self._client.cookies.update(cookies)

        # httpx: 'data' for raw bytes/str should be 'content'
        data = kwargs.pop("data", None)
        if data is not None:
            if isinstance(data, (bytes, str)):
                kwargs["content"] = data
            else:
                kwargs["data"] = data

        start_timestamp = time.time()
        response = self._send_request_safe_mode(method, url, **kwargs)

        # Extract socket info while the stream is still open (before read())
        try:
            hs = response.stream._stream._httpcore_stream
            pool = hs._pool
            if pool.connections:
                inner_conn = pool.connections[-1]._connection
                raw_sock = inner_conn._network_stream._sock
                client_ip, client_port = raw_sock.getsockname()
                self.data.address.client_ip = client_ip
                self.data.address.client_port = client_port
                server_ip, server_port = raw_sock.getpeername()
                self.data.address.server_ip = server_ip
                self.data.address.server_port = server_port
                logger.debug(f"client IP: {client_ip}, Port: {client_port}")
                logger.debug(f"server IP: {server_ip}, Port: {server_port}")
        except Exception:
            pass

        # Ensure the response body is fully read so that .elapsed is available
        if not response.is_stream_consumed:
            try:
                response.read()
            except Exception:
                pass
        try:
            response_time_ms = round((time.time() - start_timestamp) * 1000, 2)

            # get length of the response content
            content_size = int(dict(response.headers).get("content-length") or 0)

            # record the consumed time
            self.data.stat.response_time_ms = response_time_ms
            try:
                self.data.stat.elapsed_ms = response.elapsed.total_seconds() * 1000.0
            except RuntimeError:
                self.data.stat.elapsed_ms = response_time_ms
            self.data.stat.content_size = content_size

            # record request and response histories, include 30X redirection
            response_list = response.history + [response]
            self.data.req_resps = [
                get_req_resp_record(resp_obj) for resp_obj in response_list
            ]

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as ex:
                logger.error(f"{str(ex)}")
            else:
                logger.info(
                    f"status_code: {response.status_code}, "
                    f"response_time(ms): {response_time_ms} ms, "
                    f"response_length: {content_size} bytes"
                )

            return response
        finally:
            self._close_request_body(kwargs.get("data"))

    def _send_request_safe_mode(self, method, url, **kwargs):
        """
        Send an HTTP request, and catch any exception that might occur due to connection problems.
        """
        try:
            return self._client.request(method, url, **kwargs)
        except (httpx.UnsupportedProtocol, httpx.InvalidURL):
            raise
        except httpx.HTTPError as ex:
            resp = httpx.Response(
                status_code=0,
                request=httpx.Request(method, url),
            )
            resp._error = ex
            return resp

    def close(self):
        self._client.close()
