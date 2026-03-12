from fetchers.base_fetcher import BaseFetcher
from httporchestrator import Flow


class DummyFetcher(BaseFetcher):
    NAME = "Dummy"
    BASE_URL = ""
    steps = []

    def build_marker(self):
        return "marker-value"


def test_runner_preserves_fetcher_methods_across_run():
    fetcher = DummyFetcher()

    assert fetcher.build_marker() == "marker-value"
    run = fetcher.run()

    assert fetcher.build_marker() == "marker-value"
    assert run.summary.name == "Dummy"


def test_fetcher_instances_keep_independent_variable_state():
    first = DummyFetcher().variables({"shared_var": "first"}).export(["shared_var"])
    second = DummyFetcher()

    first_run = first.run()
    second_run = second.run()

    assert first_run.exported["shared_var"] == "first"
    assert "shared_var" not in second_run.session_variables


def test_fetcher_base_uses_composition_not_workflow_inheritance():
    assert not issubclass(BaseFetcher, Flow)
