import unittest

from fetchers.limewire_fetcher import LimewireFetcherFactory
from fetchers.utils import Mode


def _step_struct(fetcher, index):
    return fetcher.steps[index].struct()


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
