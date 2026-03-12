import json
import os
from collections.abc import Sequence

from loguru import logger

from fetchers.utils import Mode, resolve_filename
from httporchestrator import Flow


class BaseFetcher:
    NAME = None
    BASE_URL = None
    steps = []

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

    def transform_body(self, body: bytes) -> bytes:
        return body

    def steps_for_mode(
        self,
        mode: Mode,
        info_steps: Sequence,
        fetch_steps: Sequence | None = None,
    ) -> list:
        steps = list(info_steps)
        if mode == Mode.INFO or fetch_steps is None:
            return steps
        return [*steps, *list(fetch_steps)]

    def build_info_steps(self) -> list:
        return list(getattr(type(self), "steps", []))

    def build_fetch_steps(self) -> list:
        return []

    def build_steps(self, mode: Mode) -> list:
        return self.steps_for_mode(mode, self.build_info_steps(), self.build_fetch_steps())

    def save_file(self, response: object, fallback_filename: str) -> dict:
        if response.status_code != 200:
            logger.warning(
                "[{}] download failed with HTTP {} - skipping save",
                self.NAME,
                response.status_code,
            )
            return {}

        resolved_name = os.path.basename(resolve_filename(response.headers, fallback_filename))
        payload = self.transform_body(response.body)

        path = os.path.join(os.getcwd(), resolved_name)
        with open(path, "wb") as file_handle:
            file_handle.write(payload)

        logger.success(
            "[{}] downloaded file saved to {} ({} bytes)",
            self.NAME,
            path,
            len(payload),
        )
        return {"local_file_path": path}

    def __init__(self, *, mode: Mode = Mode.FETCH, log_details: bool = False):
        self.mode = mode
        self.flow = Flow(
            name=self.NAME,
            base_url=self.BASE_URL or "",
            steps=tuple(self.build_steps(mode)),
            log_details=log_details,
            add_request_id=False,
        ).with_artifact_dir(os.getcwd())
        self.steps = list(self.flow.steps)

    def variables(self, variables: dict) -> "BaseFetcher":
        self.flow = self.flow.state(dict(variables or {}))
        return self

    def export(self, export: list[str]) -> "BaseFetcher":
        self.flow = self.flow.export(list(export))
        return self

    def run(self, param: dict | None = None):
        self.flow = self.flow.with_steps(tuple(self.steps))
        return self.flow.run(inputs=param)
