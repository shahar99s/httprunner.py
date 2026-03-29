"""Integration test: TransferNow download notification.

Test steps
----------
1. Upload a test file to TransferNow (or use a pre-configured URL + sender
   secret).  The sender email is set to a monitored temp-mail address.
2. Use ``TransferNowFetcherFactory`` as a separate user to info / fetch the file.
3. Verify notification:
   - After INFO mode the ``download_events`` list must be empty (no download
     happened yet).
   - After FETCH mode a new entry appears in ``download_events`` and a
     notification email arrives in the sender's inbox.

TransferNow provides a ``sender_secret`` parameter that unlocks the stats API
(``/api/transfer/v2/transfers/{id}?senderSecret=...``), which exposes
``downloadEvents``.  This is the most reliable way to confirm a download
happened on the server side.

Environment variables
---------------------
TEST_TRANSFERNOW_URL
    Required (unless upload is implemented via TEST_TRANSFERNOW_API_KEY).
    Full TransferNow download URL including utm_source / utm_medium params.
TEST_TRANSFERNOW_SENDER_SECRET
    Required alongside TEST_TRANSFERNOW_URL.  The sender secret returned by
    TransferNow when a transfer is created.
TEST_TRANSFERNOW_SENDER_EMAIL
    Optional.  When set together with TEST_TRANSFERNOW_URL the notification
    check also polls the temp inbox; if absent the test relies on the stats API.
"""

import os
import unittest

import httpx
import pytest

from fetchers.mail_checker import TempMailChecker
from fetchers.transfernow_fetcher import TransferNowFetcherFactory
from fetchers.utils import Mode

_TEST_CONTENT = b"Hello, TransferNow notification test!"
_TEST_FILENAME = "transfernow_test.txt"


def _upload_to_transfernow(
    file_content: bytes,
    filename: str,
    sender_email: str,
) -> dict:
    """Upload *file_content* to TransferNow and return transfer info dict with
    ``url`` and ``sender_secret`` keys.

    Uses the TransferNow public REST API.
    """
    base_url = "https://www.transfernow.net"

    # Step 1: create the transfer
    create_resp = httpx.post(
        f"{base_url}/api/transfer",
        json={
            "from": sender_email,
            "message": "Integration test upload",
            "notify": True,
        },
        timeout=30,
    )
    create_resp.raise_for_status()
    data = create_resp.json()
    transfer_id = data.get("id") if data.get("id") is not None else data.get("transferId")
    sender_secret = data.get("senderSecret") if data.get("senderSecret") is not None else data.get("sender_secret")
    if not transfer_id:
        raise RuntimeError(f"TransferNow create transfer did not return an id: {data}")

    # Step 2: upload the file
    upload_resp = httpx.post(
        f"{base_url}/api/transfer/{transfer_id}/upload",
        files={"file": (filename, file_content, "text/plain")},
        timeout=60,
    )
    upload_resp.raise_for_status()

    # Step 3: finalise the transfer
    complete_resp = httpx.post(
        f"{base_url}/api/transfer/{transfer_id}/complete",
        json={"transferId": transfer_id},
        timeout=30,
    )
    complete_resp.raise_for_status()

    complete_data = complete_resp.json()
    # The download URL is returned in the complete response; fall back to the create
    # response only as a last resort since some API versions embed it there too.
    download_url = complete_data.get("url") or complete_data.get("data", {}).get("url")
    if not download_url:
        raise RuntimeError(
            f"TransferNow complete did not return a download URL: {complete_data}"
        )

    return {
        "url": download_url,
        "sender_secret": sender_secret,
    }


@pytest.mark.integration
class TestTransferNowNotification(unittest.TestCase):
    """Integration test: TransferNow sends a download notification on each download.

    TransferNow records every download event (IP, timestamp) and notifies the
    sender on the first download per recipient.  The stats API (with
    sender_secret) exposes the ``downloadEvents`` list, which is the primary
    way to verify a download happened.

    Steps:
    1. Upload a test file (sender email = monitored temp inbox).
    2. Info via TransferNowFetcherFactory with sender_secret → events list empty.
    3. Fetch via TransferNowFetcherFactory with sender_secret → events list grows.
    4. Notification email arrives in sender's inbox.
    """

    @classmethod
    def setUpClass(cls):
        cls.skip_reason = None
        try:
            cls.mail = TempMailChecker.generate_inbox()
            url = os.environ.get("TEST_TRANSFERNOW_URL")
            sender_secret = os.environ.get("TEST_TRANSFERNOW_SENDER_SECRET")
            if url and sender_secret:
                cls.transfer_url = url
                cls.sender_secret = sender_secret
            else:
                result = _upload_to_transfernow(
                    _TEST_CONTENT, _TEST_FILENAME, cls.mail.email
                )
                cls.transfer_url = result["url"]
                cls.sender_secret = result.get("sender_secret")
            if not cls.sender_secret:
                raise RuntimeError(
                    "TransferNow sender_secret is required for notification verification. "
                    "Set TEST_TRANSFERNOW_SENDER_SECRET env var."
                )
        except Exception as exc:
            cls.skip_reason = f"Upload/setup failed: {exc}"

    def setUp(self):
        if self.skip_reason:
            self.skipTest(self.skip_reason)

    def _session_vars(self, fetcher):
        return fetcher._HttpRunner__final_session_variables

    def _make_fetcher(self, mode: Mode) -> "TransferNowFetcherFactory":
        return TransferNowFetcherFactory(
            self.transfer_url,
            sender_secret=self.sender_secret,
        ).create(mode=mode)

    # ------------------------------------------------------------------
    # Test 1 – INFO mode
    # ------------------------------------------------------------------
    def test_info_shows_empty_download_events(self):
        """INFO mode with sender_secret must report an empty download events list
        when the file has not been downloaded yet.
        """
        fetcher = self._make_fetcher(Mode.INFO)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        download_events = session_vars.get("download_events", [])
        self.assertEqual(
            download_events,
            [],
            "Expected no download events after INFO mode (no download occurred)",
        )

    # ------------------------------------------------------------------
    # Test 2 – FETCH mode
    # ------------------------------------------------------------------
    def test_fetch_creates_download_event_and_sends_notification(self):
        """FETCH mode downloads the file.  TransferNow records the event and
        sends a notification email to the sender on the first download.
        """
        fetcher = self._make_fetcher(Mode.FETCH)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        download_events = session_vars.get("download_events", [])
        self.assertGreater(
            len(download_events),
            0,
            "Expected at least one download event after FETCH mode",
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
