import unittest
from unittest.mock import MagicMock

from fetchers.limewire_fetcher import LimewireFetcherFactory
from fetchers.utils import Mode
from httprunner.response import ResponseObject


def _step_struct(fetcher, index):
    return fetcher.steps[index].struct()


def _make_response(data: dict, status_code: int = 200) -> ResponseObject:
    """Return a ResponseObject backed by a MagicMock httpx-style response."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.status_code = status_code
    return ResponseObject(mock_resp)


class TestLimewireFetcherFactory(unittest.TestCase):
    def test_is_relevant_url_valid(self):
        valid_urls = [
            "https://limewire.com/d/abc123",
            "https://www.limewire.com/d/XyZ_-456",
            "https://limewire.com/d/some-content-id?ref=share",
        ]
        for url in valid_urls:
            with self.subTest(url=url):
                self.assertTrue(LimewireFetcherFactory.is_relevant_url(url))

    def test_is_relevant_url_invalid(self):
        invalid_urls = [
            "https://example.com/d/abc123",
            "https://limewire.com/",
            "https://limewire.com/browse",
            "https://notlimewire.com/d/abc123",
            # wwwlimewire.com (no dot) was incorrectly accepted by lstrip("www.") — must be rejected
            "https://wwwlimewire.com/d/abc123",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertFalse(LimewireFetcherFactory.is_relevant_url(url))

    def test_extracts_content_id(self):
        factory = LimewireFetcherFactory("https://limewire.com/d/abc123XYZ")
        self.assertEqual(factory.content_id, "abc123XYZ")

    def test_extracts_content_id_with_hyphens_and_underscores(self):
        factory = LimewireFetcherFactory("https://limewire.com/d/my-file_01")
        self.assertEqual(factory.content_id, "my-file_01")

    def test_invalid_url_raises_value_error(self):
        with self.assertRaises(ValueError):
            LimewireFetcherFactory("https://example.com/not-limewire")
        with self.assertRaises(ValueError):
            LimewireFetcherFactory("@@@")

    def test_info_mode_has_one_step(self):
        fetcher = LimewireFetcherFactory("https://limewire.com/d/abc123").create(mode=Mode.INFO)
        self.assertEqual(len(fetcher.steps), 1)
        step = _step_struct(fetcher, 0)
        self.assertEqual(step.name, "get content metadata")

    def test_fetch_mode_has_two_steps(self):
        fetcher = LimewireFetcherFactory("https://limewire.com/d/abc123").create(mode=Mode.FETCH)
        self.assertEqual(len(fetcher.steps), 2)
        self.assertEqual(_step_struct(fetcher, 0).name, "get content metadata")
        self.assertEqual(_step_struct(fetcher, 1).name, "download")

    def test_metadata_step_url_contains_content_id(self):
        content_id = "testContentId99"
        fetcher = LimewireFetcherFactory(f"https://limewire.com/d/{content_id}").create()
        step = _step_struct(fetcher, 0)
        self.assertIn(content_id, step.request.url)

    def test_factory_name_is_limewire(self):
        fetcher = LimewireFetcherFactory("https://limewire.com/d/abc123").create()
        self.assertEqual(fetcher.NAME, "Limewire")

    def test_factory_base_url(self):
        fetcher = LimewireFetcherFactory("https://limewire.com/d/abc123").create()
        self.assertEqual(fetcher.BASE_URL, "https://limewire.com")

    def test_registry_detects_limewire_url(self):
        from fetchers.fetcher_registry import find_relevant_fetcher_factory

        factory_cls = find_relevant_fetcher_factory("https://limewire.com/d/abc123")
        self.assertIsNotNone(factory_cls)
        self.assertIs(factory_cls, LimewireFetcherFactory)


class TestLimewireFetcherCallbacks(unittest.TestCase):
    """Unit-test the callback methods with mock API responses."""

    def _fetcher(self):
        return LimewireFetcherFactory("https://limewire.com/d/cid99").create()

    # ------------------------------------------------------------------
    # extract_metadata
    # ------------------------------------------------------------------

    def test_extract_metadata_full_response(self):
        fetcher = self._fetcher()
        resp = _make_response({
            "id": "cid99",
            "file_name": "report.pdf",
            "title": "Q4 Report",
            "size": 204800,
            "file_type": "application/pdf",
            "file_url": "https://cdn.limewire.com/files/cid99/report.pdf",
            "downloads_count": 3,
            "creator_id": "user42",
            "created_at": "2024-01-15T10:00:00Z",
        })
        meta = fetcher.extract_metadata(resp)

        self.assertEqual(meta["id"], "cid99")
        self.assertEqual(meta["filename"], "report.pdf")
        self.assertEqual(meta["size"], 204800)
        self.assertEqual(meta["file_url"], "https://cdn.limewire.com/files/cid99/report.pdf")
        self.assertEqual(meta["downloads_count"], 3)
        self.assertEqual(meta["state"], "available")

    def test_extract_metadata_uses_name_fallback(self):
        """When file_name is absent, 'name' should be used."""
        fetcher = self._fetcher()
        resp = _make_response({
            "name": "video.mp4",
            "file_url": "https://cdn.limewire.com/files/cid99/video.mp4",
        })
        meta = fetcher.extract_metadata(resp)
        self.assertEqual(meta["filename"], "video.mp4")

    def test_extract_metadata_default_filename(self):
        """When neither file_name nor name are present, fallback filename is used."""
        fetcher = self._fetcher()
        resp = _make_response({"file_url": "https://cdn.limewire.com/files/cid99/x"})
        meta = fetcher.extract_metadata(resp)
        self.assertEqual(meta["filename"], "limewire-cid99")

    def test_extract_metadata_state_from_file_url_present(self):
        fetcher = self._fetcher()
        resp = _make_response({"file_url": "https://cdn.limewire.com/files/cid99/x"})
        meta = fetcher.extract_metadata(resp)
        self.assertEqual(meta["state"], "available")

    def test_extract_metadata_state_from_file_url_absent(self):
        """Without file_url and without a status field, state should be 'unavailable'."""
        fetcher = self._fetcher()
        resp = _make_response({"id": "cid99", "downloads_count": 5})
        meta = fetcher.extract_metadata(resp)
        self.assertEqual(meta["state"], "unavailable")
        self.assertIsNone(meta["file_url"])

    def test_extract_metadata_explicit_status_active(self):
        fetcher = self._fetcher()
        resp = _make_response({"status": "active", "file_url": "https://cdn.limewire.com/files/cid99/x"})
        meta = fetcher.extract_metadata(resp)
        self.assertEqual(meta["state"], "available")

    def test_extract_metadata_explicit_status_deleted(self):
        fetcher = self._fetcher()
        resp = _make_response({"status": "deleted", "file_url": "https://cdn.limewire.com/files/cid99/x"})
        meta = fetcher.extract_metadata(resp)
        self.assertEqual(meta["state"], "unavailable")

    def test_extract_metadata_empty_response(self):
        fetcher = self._fetcher()
        resp = _make_response({})
        meta = fetcher.extract_metadata(resp)
        self.assertEqual(meta["id"], "cid99")
        self.assertEqual(meta["filename"], "limewire-cid99")
        self.assertEqual(meta["state"], "unavailable")

    # ------------------------------------------------------------------
    # extract_file_url — must NOT raise (Bug 1 fix)
    # ------------------------------------------------------------------

    def test_extract_file_url_present(self):
        fetcher = self._fetcher()
        url = "https://cdn.limewire.com/files/cid99/file.zip"
        self.assertEqual(fetcher.extract_file_url({"file_url": url}), url)

    def test_extract_file_url_absent_returns_none(self):
        """extract_file_url must return None (not raise) when file_url is missing.

        Before the fix this would raise ValueError, which propagated before the
        assert_equal("available", True) validator could fire.
        """
        fetcher = self._fetcher()
        result = fetcher.extract_file_url({"file_url": None})
        self.assertIsNone(result)

        result = fetcher.extract_file_url({})
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # is_available
    # ------------------------------------------------------------------

    def test_is_available_true(self):
        fetcher = self._fetcher()
        self.assertTrue(fetcher.is_available({"state": "available"}))

    def test_is_available_false_unavailable(self):
        fetcher = self._fetcher()
        self.assertFalse(fetcher.is_available({"state": "unavailable"}))

    def test_is_available_false_missing_state(self):
        fetcher = self._fetcher()
        self.assertFalse(fetcher.is_available({}))

    # ------------------------------------------------------------------
    # extract_downloads_count
    # ------------------------------------------------------------------

    def test_extract_downloads_count_present(self):
        fetcher = self._fetcher()
        self.assertEqual(fetcher.extract_downloads_count({"downloads_count": 7}), 7)

    def test_extract_downloads_count_absent(self):
        fetcher = self._fetcher()
        self.assertIsNone(fetcher.extract_downloads_count({}))

    # ------------------------------------------------------------------
    # extract_filename
    # ------------------------------------------------------------------

    def test_extract_filename_from_metadata(self):
        fetcher = self._fetcher()
        self.assertEqual(fetcher.extract_filename({"filename": "archive.zip"}), "archive.zip")

    def test_extract_filename_fallback(self):
        fetcher = self._fetcher()
        self.assertEqual(fetcher.extract_filename({}), "limewire-cid99")

    # ------------------------------------------------------------------
    # Download step condition — tested via OptionalStep.run() public interface
    # ------------------------------------------------------------------

    def _run_download_step(self, mode: Mode, step_vars: dict) -> str:
        """
        Run the download step against a mock runner that injects step_vars
        and return the step result's attachment string.
        An attachment of "skipped(optional)" means the step was not executed.
        """
        fetcher = LimewireFetcherFactory("https://limewire.com/d/cid99").create(mode=mode)
        download_step = fetcher.steps[1]

        mock_runner = MagicMock()
        mock_runner.merge_step_variables.return_value = dict(step_vars)
        result = download_step.run(mock_runner)
        return result.attachment

    def test_download_step_skipped_when_unavailable(self):
        """When available=False the download step must not execute."""
        attachment = self._run_download_step(
            Mode.FETCH, {"available": False, "downloads_count": 5}
        )
        self.assertEqual(attachment, "skipped(optional)")

    def test_download_step_skipped_when_no_downloads_left(self):
        """When downloads_count=0 the download step must not execute."""
        attachment = self._run_download_step(
            Mode.FETCH, {"available": True, "downloads_count": 0}
        )
        self.assertEqual(attachment, "skipped(optional)")

    def test_download_step_skipped_when_downloads_count_missing(self):
        """When downloads_count is absent the download step must not execute."""
        attachment = self._run_download_step(
            Mode.FETCH, {"available": True, "downloads_count": None}
        )
        self.assertEqual(attachment, "skipped(optional)")

    def test_download_step_runs_when_available_with_downloads(self):
        """When available=True and downloads_count>0 in FETCH mode, step executes."""
        import httpx
        from httprunner.models import TConfig, SessionData

        config = TConfig(name="test")
        config.base_url = "https://limewire.com"
        config.add_request_id = False

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = httpx.Headers({"Content-Type": "application/octet-stream"})
        mock_resp.content = b"file"
        mock_resp.json.side_effect = ValueError
        mock_resp.text = ""

        mock_session = MagicMock()
        mock_session.request.return_value = mock_resp
        mock_session.data = SessionData()

        mock_runner = MagicMock()
        mock_runner.merge_step_variables.return_value = {
            "available": True,
            "downloads_count": 3,
            "file_url": "https://cdn.limewire.com/files/cid99/f.zip",
            "filename": "f.zip",
        }
        mock_runner.get_config.return_value = config
        mock_runner.session = mock_session

        fetcher = LimewireFetcherFactory("https://limewire.com/d/cid99").create(mode=Mode.FETCH)
        result = fetcher.steps[1].run(mock_runner)

        # Step executed (not skipped) and issued an HTTP request
        self.assertNotEqual(result.attachment, "skipped(optional)")
        self.assertTrue(mock_session.request.called)

    def test_download_step_skipped_in_info_mode(self):
        """INFO mode fetcher has only one step and no download step."""
        fetcher = LimewireFetcherFactory("https://limewire.com/d/cid99").create(mode=Mode.INFO)
        self.assertEqual(len(fetcher.steps), 1)

