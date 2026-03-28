from __future__ import annotations

import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk
from typing import Any, Sequence

try:
    import windnd
except ImportError:
    windnd = None

from packing_mvp import __version__
from packing_mvp.catalog import (
    DEFAULT_GAP_MM,
    DEFAULT_TRUCK_HEIGHT_MM,
    DEFAULT_TRUCK_LENGTH_MM,
    DEFAULT_TRUCK_WIDTH_MM,
    CatalogItem,
    PackProject,
)
from packing_mvp.presentation import (
    format_result_summary,
    get_result_banner,
    result_is_constraint_failure,
    result_is_successful_fit,
)
from packing_mvp.project_io import load_project, save_project
from packing_mvp.runner import (
    PackingRequest,
    PackingRunResult,
    create_failure_run_result,
    make_default_output_dir,
    run_packing_job,
)
from packing_mvp.step_extract import extract_catalog_item
from packing_mvp.visualization import open_3d_preview

STEP_FILE_SUFFIXES = {".step", ".stp"}
DEFAULT_GUI_SEED = 42
SUCCESS_BANNER = "success"
NO_FIT_BANNER = "no_fit"
ERROR_BANNER = "error"
NEUTRAL_BANNER = "neutral"
DEFAULT_WINDOW_WIDTH = 1320
DEFAULT_WINDOW_HEIGHT = 940
WINDOW_MARGIN_X = 120
WINDOW_MARGIN_Y = 100

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


def _banner_for_result(result: PackingRunResult) -> str:
    return get_result_banner(exit_code=result.exit_code, result_data=result.result_data)


def _format_client_result(result_data: dict[str, Any]) -> str:
    if not result_is_successful_fit(result_data):
        return format_result_summary(result_data)
    used = result_data.get("used_extents_mm") or {}
    lines = [format_result_summary(result_data)]
    if all(used.get(axis) is not None for axis in ("maxX", "maxY", "maxZ")):
        lines.append(
            "Габариты уложенной сцены (мм): "
            f"{_format_mm_value(used['maxX'])} x {_format_mm_value(used['maxY'])} x {_format_mm_value(used['maxZ'])}"
        )
    if (result_data.get("units") or {}).get("auto_scale_applied"):
        lines.append("Размеры исходного STEP автоматически приведены к миллиметрам.")
    return "\n".join(lines)


def _pick_step_files(dropped_paths: Sequence[str | bytes]) -> tuple[Path, ...]:
    picked: list[Path] = []
    seen: set[Path] = set()
    for raw_path in dropped_paths:
        decoded = os.fsdecode(raw_path).strip().strip("{}").strip('"')
        if not decoded:
            continue
        candidate = Path(decoded)
        if candidate.suffix.lower() not in STEP_FILE_SUFFIXES or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        picked.append(candidate)
    return tuple(picked)


def _pick_step_file(dropped_paths: Sequence[str | bytes]) -> Path | None:
    paths = _pick_step_files(dropped_paths)
    return paths[0] if paths else None


def _input_summary(items: Sequence[CatalogItem]) -> str:
    if not items:
        return "STEP-файлы пока не выбраны. Загрузите грузовые места для расчёта."
    return (
        f"Загружено типов STEP: {len(items)}. "
        f"Всего грузовых мест: {sum(item.quantity for item in items)}."
    )


class PackingGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Укладка грузовых мест из STEP")
        self._set_initial_geometry()
        self.minsize(1000, 760)
        self.configure(bg=PALETTE["bg"])

        self._fonts = self._build_fonts()
        self._configure_theme()
        self._catalog_items: list[CatalogItem] = []
        self._input_quantity_vars: dict[Path, tk.StringVar] = {}
        self._worker: threading.Thread | None = None
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._poll_after_id: str | None = None
        self._running = False
        self._advanced_visible = False
        self._selected_item_id: str | None = None
        self._last_result: PackingRunResult | None = None

        self.input_var = tk.StringVar()
        self.input_count_var = tk.StringVar(value="0")
        self.input_summary_var = tk.StringVar(value=_input_summary(()))
        self.update_status_var = tk.StringVar(value=f"Версия {__version__}")
        self.output_var = tk.StringVar()
        self.max_l_var = tk.StringVar(value=str(int(DEFAULT_TRUCK_LENGTH_MM)))
        self.max_w_var = tk.StringVar(value=str(int(DEFAULT_TRUCK_WIDTH_MM)))
        self.max_h_var = tk.StringVar(value=str(int(DEFAULT_TRUCK_HEIGHT_MM)))
        self.gap_var = tk.StringVar(value=str(int(DEFAULT_GAP_MM)))
        self.scale_var = tk.StringVar(value="1.0")
        self.status_var = tk.StringVar(
            value="Загрузите STEP-файлы, проверьте габариты грузовых мест и запустите расчёт укладки."
        )
        self._selected_dims_l_var = tk.StringVar()
        self._selected_dims_w_var = tk.StringVar()
        self._selected_dims_h_var = tk.StringVar()
        self._selected_qty_var = tk.StringVar(value="1")

        self._build_ui()
        self._refresh_catalog()
        self._set_status_banner(NEUTRAL_BANNER)
        self._poll_after_id = self.after(150, self._poll_events)
        self.after(50, self._configure_dragdrop)
        self.bind("<Configure>", self._on_window_configure)
        self.bind_all("<MouseWheel>", self._handle_global_mousewheel, add="+")

    def destroy(self) -> None:
        if self._poll_after_id is not None:
            try:
                self.after_cancel(self._poll_after_id)
            except tk.TclError:
                pass
        try:
            self.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        super().destroy()

    def _set_initial_geometry(self) -> None:
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = max(1000, min(DEFAULT_WINDOW_WIDTH, screen_width - WINDOW_MARGIN_X))
        height = max(760, min(DEFAULT_WINDOW_HEIGHT, screen_height - WINDOW_MARGIN_Y))
        x_offset = max(0, (screen_width - width) // 2)
        y_offset = max(0, (screen_height - height) // 3)
        self.geometry(f"{width}x{height}+{x_offset}+{y_offset}")

    def _build_fonts(self) -> dict[str, font.Font]:
        font.nametofont("TkDefaultFont").configure(family="Segoe UI", size=10)
        font.nametofont("TkTextFont").configure(family="Segoe UI", size=10)
        font.nametofont("TkFixedFont").configure(family="Consolas", size=10)
        return {
            "title": font.Font(self, family="Segoe UI", size=20, weight="bold"),
            "subtitle": font.Font(self, family="Segoe UI", size=11),
            "section": font.Font(self, family="Segoe UI", size=12, weight="bold"),
            "body": font.Font(self, family="Segoe UI", size=10),
            "label": font.Font(self, family="Segoe UI", size=10),
            "button": font.Font(self, family="Segoe UI", size=10, weight="bold"),
            "status": font.Font(self, family="Segoe UI", size=11, weight="bold"),
            "hero": font.Font(self, family="Segoe UI", size=12, weight="bold"),
        }

    def _configure_theme(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(".", background=PALETTE["bg"], foreground=PALETTE["text"], font=self._fonts["body"])
        style.configure("App.TFrame", background=PALETTE["bg"])
        style.configure("Card.TFrame", background=PALETTE["surface"])
        style.configure("HeaderCard.TFrame", background=PALETTE["surface_alt"])
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
        style.configure("Header.TLabel", background=PALETTE["surface_alt"], foreground=PALETTE["text"], font=self._fonts["title"])
        style.configure("Muted.TLabel", background=PALETTE["bg"], foreground=PALETTE["muted"], font=self._fonts["subtitle"])
        style.configure("MutedCard.TLabel", background=PALETTE["surface_alt"], foreground=PALETTE["muted"], font=self._fonts["subtitle"])
        style.configure("FieldLabel.TLabel", background=PALETTE["surface"], foreground=PALETTE["muted"], font=self._fonts["label"])
        style.configure("CardCount.TLabel", background=PALETTE["surface_alt"], foreground=PALETTE["accent"], font=self._fonts["section"])
        style.configure(
            "Input.TEntry",
            fieldbackground=PALETTE["field"],
            background=PALETTE["field"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            padding=(10, 8),
        )
        style.map(
            "Input.TEntry",
            bordercolor=[("focus", PALETTE["accent"]), ("!focus", PALETTE["border"])],
            lightcolor=[("focus", PALETTE["accent"]), ("!focus", PALETTE["border"])],
            darkcolor=[("focus", PALETTE["accent"]), ("!focus", PALETTE["border"])],
        )
        style.configure("Primary.TButton", background=PALETTE["accent"], foreground=PALETTE["accent_text"], borderwidth=0, padding=(18, 11), font=self._fonts["button"])
        style.map(
            "Primary.TButton",
            background=[("active", PALETTE["accent_hover"]), ("pressed", PALETTE["accent_hover"]), ("disabled", PALETTE["disabled"])],
            foreground=[("disabled", PALETTE["accent_text"])],
        )
        style.configure("Hero.TButton", background=PALETTE["accent"], foreground=PALETTE["accent_text"], borderwidth=0, padding=(24, 15), font=self._fonts["hero"])
        style.map(
            "Hero.TButton",
            background=[("active", PALETTE["accent_hover"]), ("pressed", PALETTE["accent_hover"]), ("disabled", PALETTE["disabled"])],
            foreground=[("disabled", PALETTE["accent_text"])],
        )
        style.configure("Secondary.TButton", background=PALETTE["surface"], foreground=PALETTE["text"], borderwidth=1, bordercolor=PALETTE["border"], padding=(14, 10), font=self._fonts["body"])
        style.map(
            "Secondary.TButton",
            background=[("active", PALETTE["surface_alt"]), ("pressed", PALETTE["surface_alt"]), ("disabled", PALETTE["bg"])],
            foreground=[("disabled", PALETTE["muted"])],
            bordercolor=[("focus", PALETTE["accent"]), ("!focus", PALETTE["border"])],
        )
        style.configure("Ghost.TButton", background=PALETTE["bg"], foreground=PALETTE["muted"], borderwidth=0, padding=(8, 6), font=self._fonts["body"])
        style.map("Ghost.TButton", background=[("active", PALETTE["surface_alt"]), ("pressed", PALETTE["surface_alt"])], foreground=[("disabled", PALETTE["muted"])])
        style.configure("Treeview", background=PALETTE["surface"], fieldbackground=PALETTE["surface"], foreground=PALETTE["text"], bordercolor=PALETTE["border"], rowheight=28, relief="flat")
        style.map("Treeview", background=[("selected", PALETTE["accent_soft"])], foreground=[("selected", PALETTE["text"])])
        style.configure("Treeview.Heading", background=PALETTE["surface_alt"], foreground=PALETTE["text"], relief="flat", font=self._fonts["button"], padding=(8, 8))
        style.configure("Vertical.TScrollbar", background=PALETTE["surface_alt"], troughcolor=PALETTE["bg"], bordercolor=PALETTE["border"], arrowcolor=PALETTE["muted"])

    def _build_ui(self) -> None:
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        outer = ttk.Frame(self, style="App.TFrame")
        outer.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_rowconfigure(1, weight=0)
        outer.grid_columnconfigure(0, weight=1)

        body = ttk.Frame(outer, style="App.TFrame")
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        self.scroll_canvas = tk.Canvas(body, bg=PALETTE["bg"], highlightthickness=0, bd=0, relief="flat")
        self.scroll_canvas.grid(row=0, column=0, sticky="nsew")
        ybar = ttk.Scrollbar(body, orient="vertical", command=self.scroll_canvas.yview, style="Vertical.TScrollbar")
        ybar.grid(row=0, column=1, sticky="ns")
        self.scroll_canvas.configure(yscrollcommand=ybar.set)
        self.form_frame = ttk.Frame(self.scroll_canvas, style="App.TFrame")
        self.form_window = self.scroll_canvas.create_window((0, 0), window=self.form_frame, anchor="nw")
        self.form_frame.bind("<Configure>", lambda _e: self._update_scrollregion())
        self.scroll_canvas.bind("<Configure>", self._resize_form)

        header = ttk.Frame(self.form_frame, style="HeaderCard.TFrame", padding=(20, 18))
        header.pack(fill="x", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)
        ttk.Label(header, text="Укладка грузовых мест из STEP", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Загрузите один или несколько STEP-файлов, уточните габариты и количество, затем рассчитайте схему загрузки кузова.",
            style="MutedCard.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))
        ttk.Label(header, textvariable=self.input_summary_var, style="MutedCard.TLabel").grid(row=2, column=0, sticky="w")
        ttk.Label(header, textvariable=self.input_count_var, style="CardCount.TLabel").grid(row=0, column=1, rowspan=3, sticky="e")

        cat = ttk.Labelframe(self.form_frame, text="Каталог грузовых мест", style="Section.TLabelframe")
        cat.pack(fill="both", expand=True, pady=(0, 12))
        top = ttk.Frame(cat, style="Card.TFrame")
        top.pack(fill="x", padx=12, pady=(12, 8))
        self.select_input_button = ttk.Button(top, text="Загрузить STEP-файлы", command=self._select_files, style="Hero.TButton")
        self.select_input_button.pack(side="left")
        ttk.Label(top, textvariable=self.input_var, style="FieldLabel.TLabel").pack(side="left", fill="x", expand=True, padx=(14, 10))
        count_wrap = ttk.Frame(top, style="Card.TFrame")
        count_wrap.pack(side="right")
        ttk.Label(count_wrap, text="Всего мест:", style="FieldLabel.TLabel").pack(side="left", padx=(0, 6))
        ttk.Label(count_wrap, textvariable=self.input_count_var, style="CardCount.TLabel").pack(side="left")
        cols = ("filename", "dims", "qty", "override", "path")
        self.catalog_tree = ttk.Treeview(cat, columns=cols, show="headings", height=8)
        for col, text, width in (
            ("filename", "Имя файла", 240),
            ("dims", "Д x Ш x В (мм)", 170),
            ("qty", "Кол-во", 80),
            ("override", "Ручн.", 80),
            ("path", "Источник", 540),
        ):
            self.catalog_tree.heading(col, text=text)
            self.catalog_tree.column(col, width=width, anchor="w" if col in {"filename", "path"} else "center")
        self.catalog_tree.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.catalog_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        edit = ttk.Labelframe(self.form_frame, text="Выбранный тип", style="Section.TLabelframe")
        edit.pack(fill="x", pady=(0, 12))
        row = ttk.Frame(edit, style="Card.TFrame")
        row.pack(fill="x", padx=12, pady=(12, 8))
        for i in range(8):
            row.grid_columnconfigure(i, weight=1 if i in {1, 3, 5, 7} else 0)
        for col, text, var in (
            (0, "Длина", self._selected_dims_l_var),
            (2, "Ширина", self._selected_dims_w_var),
            (4, "Высота", self._selected_dims_h_var),
            (6, "Количество", self._selected_qty_var),
        ):
            ttk.Label(row, text=text, style="FieldLabel.TLabel").grid(row=0, column=col, sticky="w")
            ttk.Entry(row, textvariable=var, width=12, style="Input.TEntry").grid(row=0, column=col + 1, sticky="ew", padx=(8, 14 if col < 6 else 0))
        btns = ttk.Frame(edit, style="Card.TFrame")
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="Применить изменения", command=self._apply_selected, style="Primary.TButton").pack(side="left")
        ttk.Button(btns, text="Удалить из проекта", command=self._remove_selected, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Удалить STEP-файл", command=self._delete_selected_file, style="Secondary.TButton").pack(side="left", padx=(8, 0))

        truck = ttk.Labelframe(self.form_frame, text="Параметры кузова", style="Section.TLabelframe")
        truck.pack(fill="x", pady=(0, 12))
        row = ttk.Frame(truck, style="Card.TFrame")
        row.pack(fill="x", padx=12, pady=12)
        for i in range(8):
            row.grid_columnconfigure(i, weight=1 if i in {1, 3, 5, 7} else 0)
        for col, text, var in (
            (0, "Длина", self.max_l_var),
            (2, "Ширина", self.max_w_var),
            (4, "Высота", self.max_h_var),
            (6, "Зазор", self.gap_var),
        ):
            ttk.Label(row, text=text, style="FieldLabel.TLabel").grid(row=0, column=col, sticky="w")
            ttk.Entry(row, textvariable=var, style="Input.TEntry").grid(row=0, column=col + 1, sticky="ew", padx=(8, 14 if col < 6 else 0))

        adv_wrap = ttk.Frame(self.form_frame, style="App.TFrame")
        adv_wrap.pack(fill="x", pady=(0, 12))
        self.advanced_toggle_button = ttk.Button(adv_wrap, text="Показать дополнительные параметры", command=self._toggle_advanced, style="Ghost.TButton")
        self.advanced_toggle_button.pack(anchor="w", pady=(0, 8))
        self.advanced_frame = ttk.Labelframe(adv_wrap, text="Дополнительно", style="Section.TLabelframe")
        row = ttk.Frame(self.advanced_frame, style="Card.TFrame")
        row.pack(fill="x", padx=12, pady=12)
        row.grid_columnconfigure(1, weight=1)
        ttk.Label(row, text="Папка результата", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Entry(row, textvariable=self.output_var, style="Input.TEntry").grid(row=0, column=1, sticky="ew", padx=(8, 12))
        self.output_button = ttk.Button(row, text="Обзор", command=self._select_output, style="Secondary.TButton")
        self.output_button.grid(row=0, column=2, sticky="w")
        ttk.Label(row, text="Масштаб", style="FieldLabel.TLabel").grid(row=0, column=3, sticky="w", padx=(14, 0))
        ttk.Entry(row, textvariable=self.scale_var, width=10, style="Input.TEntry").grid(row=0, column=4, sticky="ew", padx=(8, 0))

        foot = ttk.Frame(outer, style="App.TFrame")
        foot.grid(row=1, column=0, sticky="ew")
        foot.grid_columnconfigure(0, weight=1)
        self.action_bar = ttk.Frame(foot, style="App.TFrame")
        self.action_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        self.run_button = ttk.Button(self.action_bar, text="Рассчитать укладку", command=self._start_run, style="Primary.TButton")
        self.run_button.pack(side="left")
        ttk.Button(self.action_bar, text="Сохранить проект", command=self._save_project, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(self.action_bar, text="Загрузить проект", command=self._load_project_file, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        self.open_folder_button = ttk.Button(self.action_bar, text="Открыть результат", command=self._open_result_dir, state="disabled", style="Secondary.TButton")
        self.open_folder_button.pack(side="left", padx=(8, 0))
        self.open_top_button = ttk.Button(self.action_bar, text="Вид сверху", command=lambda: self._open_preview("top"), state="disabled", style="Secondary.TButton")
        self.open_top_button.pack(side="left", padx=(8, 0))
        self.open_side_button = ttk.Button(self.action_bar, text="Вид сбоку", command=lambda: self._open_preview("side"), state="disabled", style="Secondary.TButton")
        self.open_side_button.pack(side="left", padx=(8, 0))
        self.open_gif_button = ttk.Button(self.action_bar, text="GIF", command=self._open_animation, state="disabled", style="Secondary.TButton")
        self.open_gif_button.pack(side="left", padx=(8, 0))
        ttk.Button(self.action_bar, text="3D-предпросмотр", command=self._open_3d, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        self.check_updates_button = ttk.Button(self.action_bar, text="Проверить обновления", command=self._check_updates_clicked, style="Ghost.TButton")
        self.check_updates_button.pack(side="right")

        self.status_frame = ttk.Frame(foot, style="App.TFrame")
        self.status_frame.grid(row=1, column=0, sticky="ew")
        self.banner_label = tk.Label(
            self.status_frame,
            textvariable=self.status_var,
            justify="left",
            anchor="w",
            bg=PALETTE["banner_neutral_bg"],
            fg=PALETTE["banner_neutral_fg"],
            padx=14,
            pady=14,
            wraplength=1100,
            font=self._fonts["status"],
        )
        self.banner_label.pack(fill="x")
        ttk.Label(self.status_frame, textvariable=self.update_status_var, style="Muted.TLabel").pack(anchor="e", pady=(6, 0))
        self.log_container = ttk.Labelframe(foot, text="Журнал", style="Section.TLabelframe")
        self.log_container.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.log_text = tk.Text(
            self.log_container,
            height=8,
            wrap="word",
            state="disabled",
            bg=PALETTE["field"],
            fg=PALETTE["text"],
            relief="flat",
            padx=10,
            pady=10,
            insertbackground=PALETTE["text"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent"],
        )
        self.log_text.pack(fill="both", expand=True, padx=12, pady=12)

    def _configure_dragdrop(self) -> None:
        if windnd is not None:
            try:
                windnd.hook_dropfiles(self, func=lambda paths: self._apply_input_paths(_pick_step_files(paths)))
            except Exception:
                pass

    def _handle_global_mousewheel(self, event: tk.Event[tk.Misc]) -> str | None:
        widget = getattr(event, "widget", None)
        if widget is None:
            widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None:
            return None
        if self._is_descendant(widget, self.log_container):
            return None
        if not any(
            self._is_descendant(widget, anchor)
            for anchor in (self.form_frame, self.scroll_canvas, self.action_bar, self.status_frame)
        ):
            return None
        if self.scroll_canvas.yview() == (0.0, 1.0):
            return None

        delta = getattr(event, "delta", 0)
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

    def _on_window_configure(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is self:
            self.banner_label.configure(wraplength=max(self.winfo_width() - 140, 480))

    def _resize_form(self, event: tk.Event[tk.Canvas]) -> None:
        self.scroll_canvas.itemconfigure(self.form_window, width=event.width)
        self._update_scrollregion()

    def _update_scrollregion(self) -> None:
        bbox = self.scroll_canvas.bbox("all")
        if bbox:
            self.scroll_canvas.configure(scrollregion=bbox)

    def _toggle_advanced(self) -> None:
        self._advanced_visible = not self._advanced_visible
        if self._advanced_visible:
            self.advanced_frame.pack(fill="x")
            self.advanced_toggle_button.configure(text="Скрыть дополнительные параметры")
        else:
            self.advanced_frame.pack_forget()
            self.advanced_toggle_button.configure(text="Показать дополнительные параметры")
        self.update_idletasks()
        self._update_scrollregion()

    def _select_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Выберите STEP-файлы", filetypes=[("STEP files", "*.stp *.step"), ("All files", "*.*")])
        if paths:
            self._apply_input_paths(Path(path) for path in paths)

    def _select_output(self) -> None:
        current = self.output_var.get().strip() or None
        selected = filedialog.askdirectory(title="Выберите папку результата", initialdir=current)
        if selected:
            self.output_var.set(selected)

    def _save_project(self) -> None:
        items = self._catalog_from_ui()
        if not items:
            messagebox.showerror("Проект", "Сначала загрузите хотя бы один STEP-файл.")
            return
        path = filedialog.asksaveasfilename(title="Сохранить проект", defaultextension=".packproj", filetypes=[("Проект укладки", "*.packproj")])
        if not path:
            return
        project = PackProject(items=tuple(items), result=(self._last_result.result_data if self._last_result else None))
        save_project(project, Path(path))
        self._append_log(f"Проект сохранён: {path}")

    def _load_project_file(self) -> None:
        path = filedialog.askopenfilename(title="Открыть проект", filetypes=[("Проект укладки", "*.packproj")])
        if not path:
            return
        project = load_project(Path(path))
        self.max_l_var.set(str(int(project.truck.length_mm)))
        self.max_w_var.set(str(int(project.truck.width_mm)))
        self.max_h_var.set(str(int(project.truck.height_mm)))
        self.gap_var.set(str(int(project.truck.gap_mm)))
        self._catalog_items = list(project.items)
        self._input_quantity_vars = {Path(item.source_path).resolve(): tk.StringVar(value=str(item.quantity)) for item in self._catalog_items}
        self._refresh_catalog()
        self._append_log(f"Проект загружен: {path}")
        if project.result:
            self.status_var.set(_format_client_result(project.result))
            self._set_status_banner(SUCCESS_BANNER if result_is_successful_fit(project.result) else NO_FIT_BANNER)

    def _apply_input_paths(self, input_paths: Sequence[Path]) -> None:
        existing = {Path(item.source_path).resolve() for item in self._catalog_items}
        for path in input_paths:
            resolved = Path(path).resolve()
            if resolved in existing:
                continue
            item_id = f"item_{len(self._catalog_items) + 1:03d}"
            try:
                item = extract_catalog_item(resolved, item_id=item_id, quantity=1, scale=float(self.scale_var.get() or "1.0"))
            except Exception as exc:
                self._append_log(f"Не удалось определить габариты для {resolved.name}: {exc}")
                item = CatalogItem(item_id=item_id, filename=resolved.name, source_path=str(resolved), detected_dims_mm=(1.0, 1.0, 1.0), dimensions_mm=(1.0, 1.0, 1.0), quantity=1, manual_override=True)
            self._catalog_items.append(item)
            self._input_quantity_vars[resolved] = tk.StringVar(value=str(item.quantity))
            existing.add(resolved)
        if self._catalog_items and not self.output_var.get().strip():
            self.output_var.set(str(make_default_output_dir(Path(self._catalog_items[0].source_path))))
        if self._catalog_items:
            self.status_var.set("STEP-файлы загружены. Проверьте размеры и количество, затем запустите расчёт.")
        self._refresh_catalog()

    def _refresh_catalog(self) -> None:
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        for item in self._catalog_items:
            path = Path(item.source_path).resolve()
            qty_var = self._input_quantity_vars.setdefault(path, tk.StringVar(value=str(item.quantity)))
            qty_var.set(str(item.quantity))
            self.catalog_tree.insert("", "end", iid=item.item_id, values=(item.filename, f"{_format_mm_value(item.dimensions_mm[0])} x {_format_mm_value(item.dimensions_mm[1])} x {_format_mm_value(item.dimensions_mm[2])}", item.quantity, "да" if item.manual_override else "нет", item.source_path))
        self.input_var.set("; ".join(item.source_path for item in self._catalog_items))
        self.input_count_var.set(str(sum(item.quantity for item in self._catalog_items)))
        self.input_summary_var.set(_input_summary(self._catalog_items))
        if self._catalog_items:
            if self._selected_item_id not in {item.item_id for item in self._catalog_items}:
                self._selected_item_id = self._catalog_items[0].item_id
            self.catalog_tree.selection_set(self._selected_item_id)
            self._load_selected()
        else:
            self._selected_item_id = None
            self._selected_dims_l_var.set("")
            self._selected_dims_w_var.set("")
            self._selected_dims_h_var.set("")
            self._selected_qty_var.set("1")
        self.update_idletasks()
        self._update_scrollregion()

    def _on_tree_select(self, _event: object | None = None) -> None:
        selection = self.catalog_tree.selection()
        if selection:
            self._selected_item_id = selection[0]
            self._load_selected()

    def _selected_item(self) -> CatalogItem | None:
        for item in self._catalog_items:
            if item.item_id == self._selected_item_id:
                return item
        return None

    def _load_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        self._selected_dims_l_var.set(_format_mm_value(item.dimensions_mm[0]))
        self._selected_dims_w_var.set(_format_mm_value(item.dimensions_mm[1]))
        self._selected_dims_h_var.set(_format_mm_value(item.dimensions_mm[2]))
        self._selected_qty_var.set(str(item.quantity))

    def _apply_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        updated = item.with_dimensions((_positive_float(self._selected_dims_l_var.get(), "Длина"), _positive_float(self._selected_dims_w_var.get(), "Ширина"), _positive_float(self._selected_dims_h_var.get(), "Высота"))).with_quantity(_positive_int(self._selected_qty_var.get(), "Количество"))
        for idx, current in enumerate(self._catalog_items):
            if current.item_id == item.item_id:
                self._catalog_items[idx] = updated
                self._input_quantity_vars[Path(updated.source_path).resolve()].set(str(updated.quantity))
                break
        self._append_log(f"Параметры обновлены для {updated.filename}.")
        self._refresh_catalog()

    def _remove_selected(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        self._catalog_items = [current for current in self._catalog_items if current.item_id != item.item_id]
        self._input_quantity_vars.pop(Path(item.source_path).resolve(), None)
        self._selected_item_id = self._catalog_items[0].item_id if self._catalog_items else None
        self._append_log(f"Удалено из проекта: {item.filename}")
        self._refresh_catalog()

    def _delete_selected_file(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        if not messagebox.askyesno("Удаление STEP-файла", f"Удалить файл {item.filename} с диска?"):
            return
        try:
            Path(item.source_path).unlink(missing_ok=False)
        except FileNotFoundError:
            messagebox.showerror("Удаление STEP-файла", "Файл уже отсутствует на диске.")
            return
        self._append_log(f"STEP-файл удалён: {item.source_path}")
        self._remove_selected()

    def _catalog_from_ui(self) -> list[CatalogItem]:
        items: list[CatalogItem] = []
        for item in self._catalog_items:
            path = Path(item.source_path).resolve()
            items.append(item.with_quantity(_positive_int(self._input_quantity_vars[path].get(), "Количество")))
        return items

    def _build_request(self) -> PackingRequest:
        items = self._catalog_from_ui()
        if not items:
            raise ValueError("Нужно выбрать хотя бы один STEP-файл.")
        self.input_count_var.set(str(sum(item.quantity for item in items)))
        self.input_summary_var.set(_input_summary(items))
        out_dir = Path(self.output_var.get().strip()) if self.output_var.get().strip() else make_default_output_dir(Path(items[0].source_path))
        self.output_var.set(str(out_dir))
        return PackingRequest(
            input_path=Path(items[0].source_path),
            input_paths=tuple(Path(item.source_path) for item in items),
            input_quantities=tuple(item.quantity for item in items),
            catalog_items=tuple(items),
            out_dir=out_dir,
            max_l=_positive_float(self.max_l_var.get(), "Длина кузова"),
            max_w=_positive_float(self.max_w_var.get(), "Ширина кузова"),
            max_h=_positive_float(self.max_h_var.get(), "Высота кузова"),
            gap=_nonnegative_float(self.gap_var.get(), "Зазор"),
            scale=_positive_float(self.scale_var.get(), "Масштаб"),
            seed=DEFAULT_GUI_SEED,
        )

    def _start_run(self) -> None:
        if self._running:
            return
        try:
            request = self._build_request()
        except Exception as exc:
            messagebox.showerror("Укладка", str(exc))
            return
        self._clear_log()
        self._append_log("Запуск фонового расчёта укладки...")
        self.status_var.set("Расчёт укладки выполняется...")
        self._set_status_banner(NEUTRAL_BANNER)
        self._set_running(True)

        def worker() -> None:
            try:
                result = run_packing_job(request, with_console=False, status_callback=lambda message: self._events.put(("status", message)))
            except Exception as exc:
                result = create_failure_run_result(request, message=str(exc), with_console=False)
            self._events.put(("done", result))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _poll_events(self) -> None:
        self._poll_after_id = None
        while True:
            try:
                event_type, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if event_type == "status":
                self.status_var.set(str(payload))
                self._append_log(str(payload))
            elif event_type == "done":
                self._handle_result(payload)
                break
        self._poll_after_id = self.after(150, self._poll_events)

    def _handle_result(self, result: object) -> None:
        self._set_running(False)
        if not isinstance(result, PackingRunResult):
            self._set_status_banner(ERROR_BANNER)
            self.status_var.set("Получен некорректный ответ от фонового расчёта.")
            self._append_log("Получен некорректный ответ от фонового расчёта.")
            return
        self._last_result = result
        summary = _format_client_result(result.result_data)
        self.status_var.set(summary)
        self._append_log(summary)
        self._set_status_banner(_banner_for_result(result))
        self.open_folder_button.configure(state="normal")
        self.open_top_button.configure(state="normal" if result.preview_top_path and result.preview_top_path.exists() else "disabled")
        self.open_side_button.configure(state="normal" if result.preview_side_path and result.preview_side_path.exists() else "disabled")
        self.open_gif_button.configure(state="normal" if result.preview_gif_path and result.preview_gif_path.exists() else "disabled")
        if result.exit_code == 0 and result_is_successful_fit(result.result_data):
            messagebox.showinfo("Расчёт завершён", summary)
        elif _banner_for_result(result) == NO_FIT_BANNER or result_is_constraint_failure(result.result_data):
            messagebox.showerror("Не все грузовые места помещаются", summary)
        else:
            messagebox.showerror("Ошибка расчёта", summary)

    def _open_result_dir(self) -> None:
        if self._last_result:
            _open_path(self._last_result.out_dir)

    def _open_preview(self, which: str) -> None:
        if self._last_result is None:
            return
        path = self._last_result.preview_top_path if which == "top" else self._last_result.preview_side_path
        if path and path.exists():
            _open_path(path)

    def _open_animation(self) -> None:
        if self._last_result and self._last_result.preview_gif_path and self._last_result.preview_gif_path.exists():
            _open_path(self._last_result.preview_gif_path)

    def _open_3d(self) -> None:
        if self._last_result is None:
            return
        try:
            open_3d_preview(self, self._last_result.result_data)
        except Exception as exc:
            messagebox.showerror("3D-предпросмотр", str(exc))

    def _check_updates_clicked(self) -> None:
        self.update_status_var.set(f"Версия {__version__}. Автоматические обновления в этой сборке не настроены.")

    def _set_running(self, running: bool) -> None:
        self._running = running
        state = "disabled" if running else "normal"
        for widget in (self.run_button, self.select_input_button, self.advanced_toggle_button, self.check_updates_button):
            widget.configure(state=state)
        if hasattr(self, "output_button"):
            self.output_button.configure(state=state)

    def _set_status_banner(self, banner: str) -> None:
        if banner == SUCCESS_BANNER:
            bg, fg = PALETTE["banner_success_bg"], PALETTE["banner_success_fg"]
        elif banner == NO_FIT_BANNER:
            bg, fg = PALETTE["banner_warning_bg"], PALETTE["banner_warning_fg"]
        elif banner == ERROR_BANNER:
            bg, fg = PALETTE["banner_error_bg"], PALETTE["banner_error_fg"]
        else:
            bg, fg = PALETTE["banner_neutral_bg"], PALETTE["banner_neutral_fg"]
        self.banner_label.configure(bg=bg, fg=fg)

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message.rstrip() + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


def _positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{label}: введите целое число.") from exc
    if parsed <= 0:
        raise ValueError(f"{label}: значение должно быть больше нуля.")
    return parsed


def _positive_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{label}: введите число.") from exc
    if parsed <= 0:
        raise ValueError(f"{label}: значение должно быть больше нуля.")
    return parsed


def _nonnegative_float(value: str, label: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{label}: введите число.") from exc
    if parsed < 0:
        raise ValueError(f"{label}: значение не может быть отрицательным.")
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


def main() -> None:
    app = PackingGui()
    app.mainloop()


if __name__ == "__main__":
    main()
