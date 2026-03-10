from __future__ import annotations

import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp.updater import (
    DownloadedUpdate,
    ReleaseAsset,
    ReleaseInfo,
    check_for_updates,
    download_update,
    prepare_update_launcher,
)


class _BinaryResponse(io.BytesIO):
    def __enter__(self) -> "_BinaryResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _release_payload() -> dict[str, object]:
    return {
        "tag_name": "v0.4.0",
        "html_url": "https://github.com/mashingaan/packing/releases/tag/v0.4.0",
        "assets": [
            {
                "name": "PackingMVP-Setup.exe",
                "browser_download_url": "https://example.com/PackingMVP-Setup.exe",
            },
            {
                "name": "PackingMVP-Setup.exe.sha256",
                "browser_download_url": "https://example.com/PackingMVP-Setup.exe.sha256",
            },
        ],
    }


class UpdaterTests(unittest.TestCase):
    def test_check_for_updates_detects_new_version_and_sha256(self) -> None:
        installer_bytes = b"new-installer"
        installer_hash = hashlib.sha256(installer_bytes).hexdigest()

        with patch("packing_mvp.updater._fetch_json", return_value=_release_payload()):
            with patch(
                "packing_mvp.updater._fetch_text",
                return_value=f"{installer_hash}  PackingMVP-Setup.exe\n",
            ):
                result = check_for_updates(current_version="0.3.0")

        self.assertTrue(result.update_available)
        self.assertEqual(result.latest_version, "0.4.0")
        self.assertIsNotNone(result.release_info)
        self.assertEqual(result.release_info.expected_sha256, installer_hash)
        self.assertEqual(result.release_info.installer_asset.name, "PackingMVP-Setup.exe")

    def test_check_for_updates_returns_not_configured_when_repo_is_missing(self) -> None:
        result = check_for_updates(repository="", current_version="0.3.0")

        self.assertFalse(result.configured)
        self.assertFalse(result.update_available)
        self.assertEqual(result.error, "GitHub Releases не настроен.")

    def test_download_update_writes_installer_and_validates_hash(self) -> None:
        installer_bytes = b"new-installer"
        installer_hash = hashlib.sha256(installer_bytes).hexdigest()
        release_info = ReleaseInfo(
            version="0.4.0",
            release_url="https://github.com/mashingaan/packing/releases/tag/v0.4.0",
            installer_asset=ReleaseAsset(
                name="PackingMVP-Setup.exe",
                download_url="https://example.com/PackingMVP-Setup.exe",
            ),
            expected_sha256=installer_hash,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("packing_mvp.updater.urlopen", return_value=_BinaryResponse(installer_bytes)):
                downloaded_update = download_update(release_info, download_dir=Path(tmp_dir))

            self.assertTrue(downloaded_update.installer_path.exists())
            self.assertEqual(downloaded_update.installer_path.read_bytes(), installer_bytes)

    def test_prepare_update_launcher_writes_expected_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            installer_path = tmp_path / "PackingMVP-Setup.exe"
            installer_path.write_bytes(b"installer")
            downloaded_update = DownloadedUpdate(
                release_info=ReleaseInfo(
                    version="0.4.0",
                    release_url="https://github.com/mashingaan/packing/releases/tag/v0.4.0",
                    installer_asset=ReleaseAsset(
                        name="PackingMVP-Setup.exe",
                        download_url="https://example.com/PackingMVP-Setup.exe",
                    ),
                ),
                installer_path=installer_path,
            )

            script_path = prepare_update_launcher(
                downloaded_update,
                app_executable=Path(r"C:\Users\User\AppData\Local\Programs\Packing MVP\Packing.exe"),
                current_pid=4321,
                work_dir=tmp_path,
            )

            script_text = script_path.read_text(encoding="utf-8")

        self.assertIn("$pidToWait = 4321", script_text)
        self.assertIn("PackingMVP-Setup.exe", script_text)
        self.assertIn("Packing.exe", script_text)
        self.assertIn("/VERYSILENT", script_text)
        self.assertIn("$defaultInstallDirName = 'Packing MVP'", script_text)
        self.assertIn("Inno Setup: App Path", script_text)
        self.assertIn("Start-Process -FilePath $launchTarget | Out-Null", script_text)

    def test_prepare_update_launcher_prefers_installed_copy_over_current_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            installer_path = tmp_path / "PackingMVP-Setup.exe"
            installer_path.write_bytes(b"installer")
            downloaded_update = DownloadedUpdate(
                release_info=ReleaseInfo(
                    version="0.4.0",
                    release_url="https://github.com/mashingaan/packing/releases/tag/v0.4.0",
                    installer_asset=ReleaseAsset(
                        name="PackingMVP-Setup.exe",
                        download_url="https://example.com/PackingMVP-Setup.exe",
                    ),
                ),
                installer_path=installer_path,
            )

            script_path = prepare_update_launcher(
                downloaded_update,
                app_executable=Path(r"C:\Users\User\Desktop\Packing.exe"),
                current_pid=4321,
                work_dir=tmp_path,
            )

            script_text = script_path.read_text(encoding="utf-8")

        self.assertLess(
            script_text.index("$defaultInstalledApp = Join-Path"),
            script_text.index("[void]$launchCandidates.Add($app)"),
        )
        self.assertIn("HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall", script_text)
        self.assertIn("{8FD8A4C6-8F6F-4F8B-A9AA-FA38718AC550}_is1", script_text)


if __name__ == "__main__":
    unittest.main()
