from fetchers.filemail_fetcher import FilemailFetcherFactory
from fetchers.mediafire_fetcher import MediaFireFetcherFactory
from fetchers.transfernow_fetcher import TransferNowFetcherFactory
from fetchers.utils import Mode
from fetchers.wetransfer_fetcher import WeTransferFetcherFactory
from fetchers.sendgb_fetcher import SendgbFetcherFactory

from browserforge.headers import HeaderGenerator

"""Manual smoke entrypoint for fetcher development."""

if __name__ == "__main__":
    browser_headers = HeaderGenerator(
        browser='chrome', 
        os='windows', 
        device='desktop'
    )
    
    mode = Mode.FORCE_FETCH  # or Mode.FETCH / Mode.FORCE_FETCH


    # runner = TransferNowFetcherFactory(
    #     "https://www.transfernow.net/dl/202603120kavmEMg/yBLpPYkJ",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.test_start()


    # runner = MediaFireFetcherFactory(
    #     "https://www.mediafire.com/file/5rv03j13foves42/30-SUPER-FAVOR+(3).jpg/file",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.test_start()

    # runner = WeTransferFetcherFactory(
    #     "https://wetransfer.com/downloads/b1446cfa95a605d896ee821c7b76222f20260311083557/0626bd?t_exp=1773477358&t_lsid=978b789e-6348-4a88-a31f-5f4c19a65395&t_network=link&t_rid=ZW1haWx8YWRyb2l0fDZiMzcwNjdmLTQzNGEtNGQzMC1iNDg1LTdhNzQ0ZTJjNjM5NA==&t_s=download_link&t_ts=1773218158", 
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.test_start()

    # runner = WeTransferFetcherFactory(
    #     "https://we.tl/t-mQ7BfOv3WD",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.test_start()

    runner = SendgbFetcherFactory(
        "https://sendgb.com/g4D2eAoOamH",
        headers=browser_headers.generate()
    ).create(mode=mode)
    runner.test_start()

    # runner = FilemailFetcherFactory(
    #     "https://www.filemail.com/d/ifyvssdfbjbnzni",
    #     headers=browser_headers.generate()
    # ).create(mode=mode)
    # runner.test_start()

    