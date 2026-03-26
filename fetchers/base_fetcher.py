import json
import os
from urllib.parse import unquote

from loguru import logger

from httprunner import Config, HttpRunner


class BaseFetcher(HttpRunner):
    NAME = None
    BASE_URL = None

    def log_json(self, label: str, payload: dict):
        logger.info(
            "[{}] {}\n{}",
            self.NAME,
            label,
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
        )

    def save_file(self, response: object, fallback_filename: str) -> str:
        disposition = response.headers.get("Content-Disposition", "")
        resolved_name = fallback_filename
        if disposition:
            for item in disposition.split(";"):
                part = item.strip()
                if part.startswith("filename*="):
                    encoded_name = part.split("=", 1)[1].strip('"')
                    if "''" in encoded_name:
                        encoded_name = encoded_name.split("''", 1)[1]
                    resolved_name = unquote(encoded_name)
                    break
                if part.startswith("filename="):
                    resolved_name = unquote(part.split("=", 1)[1].strip('"'))

        resolved_name = os.path.basename(resolved_name)

        path = os.path.join(os.getcwd(), resolved_name)
        with open(path, "wb") as file_handle:
            file_handle.write(response.body)

        logger.success(
            "[{}] downloaded file saved to {} ({} bytes)",
            self.NAME,
            path,
            len(response.body),
        )
        return path

    def __init__(self):
        super().__init__()
        self.config = Config(name=self.NAME)
        self.config.base_url(self.BASE_URL)
        self.config.add_request_id(False)
