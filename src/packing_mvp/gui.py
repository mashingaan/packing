from __future__ import annotations

import multiprocessing
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk
from typing import Any, Sequence

try:
    import windnd
except ImportError:
    windnd = None

from packing_mvp import __version__
from packing_mvp.presentation import (
    format_result_summary,
    get_result_banner,
    result_is_constraint_failure,
    result_is_successful_fit,
)
from packing_mvp.update_config import AUTO_CHECK_FOR_UPDATES
from packing_mvp.updater import (
    DownloadedUpdate,
    ReleaseInfo,
    UpdateCheckResult,
    can_apply_update,
    check_for_updates,
    download_update,
    is_update_configured,
    start_update_installer,
)
from packing_mvp.runner import (
    PackingRequest,
    PackingRunResult,
    create_failure_run_result,
    make_default_output_dir,
    run_packing_job_in_subprocess,
)


PALETTE = {
    "bg": "#F4EFE8",
    "surface": "#FFFDFC",
    "surface_alt": "#F1E8DD",
    "field": "#FCF8F2",
    "border": "#D8CCBE",
    "text": "#23313A",
    "muted": "#66737C",
    "accent": "#2F7A6D",
    "accent_hover": "#266459",
    "accent_soft": "#D9ECE6",
    "accent_text": "#FFFFFF",
    "disabled": "#AAB8B3",
    "banner_neutral_bg": "#ECE2D6",
    "banner_neutral_fg": "#44545F",
    "banner_success_bg": "#DCEDE5",
    "banner_success_fg": "#234E44",
    "banner_warning_bg": "#F6E7D2",
    "banner_warning_fg": "#775424",
    "banner_error_bg": "#F3DED9",
    "banner_error_fg": "#7B3C33",
}

SUCCESS_BANNER = "success"
NO_FIT_BANNER = "no_fit"
ERROR_BANNER = "error"
NEUTRAL_BANNER = "neutral"
STEP_FILE_SUFFIXES = {".step", ".stp"}
DEFAULT_GUI_SEED = 42
DEFAULT_WINDOW_WIDTH = 1280
DEFAULT_WINDOW_HEIGHT = 940
WINDOW_MARGIN_X = 120
WINDOW_MARGIN_Y = 100
DEFAULT_LOG_HEIGHT = 7


def _banner_for_result(result: PackingRunResult) -> str:
    return get_result_banner(exit_code=result.exit_code, result_data=result.result_data)


def _format_client_result(result_data: dict[str, Any]) -> str:
    if not result_is_successful_fit(result_data):
        return format_result_summary(result_data)

    dims = result_data.get("recommended_dims_mm") or {}
    used_extents = result_data.get("used_extents_mm") or {}
    stats = result_data.get("stats") or {}
    constraints = result_data.get("constraints") or {}
    units = result_data.get("units") or {}
    report = ["Все детали помещаются"]

    if all(dims.get(axis) is not None for axis in ("L", "W", "H")):
        report.append(
            "Рекомендуемые размеры ящика: "
            f"{_format_mm_value(dims['L'])} x {_format_mm_value(dims['W'])} x {_format_mm_value(dims['H'])} мм"
        )
        report.append(
            f"Короткая длина возможна: {_format_mm_value(dims['L'])} мм — это только длина, "
            "а не весь размер ящика"
        )

    if all(used_extents.get(axis) is not None for axis in ("maxX", "maxY", "maxZ")):
        report.append(
            "Габариты уложенных деталей: "
            f"{_format_mm_value(used_extents['maxX'])} x {_format_mm_value(used_extents['maxY'])} x "
            f"{_format_mm_value(used_extents['maxZ'])} мм"
        )

    report.append("Детали могут быть повернуты на 90° и разложены по ширине/высоте")
    report.append(f"Деталей: {_as_int_value(stats.get('n_parts'))}")

    recommended_length = dims.get("L")
    reference_length = constraints.get("maxL")
    if isinstance(recommended_length, (int, float)) and isinstance(reference_length, (int, float)) and reference_length > 0:
        usage_percent = round(float(recommended_length) / float(reference_length) * 100)
        report.append(f"Использовано: {usage_percent}% длины")

    fill_ratio = stats.get("fill_ratio_bbox")
    if isinstance(fill_ratio, (int, float)):
        report.append(f"Заполнение по габаритам деталей: {fill_ratio * 100:.1f}%")

    if units.get("auto_scale_applied"):
        report.append("Размеры автоматически приведены к миллиметрам.")

    return "\n".join(report)


def _pick_step_files(dropped_paths: Sequence[str | bytes]) -> tuple[Path, ...]:
    picked_paths: list[Path] = []
    seen_paths: set[Path] = set()
    for raw_path in dropped_paths:
        decoded = os.fsdecode(raw_path).strip().strip("{}").strip('"')
        if not decoded:
            continue

        candidate = Path(decoded)
        if candidate.suffix.lower() not in STEP_FILE_SUFFIXES or not candidate.is_file():
            continue

        resolved_candidate = candidate.resolve()
        if resolved_candidate in seen_paths:
            continue

        seen_paths.add(resolved_candidate)
        picked_paths.append(candidate)

    return tuple(picked_paths)


def _pick_step_file(dropped_paths: Sequence[str | bytes]) -> Path | None:
    picked_paths = _pick_step_files(dropped_paths)
    return picked_paths[0] if picked_paths else None


def _format_input_summary(input_paths: Sequence[Path], *, total_items: int | None = None) -> str:
    if not input_paths:
        return "STEP-файлы пока не выбраны. Нажмите большую кнопку ниже, чтобы начать."

    resolved_total_items = total_items if total_items is not None else len(input_paths)
    if len(input_paths) == 1:
        if resolved_total_items > 1:
            return f"Выбран файл: {input_paths[0].name}. Кол-во: {resolved_total_items}"
        return f"Выбран файл: {input_paths[0].name}"

    preview_names = ", ".join(path.name for path in input_paths[:3])
    if len(input_paths) > 3:
        preview_names += f" и ещё {len(input_paths) - 3}"
    if resolved_total_items != len(input_paths):
        return (
            f"Выбрано STEP-файлов: {len(input_paths)}. "
            f"Всего деталей: {resolved_total_items}. {preview_names}"
        )
    return f"Выбрано STEP-файлов: {len(input_paths)}. {preview_names}"


class PackingGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Укладка деталей из STEP")
        self._set_initial_geometry()
        self.minsize(920, 700)
        self.configure(bg=PALETTE["bg"])

        self._process_context = multiprocessing.get_context("spawn")
        self._events: Any | None = None
        self._worker: multiprocessing.Process | None = None
        self._active_request: PackingRequest | None = None
        self._worker_stopped = False
        self._last_result: PackingRunResult | None = None
        self._fonts = self._build_fonts()
        self._suggested_output_dir: Path | None = None
        self._advanced_visible = False
        self._poll_after_id: str | None = None
        self._dragdrop_after_id: str | None = None
        self._layout_after_id: str | None = None
        self._form_canvas_window: int | None = None
        self._wrap_targets: list[tuple[tk.Widget, tk.Widget, int, int]] = []
        self._selected_input_paths: tuple[Path, ...] = ()
        self._input_quantity_vars: dict[Path, tk.StringVar] = {}
        self._update_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._update_check_in_progress = False
        self._update_download_in_progress = False
        self._updates_enabled = is_update_configured()
        self._auto_update_after_id: str | None = None

        self.input_var = tk.StringVar()
        self.input_count_var = tk.StringVar(value="0")
        self.update_status_var = tk.StringVar(value=self._default_update_status_text())
        self.input_summary_var = tk.StringVar(
            value="STEP-файл пока не выбран. Нажмите большую кнопку ниже, чтобы начать."
        )
        self.output_var = tk.StringVar()
        self.max_w_var = tk.StringVar(value="2400")
        self.max_h_var = tk.StringVar(value="1800")
        self.max_l_var = tk.StringVar(value="")
        self.gap_var = tk.StringVar(value="10")
        self.scale_var = tk.StringVar(value="1.0")
        self.status_var = tk.StringVar(
            value=(
                "1. Выберите STEP-файл. "
                "2. Проверьте параметры ящика. "
                "3. Нажмите «Рассчитать укладку»."
            )
        )

        self.input_summary_var.set("STEP-файлы пока не выбраны. Нажмите большую кнопку ниже, чтобы начать.")
        self.status_var.set(
            "1. Выберите один или несколько STEP-файлов. "
            "2. Проверьте параметры ящика. "
            "3. Нажмите «Рассчитать укладку»."
        )
        self.input_summary_var.trace_add("write", self._handle_dynamic_text_change)
        self.status_var.trace_add("write", self._handle_dynamic_text_change)

        self._configure_theme()
        self._build_widgets()
        self._set_status_banner(NEUTRAL_BANNER)
        self._refresh_update_controls()
        self.bind_all("<MouseWheel>", self._handle_global_mousewheel, add="+")
        self._dragdrop_after_id = self.after(0, self._configure_drag_and_drop)
        self._poll_after_id = self.after(150, self._poll_events)
        self._schedule_layout_refresh()
        if AUTO_CHECK_FOR_UPDATES and self._updates_enabled and can_apply_update():
            self._auto_update_after_id = self.after(1200, self._trigger_startup_update_check)

    def destroy(self) -> None:
        for after_attr in ("_dragdrop_after_id", "_poll_after_id", "_layout_after_id", "_auto_update_after_id"):
            after_id = getattr(self, after_attr, None)
            if after_id is None:
                continue
            try:
                self.after_cancel(after_id)
            except tk.TclError:
                pass
            setattr(self, after_attr, None)

        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass

        self._cleanup_worker(terminate=True)
        super().destroy()

    def _set_initial_geometry(self) -> None:
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = max(920, min(DEFAULT_WINDOW_WIDTH, screen_width - WINDOW_MARGIN_X))
        height = max(700, min(DEFAULT_WINDOW_HEIGHT, screen_height - WINDOW_MARGIN_Y))
        x_offset = max(0, (screen_width - width) // 2)
        y_offset = max(0, (screen_height - height) // 3)
        self.geometry(f"{width}x{height}+{x_offset}+{y_offset}")

    def _build_fonts(self) -> dict[str, font.Font]:
        font.nametofont("TkDefaultFont").configure(family="Segoe UI", size=11)
        font.nametofont("TkTextFont").configure(family="Segoe UI", size=11)
        font.nametofont("TkFixedFont").configure(family="Consolas", size=11)

        return {
            "title": font.Font(self, family="Segoe UI", size=21, weight="bold"),
            "subtitle": font.Font(self, family="Segoe UI", size=11),
            "section": font.Font(self, family="Segoe UI", size=12, weight="bold"),
            "body": font.Font(self, family="Segoe UI", size=11),
            "label": font.Font(self, family="Segoe UI", size=10),
            "button": font.Font(self, family="Segoe UI", size=11, weight="bold"),
            "mono": font.Font(self, family="Consolas", size=11),
            "status": font.Font(self, family="Segoe UI", size=12, weight="bold"),
        }

    def _default_update_status_text(self) -> str:
        if self._updates_enabled:
            return f"Версия {__version__}"
        return f"Версия {__version__}, обновления не настроены"

    def _refresh_update_controls(self) -> None:
        if not hasattr(self, "check_updates_button"):
            return

        button_state = "normal"
        button_text = "Проверить обновления"
        if self._update_download_in_progress:
            button_state = "disabled"
            button_text = "Скачивание..."
        elif self._update_check_in_progress:
            button_state = "disabled"
            button_text = "Проверка..."
        elif hasattr(self, "run_button") and str(self.run_button.cget("state")) == "disabled":
            button_state = "disabled"
        elif not self._updates_enabled:
            button_state = "disabled"
            button_text = "GitHub Releases не настроен"
        elif self._worker is not None and self._worker.is_alive():
            button_state = "disabled"

        self.check_updates_button.configure(text=button_text, state=button_state)

    def _trigger_startup_update_check(self) -> None:
        self._auto_update_after_id = None
        self._start_update_check(user_initiated=False)

    def _check_for_updates_clicked(self) -> None:
        self._start_update_check(user_initiated=True)

    def _start_update_check(self, *, user_initiated: bool) -> None:
        if self._update_check_in_progress or self._update_download_in_progress:
            return
        if not self._updates_enabled:
            if user_initiated:
                messagebox.showinfo("Обновления", "GitHub Releases для проверки обновлений не настроен.")
            return

        self._update_check_in_progress = True
        self.update_status_var.set("Проверка обновлений...")
        self._refresh_update_controls()
        threading.Thread(
            target=self._run_update_check_thread,
            kwargs={"user_initiated": user_initiated},
            daemon=True,
        ).start()

    def _run_update_check_thread(self, *, user_initiated: bool) -> None:
        result = check_for_updates(current_version=__version__)
        self._update_events.put(
            (
                "update_check_done",
                {
                    "result": result,
                    "user_initiated": user_initiated,
                },
            )
        )

    def _start_update_download(self, release_info: ReleaseInfo) -> None:
        if self._update_download_in_progress:
            return

        self._update_download_in_progress = True
        self.update_status_var.set(f"Скачивание версии {release_info.version}...")
        self._append_log(f"Найдено обновление {release_info.version}. Скачивание установщика...")
        self._refresh_update_controls()
        threading.Thread(
            target=self._run_update_download_thread,
            args=(release_info,),
            daemon=True,
        ).start()

    def _run_update_download_thread(self, release_info: ReleaseInfo) -> None:
        try:
            downloaded_update = download_update(release_info)
        except Exception as exc:
            self._update_events.put(
                (
                    "update_download_failed",
                    {
                        "error": str(exc),
                    },
                )
            )
            return

        self._update_events.put(
            (
                "update_download_done",
                {
                    "downloaded_update": downloaded_update,
                },
            )
        )
    def _configure_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=PALETTE["bg"], foreground=PALETTE["text"], font=self._fonts["body"])
        style.configure("App.TFrame", background=PALETTE["bg"])
        style.configure("SectionBody.TFrame", background=PALETTE["surface"])
        style.configure("BannerNeutral.TFrame", background=PALETTE["banner_neutral_bg"])
        style.configure("BannerSuccess.TFrame", background=PALETTE["banner_success_bg"])
        style.configure("BannerWarning.TFrame", background=PALETTE["banner_warning_bg"])
        style.configure("BannerError.TFrame", background=PALETTE["banner_error_bg"])

        style.configure(
            "Header.TLabel",
            background=PALETTE["bg"],
            foreground=PALETTE["text"],
            font=self._fonts["title"],
        )
        style.configure(
            "Muted.TLabel",
            background=PALETTE["bg"],
            foreground=PALETTE["muted"],
            font=self._fonts["subtitle"],
        )
        style.configure(
            "Section.TLabelframe",
            background=PALETTE["surface"],
            bordercolor=PALETTE["border"],
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "Section.TLabelframe.Label",
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            font=self._fonts["section"],
        )
        style.configure(
            "FieldLabel.TLabel",
            background=PALETTE["surface"],
            foreground=PALETTE["muted"],
            font=self._fonts["label"],
        )
        style.configure(
            "Caption.TLabel",
            background=PALETTE["surface"],
            foreground=PALETTE["muted"],
            font=self._fonts["label"],
        )
        style.configure(
            "BannerNeutralLabel.TLabel",
            background=PALETTE["banner_neutral_bg"],
            foreground=PALETTE["banner_neutral_fg"],
            font=self._fonts["label"],
        )
        style.configure(
            "BannerNeutralText.TLabel",
            background=PALETTE["banner_neutral_bg"],
            foreground=PALETTE["text"],
            font=self._fonts["status"],
        )
        style.configure(
            "BannerSuccessLabel.TLabel",
            background=PALETTE["banner_success_bg"],
            foreground=PALETTE["banner_success_fg"],
            font=self._fonts["label"],
        )
        style.configure(
            "BannerSuccessText.TLabel",
            background=PALETTE["banner_success_bg"],
            foreground=PALETTE["banner_success_fg"],
            font=self._fonts["status"],
        )
        style.configure(
            "BannerWarningLabel.TLabel",
            background=PALETTE["banner_warning_bg"],
            foreground=PALETTE["banner_warning_fg"],
            font=self._fonts["label"],
        )
        style.configure(
            "BannerWarningText.TLabel",
            background=PALETTE["banner_warning_bg"],
            foreground=PALETTE["banner_warning_fg"],
            font=self._fonts["status"],
        )
        style.configure(
            "BannerErrorLabel.TLabel",
            background=PALETTE["banner_error_bg"],
            foreground=PALETTE["banner_error_fg"],
            font=self._fonts["label"],
        )
        style.configure(
            "BannerErrorText.TLabel",
            background=PALETTE["banner_error_bg"],
            foreground=PALETTE["banner_error_fg"],
            font=self._fonts["status"],
        )
        style.configure(
            "Input.TEntry",
            fieldbackground=PALETTE["field"],
            background=PALETTE["field"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            padding=(12, 10),
        )
        style.map(
            "Input.TEntry",
            bordercolor=[("focus", PALETTE["accent"]), ("!focus", PALETTE["border"])],
            lightcolor=[("focus", PALETTE["accent"]), ("!focus", PALETTE["border"])],
            darkcolor=[("focus", PALETTE["accent"]), ("!focus", PALETTE["border"])],
        )
        style.configure(
            "Primary.TButton",
            background=PALETTE["accent"],
            foreground=PALETTE["accent_text"],
            font=self._fonts["button"],
            borderwidth=0,
            padding=(22, 13),
            relief="flat",
        )
        style.map(
            "Primary.TButton",
            background=[
                ("active", PALETTE["accent_hover"]),
                ("pressed", PALETTE["accent_hover"]),
                ("disabled", PALETTE["disabled"]),
            ],
            foreground=[("disabled", PALETTE["accent_text"])],
        )
        style.configure(
            "Hero.TButton",
            background=PALETTE["accent"],
            foreground=PALETTE["accent_text"],
            font=font.Font(self, family="Segoe UI", size=14, weight="bold"),
            borderwidth=0,
            padding=(28, 18),
            relief="flat",
        )
        style.map(
            "Hero.TButton",
            background=[
                ("active", PALETTE["accent_hover"]),
                ("pressed", PALETTE["accent_hover"]),
                ("disabled", PALETTE["disabled"]),
            ],
            foreground=[("disabled", PALETTE["accent_text"])],
        )
        style.configure(
            "Secondary.TButton",
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            font=self._fonts["body"],
            borderwidth=1,
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["surface"],
            darkcolor=PALETTE["surface"],
            padding=(14, 10),
            relief="flat",
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("active", PALETTE["surface_alt"]),
                ("pressed", PALETTE["surface_alt"]),
                ("disabled", PALETTE["bg"]),
            ],
            foreground=[("disabled", PALETTE["muted"])],
            bordercolor=[("focus", PALETTE["accent"]), ("!focus", PALETTE["border"])],
        )
        style.configure(
            "Ghost.TButton",
            background=PALETTE["bg"],
            foreground=PALETTE["muted"],
            font=self._fonts["body"],
            borderwidth=0,
            padding=(12, 10),
            relief="flat",
        )
        style.map(
            "Ghost.TButton",
            background=[("active", PALETTE["surface_alt"]), ("pressed", PALETTE["surface_alt"])],
            foreground=[("disabled", PALETTE["muted"])],
        )
        style.configure(
            "Vertical.TScrollbar",
            background=PALETTE["surface_alt"],
            troughcolor=PALETTE["bg"],
            bordercolor=PALETTE["border"],
            arrowcolor=PALETTE["muted"],
        )

    def _build_widgets(self) -> None:
        self.root_frame = ttk.Frame(self, padding=(28, 24, 28, 28), style="App.TFrame")
        self.root_frame.pack(fill="both", expand=True)
        self.root_frame.columnconfigure(0, weight=1)
        self.root_frame.rowconfigure(0, weight=1)

        scroll_shell = ttk.Frame(self.root_frame, style="App.TFrame")
        scroll_shell.grid(row=0, column=0, sticky="nsew", pady=(0, 18))
        scroll_shell.columnconfigure(0, weight=1)
        scroll_shell.rowconfigure(0, weight=1)

        self.scroll_canvas = tk.Canvas(
            scroll_shell,
            background=PALETTE["bg"],
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
        )
        self.scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self.form_scrollbar = ttk.Scrollbar(
            scroll_shell,
            orient="vertical",
            command=self.scroll_canvas.yview,
            style="Vertical.TScrollbar",
        )
        self.form_scrollbar.grid(row=0, column=1, sticky="ns", padx=(12, 0))
        self.scroll_canvas.configure(yscrollcommand=self.form_scrollbar.set)

        self.form_body = ttk.Frame(self.scroll_canvas, style="App.TFrame")
        self._form_canvas_window = self.scroll_canvas.create_window((0, 0), window=self.form_body, anchor="nw")
        self.scroll_canvas.bind("<Configure>", self._on_scroll_canvas_configure)
        self.form_body.bind("<Configure>", self._on_form_body_configure)
        self.form_body.columnconfigure(0, weight=1)

        header = ttk.Frame(self.form_body, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)

        ttk.Label(header, text="Укладка деталей из STEP-файла", style="Header.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        header_actions = ttk.Frame(header, style="App.TFrame")
        header_actions.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(20, 0))
        self.update_status_label = ttk.Label(
            header_actions,
            textvariable=self.update_status_var,
            style="Muted.TLabel",
            justify="right",
        )
        self.update_status_label.grid(row=0, column=0, sticky="e")
        self.check_updates_button = ttk.Button(
            header_actions,
            text="Проверить обновления",
            command=self._check_for_updates_clicked,
            style="Secondary.TButton",
        )
        self.check_updates_button.grid(row=1, column=0, sticky="e", pady=(10, 0))

        self.header_subtitle_label = ttk.Label(
            header,
            text=(
                "Сначала выберите STEP-файл. Основные параметры уже заполнены, "
                "поэтому в большинстве случаев после выбора файла можно сразу запускать расчёт."
            ),
            style="Muted.TLabel",
            justify="left",
        )
        self.header_subtitle_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self._register_wrap_label(self.header_subtitle_label, header, padding=8)

        self.select_input_button = ttk.Button(
            header,
            text="Выбрать STEP-файл",
            command=self._select_input_file,
            style="Hero.TButton",
        )
        self.select_input_button.grid(row=2, column=0, sticky="w", pady=(18, 10))
        self.select_input_button.configure(text="Выбрать STEP-файлы")

        self.input_summary_label = ttk.Label(
            header,
            textvariable=self.input_summary_var,
            style="Muted.TLabel",
            justify="left",
        )
        self.input_summary_label.grid(row=3, column=0, sticky="ew")
        self._register_wrap_label(self.input_summary_label, header, padding=8)
        self.header_subtitle_label.configure(
            text=(
                "Сначала выберите один или несколько STEP-файлов. Основные параметры уже заполнены, "
                "поэтому в большинстве случаев после выбора файлов можно сразу запускать расчёт."
            )
        )

        files = ttk.LabelFrame(
            self.form_body,
            text="1. STEP-файл и папка результата",
            style="Section.TLabelframe",
            padding=(20, 18, 20, 18),
        )
        files.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        files.columnconfigure(1, weight=1)

        ttk.Label(files, text="Выбранный STEP-файл", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w", pady=6
        )
        ttk.Entry(files, textvariable=self.input_var, style="Input.TEntry", state="readonly").grid(
            row=0,
            column=1,
            sticky="ew",
            pady=6,
            padx=(16, 0),
        )
        ttk.Label(files, text="Кол-во", style="FieldLabel.TLabel").grid(row=0, column=2, sticky="e", pady=6, padx=(12, 8))
        ttk.Entry(
            files,
            textvariable=self.input_count_var,
            style="Input.TEntry",
            state="readonly",
            width=6,
        ).grid(row=0, column=3, sticky="e", pady=6)

        ttk.Label(files, text="Файлы и количество", style="FieldLabel.TLabel").grid(
            row=1, column=0, sticky="nw", pady=6
        )
        self.input_items_frame = ttk.Frame(files, style="SectionBody.TFrame")
        self.input_items_frame.grid(row=1, column=1, columnspan=3, sticky="ew", pady=6, padx=(16, 0))
        self.input_items_frame.columnconfigure(0, weight=1)
        self._rebuild_input_rows()

        ttk.Label(files, text="Папка результата", style="FieldLabel.TLabel").grid(
            row=2, column=0, sticky="w", pady=6
        )
        output_row = ttk.Frame(files, style="SectionBody.TFrame")
        output_row.grid(row=2, column=1, sticky="ew", pady=6, padx=(16, 0))
        output_row.columnconfigure(0, weight=1)

        ttk.Entry(output_row, textvariable=self.output_var, style="Input.TEntry").grid(
            row=0, column=0, sticky="ew", padx=(0, 12)
        )
        self.output_button = ttk.Button(
            output_row,
            text="Изменить папку...",
            command=self._select_output_dir,
            style="Secondary.TButton",
        )
        self.output_button.grid(row=0, column=1, sticky="e")

        self.files_caption_label = ttk.Label(
            files,
            text="Если папку не менять, программа предложит путь автоматически после выбора STEP-файла.",
            style="Caption.TLabel",
            justify="left",
        )
        self.files_caption_label.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._register_wrap_label(self.files_caption_label, files, padding=48)
        self.files_caption_label.configure(
            text="Если папку не менять, программа предложит путь автоматически после выбора STEP-файлов."
        )

        params = ttk.LabelFrame(
            self.form_body,
            text="2. Параметры ящика",
            style="Section.TLabelframe",
            padding=(20, 18, 20, 18),
        )
        params.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        for column in range(2):
            params.columnconfigure(column, weight=1)

        self._entry_field(params, 0, 0, "Макс. ширина ящика, мм", self.max_w_var)
        self._entry_field(params, 0, 1, "Макс. высота ящика, мм", self.max_h_var)
        self._entry_field(
            params,
            1,
            0,
            "Макс. длина ящика, мм",
            self.max_l_var,
            hint="Оставьте поле пустым, если длину нужно подобрать автоматически.",
        )
        self._entry_field(params, 1, 1, "Зазор между деталями, мм", self.gap_var)

        self.advanced_toggle_button = ttk.Button(
            self.form_body,
            text="Показать дополнительные параметры",
            command=self._toggle_advanced,
            style="Secondary.TButton",
        )
        self.advanced_toggle_button.grid(row=3, column=0, sticky="w", pady=(0, 16))

        self.advanced_frame = ttk.LabelFrame(
            self.form_body,
            text="Дополнительно",
            style="Section.TLabelframe",
            padding=(20, 18, 20, 18),
        )
        self.advanced_frame.grid(row=4, column=0, sticky="ew", pady=(0, 4))
        self.advanced_frame.columnconfigure(0, weight=1)
        self._entry_field(
            self.advanced_frame,
            0,
            0,
            "Коррекция масштаба модели",
            self.scale_var,
            hint="Используйте только если модель открылась в неверных единицах.",
        )
        self.advanced_frame.grid_remove()

        self.footer_frame = ttk.Frame(self.root_frame, style="App.TFrame")
        self.footer_frame.grid(row=1, column=0, sticky="ew")
        self.footer_frame.columnconfigure(0, weight=1)

        self.action_bar = ttk.Frame(self.footer_frame, style="App.TFrame")
        self.action_bar.grid(row=0, column=0, sticky="ew", pady=(0, 18))
        self.action_bar.columnconfigure(0, weight=1)

        secondary_actions = ttk.Frame(self.action_bar, style="App.TFrame")
        secondary_actions.grid(row=0, column=0, sticky="w")

        self.open_folder_button = ttk.Button(
            secondary_actions,
            text="Открыть папку результата",
            command=self._open_result_dir,
            state="disabled",
            style="Secondary.TButton",
        )
        self.open_folder_button.grid(row=0, column=0, padx=(0, 8))
        self.open_top_button = ttk.Button(
            secondary_actions,
            text="Вид сверху",
            command=lambda: self._open_preview("top"),
            state="disabled",
            style="Secondary.TButton",
        )
        self.open_top_button.grid(row=0, column=1, padx=(0, 8))
        self.open_side_button = ttk.Button(
            secondary_actions,
            text="Вид сбоку",
            command=lambda: self._open_preview("side"),
            state="disabled",
            style="Secondary.TButton",
        )
        self.open_side_button.grid(row=0, column=2, padx=(0, 8))
        self.open_gif_button = ttk.Button(
            secondary_actions,
            text="Открыть анимацию",
            command=self._open_animation,
            state="disabled",
            style="Secondary.TButton",
        )
        self.open_gif_button.grid(row=0, column=3, padx=(0, 8))
        ttk.Button(secondary_actions, text="Выход", command=self.destroy, style="Ghost.TButton").grid(
            row=0, column=4
        )

        self.run_button = ttk.Button(
            self.action_bar,
            text="Рассчитать укладку",
            command=self._start_run,
            style="Primary.TButton",
        )
        self.run_button.grid(row=0, column=1, sticky="e")

        self.status_frame = ttk.LabelFrame(
            self.footer_frame,
            text="Ход расчёта",
            style="Section.TLabelframe",
            padding=(20, 18, 20, 20),
        )
        self.status_frame.grid(row=1, column=0, sticky="ew")
        self.status_frame.columnconfigure(0, weight=1)
        self.status_frame.rowconfigure(2, weight=1)
        self.status_frame.bind("<Configure>", self._schedule_layout_refresh)

        self.status_card = ttk.Frame(self.status_frame, padding=(16, 14, 16, 14))
        self.status_card.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.status_card.columnconfigure(0, weight=1)
        self.status_card.bind("<Configure>", self._schedule_layout_refresh)

        self.status_heading_label = ttk.Label(self.status_card, text="Текущий статус")
        self.status_heading_label.grid(row=0, column=0, sticky="w")
        self.status_message_label = ttk.Label(
            self.status_card,
            textvariable=self.status_var,
            justify="left",
        )
        self.status_message_label.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self._register_wrap_label(self.status_message_label, self.status_card, padding=32)

        ttk.Label(self.status_frame, text="Журнал", style="FieldLabel.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 8)
        )

        self.log_container = ttk.Frame(self.status_frame, style="SectionBody.TFrame")
        self.log_container.grid(row=2, column=0, sticky="ew")
        self.log_container.columnconfigure(0, weight=1)
        self.log_container.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            self.log_container,
            wrap="word",
            height=DEFAULT_LOG_HEIGHT,
            font=self._fonts["mono"],
            background=PALETTE["field"],
            foreground=PALETTE["text"],
            insertbackground=PALETTE["text"],
            selectbackground=PALETTE["accent_soft"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"],
            padx=14,
            pady=14,
            spacing1=2,
            spacing3=2,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scrollbar = ttk.Scrollbar(self.log_container, orient="vertical", command=self.log_text.yview)
        log_scrollbar.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        self.log_text.configure(yscrollcommand=log_scrollbar.set, state="disabled")

    def _register_wrap_label(
        self,
        label: tk.Widget,
        container: tk.Widget,
        *,
        padding: int,
        min_wrap: int = 160,
    ) -> None:
        self._wrap_targets.append((label, container, padding, min_wrap))

    def _handle_dynamic_text_change(self, *_args: object) -> None:
        self._schedule_layout_refresh()

    def _on_scroll_canvas_configure(self, event: tk.Event[tk.Misc]) -> None:
        if self._form_canvas_window is not None:
            self.scroll_canvas.itemconfigure(self._form_canvas_window, width=event.width)
        self._schedule_layout_refresh()

    def _on_form_body_configure(self, _event: tk.Event[tk.Misc]) -> None:
        self._schedule_layout_refresh()

    def _schedule_layout_refresh(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self._layout_after_id is not None:
            try:
                self.after_cancel(self._layout_after_id)
            except tk.TclError:
                pass
        self._layout_after_id = self.after_idle(self._refresh_layout)

    def _refresh_layout(self) -> None:
        self._layout_after_id = None
        if not self.winfo_exists():
            return

        scroll_region = self.scroll_canvas.bbox("all") or (0, 0, 0, 0)
        self.scroll_canvas.configure(scrollregion=scroll_region)
        for label, container, padding, min_wrap in self._wrap_targets:
            if not label.winfo_exists() or not container.winfo_exists():
                continue
            container_width = container.winfo_width() or container.winfo_reqwidth()
            wraplength = max(min_wrap, container_width - padding)
            if int(float(label.cget("wraplength") or 0)) != wraplength:
                label.configure(wraplength=wraplength)
        scroll_region = self.scroll_canvas.bbox("all") or (0, 0, 0, 0)
        self.scroll_canvas.configure(scrollregion=scroll_region)

    def _handle_global_mousewheel(self, event: tk.Event[tk.Misc]) -> str | None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return None
        if self._is_descendant(widget, self.log_text):
            return None
        if not self._is_descendant(widget, self.form_body) and not self._is_descendant(widget, self.scroll_canvas):
            return None
        if self.scroll_canvas.yview() == (0.0, 1.0):
            return None

        delta = event.delta
        if delta == 0:
            return None
        units = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        self.scroll_canvas.yview_scroll(units, "units")
        return "break"

    def _is_descendant(self, widget: tk.Widget, ancestor: tk.Widget) -> bool:
        current: tk.Widget | None = widget
        while current is not None:
            if current == ancestor:
                return True
            current = current.master
        return False

    def _set_status_banner(self, banner: str) -> None:
        style_map = {
            NEUTRAL_BANNER: ("BannerNeutral.TFrame", "BannerNeutralLabel.TLabel", "BannerNeutralText.TLabel"),
            SUCCESS_BANNER: ("BannerSuccess.TFrame", "BannerSuccessLabel.TLabel", "BannerSuccessText.TLabel"),
            NO_FIT_BANNER: ("BannerError.TFrame", "BannerErrorLabel.TLabel", "BannerErrorText.TLabel"),
            ERROR_BANNER: ("BannerError.TFrame", "BannerErrorLabel.TLabel", "BannerErrorText.TLabel"),
        }
        heading_map = {
            NEUTRAL_BANNER: "Текущий статус",
            SUCCESS_BANNER: "Укладка найдена",
            NO_FIT_BANNER: "Не помещается при заданных ограничениях",
            ERROR_BANNER: "Ошибка расчёта",
        }
        frame_style, label_style, text_style = style_map[banner]
        self.status_card.configure(style=frame_style)
        self.status_heading_label.configure(text=heading_map[banner], style=label_style)
        self.status_message_label.configure(style=text_style)

    def _entry_field(
        self,
        parent: tk.Misc,
        row: int,
        column: int,
        label: str,
        variable: tk.StringVar,
        hint: str | None = None,
    ) -> None:
        frame = ttk.Frame(parent, style="SectionBody.TFrame")
        right_padding = 14 if column == 0 else 0
        frame.grid(row=row, column=column, sticky="ew", padx=(0, right_padding), pady=(0, 12))
        frame.columnconfigure(0, weight=1)

        ttk.Label(frame, text=label, style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(frame, textvariable=variable, style="Input.TEntry").grid(
            row=1, column=0, sticky="ew", pady=(6, 0)
        )

        if hint:
            hint_label = ttk.Label(
                frame,
                text=hint,
                style="Caption.TLabel",
                justify="left",
            )
            hint_label.grid(row=2, column=0, sticky="ew", pady=(8, 0))
            self._register_wrap_label(hint_label, frame, padding=12, min_wrap=220)

    def _toggle_advanced(self) -> None:
        self._advanced_visible = not self._advanced_visible
        if self._advanced_visible:
            self.advanced_frame.grid()
            self.advanced_toggle_button.configure(text="Скрыть дополнительные параметры")
            self._schedule_layout_refresh()
            return

        self.advanced_frame.grid_remove()
        self.advanced_toggle_button.configure(text="Показать дополнительные параметры")
        self._schedule_layout_refresh()

    def _select_input_file(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Выберите STEP-файл",
            filetypes=[("STEP files", "*.step *.stp"), ("All files", "*.*")],
        )
        if not paths:
            return

        self._apply_input_paths(Path(path) for path in paths)

    def _configure_drag_and_drop(self) -> None:
        self._dragdrop_after_id = None
        if os.name != "nt" or windnd is None:
            return

        try:
            windnd.hook_dropfiles(self, func=self._handle_drop_files, force_unicode=True)
        except Exception:
            return

        if not self.input_var.get().strip():
            self.input_summary_var.set(
                "STEP-файл пока не выбран. Перетащите .step/.stp в окно или нажмите большую кнопку ниже."
            )

    def _handle_drop_files(self, dropped_paths: Sequence[str | bytes]) -> None:
        if self._worker is not None and self._worker.is_alive():
            self.after(0, lambda: self.status_var.set("Сначала дождитесь завершения текущего расчёта."))
            return

        step_paths = _pick_step_files(dropped_paths)
        if not step_paths:
            self.after(0, self._handle_invalid_drop)
            return
        self.after(0, lambda paths=step_paths: self._apply_input_paths(paths))

    def _handle_invalid_drop(self) -> None:
        message = "Перетащите файл с расширением .step или .stp."
        message = "Перетащите один или несколько файлов с расширением .step или .stp."
        self.status_var.set(message)
        self.input_summary_var.set(message)
        self._append_log(message)

    def _apply_input_path(self, input_path: Path) -> None:
        self._apply_input_paths((input_path,))

    def _rebuild_input_rows(self) -> None:
        for child in self.input_items_frame.winfo_children():
            child.destroy()

        if not self._selected_input_paths:
            ttk.Label(
                self.input_items_frame,
                text="После выбора файлов здесь можно задать количество для каждого STEP-файла.",
                style="Caption.TLabel",
                justify="left",
            ).grid(row=0, column=0, sticky="ew")
            return

        for row_index, input_path in enumerate(self._selected_input_paths):
            row = ttk.Frame(self.input_items_frame, style="SectionBody.TFrame")
            row.grid(row=row_index, column=0, sticky="ew", pady=(0, 6 if row_index < len(self._selected_input_paths) - 1 else 0))
            row.columnconfigure(0, weight=1)

            path_entry = ttk.Entry(row, style="Input.TEntry")
            path_entry.grid(row=0, column=0, sticky="ew")
            path_entry.insert(0, str(input_path))
            path_entry.configure(state="readonly")

            ttk.Entry(
                row,
                textvariable=self._input_quantity_vars[input_path],
                style="Input.TEntry",
                width=8,
            ).grid(row=0, column=1, sticky="e", padx=(12, 0))

    def _on_input_quantity_changed(self, *_args: object) -> None:
        self._refresh_input_summary_and_count()

    def _parse_input_quantity(self, input_path: Path, *, strict: bool) -> int:
        quantity_var = self._input_quantity_vars.get(input_path)
        raw_value = quantity_var.get().strip() if quantity_var is not None else "1"
        if not raw_value:
            if strict:
                raise ValueError(f"Количество для файла '{input_path.name}' должно быть целым числом больше нуля.")
            return 0

        try:
            quantity = int(raw_value)
        except ValueError as exc:
            if strict:
                raise ValueError(f"Количество для файла '{input_path.name}' должно быть целым числом больше нуля.") from exc
            return 0

        if quantity <= 0:
            if strict:
                raise ValueError(f"Количество для файла '{input_path.name}' должно быть больше нуля.")
            return 0
        return quantity

    def _expanded_input_paths(self, *, strict: bool) -> tuple[Path, ...]:
        if not self._selected_input_paths:
            input_text = self.input_var.get().strip()
            return (Path(input_text),) if input_text else ()

        expanded_paths: list[Path] = []
        for input_path in self._selected_input_paths:
            quantity = self._parse_input_quantity(input_path, strict=strict)
            expanded_paths.extend(input_path for _ in range(quantity))
        return tuple(expanded_paths)

    def _refresh_input_summary_and_count(self) -> None:
        total_items = sum(
            self._parse_input_quantity(input_path, strict=False)
            for input_path in self._selected_input_paths
        )
        self.input_count_var.set(str(total_items))
        self.input_summary_var.set(
            _format_input_summary(self._selected_input_paths, total_items=total_items)
        )

    def _apply_input_paths(self, input_paths: Sequence[Path]) -> None:
        normalized_paths = tuple(Path(path) for path in input_paths)
        if not normalized_paths:
            return

        previous_quantities = {
            path: quantity_var.get()
            for path, quantity_var in self._input_quantity_vars.items()
        }
        self._selected_input_paths = normalized_paths
        self._input_quantity_vars = {}
        for input_path in normalized_paths:
            quantity_var = tk.StringVar(value=previous_quantities.get(input_path, "1"))
            quantity_var.trace_add("write", self._on_input_quantity_changed)
            self._input_quantity_vars[input_path] = quantity_var

        self.input_var.set("; ".join(str(path) for path in normalized_paths))
        self._rebuild_input_rows()
        self._refresh_input_summary_and_count()

        primary_input_path = normalized_paths[0]
        if self._should_refresh_output_dir():
            self._suggested_output_dir = make_default_output_dir(primary_input_path)
            self.output_var.set(str(self._suggested_output_dir))

        if len(normalized_paths) == 1:
            self.status_var.set("STEP-файл выбран. Проверьте параметры ниже и нажмите «Рассчитать укладку».")
        else:
            self.status_var.set("STEP-файлы выбраны. Проверьте параметры ниже и нажмите «Рассчитать укладку».")

    def _select_output_dir(self) -> None:
        initial = self.output_var.get().strip() or str(Path.home())
        path = filedialog.askdirectory(title="Выберите папку результата", initialdir=initial)
        if path:
            self.output_var.set(path)
            self._suggested_output_dir = None

    def _should_refresh_output_dir(self) -> bool:
        current_output = self.output_var.get().strip()
        if not current_output:
            return True
        if self._suggested_output_dir is None:
            return False
        return Path(current_output) == self._suggested_output_dir

    def _start_run(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return

        try:
            request = self._build_request()
        except ValueError as exc:
            messagebox.showerror("Неверные параметры", str(exc))
            return

        self._last_result = None
        self._set_running(True)
        self._set_status_banner(NEUTRAL_BANNER)
        self._clear_log()
        self.status_var.set("Чтение STEP-файла...")
        self._append_log("Запуск расчёта.")
        self._append_log("Чтение STEP-файла...")
        self.after(10, lambda req=request: self._start_worker_process(req))

    def _build_request(self) -> PackingRequest:
        input_path_text = self.input_var.get().strip()
        if not input_path_text:
            raise ValueError("Нужно выбрать хотя бы один STEP-файл.")
        if not input_path_text:
            raise ValueError("Нужно выбрать STEP-файл.")

        input_paths = self._expanded_input_paths(strict=True)
        if not input_paths:
            raise ValueError("Нужно выбрать хотя бы один STEP-файл.")

        input_path = input_paths[0]
        if not input_path.exists():
            raise ValueError(f"STEP-файл не найден: {input_path}")

        missing_paths = [path for path in input_paths if not path.exists()]
        if missing_paths:
            raise ValueError(f"STEP-файл не найден: {missing_paths[0]}")

        output_text = self.output_var.get().strip()
        out_dir = Path(output_text) if output_text else make_default_output_dir(input_path)
        self.output_var.set(str(out_dir))
        if not output_text:
            self._suggested_output_dir = out_dir

        max_l_text = self.max_l_var.get().strip()
        max_l = _positive_float(max_l_text, "Макс. длина ящика") if max_l_text else None

        return PackingRequest(
            input_path=input_path,
            input_paths=input_paths,
            out_dir=out_dir,
            max_w=_positive_float(self.max_w_var.get(), "Макс. ширина ящика"),
            max_h=_positive_float(self.max_h_var.get(), "Макс. высота ящика"),
            max_l=max_l,
            gap=_nonnegative_float(self.gap_var.get(), "Зазор между деталями"),
            scale=_positive_float(self.scale_var.get(), "Коррекция масштаба модели"),
            seed=DEFAULT_GUI_SEED,
        )

    def _prepare_run(self, request: PackingRequest) -> None:
        self._start_worker_process(request)
        return
        try:
            parts, units = extract_parts_from_step(
                input_path=request.input_path,
                scale=request.scale,
            )
        except Exception as exc:
            result = create_failure_run_result(
                request,
                message=str(exc),
                with_console=False,
            )
            self._handle_result(result)
            return

        self.status_var.set("Укладка деталей...")
        self._append_log(f"STEP-файл прочитан. Деталей найдено: {len(parts)}.")
        self._worker = threading.Thread(
            target=self._run_job_thread,
            args=(request, parts, units),
            daemon=True,
        )
        self._worker.start()

    def _run_job_thread(
        self,
        request: PackingRequest,
        parts: list[Any],
        units: dict[str, Any],
    ) -> None:
        raise RuntimeError("Thread-based worker path is no longer used.")
        result = run_packing_job(
            request,
            with_console=False,
            status_callback=lambda message: self._events.put(("status", message)),
            preloaded_parts=parts,
            preloaded_units=units,
        )
        self._events.put(("done", result))

    def _start_worker_process(self, request: PackingRequest) -> None:
        self._cleanup_worker()
        self._active_request = request
        self._worker_stopped = False

        try:
            self._events = self._process_context.Queue()
            self._worker = self._process_context.Process(
                target=run_packing_job_in_subprocess,
                args=(request, self._events),
                daemon=True,
            )
            self._worker.start()
        except Exception as exc:
            self._cleanup_worker(terminate=True)
            result = create_failure_run_result(
                request,
                message=f"Failed to start background worker: {exc}",
                with_console=False,
            )
            self._handle_result(result)

    def _cleanup_worker(self, *, terminate: bool = False) -> None:
        worker = self._worker
        events = self._events
        self._worker = None
        self._events = None
        self._active_request = None
        self._worker_stopped = False

        if worker is not None:
            try:
                if terminate and worker.is_alive():
                    worker.terminate()
                worker.join(timeout=1.0 if terminate else 0.2)
            except Exception:
                pass

        if events is not None:
            try:
                events.close()
            except (AttributeError, OSError, ValueError):
                pass
            try:
                events.join_thread()
            except (AttributeError, RuntimeError, OSError, ValueError):
                pass

    def _handle_worker_failure(self, message: str) -> None:
        request = self._active_request
        if request is None:
            self._set_running(False)
            self._set_status_banner(ERROR_BANNER)
            self.status_var.set("Непредвиденная ошибка интерфейса.")
            self._append_log(message)
            return

        result = create_failure_run_result(
            request,
            message=message,
            with_console=False,
        )
        self._handle_result(result)

    def _handle_worker_exit_without_result(self) -> None:
        request = self._active_request
        if request is None:
            return

        exit_code = self._worker.exitcode if self._worker is not None else None
        if exit_code in (None, 0):
            message = "Background worker finished without returning a result."
        else:
            message = f"Background worker exited unexpectedly with code {exit_code}."
        self._handle_worker_failure(message)

    def _poll_events(self) -> None:
        self._poll_after_id = None
        while self._events is not None:
            try:
                event_type, payload = self._events.get_nowait()
            except (OSError, EOFError):
                self._handle_worker_exit_without_result()
                break
            except queue.Empty:
                break

            if event_type == "status":
                message = str(payload)
                if message != self.status_var.get():
                    self.status_var.set(message)
                    self._append_log(message)
            elif event_type == "done":
                self._handle_result(payload)
                return
            elif event_type == "worker_error":
                self._handle_worker_failure(str(payload))
                return

        while True:
            try:
                event_type, payload = self._update_events.get_nowait()
            except queue.Empty:
                break

            if event_type == "update_check_done":
                self._handle_update_check_result(payload)
            elif event_type == "update_download_done":
                self._handle_update_download_done(payload)
            elif event_type == "update_download_failed":
                self._handle_update_download_failed(payload)

        if self._worker is not None and self._active_request is not None:
            if self._worker.is_alive():
                self._worker_stopped = False
            elif self._worker_stopped:
                self._handle_worker_exit_without_result()
                return
            else:
                self._worker_stopped = True

        self._poll_after_id = self.after(150, self._poll_events)

    def _handle_update_check_result(self, payload: object) -> None:
        self._update_check_in_progress = False
        self._refresh_update_controls()
        if not isinstance(payload, dict):
            self.update_status_var.set(self._default_update_status_text())
            return

        result = payload.get("result")
        user_initiated = bool(payload.get("user_initiated"))
        if not isinstance(result, UpdateCheckResult):
            self.update_status_var.set(self._default_update_status_text())
            if user_initiated:
                messagebox.showerror("Обновления", "Неверный ответ модуля обновлений.")
            return

        if result.error:
            self.update_status_var.set(self._default_update_status_text())
            if user_initiated:
                messagebox.showerror("Обновления", result.error)
            return

        if result.update_available and result.release_info is not None:
            self.update_status_var.set(f"Доступна версия {result.release_info.version}")
            prompt = (
                f"Доступна новая версия {result.release_info.version}.\n"
                f"Сейчас установлена версия {result.current_version}.\n\n"
                "Скачать и установить обновление сейчас?"
            )
            if messagebox.askyesno("Доступно обновление", prompt):
                self._start_update_download(result.release_info)
            return

        self.update_status_var.set(f"Версия {result.current_version} актуальна")
        if user_initiated:
            messagebox.showinfo(
                "Обновления",
                f"Уже установлена актуальная версия {result.current_version}.",
            )

    def _handle_update_download_done(self, payload: object) -> None:
        self._update_download_in_progress = False
        self._refresh_update_controls()
        if not isinstance(payload, dict):
            self.update_status_var.set(self._default_update_status_text())
            messagebox.showerror("Обновления", "Неверный ответ загрузки обновления.")
            return

        downloaded_update = payload.get("downloaded_update")
        if not isinstance(downloaded_update, DownloadedUpdate):
            self.update_status_var.set(self._default_update_status_text())
            messagebox.showerror("Обновления", "Не удалось подготовить обновление.")
            return

        self.update_status_var.set(f"Обновление {downloaded_update.release_info.version} скачано")
        self._append_log(f"Скачан установщик: {downloaded_update.installer_path}")
        if not can_apply_update():
            messagebox.showinfo(
                "Обновления",
                "Установщик скачан, но автоматическая установка доступна только в собранном EXE.\n\n"
                f"Путь: {downloaded_update.installer_path}",
            )
            return

        should_install = messagebox.askyesno(
            "Установить обновление",
            "Приложение закроется, установит новую версию и запустится снова.\n\nПродолжить?",
        )
        if not should_install:
            return

        try:
            start_update_installer(
                downloaded_update,
                app_executable=Path(sys.executable),
                current_pid=os.getpid(),
            )
        except Exception as exc:
            messagebox.showerror("Обновления", str(exc))
            return

        self._append_log("Запущен тихий установщик обновления.")
        self.destroy()

    def _handle_update_download_failed(self, payload: object) -> None:
        self._update_download_in_progress = False
        self._refresh_update_controls()
        error_message = "Не удалось скачать обновление."
        if isinstance(payload, dict):
            error_message = str(payload.get("error") or error_message)
        self.update_status_var.set(self._default_update_status_text())
        messagebox.showerror("Обновления", error_message)
    def _handle_result(self, result: object) -> None:
        self._cleanup_worker()
        self._set_running(False)
        if not isinstance(result, PackingRunResult):
            self._set_status_banner(ERROR_BANNER)
            self.status_var.set("Непредвиденная ошибка интерфейса.")
            self._append_log("Неверный тип результата.")
            return

        self._last_result = result
        self.open_folder_button.configure(state="normal")

        if result.preview_top_path is not None and result.preview_top_path.exists():
            self.open_top_button.configure(state="normal")
        if result.preview_side_path is not None and result.preview_side_path.exists():
            self.open_side_button.configure(state="normal")
        if result.preview_gif_path is not None and result.preview_gif_path.exists():
            self.open_gif_button.configure(state="normal")

        banner = _banner_for_result(result)
        summary = _format_client_result(result.result_data)
        self._set_status_banner(banner)
        self.status_var.set(summary)
        self._append_log(summary)

        if result.exit_code == 0 and result_is_successful_fit(result.result_data):
            self._append_log(f"Результаты сохранены в: {result.out_dir}")
            messagebox.showinfo("Готово", summary)
        else:
            self._append_log(f"Подробности смотрите в: {result.log_path}")
            self._append_log(f"Результаты сохранены в: {result.out_dir}")
            if banner == NO_FIT_BANNER or result_is_constraint_failure(result.result_data):
                messagebox.showerror("Не помещается", summary)
            else:
                messagebox.showerror("Ошибка упаковки", summary)

    def _open_result_dir(self) -> None:
        if self._last_result is None:
            return
        _open_path(self._last_result.out_dir)

    def _open_preview(self, which: str) -> None:
        if self._last_result is None:
            return
        path = self._last_result.preview_top_path if which == "top" else self._last_result.preview_side_path
        if path is not None and path.exists():
            _open_path(path)

    def _open_animation(self) -> None:
        if self._last_result is None:
            return
        path = self._last_result.preview_gif_path
        if path is not None and path.exists():
            _open_path(path)

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.run_button.configure(state=state)
        self.select_input_button.configure(state=state)
        self.output_button.configure(state=state)
        self.advanced_toggle_button.configure(state=state)
        if running:
            self.open_folder_button.configure(state="disabled")
            self.open_top_button.configure(state="disabled")
            self.open_side_button.configure(state="disabled")
            self.open_gif_button.configure(state="disabled")
        self._refresh_update_controls()

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


def _positive_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{label}: нужно ввести число.") from exc
    if parsed <= 0:
        raise ValueError(f"{label}: значение должно быть больше нуля.")
    return parsed


def _nonnegative_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{label}: нужно ввести число.") from exc
    if parsed < 0:
        raise ValueError(f"{label}: значение не может быть отрицательным.") from exc
    return parsed
def _open_path(path: Path) -> None:
    resolved = Path(path).resolve()
    try:
        os.startfile(str(resolved))  # type: ignore[attr-defined]
    except AttributeError:
        messagebox.showinfo("Путь", str(resolved))


def _format_mm_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.1f}"
    return str(value)


def _as_int_value(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    return 0


def main() -> None:
    multiprocessing.freeze_support()
    app = PackingGui()
    app.mainloop()


if __name__ == "__main__":
    main()
