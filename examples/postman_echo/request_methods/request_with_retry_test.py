# -*- coding: utf-8 -*-
"""

  @Date     :     2022/4/7
  @File     :     request_retry.py
  @Author   :     duanchao.bill
  @Desc     :

"""

from httprunner import HttpRunner, Config, Step, RunRequest, RunWorkflow


class WorkflowRetry(HttpRunner):
    config = (
        Config("request methods workflow in hardcode")
        .base_url("https://postman-echo.com")
        .verify(False)
    )

    steps = [
        Step(
            RunRequest("run with retry")
            .retry(retry_times=1, retry_interval=1)
            .get("/get")
            .params(**{"foo1": "${fake_randnum()}"})
            .headers(**{"User-Agent": "HttpRunner/3.0"})
            .validate()
            .assert_equal("body.args.foo1", "2")
        )
    ]
