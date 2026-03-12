import json
import os
import uuid
from typing import List

import pytest
from httprunner import Config, Step
from loguru import logger


def publish_summary_artifact(file_name, payload):
    artifacts_dir = os.path.join(os.getcwd(), "logs", "pytest-summaries")
    os.makedirs(artifacts_dir, exist_ok=True)
    artifact_path = os.path.join(artifacts_dir, file_name)
    with open(artifact_path, "w", encoding="utf-8") as artifact_file:
        json.dump(payload, artifact_file, ensure_ascii=False, indent=2, default=str)
    logger.debug(f"published summary artifact: {artifact_path}")


@pytest.fixture(scope="session", autouse=True)
def session_fixture(request):
    """setup and teardown each task"""
    total_testcases_num = request.node.testscollected
    testcases = []
    for item in request.node.items:
        testcase = {
            "name": item.cls.config.name,
            "path": item.cls.config.path,
            "node_id": item.nodeid,
        }
        testcases.append(testcase)

    logger.debug(f"collected {total_testcases_num} testcases: {testcases}")

    yield

    logger.debug("teardown task fixture")

    publish_summary_artifact(
        "task-summary.json",
        {
            "total_testcases": total_testcases_num,
            "testcases": testcases,
        },
    )


@pytest.fixture(scope="function", autouse=True)
def testcase_fixture(request):
    """setup and teardown each testcase"""
    config: Config = request.cls.config
    teststeps: List[Step] = request.cls.teststeps

    logger.debug(f"setup testcase fixture: {config.name} - {request.module.__name__}")

    def update_request_headers(steps, index):
        for teststep in steps:
            if teststep.request:
                index += 1
                teststep.request.headers["X-Request-ID"] = f"{prefix}-{index}"
            elif teststep.testcase and hasattr(teststep.testcase, "teststeps"):
                update_request_headers(teststep.testcase.teststeps, index)

    # you can update testcase teststep like this
    prefix = f"HRUN-{uuid.uuid4()}"
    update_request_headers(teststeps, 0)

    yield

    logger.debug(
        f"teardown testcase fixture: {config.name} - {request.module.__name__}"
    )

    summary = request.instance.get_summary()
    logger.debug(f"testcase result summary: {summary}")

    publish_summary_artifact(
        f"{request.node.name}-summary.json",
        summary.dict(),
    )
