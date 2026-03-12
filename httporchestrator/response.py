from __future__ import annotations

from typing import Any


class Response:
    def __init__(self, raw_response):
        self.raw = raw_response

    @property
    def status_code(self) -> int:
        return self.raw.status_code

    @property
    def headers(self) -> dict[str, str]:
        return dict(self.raw.headers)

    @property
    def cookies(self) -> dict[str, str]:
        return dict(self.raw.cookies)

    @property
    def text(self) -> str:
        return self.raw.text

    @property
    def content(self) -> bytes:
        return self.raw.content

    @property
    def url(self):
        return self.raw.url

    @property
    def body(self) -> Any:
        try:
            return self.raw.json()
        except ValueError:
            return self.raw.content

    def json(self) -> Any:
        return self.raw.json()
