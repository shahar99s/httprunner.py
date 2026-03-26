# NOTE: Rewritten for simplified httprunner (no expression engine)
from httprunner import HttpRunner, Config, Step, RunRequest


class WorkflowRequestWithFunctions(HttpRunner):

    config = (
        Config("request methods workflow with functions")
        .variables(
            **{
                "foo1": "config_bar1",
                "foo2": "config_bar2",
                "expect_foo1": "config_bar1",
                "expect_foo2": "config_bar2",
            }
        )
        .base_url("https://postman-echo.com")
        .verify(False)
        .export(*["foo3"])
    )

    steps = [
        Step(
            RunRequest("get with params")
            .variables(
                **{"foo1": "bar11", "foo2": "bar21", "sum_v": "3"}
            )
            .get("/get")
            .params(**{"foo1": "bar11", "foo2": "bar21", "sum_v": "3"})
            .headers(**{"User-Agent": "HttpRunner/v4.3.5"})
            .extract()
            .extractor("body.args.foo2", "foo3")
            .validate()
            .assert_equal("status_code", 200)
            .assert_equal("body.args.foo1", "bar11")
            .assert_equal("body.args.sum_v", "3")
            .assert_equal("body.args.foo2", "bar21")
        ),
        Step(
            RunRequest("post raw text")
            .variables(**{"foo1": "bar12", "foo3": "bar32"})
            .post("/post")
            .headers(
                **{
                    "User-Agent": "HttpRunner/v4.3.5",
                    "Content-Type": "text/plain",
                }
            )
            .data(
                "This is expected to be sent back as part of response body: bar12-config_bar2-bar32."
            )
            .validate()
            .assert_equal("status_code", 200)
            .assert_equal(
                "body.data",
                "This is expected to be sent back as part of response body: bar12-config_bar2-bar32.",
            )
            .assert_type_match("body.json", "None")
            .assert_type_match("body.json", "NoneType")
            .assert_type_match("body.json", None)
        ),
        Step(
            RunRequest("post form data")
            .variables(**{"foo2": "bar23"})
            .post("/post")
            .headers(
                **{
                    "User-Agent": "HttpRunner/v4.3.5",
                    "Content-Type": "application/x-www-form-urlencoded",
                }
            )
            .data("foo1=config_bar1&foo2=bar23&foo3=bar21")
            .validate()
            .assert_equal("status_code", 200, "response status code should be 200")
            .assert_equal("body.form.foo1", "config_bar1")
            .assert_equal("body.form.foo2", "bar23")
            .assert_equal("body.form.foo3", "bar21")
        ),
    ]


if __name__ == "__main__":
    WorkflowRequestWithFunctions().run()
