import json
import os

from loguru import logger

from fetchers.utils import Mode, should_download
from httprunner import HttpRunner, Config
from httprunner.parser import Parser


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
        if "filename=" in disposition:
            resolved_name = disposition.split("filename=")[-1].strip('"')

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

    def _init_parser_functions(self):
        # Automatically grab required functions from the subclass
        parser_functions = {}
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and not attr_name.startswith('__') and attr_name not in dir(HttpRunner):
                parser_functions[attr_name] = attr
        if parser_functions:
            self.parser = Parser(parser_functions)

    def __init__(self, parser_functions=None):
        super().__init__()
        self.config = Config(name=self.NAME)
        self.config.base_url(self.BASE_URL)
        self.config.add_request_id(False)
        self.parser_functions = parser_functions
        if not self.parser_functions:
            self._init_parser_functions()
        # Ensure teststeps is set if present in subclass
        if hasattr(self, "teststeps"):
            self.teststeps = getattr(self, "teststeps")
