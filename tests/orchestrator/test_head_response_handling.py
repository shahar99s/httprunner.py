from types import SimpleNamespace

from httporchestrator.engine.workflow_logger import WorkflowLogger
from httporchestrator.recording import ExchangeRecorder


class HeadResponseDouble:
    def __init__(self):
        self.status_code = 302
        self.headers = {"Location": "https://example.com/final"}
        self.cookies = {}
        self.encoding = None
        self.is_error = False
        self.request = SimpleNamespace(
            method="HEAD",
            url="https://example.com/start",
            headers={},
            content=b"",
        )

    def raise_for_status(self):
        return None

    def json(self):
        raise AssertionError("HEAD responses should not be parsed as JSON")

    @property
    def text(self):
        raise AssertionError("HEAD responses should not read text bodies")

    @property
    def content(self):
        raise AssertionError("HEAD responses should not read binary bodies")


def test_workflow_logger_skips_head_response_body():
    WorkflowLogger().log_response(HeadResponseDouble(), response_time_ms=12.5, log_details=True)


def test_exchange_recorder_skips_head_response_body():
    record = ExchangeRecorder().capture(HeadResponseDouble(), log_details=False)

    assert record.response.body is None
