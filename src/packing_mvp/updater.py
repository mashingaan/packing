from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from packaging.version import InvalidVersion, Version

from packing_mvp import __version__
from packing_mvp.update_config import (
    GITHUB_API_BASE_URL,
    GITHUB_REPOSITORY,
    RELEASE_ASSET_NAME,
    UPDATE_REQUEST_TIMEOUT_SECONDS,
)

INSTALLER_ARGUMENTS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-")


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    release_url: str
    installer_asset: ReleaseAsset
    published_at: str | None = None
    notes: str = ""
    expected_sha256: str | None = None


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest_version: str | None
    update_available: bool
    release_info: ReleaseInfo | None = None
    error: str | None = None
    configured: bool = True


@dataclass(frozen=True)
class DownloadedUpdate:
    release_info: ReleaseInfo
    installer_path: Path


class UpdateError(RuntimeError):
    """Raised when the application cannot fetch or apply an update."""


def is_update_configured(repository: str | None = None) -> bool:
    try:
        resolved_repository = GITHUB_REPOSITORY if repository is None else repository
        _split_repository(resolved_repository)
    except UpdateError:
        return False
    return True


def can_apply_update() -> bool:
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def check_for_updates(
    *,
    repository: str | None = None,
    current_version: str = __version__,
    release_asset_name: str | None = None,
) -> UpdateCheckResult:
    resolved_repository = (GITHUB_REPOSITORY if repository is None else repository).strip()
    if not is_update_configured(resolved_repository):
        return UpdateCheckResult(
            current_version=current_version,
            latest_version=None,
            update_available=False,
            configured=False,
            error="GitHub Releases не настроен.",
        )

    try:
        release_payload = _fetch_json(_release_api_url(resolved_repository))
        release_info = _release_info_from_payload(
            release_payload,
            preferred_asset_name=release_asset_name or RELEASE_ASSET_NAME,
        )
        update_available = _parse_version(release_info.version) > _parse_version(current_version)
        return UpdateCheckResult(
            current_version=current_version,
            latest_version=release_info.version,
            update_available=update_available,
            release_info=release_info,
        )
    except UpdateError as exc:
        return UpdateCheckResult(
            current_version=current_version,
            latest_version=None,
            update_available=False,
            error=str(exc),
        )


def download_update(release_info: ReleaseInfo, *, download_dir: Path | None = None) -> DownloadedUpdate:
    target_dir = Path(download_dir) if download_dir is not None else Path(
        tempfile.mkdtemp(prefix=f"packing-mvp-update-{release_info.version}-")
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    installer_path = target_dir / release_info.installer_asset.name

    request = _build_request(release_info.installer_asset.download_url)
    digest = hashlib.sha256()
    try:
        with urlopen(request, timeout=UPDATE_REQUEST_TIMEOUT_SECONDS) as response, installer_path.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 128)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
    except (OSError, HTTPError, URLError) as exc:
        installer_path.unlink(missing_ok=True)
        raise UpdateError(f"Не удалось скачать установщик: {exc}") from exc

    actual_sha256 = digest.hexdigest()
    if release_info.expected_sha256 is not None and actual_sha256 != release_info.expected_sha256:
        installer_path.unlink(missing_ok=True)
        raise UpdateError("Контрольная сумма установщика не совпала с release-артефактом.")

    return DownloadedUpdate(release_info=release_info, installer_path=installer_path)


def prepare_update_launcher(
    downloaded_update: DownloadedUpdate,
    *,
    app_executable: Path | None = None,
    current_pid: int | None = None,
    work_dir: Path | None = None,
) -> Path:
    installer_path = downloaded_update.installer_path.resolve()
    script_dir = Path(work_dir) if work_dir is not None else installer_path.parent
    script_dir.mkdir(parents=True, exist_ok=True)

    launch_script_path = script_dir / f"apply-update-{downloaded_update.release_info.version}.ps1"
    launch_script_path.write_text(
        _build_update_launcher_script(
            installer_path=installer_path,
            app_executable=(app_executable or Path(sys.executable)).resolve(),
            current_pid=current_pid or os.getpid(),
        ),
        encoding="utf-8",
    )
    return launch_script_path


def start_update_installer(
    downloaded_update: DownloadedUpdate,
    *,
    app_executable: Path | None = None,
    current_pid: int | None = None,
) -> Path:
    if not can_apply_update():
        raise UpdateError("Автоматическая установка доступна только в собранном Windows-приложении.")

    launch_script_path = prepare_update_launcher(
        downloaded_update,
        app_executable=app_executable,
        current_pid=current_pid,
    )
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(launch_script_path),
            ],
            cwd=str(launch_script_path.parent),
            creationflags=creationflags,
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError(f"Не удалось запустить установщик обновления: {exc}") from exc
    return launch_script_path


def _release_api_url(repository: str) -> str:
    owner, name = _split_repository(repository)
    return f"{GITHUB_API_BASE_URL}/repos/{owner}/{name}/releases/latest"


def _split_repository(repository: str) -> tuple[str, str]:
    trimmed = repository.strip()
    if not trimmed or "/" not in trimmed:
        raise UpdateError("Неверно задан GitHub-репозиторий для обновлений.")

    owner, name = (part.strip() for part in trimmed.split("/", 1))
    if not owner or not name:
        raise UpdateError("Неверно задан GitHub-репозиторий для обновлений.")
    return owner, name


