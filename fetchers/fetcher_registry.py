"""Auto-detect file-sharing provider from a URL and create the right fetcher.

Factories are discovered automatically from all *_fetcher.py modules in the
fetchers/ directory.  Each factory class must:
  1. Have a name ending with ``FetcherFactory``.
  2. Accept ``(link, *, headers=...)`` in ``__init__`` and raise ``ValueError``
     when the URL doesn't belong to that provider.
  3. Expose a ``create(mode)`` method returning a ``BaseFetcher``.
"""

import importlib
import inspect
import pathlib
from typing import Dict

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode

_FACTORIES: list[type] | None = None
_FETCHERS_DIR = pathlib.Path(__file__).parent


def _discover_factories() -> list[type]:
    """Import every *_fetcher.py module and collect FetcherFactory classes."""
    global _FACTORIES
    if _FACTORIES is not None:
        return _FACTORIES

    factories: list[type] = []
    for path in sorted(_FETCHERS_DIR.glob("*_fetcher.py")):
        module_name = f"fetchers.{path.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj.__name__.endswith("FetcherFactory")
                and obj.__module__ == module.__name__
            ):
                factories.append(obj)

    _FACTORIES = factories
    return _FACTORIES


def find_relevant_fetcher_factory(url: str) -> type | None:
    for factory_cls in _discover_factories():
        if factory_cls.is_relevant_url(url):
            return factory_cls
    return None


def create_fetcher(
    url: str,
    headers: Dict[str, str] | None = None,
    mode: Mode = Mode.FETCH,
) -> BaseFetcher:

    factory_cls = find_relevant_fetcher_factory(url)
    if factory_cls:
        factory = factory_cls(url, headers=headers)
        return factory.create(mode=mode)
    raise ValueError(f"Error: No supported provider detected for URL: {url}")
