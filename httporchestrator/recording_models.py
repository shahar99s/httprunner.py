"""Runtime request/response recording models used in step results."""

from typing import Dict, List, Union

from pydantic import BaseModel, Field

from httporchestrator.models import Cookies, Headers, MethodEnum


class RequestMetrics(BaseModel):
    content_size: float = 0
    response_time_ms: float = 0
    elapsed_ms: float = 0


class AddressData(BaseModel):
    client_ip: str = "N/A"
    client_port: int = 0
    server_ip: str = "N/A"
    server_port: int = 0


class RequestData(BaseModel):
    method: MethodEnum = MethodEnum.GET
    url: str
    headers: Headers = Field(default_factory=dict)
    cookies: Cookies = Field(default_factory=dict)
    body: Union[str, bytes, List, Dict, None] = Field(default_factory=dict)


class ResponseData(BaseModel):
    status_code: int
    headers: Dict
    cookies: Cookies
    encoding: Union[str, None] = None
    content_type: str
    body: Union[str, bytes, List, Dict, None]


class RequestResponseRecord(BaseModel):
    request: RequestData
    response: ResponseData


class RequestSession(BaseModel):
    """RequestStep session data, including request, response, checks and stat data."""

    success: bool = False
    req_resps: List[RequestResponseRecord] = Field(default_factory=list)
    stat: RequestMetrics = Field(default_factory=RequestMetrics)
    address: AddressData = Field(default_factory=AddressData)
    checks: List[Dict] = Field(default_factory=list)
