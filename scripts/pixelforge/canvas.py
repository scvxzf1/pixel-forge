"""ASCII grid parser/serializer, localized region patching, and PixelCanvas
with pixel-perfect Bresenham lines, midpoint ellipses, flood fill, and ordered Bayer dithering.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union
from PIL import Image

from .palette import (
    ColorDef,
    RGBA,
    extract_palette,
    get_palette,
    img_pixels,
    nearest_palette_char,
    rgba_to_hex,
)

GridLike = Union[str, Sequence[str]]

_BAYER_2X2 = (
    (0, 2),
    (3, 1),
)

_BAYER_4X4 = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)


def parse_grid_lines(grid: GridLike, frame_index: int = 0) -> List[str]:
    """Validate and normalize an ASCII grid into a list of equal-width row strings."""
    if isinstance(grid, str):
        # Strip only leading/trailing empty newline boundaries; preserve space-filled rows
        lines = grid.strip("\r\n").splitlines()
    else:
        lines = list(grid)

    if not lines or not lines[0]:
        raise ValueError(f"[Frame {frame_index}] Empty ASCII grid.")

    width = len(lines[0])
    for y, row in enumerate(lines):
        if not isinstance(row, str):
            raise ValueError(f"[Frame {frame_index}] Row {y} must be a string, got {type(row).__name__}.")
        if len(row) != width:
            diff = len(row) - width
            hint = f"{abs(diff)} char(s) too {'long' if diff > 0 else 'short'}"
            raise ValueError(
                f"[Frame {frame_index}] Row {y} width mismatch: expected {width} (from row 0), "
                f"got {len(row)} ({hint}). Row content: {row!r}"
            )
    return lines


def render_grid(
    grid: GridLike,
    palette: Union[str, Dict[str, ColorDef], None] = None,
    frame_index: int = 0,
) -> Image.Image:
    """Render a validated ASCII character grid to a 1x RGBA PIL Image."""
    lines = parse_grid_lines(grid, frame_index=frame_index)
    pal = get_palette(palette)
    h = len(lines)
    w = len(lines[0])
    pixels: List[RGBA] = []

    for y, row in enumerate(lines):
        for x, ch in enumerate(row):
            if ch not in pal:
                valid = "".join(sorted(k for k in pal if k != " "))
                raise ValueError(
                    f"[Frame {frame_index}] Undefined palette char {ch!r} at (x={x}, y={y}). "
                    f"Defined chars: {valid!r}"
                )
            pixels.append(pal[ch])

    img = Image.new("RGBA", (w, h))
    img.putdata(pixels)
    return img


def image_to_grid(
    img: Image.Image,
    palette: Optional[Union[str, Dict[str, ColorDef]]] = None,
    max_colors: int = 48,
    alpha_threshold: int = 16,
) -> Tuple[List[str], Dict[str, str]]:
    """Decompile a 1x RGBA Image into (ascii_grid_lines, hex_palette_dict)."""
    rgba_img = img.convert("RGBA")
    w, h = rgba_img.size

    if palette is None:
        pal_dict = extract_palette(rgba_img, max_colors=max_colors, alpha_threshold=alpha_threshold)
    elif isinstance(palette, str):
        resolved = get_palette(palette)
        pal_dict = {k: rgba_to_hex(v) for k, v in resolved.items() if k != " "}
    else:
        resolved = get_palette(palette)
        pal_dict = {k: rgba_to_hex(v) for k, v in resolved.items() if k != " "}

    # Cache exact RGBA -> char lookups for speed
    cache: Dict[RGBA, str] = {}
    data = img_pixels(rgba_img)
    lines: List[str] = []
    for y in range(h):
        row_chars: List[str] = []
        offset = y * w
        for x in range(w):
            px = data[offset + x]
            if px[3] < alpha_threshold:
                row_chars.append(".")
            else:
                ch = cache.get(px)
                if ch is None:
                    ch = nearest_palette_char(px, pal_dict, alpha_threshold=alpha_threshold)
                    cache[px] = ch
                row_chars.append(ch)
        lines.append("".join(row_chars))
    return lines, pal_dict


def extract_region_grid(grid: GridLike, x: int, y: int, w: int, h: int) -> List[str]:
    """Slice a rectangular (x, y, w, h) sub-grid out of an ASCII grid."""
    lines = parse_grid_lines(grid)
    gh = len(lines)
    gw = len(lines[0])
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > gw or y + h > gh:
        raise ValueError(
            f"Region (x={x}, y={y}, w={w}, h={h}) out of bounds for {gw}x{gh} grid."
        )
    return [lines[ry][x : x + w] for ry in range(y, y + h)]


def patch_region_grid(
    base_grid: GridLike,
    patch_grid: GridLike,
    x: int,
    y: int,
    mode: str = "replace",
    transparent_chars: Tuple[str, ...] = (".", " "),
) -> List[str]:
    """Write a rectangular ASCII sub-grid back into `base_grid` at `(x, y)`.

    mode='replace': overwrites every cell in the region (including transparent '.').
    mode='alpha_over': only non-transparent chars in `patch_grid` overwrite `base_grid`.
    """
    if mode not in ("replace", "alpha_over"):
        raise ValueError("mode must be 'replace' or 'alpha_over'")
    base_lines = [list(row) for row in parse_grid_lines(base_grid)]
    patch_lines = parse_grid_lines(patch_grid)
    bh, bw = len(base_lines), len(base_lines[0])
    ph, pw = len(patch_lines), len(patch_lines[0])

    if x < 0 or y < 0 or x + pw > bw or y + ph > bh:
        raise ValueError(
            f"Patch of size {pw}x{ph} at ({x}, {y}) exceeds base canvas {bw}x{bh}."
        )

    for py in range(ph):
        for px in range(pw):
            ch = patch_lines[py][px]
            if mode == "replace" or ch not in transparent_chars:
                base_lines[y + py][x + px] = ch

    return ["".join(row) for row in base_lines]


def extract_region_image(img: Image.Image, x: int, y: int, w: int, h: int) -> Image.Image:
    """Crop a rectangular (x, y, w, h) sub-image with bounds validation."""
    iw, ih = img.size
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > iw or y + h > ih:
        raise ValueError(f"Region (x={x}, y={y}, w={w}, h={h}) out of bounds for {iw}x{ih} image.")
    return img.convert("RGBA").crop((x, y, x + w, y + h))


def patch_region_image(
    base_img: Image.Image,
    patch: Union[Image.Image, GridLike],
    x: int,
    y: int,
    palette: Union[str, Dict[str, ColorDef], None] = None,
    mode: str = "replace",
) -> Image.Image:
    """Apply an Image or ASCII patch onto `base_img` at `(x, y)`."""
    if mode not in ("replace", "alpha_over"):
        raise ValueError("mode must be 'replace' or 'alpha_over'")
    patch_img = (
        patch.convert("RGBA")
        if isinstance(patch, Image.Image)
        else render_grid(patch, palette=palette)
    )
    bw, bh = base_img.size
    pw, ph = patch_img.size
    if x < 0 or y < 0 or x + pw > bw or y + ph > bh:
        raise ValueError(
            f"Patch of size {pw}x{ph} at ({x}, {y}) exceeds base image {bw}x{bh}."
        )

    out = base_img.convert("RGBA").copy()
    if mode == "replace":
        out.paste(patch_img, (x, y))
    else:
        sub = out.crop((x, y, x + pw, y + ph))
        merged = Image.alpha_composite(sub, patch_img)
        out.paste(merged, (x, y))
    return out


def _bresenham_points(x0: int, y0: int, x1: int, y1: int) -> List[Tuple[int, int]]:
    pts: List[Tuple[int, int]] = []
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    cx, cy = x0, y0
    while True:
        pts.append((cx, cy))
        if cx == x1 and cy == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            cx += sx
        if e2 <= dx:
            err += dx
            cy += sy
    return pts


def _prune_l_corners(pts: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Aseprite-style pixel-perfect stroke filter: removes 90-degree L-corner doubles."""
    if len(pts) < 3:
        return list(pts)
    result = [pts[0]]
    i = 1
    while i < len(pts) - 1:
        px, py = result[-1]
        cx, cy = pts[i]
        nx, ny = pts[i + 1]
        is_l_corner = (
            abs(px - nx) == 1
            and abs(py - ny) == 1
            and ((cx == px and abs(cy - py) == 1) or (cy == py and abs(cx - px) == 1))
        )
        if is_l_corner:
            # Skip current L-corner pixel and advance
            i += 1
            continue
        result.append((cx, cy))
        i += 1
    result.append(pts[-1])
    return result


