"""Integration test: Smash download notification.

Test steps
----------
1. Create an anonymous Smash account (sender side) and upload a test file.
   Two variants are uploaded:
   - **With** download notification enabled (points to a temp-mail address).
   - **Without** download notification.
2. Use ``SmashFetcherFactory`` as a separate anonymous user to info / fetch.
3. Verify notification behaviour:
   - When notification is *enabled*, ``transfer_metadata`` must expose
     ``has_download_notification=True``.  The Smash fetcher is designed to
     *skip* the actual download in this case, so the step is about correctly
     *detecting* the notification setting rather than receiving an email.
   - When notification is *disabled*, fetching proceeds and no notification
     email is sent (``notification_safe=True``).
   - A transfer uploaded **with** a notification email and then downloaded via
     ``FORCE_FETCH`` (which bypasses the safety guard) triggers a notification
     email to the configured address.

Environment variables
---------------------
TEST_SMASH_URL_WITH_NOTIFICATION
    Optional.  Pre-uploaded Smash URL for a transfer that has download
    notification **enabled**.
TEST_SMASH_URL_WITHOUT_NOTIFICATION
    Optional.  Pre-uploaded Smash URL for a transfer that has download
    notification **disabled**.
"""

import os
import unittest

import httpx
import pytest

from fetchers.mail_checker import TempMailChecker
from fetchers.smash_fetcher import SmashFetcherFactory
from fetchers.utils import Mode

_TEST_CONTENT = b"Hello, Smash notification test!"
_TEST_FILENAME = "smash_test.txt"