def _parse_version(raw_version: str) -> Version:
    normalized_version = raw_version.strip()
    if normalized_version.lower().startswith("v"):
        normalized_version = normalized_version[1:]
    try:
        return Version(normalized_version)
    except InvalidVersion as exc:
        raise UpdateError(f"Не удалось разобрать версию релиза: {raw_version}") from exc


def _fetch_json(url: str) -> dict[str, object]:
    try:
        with urlopen(_build_request(url), timeout=UPDATE_REQUEST_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("В GitHub Releases пока нет опубликованных релизов.") from exc
        raise UpdateError(f"GitHub Releases вернул HTTP {exc.code}.") from exc
    except URLError as exc:
        raise UpdateError(f"Не удалось подключиться к GitHub Releases: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise UpdateError("GitHub Releases вернул некорректный JSON.") from exc


def _fetch_text(url: str) -> str:
    try:
        with urlopen(_build_request(url), timeout=UPDATE_REQUEST_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except HTTPError as exc:
        raise UpdateError(f"Не удалось скачать контрольную сумму обновления: HTTP {exc.code}.") from exc
    except URLError as exc:
        raise UpdateError(f"Не удалось скачать контрольную сумму обновления: {exc.reason}") from exc


def _build_request(url: str) -> Request:
    return Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"packing-mvp/{__version__}",
        },
    )


def _release_info_from_payload(
    release_payload: dict[str, object],
    *,
    preferred_asset_name: str,
) -> ReleaseInfo:
    tag_name = str(release_payload.get("tag_name") or "").strip()
    if not tag_name:
        raise UpdateError("GitHub release не содержит tag_name.")

    assets = list(release_payload.get("assets") or [])
    installer_asset = _select_installer_asset(assets, preferred_asset_name=preferred_asset_name)
    expected_sha256 = _select_expected_sha256(assets, installer_asset=installer_asset)
    return ReleaseInfo(
        version=_normalized_version_string(tag_name),
        release_url=str(release_payload.get("html_url") or installer_asset.download_url),
        installer_asset=installer_asset,
        published_at=str(release_payload.get("published_at") or "") or None,
        notes=str(release_payload.get("body") or ""),
        expected_sha256=expected_sha256,
    )


def _select_installer_asset(assets: list[object], *, preferred_asset_name: str) -> ReleaseAsset:
    release_assets = [_asset_from_payload(asset) for asset in assets]
    release_assets = [asset for asset in release_assets if asset is not None]
    if not release_assets:
        raise UpdateError("В релизе GitHub нет доступных файлов.")

    exact_match = next((asset for asset in release_assets if asset.name == preferred_asset_name), None)
    if exact_match is not None:
        return exact_match

    exe_assets = [asset for asset in release_assets if asset.name.lower().endswith(".exe")]
    if not exe_assets:
        raise UpdateError("В релизе GitHub не найден Windows-установщик (.exe).")

    setup_asset = next((asset for asset in exe_assets if "setup" in asset.name.lower()), None)
    return setup_asset or exe_assets[0]


def _asset_from_payload(asset_payload: object) -> ReleaseAsset | None:
    if not isinstance(asset_payload, dict):
        return None

    name = str(asset_payload.get("name") or "").strip()
    download_url = str(asset_payload.get("browser_download_url") or "").strip()
    if not name or not download_url:
        return None
    return ReleaseAsset(name=name, download_url=download_url)


def _select_expected_sha256(assets: list[object], *, installer_asset: ReleaseAsset) -> str | None:
    release_assets = [_asset_from_payload(asset) for asset in assets]
    release_assets = [asset for asset in release_assets if asset is not None]
    expected_name = f"{installer_asset.name}.sha256"
    checksum_asset = next((asset for asset in release_assets if asset.name == expected_name), None)
    if checksum_asset is None:
        checksum_asset = next((asset for asset in release_assets if asset.name.lower().endswith(".sha256")), None)
    if checksum_asset is None:
        return None

    checksum_text = _fetch_text(checksum_asset.download_url)
    return _parse_sha256(checksum_text, installer_name=installer_asset.name)


def _parse_sha256(checksum_text: str, *, installer_name: str) -> str:
    for line in checksum_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        parts = stripped.split()
        candidate = parts[0].lower()
        if len(candidate) != 64 or any(ch not in "0123456789abcdef" for ch in candidate):
            continue
        if len(parts) == 1:
            return candidate
        if Path(parts[-1].lstrip("*")).name == installer_name:
            return candidate

    raise UpdateError("Не удалось разобрать SHA256 из release-артефакта.")


def _normalized_version_string(raw_version: str) -> str:
    return str(_parse_version(raw_version))


def _build_update_launcher_script(
    *,
    installer_path: Path,
    app_executable: Path,
    current_pid: int,
) -> str:
    installer_literal = _powershell_literal(str(installer_path))
    app_literal = _powershell_literal(str(app_executable))
    installer_arguments = ", ".join(_powershell_literal(argument) for argument in INSTALLER_ARGUMENTS)
    return "\n".join(
        [
            f"$installer = {installer_literal}",
            f"$app = {app_literal}",
            f"$pidToWait = {current_pid}",
            f"$installerArgs = @({installer_arguments})",
            "while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {",
            "    Start-Sleep -Milliseconds 500",
            "}",
            "Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait | Out-Null",
            "if (Test-Path -LiteralPath $app) {",
            "    Start-Process -FilePath $app | Out-Null",
            "}",
            "Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue",
        ]
    )


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
