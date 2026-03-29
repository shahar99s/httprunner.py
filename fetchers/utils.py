from enum import Enum, auto

from loguru import logger


class Mode(Enum):
    INFO = auto()
    FETCH = auto()
    FORCE_FETCH = auto()


def should_download(mode: Mode, downloads_count: int | None) -> bool:
    if mode == Mode.FORCE_FETCH:
        return True

    if mode != Mode.FETCH:
        logger.debug(
            "Skipping download because mode is {} (downloads_count={})",
            mode.name,
            downloads_count,
        )
        return False

    if downloads_count is None:
        logger.critical("Skipping download because downloads_count is missing")
        return False

    return True
