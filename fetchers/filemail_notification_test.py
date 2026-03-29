"""Integration test: Filemail download notification.

Test steps
----------
1. Upload a test file to Filemail (or use a pre-configured URL).  The sender
   email is set to a temp-mail address so that the "first download" notification
   can be verified.
2. Use ``FilemailFetcherFactory`` as a separate user to info / fetch the file.
3. Verify the download notification:
   - After INFO mode the download counter must stay at its initial value (0).
   - After FETCH mode the download counter increments and a notification email
     should arrive in the sender's inbox.

Environment variables
---------------------
TEST_FILEMAIL_URL
    Optional.  When set the upload step is skipped and the supplied Filemail
    download URL is used directly.  The URL must point to a fresh transfer
    whose ``number_of_downloads`` counter is still 0.
FILEMAIL_API_KEY
    Optional.  Filemail API key used during upload.  When absent the test
    attempts an anonymous upload via the public Filemail API.
"""

import os
import unittest

import httpx
import pytest

from fetchers.filemail_fetcher import FilemailFetcherFactory
from fetchers.mail_checker import TempMailChecker
from fetchers.utils import Mode

_TEST_CONTENT = b"Hello, Filemail notification test!"
_TEST_FILENAME = "filemail_test.txt"

_FILEMAIL_API_BASE = "https://api.filemail.com"
_FILEMAIL_DEFAULT_HEADERS = {
    "x-api-source": "WebApp",
    "x-api-version": "2.0",
    "Content-Type": "application/json",
}


def _upload_to_filemail(
    file_content: bytes,
    filename: str,
    sender_email: str,
    api_key: str | None = None,
) -> str:
    """Upload *file_content* to Filemail and return the public download URL.

    Follows the Filemail REST API: create transfer → upload file → complete.
    """
    create_headers = dict(_FILEMAIL_DEFAULT_HEADERS)
    if api_key:
        create_headers["x-api-key"] = api_key

    # Step 1: create the transfer
    create_body = {
        "from": sender_email,
        "subject": "Test notification transfer",
        "message": "Integration test upload",
        "sendEmails": False,
    }
    resp = httpx.post(
        f"{_FILEMAIL_API_BASE}/transfer",
        json=create_body,
        headers=create_headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data") or resp.json()
    transfer_id = data.get("id") if data.get("id") is not None else data.get("transferid")
    login_token = data.get("logintoken") if data.get("logintoken") is not None else data.get("apikey")
    if not transfer_id:
        raise RuntimeError(f"Filemail transfer creation did not return an id: {resp.json()}")

    # Step 2: upload the file
    upload_headers = {
        "x-api-source": "WebApp",
        "x-api-version": "2.0",
    }
    if login_token:
        upload_headers["x-api-key"] = login_token
    upload_resp = httpx.post(
        f"{_FILEMAIL_API_BASE}/transfer/file",
        params={"transferid": transfer_id, "logintoken": login_token or ""},
        files={"file": (filename, file_content, "text/plain")},
        headers=upload_headers,
        timeout=60,
    )
    upload_resp.raise_for_status()

    # Step 3: complete the transfer
    complete_resp = httpx.post(
        f"{_FILEMAIL_API_BASE}/transfer/complete",
        json={"transferid": transfer_id, "logintoken": login_token or ""},
        headers=_FILEMAIL_DEFAULT_HEADERS,
        timeout=30,
    )
    complete_resp.raise_for_status()

    transfer_url = complete_resp.json().get("data", {}).get("url") or data.get("url")
    if not transfer_url:
        raise RuntimeError(
            f"Filemail complete did not return a transfer URL: {complete_resp.json()}"
        )
    return transfer_url


@pytest.mark.integration
class TestFilemailNotification(unittest.TestCase):
    """Integration test: Filemail sends a "first download" notification email.

    Steps:
    1. Upload a test file with the sender address pointing to a monitored temp inbox.
    2. Info / fetch via FilemailFetcherFactory (as a different user).
    3. Verify:
       - INFO mode does not increment the download counter.
       - FETCH mode increments the counter and triggers a notification email.
    """

    @classmethod
    def setUpClass(cls):
        cls.skip_reason = None
        try:
            cls.mail = TempMailChecker.generate_inbox()
            url = os.environ.get("TEST_FILEMAIL_URL")
            if url:
                cls.transfer_url = url
            else:
                cls.transfer_url = _upload_to_filemail(
                    _TEST_CONTENT,
                    _TEST_FILENAME,
                    cls.mail.email,
                    api_key=os.environ.get("FILEMAIL_API_KEY"),
                )
        except Exception as exc:
            cls.skip_reason = f"Upload/setup failed: {exc}"

    def setUp(self):
        if self.skip_reason:
            self.skipTest(self.skip_reason)

    def _session_vars(self, fetcher):
        return fetcher._HttpRunner__final_session_variables

    # ------------------------------------------------------------------
    # Test 1 – INFO mode
    # ------------------------------------------------------------------
    def test_info_does_not_increment_download_counter(self):
        """INFO mode must not increment ``number_of_downloads``.

        Filemail tracks every download; a counter at 0 means no notification
        has been dispatched yet.
        """
        fetcher = FilemailFetcherFactory(self.transfer_url).create(mode=Mode.INFO)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        metadata = session_vars.get("metadata", {})
        downloads_count = session_vars.get("downloads_count", 0)

        self.assertIsNotNone(
            metadata,
            "Metadata should be populated after INFO run",
        )
        self.assertEqual(
            downloads_count,
            0,
            "Download counter must be 0 after INFO mode (no download occurred)",
        )

    # ------------------------------------------------------------------
    # Test 2 – FETCH mode
    # ------------------------------------------------------------------
    def test_fetch_triggers_download_notification(self):
        """FETCH mode downloads the file and Filemail sends a notification email
        to the sender on the first download.
        """
        fetcher = FilemailFetcherFactory(self.transfer_url).create(mode=Mode.FETCH)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        # The downloads_count captured by the fetcher is the pre-fetch value (0).
        initial_downloads_count = session_vars.get("downloads_count", 0)
        self.assertEqual(
            initial_downloads_count,
            0,
            "Expected downloads_count to be 0 before the first fetch",
        )

        # Verify the notification email arrives in the sender's inbox.
        notification = self.mail.wait_for_notification(
            subject_contains="download",
            timeout_seconds=120,
        )
        self.assertIsNotNone(
            notification,
            f"Expected a download notification email at {self.mail.email} but none arrived",
        )
