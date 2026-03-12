"""Auto-detect file-sharing provider from a URL and create the right fetcher.

Fetcher classes are discovered automatically from all ``*_fetcher.py`` modules
in the ``fetchers/`` directory. Each fetcher class must:
  1. Have a name ending with ``Fetcher``.
  2. Expose ``is_relevant_url(url)``.
  3. Accept ``(link, headers=..., mode=...)`` at construction time.
"""

import importlib
import inspect
import pathlib
from typing import Dict

from loguru import logger

from fetchers.base_fetcher import BaseFetcher
from fetchers.utils import Mode

_FETCHER_CLASSES: list[type] | None = None
_FETCHERS_DIR = pathlib.Path(__file__).parent


def _discover_fetcher_classes() -> list[type]:
    """Import every *_fetcher.py module and collect top-level fetcher classes."""
    global _FETCHER_CLASSES
    if _FETCHER_CLASSES is not None:
        return _FETCHER_CLASSES

    classes: list[type] = []
    for path in sorted(_FETCHERS_DIR.glob("*_fetcher.py")):
        module_name = f"fetchers.{path.stem}"
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            logger.info(
                "Skipping fetcher module '{}' due to import error: {}",
                module_name,
                e,
            )
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj.__module__ == module.__name__
                and obj.__name__.endswith("Fetcher")
                and obj.__name__ != "BaseFetcher"
                and hasattr(obj, "is_relevant_url")
            ):
                classes.append(obj)

    _FETCHER_CLASSES = classes
    return _FETCHER_CLASSES


def find_relevant_fetcher_class(url: str) -> type | None:
    for fetcher_cls in _discover_fetcher_classes():
        if fetcher_cls.is_relevant_url(url):
            return fetcher_cls
    return None


def create_fetcher(
    url: str,
    headers: Dict[str, str] | None = None,
    mode: Mode = Mode.FETCH,
    **kwargs,
) -> BaseFetcher:
    fetcher_cls = find_relevant_fetcher_class(url)
    if fetcher_cls:
        return fetcher_cls(url, headers=headers, mode=mode, **kwargs)
    raise ValueError(f"Error: No supported provider detected for URL: {url}")
