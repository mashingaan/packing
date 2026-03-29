from __future__ import annotations

import os
from pathlib import Path
import sys
import tkinter as tk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from packing_mvp import __version__
from packing_mvp.gui import PackingGui
from packing_mvp.updater import ReleaseAsset, ReleaseInfo, UpdateCheckResult


class GuiUpdateTests(unittest.TestCase):
    def _build_app(self) -> PackingGui:
        if os.environ.get("GITHUB_ACTIONS") == "true":
            self.skipTest("Tk update UI tests are skipped on GitHub-hosted runners.")
        try:
            app = PackingGui()
            app.update()
            return app
        except tk.TclError as exc:
            self.skipTest(f"Tk is unavailable in this environment: {exc}")

    def test_gui_shows_update_controls(self) -> None:
        app = self._build_app()
        try:
            self.assertTrue(app.check_updates_button.winfo_ismapped())
            self.assertIn(__version__, app.update_status_var.get())
            self.assertEqual(str(app.check_updates_button.cget("state")), "normal")
        finally:
            app.destroy()

    def test_gui_reports_current_version_when_update_not_needed(self) -> None:
        app = self._build_app()
        try:
            result = UpdateCheckResult(
                current_version=__version__,
                latest_version=__version__,
                update_available=False,
            )
            with patch("packing_mvp.gui.messagebox.showinfo") as showinfo:
                app._handle_update_check_result(result, user_initiated=True)

            showinfo.assert_called_once()
            self.assertIn(__version__, app.update_status_var.get())
        finally:
            app.destroy()

    def test_gui_opens_release_page_when_update_found_outside_installed_build(self) -> None:
        app = self._build_app()
        try:
            release_info = ReleaseInfo(
                version="0.6.2",
                release_url="https://github.com/mashingaan/packing/releases/tag/v0.6.2",
                installer_asset=ReleaseAsset(
                    name="PackingMVP-Setup.exe",
                    download_url="https://github.com/mashingaan/packing/releases/download/v0.6.2/PackingMVP-Setup.exe",
                ),
            )
            result = UpdateCheckResult(
                current_version=__version__,
                latest_version=release_info.version,
                update_available=True,
                release_info=release_info,
            )
            with patch("packing_mvp.gui.can_apply_update", return_value=False):
                with patch("packing_mvp.gui.messagebox.askyesno", return_value=True):
                    with patch("packing_mvp.gui._open_url") as open_url:
                        app._handle_update_check_result(result, user_initiated=True)

            open_url.assert_called_once_with(release_info.release_url)
            self.assertIn(release_info.version, app.update_status_var.get())
        finally:
            app.destroy()

    def test_gui_starts_download_when_update_found_in_installed_build(self) -> None:
        app = self._build_app()
        try:
            release_info = ReleaseInfo(
                version="0.6.2",
                release_url="https://github.com/mashingaan/packing/releases/tag/v0.6.2",
                installer_asset=ReleaseAsset(
                    name="PackingMVP-Setup.exe",
                    download_url="https://github.com/mashingaan/packing/releases/download/v0.6.2/PackingMVP-Setup.exe",
                ),
            )
            result = UpdateCheckResult(
                current_version=__version__,
                latest_version=release_info.version,
                update_available=True,
                release_info=release_info,
            )
            with patch("packing_mvp.gui.can_apply_update", return_value=True):
                with patch("packing_mvp.gui.messagebox.askyesno", return_value=True):
                    with patch.object(app, "_start_update_download") as start_update_download:
                        app._handle_update_check_result(result, user_initiated=True)

            start_update_download.assert_called_once_with(release_info)
        finally:
            app.destroy()

    def test_gui_closes_after_update_installer_starts(self) -> None:
        app = self._build_app()
        try:
            release_info = ReleaseInfo(
                version="0.6.2",
                release_url="https://github.com/mashingaan/packing/releases/tag/v0.6.2",
                installer_asset=ReleaseAsset(
                    name="PackingMVP-Setup.exe",
                    download_url="https://github.com/mashingaan/packing/releases/download/v0.6.2/PackingMVP-Setup.exe",
                ),
            )
            with patch("packing_mvp.gui.messagebox.showinfo") as showinfo:
                with patch.object(app, "after") as after:
                    app._handle_update_install_started(release_info, launch_script_path=Path("apply-update.ps1"))

            showinfo.assert_called_once()
            after.assert_called_once()
            self.assertIn(release_info.version, app.update_status_var.get())
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
