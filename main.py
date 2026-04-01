from fetchers.dropbox_transfer_fetcher import DropboxTransferFetcherFactory
from fetchers.sendgb_fetcher import SendgbFetcherFactory
from fetchers.filemail_fetcher import FilemailFetcherFactory
from fetchers.limewire_fetcher import LimewireFetcherFactory
from fetchers.mega_fetcher import MegaFetcherFactory
from fetchers.mediafire_fetcher import MediaFireFetcherFactory
from fetchers.sendanywhere_fetcher import SendAnywhereFetcherFactory
from fetchers.smash_fetcher import SmashFetcherFactory
from fetchers.terabox_fetcher import TeraBoxFetcherFactory
from fetchers.transfernow_fetcher import TransferNowFetcherFactory
from fetchers.transferxl_fetcher import TransferXLFetcherFactory
from fetchers.utils import Mode
from fetchers.wetransfer_fetcher import WeTransferFetcherFactory
from fetchers.fetcher_registry import create_fetcher, find_relevant_fetcher_factory

from browserforge.headers import HeaderGenerator

"""
TODO:
- Test mediafire user login, save file to the user files and teardown_callback download it, this will allow to bypass the downloads counter
- Make sure smash fetcher dont download when there is a download notification
- Terabox fetcher download doesn't work - cookie and js_tokens extraction should be implemented
- Verify Sendanywhere fetcher
- Cleanup the repo, remove unnecessary or complex code
"""


if __name__ == "__main__":
    browser_headers = HeaderGenerator(browser="chrome", os="windows", device="desktop")

    mode = Mode.FETCH  # or Mode.FETCH / Mode.FORCE_FETCH

    # runner = TransferNowFetcherFactory(
    #     "https://www.transfernow.net/dl/202603120kavmEMg/yBLpPYkJ",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = MediaFireFetcherFactory(
    #     "https://www.mediafire.com/file/5rv03j13foves42/30-SUPER-FAVOR+(3).jpg/file",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = WeTransferFetcherFactory(
    #     "https://wetransfer.com/downloads/b1446cfa95a605d896ee821c7b76222f20260311083557/0626bd?t_exp=1773477358&t_lsid=978b789e-6348-4a88-a31f-5f4c19a65395&t_network=link&t_rid=ZW1haWx8YWRyb2l0fDZiMzcwNjdmLTQzNGEtNGQzMC1iNDg1LTdhNzQ0ZTJjNjM5NA==&t_s=download_link&t_ts=1773218158",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = WeTransferFetcherFactory(
    #     "https://we.tl/t-mQ7BfOv3WD",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = SendgbFetcherFactory(
    #     "https://sendgb.com/g4D2eAoOamH",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = FilemailFetcherFactory(
    #     "https://www.filemail.com/d/ifyvssdfbjbnzni",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = SmashFetcherFactory(
    #     "https://fromsmash.com/oCwyCi2prh-dt?e=c2hhaGFyc2l2OUBnbWFpbC5jb20=",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = TeraBoxFetcherFactory(
    #     "https://1024terabox.com/s/1LJTcFCQ5haHb838XjlghcA",
    #     headers=browser_headers.generate(),
    # ).create(mode=mode)
    # runner.run()

    # runner = DropboxTransferFetcherFactory(
    #     "https://www.dropbox.com/l/scl/AAEMf-awt4SqTt9TW9i1N27WY1Vm-717f_0",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = TransferXLFetcherFactory(
    #     "https://www.transferxl.com/download/08JwVjM9zyJ53?utm_source=downloadmail&utm_medium=e-mail",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = SendAnywhereFetcherFactory(
    #     "https://send-anywhere.com/web/downloads/6PH9Y9DT",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = SendAnywhereFetcherFactory(
    #     "https://mandrillapp.com/track/click/30564474/sendanywhe.re?p=eyJzIjoiVEQ4a2YtMXE2di1ob0x1MVQ1MVlSdndZVVlrIiwidiI6MiwicCI6IntcInVcIjozMDU2NDQ3NCxcInZcIjoyLFwidXJsXCI6XCJodHRwOlxcXC9cXFwvc2VuZGFueXdoZS5yZVxcXC82UEg5WTlEVFwiLFwiaWRcIjpcImE1MzFmMjk0OTI2YzRiNTk4YzcxYjZiOGM1YTVjZjUzXCIsXCJ1cmxfaWRzXCI6W1wiMWY1NmQ1NmNlMmNiMWRmNjRmOGM2YjZiMTBjMTk2ZmYzYmNkOTMzYVwiXSxcIm1zZ190c1wiOjE3NzQzNzU2NDR9In0",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    # runner = LimewireFetcherFactory(
    #     "https://limewire.com/d/CONTENT_ID",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.run()

    runner = MegaFetcherFactory(
        "https://mega.nz/file/U8wDFKiJ#05e51m4TJciqQywxD6DWe8UVkCODua-uqG_usP8tOao",
        headers=browser_headers.generate(),
    ).create(mode=mode)
    runner.run()

    # --- Auto-detect example (uses create_fetcher wrapper) ---
    # runner = create_fetcher(
    #     "https://wetransfer.com/downloads/TRANSFER_ID/SECURITY_HASH",
    #     headers=browser_headers.generate(),
    #     mode=mode,
    # )
    # runner.run()