class PixelCanvas:
    """Hybrid procedural + ASCII pixel canvas for building complex/large sprites cleanly."""

    def __init__(self, width: int, height: int, fill: str = ".") -> None:
        if width <= 0 or height <= 0 or len(fill) != 1:
            raise ValueError("Positive width/height and single-char fill required.")
        self.width = width
        self.height = height
        self._buf: List[List[str]] = [[fill for _ in range(width)] for _ in range(height)]

    @classmethod
    def from_grid(cls, grid: GridLike) -> "PixelCanvas":
        lines = parse_grid_lines(grid)
        c = cls(len(lines[0]), len(lines))
        c._buf = [list(row) for row in lines]
        return c

    def copy(self) -> "PixelCanvas":
        c = PixelCanvas(self.width, self.height)
        c._buf = [row[:] for row in self._buf]
        return c

    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def set_px(self, x: int, y: int, ch: str) -> None:
        if len(ch) != 1:
            raise ValueError(f"Expected single character, got {ch!r}")
        if self.in_bounds(x, y):
            self._buf[y][x] = ch

    def get_px(self, x: int, y: int, default: str = ".") -> str:
        return self._buf[y][x] if self.in_bounds(x, y) else default

    def line(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        ch: str,
        pixel_perfect: bool = True,
    ) -> "PixelCanvas":
        pts = _bresenham_points(x0, y0, x1, y1)
        if pixel_perfect:
            pts = _prune_l_corners(pts)
        for px, py in pts:
            self.set_px(px, py, ch)
        return self

    def rect(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        outline: Optional[str] = None,
        fill: Optional[str] = None,
    ) -> "PixelCanvas":
        if w <= 0 or h <= 0:
            return self
        if fill is not None:
            for ry in range(y, y + h):
                for rx in range(x, x + w):
                    self.set_px(rx, ry, fill)
        if outline is not None:
            for rx in range(x, x + w):
                self.set_px(rx, y, outline)
                self.set_px(rx, y + h - 1, outline)
            for ry in range(y, y + h):
                self.set_px(x, ry, outline)
                self.set_px(x + w - 1, ry, outline)
        return self

    def ellipse(
        self,
        cx: int,
        cy: int,
        rx: int,
        ry: int,
        outline: Optional[str] = None,
        fill: Optional[str] = None,
    ) -> "PixelCanvas":
        """Symmetric midpoint pixel ellipse with clean 1px border."""
        if rx < 0 or ry < 0:
            return self
        if rx == 0 and ry == 0:
            if fill:
                self.set_px(cx, cy, fill)
            if outline:
                self.set_px(cx, cy, outline)
            return self

        spans: Dict[int, Tuple[int, int]] = {}
        # Midpoint ellipse algorithm
        x = 0
        y = ry
        rx2 = rx * rx
        ry2 = ry * ry
        p1 = ry2 - rx2 * ry + 0.25 * rx2
        dx = 2 * ry2 * x
        dy = 2 * rx2 * y

        border_pts = set()

        def _record(ox: int, oy: int) -> None:
            for sy in (cy - oy, cy + oy):
                lo, hi = cx - ox, cx + ox
                if sy not in spans:
                    spans[sy] = (lo, hi)
                else:
                    spans[sy] = (min(spans[sy][0], lo), max(spans[sy][1], hi))
                border_pts.add((lo, sy))
                border_pts.add((hi, sy))

        while dx < dy:
            _record(x, y)
            if p1 < 0:
                x += 1
                dx += 2 * ry2
                p1 += dx + ry2
            else:
                x += 1
                y -= 1
                dx += 2 * ry2
                dy -= 2 * rx2
                p1 += dx - dy + ry2

        p2 = ry2 * (x + 0.5) ** 2 + rx2 * (y - 1) ** 2 - rx2 * ry2
        while y >= 0:
            _record(x, y)
            if p2 > 0:
                y -= 1
                dy -= 2 * rx2
                p2 += rx2 - dy
            else:
                y -= 1
                x += 1
                dx += 2 * ry2
                dy -= 2 * rx2
                p2 += dx - dy + rx2

        # Fill horizontal spans
        if fill is not None:
            for sy, (lo, hi) in spans.items():
                for sx in range(lo, hi + 1):
                    self.set_px(sx, sy, fill)

        if outline is not None:
            # Ensure vertical continuity between adjacent scanlines
            sorted_ys = sorted(spans.keys())
            for idx, sy in enumerate(sorted_ys):
                lo, hi = spans[sy]
                if idx == 0 or idx == len(sorted_ys) - 1:
                    for sx in range(lo, hi + 1):
                        self.set_px(sx, sy, outline)
                else:
                    prev_lo, prev_hi = spans[sorted_ys[idx - 1]]
                    next_lo, next_hi = spans[sorted_ys[idx + 1]]
                    left_end = max(lo, min(prev_lo, next_lo) - 1)
                    for sx in range(lo, max(lo, left_end) + 1):
                        self.set_px(sx, sy, outline)
                    right_start = min(hi, max(prev_hi, next_hi) + 1)
                    for sx in range(min(hi, right_start), hi + 1):
                        self.set_px(sx, sy, outline)
            for bx, by in border_pts:
                self.set_px(bx, by, outline)
        return self

    def circle(
        self,
        cx: int,
        cy: int,
        r: int,
        outline: Optional[str] = None,
        fill: Optional[str] = None,
    ) -> "PixelCanvas":
        return self.ellipse(cx, cy, r, r, outline=outline, fill=fill)

    def polygon(
        self,
        points: Sequence[Tuple[int, int]],
        outline: Optional[str] = None,
        fill: Optional[str] = None,
    ) -> "PixelCanvas":
        if len(points) < 3:
            return self
        if fill is not None:
            ys = [p[1] for p in points]
            min_y = max(0, min(ys))
            max_y = min(self.height - 1, max(ys))
            n = len(points)
            for y in range(min_y, max_y + 1):
                nodes: List[float] = []
                j = n - 1
                for i in range(n):
                    xi, yi = points[i]
                    xj, yj = points[j]
                    if (yi < y <= yj) or (yj < y <= yi):
                        nodes.append(xi + (y - yi) / (yj - yi) * (xj - xi))
                    j = i
                nodes.sort()
                for k in range(0, len(nodes) - 1, 2):
                    x_start = max(0, int(round(nodes[k])))
                    x_end = min(self.width - 1, int(round(nodes[k + 1])))
                    for x in range(x_start, x_end + 1):
                        self.set_px(x, y, fill)
        if outline is not None:
            for i in range(len(points)):
                x0, y0 = points[i]
                x1, y1 = points[(i + 1) % len(points)]
                self.line(x0, y0, x1, y1, outline, pixel_perfect=True)
        return self

    def flood_fill(self, x: int, y: int, ch: str) -> "PixelCanvas":
        """4-connected bucket fill starting at (x, y)."""
        if not self.in_bounds(x, y):
            return self
        target = self._buf[y][x]
        if target == ch:
            return self
        q = deque([(x, y)])
        self._buf[y][x] = ch
        while q:
            cx, cy = q.popleft()
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if self.in_bounds(nx, ny) and self._buf[ny][nx] == target:
                    self._buf[ny][nx] = ch
                    q.append((nx, ny))
        return self

    def dither_rect(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        ch_primary: str,
        ch_secondary: str,
        ratio: float = 0.5,
        matrix_size: int = 4,
        only_on_char: Optional[str] = None,
    ) -> "PixelCanvas":
        """Ordered Bayer dithering (2x2 or 4x4) across a region or masked to `only_on_char`."""
        if matrix_size not in (2, 4):
            raise ValueError("matrix_size must be 2 or 4")
        if not (0.0 <= ratio <= 1.0):
            raise ValueError("ratio must be within [0.0, 1.0]")
        mat = _BAYER_2X2 if matrix_size == 2 else _BAYER_4X4
        denom = float(matrix_size * matrix_size)
        for ry in range(max(0, y), min(self.height, y + h)):
            for rx in range(max(0, x), min(self.width, x + w)):
                if only_on_char is not None and self._buf[ry][rx] != only_on_char:
                    continue
                thresh = (mat[ry % matrix_size][rx % matrix_size] + 0.5) / denom
                self._buf[ry][rx] = ch_secondary if ratio > thresh else ch_primary
        return self

    def stamp(
        self,
        sub_grid: Union[GridLike, "PixelCanvas"],
        x: int,
        y: int,
        transparent_chars: Tuple[str, ...] = (".", " "),
        mirror_h: bool = False,
        mirror_v: bool = False,
    ) -> "PixelCanvas":
        """Stamp a smaller ASCII motif onto this canvas at `(x, y)`."""
        lines = sub_grid.to_lines() if isinstance(sub_grid, PixelCanvas) else parse_grid_lines(sub_grid)
        if mirror_h:
            lines = [row[::-1] for row in lines]
        if mirror_v:
            lines = lines[::-1]
        for sy, row in enumerate(lines):
            for sx, ch in enumerate(row):
                if ch not in transparent_chars:
                    self.set_px(x + sx, y + sy, ch)
        return self

    def mirror_symmetrize(self, source_half: str = "left") -> "PixelCanvas":
        """Mirror left->right (or right->left) across the vertical centerline."""
        half = self.width // 2
        for y in range(self.height):
            for x in range(half):
                mx = self.width - 1 - x
                if source_half == "left":
                    self._buf[y][mx] = self._buf[y][x]
                else:
                    self._buf[y][x] = self._buf[y][mx]
        return self

    def to_lines(self) -> List[str]:
        return ["".join(row) for row in self._buf]

    def to_ascii(self) -> str:
        return "\n".join(self.to_lines())

    def render(self, palette: Union[str, Dict[str, ColorDef], None] = None) -> Image.Image:
        return render_grid(self.to_lines(), palette=palette)
