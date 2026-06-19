#!/usr/bin/env python3
"""一个简单的截图打马赛克和涂鸦工具，专门为长截图适配。"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import colorchooser, filedialog, messagebox, ttk
except ModuleNotFoundError as exc:
    print(
        "缺少 tkinter，无法启动 GUI。",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc

try:
    from PIL import Image, ImageOps, ImageTk
except ModuleNotFoundError as exc:
    print("缺少 Pillow。请先运行：python -m pip install pillow", file=sys.stderr)
    raise SystemExit(1) from exc


Image.MAX_IMAGE_PIXELS = None

MIN_ZOOM = 0.05
MAX_ZOOM = 8.0
DISPLAY_MARGIN = 96
DEFAULT_FILL_COLOR = "#000000"
IMAGE_FILETYPES = (
    ("图片文件", "*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff"),
    ("PNG", "*.png"),
    ("JPEG", "*.jpg *.jpeg"),
    ("WebP", "*.webp"),
    ("所有文件", "*.*"),
)


class MosaicTool(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("长截图打码工具")
        self.geometry("1120x820")
        self.minsize(760, 520)

        self.image: Optional[Image.Image] = None
        self.source_path: Optional[Path] = None
        self.undo_stack: list[tuple[tuple[int, int, int, int], Image.Image]] = []

        self.zoom = 1.0
        self.tool_mode = tk.StringVar(value="mosaic")
        self.block_size = tk.IntVar(value=18)
        self.fill_color = tk.StringVar(value=DEFAULT_FILL_COLOR)
        self.zoom_text = tk.StringVar(value="100%")
        self.status_text = tk.StringVar(value="打开图片后选择工具，按住鼠标左键拖出矩形，松开即应用。")

        self.image_id: Optional[int] = None
        self.selection_id: Optional[int] = None
        self.color_button: Optional[tk.Button] = None
        self.drag_start: Optional[tuple[float, float]] = None
        self.rendered_photo: Optional[ImageTk.PhotoImage] = None
        self.pending_redraw: Optional[str] = None
        self.modified = False

        self._build_ui()
        self._bind_events()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(8, 6))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(17, weight=1)

        ttk.Button(toolbar, text="打开", command=self.open_image).grid(row=0, column=0, padx=(0, 6))
        ttk.Button(toolbar, text="另存为", command=self.save_as).grid(row=0, column=1, padx=(0, 12))
        ttk.Button(toolbar, text="撤销", command=self.undo).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(toolbar, text="重置", command=self.reset_image).grid(row=0, column=3, padx=(0, 16))

        ttk.Label(toolbar, text="工具").grid(row=0, column=4, padx=(0, 6))
        ttk.Radiobutton(
            toolbar,
            text="马赛克",
            value="mosaic",
            variable=self.tool_mode,
            command=self._on_tool_change,
        ).grid(row=0, column=5, padx=(0, 4))
        ttk.Radiobutton(
            toolbar,
            text="涂色",
            value="fill",
            variable=self.tool_mode,
            command=self._on_tool_change,
        ).grid(row=0, column=6, padx=(0, 8))

        self.color_button = tk.Button(
            toolbar,
            text="颜色",
            width=6,
            command=self.choose_fill_color,
            relief="groove",
        )
        self.color_button.grid(row=0, column=7, padx=(0, 16))
        self._update_color_button()

        ttk.Label(toolbar, text="块大小").grid(row=0, column=8, padx=(0, 6))
        block_scale = ttk.Scale(
            toolbar,
            from_=4,
            to=96,
            orient="horizontal",
            variable=self.block_size,
            command=self._on_block_scale,
            length=150,
        )
        block_scale.grid(row=0, column=9, padx=(0, 4))
        tk.Spinbox(
            toolbar,
            from_=2,
            to=256,
            width=4,
            textvariable=self.block_size,
            command=self._on_block_spin,
        ).grid(row=0, column=10, padx=(0, 16))

        ttk.Button(toolbar, text="-", width=3, command=lambda: self.zoom_by(0.85)).grid(
            row=0, column=11, padx=(0, 4)
        )
        ttk.Label(toolbar, textvariable=self.zoom_text, width=6, anchor="center").grid(row=0, column=12)
        ttk.Button(toolbar, text="+", width=3, command=lambda: self.zoom_by(1.18)).grid(
            row=0, column=13, padx=(4, 6)
        )
        ttk.Button(toolbar, text="适应宽度", command=self.fit_width).grid(row=0, column=14, padx=(0, 6))
        ttk.Button(toolbar, text="100%", command=lambda: self.set_zoom(1.0)).grid(row=0, column=15)

        viewer = ttk.Frame(self)
        viewer.grid(row=1, column=0, sticky="nsew")
        viewer.columnconfigure(0, weight=1)
        viewer.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(viewer, bg="#242424", highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.y_scroll = ttk.Scrollbar(viewer, orient="vertical", command=self._yview)
        self.y_scroll.grid(row=0, column=1, sticky="ns")
        self.x_scroll = ttk.Scrollbar(viewer, orient="horizontal", command=self._xview)
        self.x_scroll.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=self.x_scroll.set, yscrollcommand=self.y_scroll.set)

        status = ttk.Frame(self, padding=(8, 4))
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(0, weight=1)
        ttk.Label(status, textvariable=self.status_text, anchor="w").grid(row=0, column=0, sticky="ew")
        ttk.Label(status, text="Ctrl+滚轮缩放  Shift+滚轮横向滚动  右键/中键拖动画布").grid(
            row=0, column=1, padx=(12, 0)
        )

    def _bind_events(self) -> None:
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_select_start)
        self.canvas.bind("<B1-Motion>", self._on_select_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_select_release)

        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", self._on_linux_mousewheel)
        self.canvas.bind("<Button-5>", self._on_linux_mousewheel)

        self.canvas.bind("<ButtonPress-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_drag)

        self.bind_all("<Control-o>", lambda _event: self.open_image())
        self.bind_all("<Control-s>", lambda _event: self.save_as())
        self.bind_all("<Control-z>", lambda _event: self.undo())
        self.bind_all("<Control-plus>", lambda _event: self.zoom_by(1.18))
        self.bind_all("<Control-equal>", lambda _event: self.zoom_by(1.18))
        self.bind_all("<Control-minus>", lambda _event: self.zoom_by(0.85))
        self.bind_all("<Control-0>", lambda _event: self.set_zoom(1.0))

    def open_image(self) -> None:
        if not self._confirm_discard_changes():
            return

        filename = filedialog.askopenfilename(title="选择图片", filetypes=IMAGE_FILETYPES)
        if not filename:
            return

        try:
            image = self._load_image(Path(filename))
        except Exception as exc:  # noqa: BLE001 - report GUI errors cleanly.
            messagebox.showerror("打开失败", f"无法打开图片：\n{exc}")
            return

        self.image = image
        self.source_path = Path(filename)
        self.undo_stack.clear()
        self.modified = False
        self.zoom = 1.0
        self._update_zoom_text()
        self.image_id = None
        self.rendered_photo = None
        self.canvas.delete("all")

        self._update_scrollregion()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.after(50, self.fit_width)
        self._update_title()
        self.status_text.set(f"已打开：{self.source_path.name}，尺寸 {image.width} x {image.height}")

    def save_as(self) -> bool:
        if self.image is None:
            self.status_text.set("请先打开图片。")
            return False

        default_ext = ".png"
        initial_name = "redacted.png"
        if self.source_path is not None:
            default_ext = self.source_path.suffix or ".png"
            initial_name = f"{self.source_path.stem}_redacted{default_ext}"

        filename = filedialog.asksaveasfilename(
            title="另存为",
            initialfile=initial_name,
            defaultextension=default_ext,
            filetypes=IMAGE_FILETYPES,
        )
        if not filename:
            return False

        try:
            self._save_image(Path(filename))
        except Exception as exc:  # noqa: BLE001 - report GUI errors cleanly.
            messagebox.showerror("保存失败", f"无法保存图片：\n{exc}")
            return False

        self.modified = False
        self._update_title()
        self.status_text.set(f"已保存：{filename}")
        return True

    def undo(self) -> None:
        if self.image is None:
            return
        if not self.undo_stack:
            self.status_text.set("没有可撤销的操作。")
            return

        bbox, patch = self.undo_stack.pop()
        self.image.paste(patch, bbox)
        self.modified = True
        self._update_title()
        self.request_redraw()
        self.status_text.set(f"已撤销区域：{self._format_bbox(bbox)}")

    def reset_image(self) -> None:
        if self.source_path is None:
            return
        if not self._confirm_discard_changes():
            return

        try:
            self.image = self._load_image(self.source_path)
        except Exception as exc:  # noqa: BLE001 - report GUI errors cleanly.
            messagebox.showerror("重置失败", f"无法重新读取原图：\n{exc}")
            return

        self.undo_stack.clear()
        self.modified = False
        self._update_scrollregion()
        self.request_redraw()
        self._update_title()
        self.status_text.set("已恢复到原图。")

    def choose_fill_color(self) -> None:
        _rgb, color = colorchooser.askcolor(color=self.fill_color.get(), title="选择涂色颜色")
        if not color:
            return

        self.fill_color.set(color)
        self._update_color_button()
        self.status_text.set(f"当前涂色颜色：{color}")

    def fit_width(self) -> None:
        if self.image is None:
            return
        view_width = max(self.canvas.winfo_width() - 20, 1)
        if self.image.width <= 0:
            return
        target_zoom = min(1.0, max(MIN_ZOOM, view_width / self.image.width))
        if math.isclose(target_zoom, self.zoom, rel_tol=0.001):
            self.request_redraw()
            return
        self.set_zoom(target_zoom)

    def zoom_by(self, factor: float) -> None:
        self.set_zoom(self.zoom * factor)

    def set_zoom(self, zoom: float, anchor: Optional[tuple[int, int]] = None) -> None:
        if self.image is None:
            return

        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if math.isclose(new_zoom, self.zoom, rel_tol=0.001):
            return

        if anchor is None:
            anchor = (self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2)

        old_zoom = self.zoom
        anchor_image_x = self.canvas.canvasx(anchor[0]) / old_zoom
        anchor_image_y = self.canvas.canvasy(anchor[1]) / old_zoom

        self.zoom = new_zoom
        self._update_scrollregion()
        self._move_view_to_anchor(anchor_image_x, anchor_image_y, anchor)
        self._update_zoom_text()
        self.request_redraw()

    def request_redraw(self) -> None:
        if self.pending_redraw is not None:
            return
        self.pending_redraw = self.after(15, self._redraw_visible_image)

    def _load_image(self, path: Path) -> Image.Image:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened)
            image.load()

        if image.mode not in {"RGB", "RGBA", "L"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        return image

    def _save_image(self, path: Path) -> None:
        if self.image is None:
            return

        suffix = path.suffix.lower()
        image = self.image
        save_kwargs: dict[str, object] = {}

        if suffix in {".jpg", ".jpeg"}:
            image = self._flatten_for_jpeg(image)
            save_kwargs.update({"quality": 95, "subsampling": 0})
        elif suffix == ".webp":
            save_kwargs.update({"quality": 95})

        image.save(path, **save_kwargs)

    def _flatten_for_jpeg(self, image: Image.Image) -> Image.Image:
        if image.mode == "RGB":
            return image
        if image.mode == "RGBA":
            background = Image.new("RGB", image.size, "white")
            background.paste(image, mask=image.getchannel("A"))
            return background
        return image.convert("RGB")

    def _redraw_visible_image(self) -> None:
        self.pending_redraw = None
        if self.image is None:
            self.rendered_photo = None
            self.canvas.delete("image")
            return

        view_width = max(self.canvas.winfo_width(), 1)
        view_height = max(self.canvas.winfo_height(), 1)
        virtual_width = self.image.width * self.zoom
        virtual_height = self.image.height * self.zoom

        canvas_x0 = max(0.0, self.canvas.canvasx(0) - DISPLAY_MARGIN)
        canvas_y0 = max(0.0, self.canvas.canvasy(0) - DISPLAY_MARGIN)
        canvas_x1 = min(virtual_width, self.canvas.canvasx(view_width) + DISPLAY_MARGIN)
        canvas_y1 = min(virtual_height, self.canvas.canvasy(view_height) + DISPLAY_MARGIN)

        if canvas_x1 <= canvas_x0 or canvas_y1 <= canvas_y0:
            return

        image_x0 = max(0, int(math.floor(canvas_x0 / self.zoom)))
        image_y0 = max(0, int(math.floor(canvas_y0 / self.zoom)))
        image_x1 = min(self.image.width, int(math.ceil(canvas_x1 / self.zoom)))
        image_y1 = min(self.image.height, int(math.ceil(canvas_y1 / self.zoom)))

        if image_x1 <= image_x0 or image_y1 <= image_y0:
            return

        crop = self.image.crop((image_x0, image_y0, image_x1, image_y1))
        display_width = max(1, int(round(crop.width * self.zoom)))
        display_height = max(1, int(round(crop.height * self.zoom)))
        resample = Image.Resampling.NEAREST if self.zoom >= 1.0 else Image.Resampling.LANCZOS
        display = crop.resize((display_width, display_height), resample)

        if display.mode not in {"RGB", "RGBA", "L"}:
            display = display.convert("RGBA")

        self.rendered_photo = ImageTk.PhotoImage(display)
        image_left = image_x0 * self.zoom
        image_top = image_y0 * self.zoom

        if self.image_id is None:
            self.image_id = self.canvas.create_image(
                image_left,
                image_top,
                anchor="nw",
                image=self.rendered_photo,
                tags=("image",),
            )
        else:
            self.canvas.coords(self.image_id, image_left, image_top)
            self.canvas.itemconfigure(self.image_id, image=self.rendered_photo)

        self.canvas.tag_lower(self.image_id)
        if self.selection_id is not None:
            self.canvas.tag_raise(self.selection_id)

    def _apply_mosaic(self, bbox: tuple[int, int, int, int]) -> None:
        if self.image is None:
            return

        x0, y0, x1, y1 = self._clamp_image_bbox(bbox)
        if x1 - x0 < 2 or y1 - y0 < 2:
            self.status_text.set("选择区域太小。")
            return

        bbox = (x0, y0, x1, y1)
        patch = self.image.crop(bbox)
        block = max(2, int(self.block_size.get()))
        small_size = (max(1, patch.width // block), max(1, patch.height // block))

        mosaic = patch.resize(small_size, Image.Resampling.BILINEAR)
        mosaic = mosaic.resize(patch.size, Image.Resampling.NEAREST)

        self.undo_stack.append((bbox, patch))
        self.image.paste(mosaic, bbox)
        self.modified = True
        self._update_title()
        self.request_redraw()
        self.status_text.set(f"已打码：{self._format_bbox(bbox)}，块大小 {block}")

    def _apply_fill(self, bbox: tuple[int, int, int, int]) -> None:
        if self.image is None:
            return

        x0, y0, x1, y1 = self._clamp_image_bbox(bbox)
        if x1 - x0 < 2 or y1 - y0 < 2:
            self.status_text.set("选择区域太小。")
            return

        bbox = (x0, y0, x1, y1)
        patch = self.image.crop(bbox)
        fill = Image.new(self.image.mode, patch.size, self._fill_color_for_mode(self.image.mode))

        self.undo_stack.append((bbox, patch))
        self.image.paste(fill, bbox)
        self.modified = True
        self._update_title()
        self.request_redraw()
        self.status_text.set(f"已涂色：{self._format_bbox(bbox)}，颜色 {self.fill_color.get()}")

    def _on_canvas_configure(self, _event: tk.Event) -> None:
        self._update_scrollregion()
        self.request_redraw()

    def _on_select_start(self, event: tk.Event) -> str:
        if self.image is None:
            return "break"

        self.canvas.focus_set()
        point = self._clamp_canvas_point(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self.drag_start = point

        if self.selection_id is not None:
            self.canvas.delete(self.selection_id)

        self.selection_id = self.canvas.create_rectangle(
            point[0],
            point[1],
            point[0],
            point[1],
            outline=self._selection_outline_color(),
            width=2,
            dash=(7, 4),
            tags=("selection",),
        )
        return "break"

    def _on_select_drag(self, event: tk.Event) -> str:
        if self.image is None or self.drag_start is None or self.selection_id is None:
            return "break"

        point = self._clamp_canvas_point(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        self.canvas.coords(self.selection_id, self.drag_start[0], self.drag_start[1], point[0], point[1])
        return "break"

    def _on_select_release(self, event: tk.Event) -> str:
        if self.image is None or self.drag_start is None:
            return "break"

        end = self._clamp_canvas_point(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))
        x0, x1 = sorted((self.drag_start[0], end[0]))
        y0, y1 = sorted((self.drag_start[1], end[1]))

        if self.selection_id is not None:
            self.canvas.delete(self.selection_id)
            self.selection_id = None
        self.drag_start = None

        image_bbox = (
            int(math.floor(x0 / self.zoom)),
            int(math.floor(y0 / self.zoom)),
            int(math.ceil(x1 / self.zoom)),
            int(math.ceil(y1 / self.zoom)),
        )
        if self.tool_mode.get() == "fill":
            self._apply_fill(image_bbox)
        else:
            self._apply_mosaic(image_bbox)
        return "break"

    def _on_mousewheel(self, event: tk.Event) -> str:
        if self.image is None:
            return "break"

        if event.state & 0x0004:
            self.set_zoom(self.zoom * (1.12 if event.delta > 0 else 0.89), anchor=(event.x, event.y))
        elif event.state & 0x0001:
            self.canvas.xview_scroll(-3 if event.delta > 0 else 3, "units")
            self.request_redraw()
        else:
            self.canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
            self.request_redraw()
        return "break"

    def _on_linux_mousewheel(self, event: tk.Event) -> str:
        if self.image is None:
            return "break"

        direction = -3 if event.num == 4 else 3
        if event.state & 0x0004:
            self.set_zoom(self.zoom * (1.12 if event.num == 4 else 0.89), anchor=(event.x, event.y))
        elif event.state & 0x0001:
            self.canvas.xview_scroll(direction, "units")
            self.request_redraw()
        else:
            self.canvas.yview_scroll(direction, "units")
            self.request_redraw()
        return "break"

    def _on_pan_start(self, event: tk.Event) -> str:
        self.canvas.scan_mark(event.x, event.y)
        return "break"

    def _on_pan_drag(self, event: tk.Event) -> str:
        self.canvas.scan_dragto(event.x, event.y, gain=1)
        self.request_redraw()
        return "break"

    def _xview(self, *args: object) -> None:
        self.canvas.xview(*args)
        self.request_redraw()

    def _yview(self, *args: object) -> None:
        self.canvas.yview(*args)
        self.request_redraw()

    def _on_block_scale(self, value: str) -> None:
        self.block_size.set(max(2, int(float(value))))

    def _on_block_spin(self) -> None:
        self.block_size.set(max(2, int(self.block_size.get())))

    def _on_tool_change(self) -> None:
        if self.tool_mode.get() == "fill":
            self.status_text.set(f"当前工具：涂色。拖出矩形后会填充颜色 {self.fill_color.get()}。")
        else:
            self.status_text.set("当前工具：马赛克。拖出矩形后会按块大小打码。")

    def _update_scrollregion(self) -> None:
        if self.image is None:
            self.canvas.configure(scrollregion=(0, 0, 0, 0))
            return
        self.canvas.configure(
            scrollregion=(
                0,
                0,
                max(1, self.image.width * self.zoom),
                max(1, self.image.height * self.zoom),
            )
        )

    def _move_view_to_anchor(
        self,
        image_x: float,
        image_y: float,
        anchor: tuple[int, int],
    ) -> None:
        if self.image is None:
            return

        virtual_width = max(1.0, self.image.width * self.zoom)
        virtual_height = max(1.0, self.image.height * self.zoom)
        target_left = image_x * self.zoom - anchor[0]
        target_top = image_y * self.zoom - anchor[1]
        self.canvas.xview_moveto(max(0.0, target_left / virtual_width))
        self.canvas.yview_moveto(max(0.0, target_top / virtual_height))

    def _clamp_canvas_point(self, x: float, y: float) -> tuple[float, float]:
        if self.image is None:
            return (0.0, 0.0)
        return (
            max(0.0, min(x, self.image.width * self.zoom)),
            max(0.0, min(y, self.image.height * self.zoom)),
        )

    def _clamp_image_bbox(self, bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        if self.image is None:
            return (0, 0, 0, 0)
        x0, y0, x1, y1 = bbox
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        return (
            max(0, min(x0, self.image.width)),
            max(0, min(y0, self.image.height)),
            max(0, min(x1, self.image.width)),
            max(0, min(y1, self.image.height)),
        )

    def _format_bbox(self, bbox: tuple[int, int, int, int]) -> str:
        x0, y0, x1, y1 = bbox
        return f"x={x0}, y={y0}, w={x1 - x0}, h={y1 - y0}"

    def _fill_color_for_mode(self, mode: str) -> int | tuple[int, int, int] | tuple[int, int, int, int]:
        red, green, blue = self._fill_color_rgb()
        if mode == "RGBA":
            return (red, green, blue, 255)
        if mode == "L":
            return int(round(0.299 * red + 0.587 * green + 0.114 * blue))
        return (red, green, blue)

    def _fill_color_rgb(self) -> tuple[int, int, int]:
        try:
            red, green, blue = self.winfo_rgb(self.fill_color.get())
        except tk.TclError:
            red, green, blue = self.winfo_rgb(DEFAULT_FILL_COLOR)
        return (red // 256, green // 256, blue // 256)

    def _selection_outline_color(self) -> str:
        if self.tool_mode.get() != "fill":
            return "#ff3b30"

        red, green, blue = self._fill_color_rgb()
        luminance = 0.299 * red + 0.587 * green + 0.114 * blue
        if luminance < 64:
            return "#ffffff"
        return self.fill_color.get()

    def _update_color_button(self) -> None:
        if self.color_button is None:
            return

        red, green, blue = self._fill_color_rgb()
        luminance = 0.299 * red + 0.587 * green + 0.114 * blue
        foreground = "white" if luminance < 128 else "black"
        color = self.fill_color.get()
        self.color_button.configure(bg=color, activebackground=color, fg=foreground, activeforeground=foreground)

    def _update_zoom_text(self) -> None:
        self.zoom_text.set(f"{round(self.zoom * 100)}%")

    def _update_title(self) -> None:
        marker = "*" if self.modified else ""
        if self.source_path is None:
            self.title(f"{marker}长截图打码工具")
        else:
            self.title(f"{marker}{self.source_path.name} - 长截图打码工具")

    def _confirm_discard_changes(self) -> bool:
        if not self.modified:
            return True
        answer = messagebox.askyesnocancel("尚未保存", "当前打码结果尚未保存。要先另存吗？")
        if answer is None:
            return False
        if answer:
            return self.save_as()
        return True

    def _on_close(self) -> None:
        if self._confirm_discard_changes():
            self.destroy()


def main() -> None:
    app = MosaicTool()
    app.mainloop()


if __name__ == "__main__":
    main()
