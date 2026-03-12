from browserforge.headers import HeaderGenerator

from fetchers.fetcher_registry import create_fetcher
from fetchers.utils import Mode

"""
TODO:
- Simplify mediafire copy ferching logic, it is very convoluted right now
- Revaildate WeTransfer fetcher. It seems when fetch return data there is no notification.
- Terabox fetcher is convoluted, try to simplify it, remove unused features and code
"""


if __name__ == "__main__":
    browser_headers = HeaderGenerator(browser="chrome", os="windows", device="desktop")
    mode = Mode.FORCE_FETCH  # or Mode.INFO / Mode.FETCH / Mode.FORCE_FETCH

    runner = create_fetcher(
        "https://limewire.com/d/4hgmi#s4wwCgGlUa",
        headers=browser_headers.generate(),
        mode=mode,
        # email="shaharsiv9@gmail.com",
        # password="t9339415",
    )
    runner.run()