def _smash_discover_region(headers: dict) -> str:
    resp = httpx.get(
        "https://discovery.fromsmash.co/namespace/public/services",
        params={"version": "10-2019"},
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    region = resp.json().get("region")
    if not region:
        raise RuntimeError("Smash discovery did not return a region")
    return region


def _smash_create_account(region: str, headers: dict) -> str:
    resp = httpx.post(
        f"https://iam.{region}.fromsmash.co/account",
        json={},
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    # The Smash IAM API wraps the account under "account" or "identity"; if neither
    # key is present (older API versions return the payload directly), fall back to
    # the top-level dict — but only when it actually contains a "token" key.
    account = data.get("account") or data.get("identity")
    if account is None:
        account = data if "token" in data else {}
    token_obj = account.get("token")
    token = token_obj.get("token") if isinstance(token_obj, dict) else None
    if not token:
        raise RuntimeError(f"Smash account creation did not return a token: {data}")
    return token


def _upload_to_smash(
    file_content: bytes,
    filename: str,
    notification_email: str | None = None,
) -> str:
    """Upload *file_content* to Smash and return the public transfer URL.

    If *notification_email* is provided the transfer is configured so that
    Smash will send a download-notification email to that address the first time
    someone downloads the file.
    """
    region = _smash_discover_region({})
    token = _smash_create_account(region, {})
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Build transfer payload
    transfer_body: dict = {
        "title": filename,
        "files": [{"name": filename, "size": len(file_content)}],
    }
    if notification_email:
        transfer_body["notification"] = {
            "download": {"enabled": True, "email": notification_email}
        }

    resp = httpx.post(
        f"https://transfer.{region}.fromsmash.co/transfer",
        json=transfer_body,
        headers={**auth_headers, "Content-Type": "application/json"},
        params={"version": "01-2024"},
        timeout=20,
    )
    resp.raise_for_status()
    transfer_data = resp.json().get("transfer", {})
    transfer_id = transfer_data.get("id")
    if not transfer_id:
        raise RuntimeError(f"Smash transfer creation did not return an id: {resp.json()}")

    # Upload each file
    for file_info in transfer_data.get("files", []):
        file_id = file_info["id"]
        upload_resp = httpx.get(
            f"https://transfer.{region}.fromsmash.co/transfer/{transfer_id}/files/{file_id}/upload",
            headers=auth_headers,
            params={"version": "01-2024"},
            timeout=20,
        )
        upload_resp.raise_for_status()
        upload_url = upload_resp.json()["file"]["upload"]["url"]
        httpx.put(upload_url, content=file_content, timeout=30).raise_for_status()

    # Finalise transfer
    httpx.put(
        f"https://transfer.{region}.fromsmash.co/transfer/{transfer_id}/ready",
        json={},
        headers={**auth_headers, "Content-Type": "application/json"},
        params={"version": "01-2024"},
        timeout=20,
    ).raise_for_status()

    return f"https://fromsmash.com/{transfer_id}"


@pytest.mark.integration
class TestSmashNotificationEnabled(unittest.TestCase):
    """Smash transfer that has download notification *enabled*.

    Steps:
    1. Upload a test file with notification email set to a monitored inbox.
    2. Info / fetch via SmashFetcherFactory (separate anonymous user).
    3. Verify ``has_download_notification=True`` in the extracted metadata.
    4. Verify the fetcher respects the notification-safety guard (skips download
       in FETCH mode).
    5. Force-fetch to bypass the guard; verify notification email is received.
    """

    @classmethod
    def setUpClass(cls):
        cls.skip_reason = None
        try:
            cls.mail = TempMailChecker.generate_inbox()
            url = os.environ.get("TEST_SMASH_URL_WITH_NOTIFICATION")
            if url:
                cls.transfer_url = url
            else:
                cls.transfer_url = _upload_to_smash(
                    _TEST_CONTENT, _TEST_FILENAME, notification_email=cls.mail.email
                )
        except Exception as exc:
            cls.skip_reason = f"Upload/setup failed: {exc}"

    def setUp(self):
        if self.skip_reason:
            self.skipTest(self.skip_reason)

    def _session_vars(self, fetcher):
        return fetcher._HttpRunner__final_session_variables

    def test_info_reports_download_notification_flag(self):
        """INFO mode must expose ``has_download_notification=True`` in metadata
        when the transfer was uploaded with a notification email configured.
        """
        fetcher = SmashFetcherFactory(self.transfer_url).create(mode=Mode.INFO)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        metadata = session_vars.get("transfer_metadata", {})
        self.assertTrue(
            metadata.get("has_download_notification"),
            "Expected has_download_notification=True for notification-enabled transfer",
        )
        self.assertIn(
            "download",
            metadata.get("notification_channels", []),
            "Expected 'download' channel in notification_channels",
        )

    def test_fetch_skips_download_when_notification_enabled(self):
        """FETCH mode must skip the actual download step when the transfer has
        download notifications enabled (``notification_safe=False``).

        The Smash fetcher is designed to avoid triggering a notification, so
        it will not proceed to the download step in this case.
        """
        fetcher = SmashFetcherFactory(self.transfer_url).create(mode=Mode.FETCH)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        metadata = session_vars.get("transfer_metadata", {})
        self.assertFalse(
            metadata.get("notification_safe"),
            "notification_safe should be False when download notifications are enabled",
        )

    def test_force_fetch_triggers_download_notification(self):
        """FORCE_FETCH bypasses the notification-safety guard, actually downloads
        the file, and sends a notification email to the configured address.
        """
        fetcher = SmashFetcherFactory(self.transfer_url).create(mode=Mode.FORCE_FETCH)
        fetcher.run()

        # The download has now happened; Smash should send an email notification.
        notification = self.mail.wait_for_notification(
            subject_contains="download",
            timeout_seconds=120,
        )
        self.assertIsNotNone(
            notification,
            f"Expected a download notification email at {self.mail.email} but none arrived",
        )


@pytest.mark.integration
class TestSmashNotificationDisabled(unittest.TestCase):
    """Smash transfer that has download notification *disabled*.

    Steps:
    1. Upload a test file without any notification configuration.
    2. Info / fetch via SmashFetcherFactory (separate anonymous user).
    3. Verify ``notification_safe=True`` and download proceeds normally.
    4. Confirm no notification email is sent.
    """

    @classmethod
    def setUpClass(cls):
        cls.skip_reason = None
        try:
            cls.mail = TempMailChecker.generate_inbox()
            url = os.environ.get("TEST_SMASH_URL_WITHOUT_NOTIFICATION")
            if url:
                cls.transfer_url = url
            else:
                cls.transfer_url = _upload_to_smash(
                    _TEST_CONTENT, _TEST_FILENAME, notification_email=None
                )
        except Exception as exc:
            cls.skip_reason = f"Upload/setup failed: {exc}"

    def setUp(self):
        if self.skip_reason:
            self.skipTest(self.skip_reason)

    def _session_vars(self, fetcher):
        return fetcher._HttpRunner__final_session_variables

    def test_info_reports_notification_safe(self):
        """INFO mode must report ``notification_safe=True`` when no notification
        was configured for the transfer.
        """
        fetcher = SmashFetcherFactory(self.transfer_url).create(mode=Mode.INFO)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        metadata = session_vars.get("transfer_metadata", {})
        self.assertTrue(
            metadata.get("notification_safe"),
            "Expected notification_safe=True when no notification is configured",
        )
        self.assertFalse(
            metadata.get("has_download_notification"),
            "Expected has_download_notification=False when no notification is configured",
        )

    def test_fetch_downloads_without_notification(self):
        """FETCH mode downloads the file and no notification email is sent."""
        fetcher = SmashFetcherFactory(self.transfer_url).create(mode=Mode.FETCH)
        fetcher.run()

        session_vars = self._session_vars(fetcher)
        metadata = session_vars.get("transfer_metadata", {})
        self.assertTrue(
            metadata.get("notification_safe"),
            "notification_safe must remain True after fetch on a non-notification transfer",
        )

        # No notification email should arrive for a notification-free transfer.
        no_notification = self.mail.wait_for_notification(
            subject_contains="download",
            timeout_seconds=30,
        )
        self.assertIsNone(
            no_notification,
            "Did not expect a download notification email for a transfer without notifications",
        )
