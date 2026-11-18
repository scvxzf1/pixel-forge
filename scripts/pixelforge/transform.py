"""Pixel-art-specialized transforms: Scale2x (EPX), RotSprite clean rotation,
outer/inner/selective outlining (Sel-out), squash & stretch, motion smear, and shadows.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Optional, Sequence, Tuple, Union
from PIL import Image, ImageDraw

from .canvas import GridLike, parse_grid_lines
from .palette import (
    ColorDef,
    RGBA,
    canonical_char_map,
    color_distance_sq,
    get_palette,
    img_pixels,
    luminance,
    normalize_rgba,
    parse_color,
)


def scale2x(img: Image.Image) -> Image.Image:
    """Apply one 2x EPX / Scale2x pass. Smooths pixel diagonals without inventing new colors."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    if w == 0 or h == 0:
        return rgba.copy()

    raw = [normalize_rgba(px) for px in img_pixels(rgba)]
    out_w = w * 2
    out_data: List[RGBA] = [(0, 0, 0, 0)] * (out_w * h * 2)

    for y in range(h):
        y_up = max(0, y - 1) * w
        y_cur = y * w
        y_dn = min(h - 1, y + 1) * w
        out_r0 = (y * 2) * out_w
        out_r1 = (y * 2 + 1) * out_w
        for x in range(w):
            p = raw[y_cur + x]
            a = raw[y_up + x]
            d = raw[y_dn + x]
            c = raw[y_cur + (x - 1 if x > 0 else 0)]
            b = raw[y_cur + (x + 1 if x + 1 < w else w - 1)]

            if a != d and c != b:
                p1 = a if c == a else p
                p2 = b if a == b else p
                p3 = c if d == c else p
                p4 = d if b == d else p
            else:
                p1 = p2 = p3 = p4 = p

            ox = x * 2
            out_data[out_r0 + ox] = p1
            out_data[out_r0 + ox + 1] = p2
            out_data[out_r1 + ox] = p3
            out_data[out_r1 + ox + 1] = p4

    out = Image.new("RGBA", (out_w, h * 2))
    out.putdata(out_data)
    return out


def shift_grid(
    grid: GridLike,
    dx: int = 0,
    dy: int = 0,
    fill: str = ".",
    wrap: bool = False,
) -> List[str]:
    """Shift an ASCII grid by integer `(dx, dy)`. Set `wrap=True` for seamless tile scrolling."""
    lines = parse_grid_lines(grid)
    if len(fill) != 1:
        raise ValueError("fill must be a single character")
    h, w = len(lines), len(lines[0])
    out: List[str] = []
    for y in range(h):
        row: List[str] = []
        for x in range(w):
            sx, sy = x - dx, y - dy
            if wrap:
                row.append(lines[sy % h][sx % w])
            elif 0 <= sx < w and 0 <= sy < h:
                row.append(lines[sy][sx])
            else:
                row.append(fill)
        out.append("".join(row))
    return out


def flip_grid(grid: GridLike, horizontal: bool = True, vertical: bool = False) -> List[str]:
    lines = parse_grid_lines(grid)
    if horizontal:
        lines = [r[::-1] for r in lines]
    if vertical:
        lines = lines[::-1]
    return lines


def shift_image(img: Image.Image, dx: int = 0, dy: int = 0, wrap: bool = False) -> Image.Image:
    """Shift an RGBA image by `(dx, dy)` pixels, cropping or wrapping cleanly."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    if dx == 0 and dy == 0:
        return rgba.copy()
    if not wrap:
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        out.paste(rgba, (dx, dy))
        return out
    src = rgba.load()
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dst = out.load()
    for y in range(h):
        for x in range(w):
            dst[x, y] = src[(x - dx) % w, (y - dy) % h]
    return out


def flip_image(img: Image.Image, horizontal: bool = True, vertical: bool = False) -> Image.Image:
    out = img.convert("RGBA")
    if horizontal:
        out = out.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if vertical:
        out = out.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return out


def rotsprite(
    img: Image.Image,
    angle_deg: float = 0.0,
    pivot: Optional[Tuple[float, float]] = None,
    dx: int = 0,
    dy: int = 0,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
) -> Image.Image:
    """Xenowhirl RotSprite-inspired clean pixel-art rotation & scaling around `pivot`.

    Uses 3x Scale2x (8x resolution) before inverse-mapped transformation and
    center-weighted mode pooling back to 1x, preserving 100% pure palette colors
    and preventing broken 1px sword blades or muddy anti-aliased fringes.

    Note: `angle_deg` follows screen coordinates (positive = clockwise, negative = counter-clockwise,
    so e.g. `-25` tilts a left-hinged chest lid upward!).
    """
    if scale_x <= 0 or scale_y <= 0:
        raise ValueError("scale_x and scale_y must be positive.")

    rgba = img.convert("RGBA")
    w, h = rgba.size
    if rgba.getchannel("A").getbbox() is None:
        return rgba.copy()

    px, py = ((w - 1) / 2.0, (h - 1) / 2.0) if pivot is None else pivot
    norm_angle = angle_deg % 360.0

    # Fast exact path for pure translation
    if abs(norm_angle) < 1e-6 and abs(scale_x - 1.0) < 1e-6 and abs(scale_y - 1.0) < 1e-6:
        return shift_image(rgba, dx=dx, dy=dy, wrap=False)

    # Fast exact path for 90 / 180 / 270 degree rotations with unit scale
    if (
        abs(scale_x - 1.0) < 1e-6
        and abs(scale_y - 1.0) < 1e-6
        and any(abs(norm_angle - k) < 1e-6 for k in (90.0, 180.0, 270.0))
    ):
        rad = math.radians(norm_angle)
        cos_a, sin_a = round(math.cos(rad)), round(math.sin(rad))
        src = rgba.load()
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dst = out.load()
        for y in range(h):
            for x in range(w):
                rx = x - dx - px
                ry = y - dy - py
                sx = int(round(rx * cos_a + ry * sin_a + px))
                sy = int(round(-rx * sin_a + ry * cos_a + py))
                if 0 <= sx < w and 0 <= sy < h:
                    dst[x, y] = src[sx, sy]
        return out

    # 3x Scale2x -> 8x clean upscaled buffer
    up = scale2x(scale2x(scale2x(rgba)))
    uw, uh = up.size  # (w*8, h*8)
    up_src = up.load()

    rad = math.radians(angle_deg)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    up_px = px * 8.0 + 3.5
    up_py = py * 8.0 + 3.5
    up_dx = dx * 8.0
    up_dy = dy * 8.0

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dst = out.load()

    # Sample a 4x4 subgrid inside each 8x8 cell with higher weight on central subpixels
    sub_offsets = (1.5, 3.0, 4.5, 6.0)
    center_weights = (1, 2, 2, 1)

    # Bounding box optimization in output space
    bbox = rgba.getchannel("A").getbbox()
    assert bbox is not None
    bx0, by0, bx1, by1 = bbox
    corners = [(bx0 - 1, by0 - 1), (bx1 + 1, by0 - 1), (bx0 - 1, by1 + 1), (bx1 + 1, by1 + 1)]
    txs, tys = [], []
    for cx, cy in corners:
        rx = (cx - px) * scale_x
        ry = (cy - py) * scale_y
        txs.append(rx * cos_a - ry * sin_a + px + dx)
        tys.append(rx * sin_a + ry * cos_a + py + dy)
    min_x = max(0, int(math.floor(min(txs))) - 1)
    max_x = min(w - 1, int(math.ceil(max(txs))) + 1)
    min_y = max(0, int(math.floor(min(tys))) - 1)
    max_y = min(h - 1, int(math.ceil(max(tys))) + 1)

    total_weight = sum(wy * wx for wy in center_weights for wx in center_weights)  # 36
    opaque_threshold = 12  # ~33% weighted coverage keeps 1px rotated lines intact without bloat

    for y in range(min_y, max_y + 1):
        base_uy = y * 8.0 - up_dy - up_py
        for x in range(min_x, max_x + 1):
            base_ux = x * 8.0 - up_dx - up_px
            opaque_w = 0
            counts: Counter[RGBA] = Counter()
            for iy, oy in enumerate(sub_offsets):
                ry = base_uy + oy
                wy = center_weights[iy]
                for ix, ox in enumerate(sub_offsets):
                    rx = base_ux + ox
                    ux = (rx * cos_a + ry * sin_a) / scale_x + up_px
                    uy = (-rx * sin_a + ry * cos_a) / scale_y + up_py
                    isx = int(ux)
                    isy = int(uy)
                    if 0 <= isx < uw and 0 <= isy < uh:
                        col = up_src[isx, isy]
                        if col[3] > 0:
                            w_sub = wy * center_weights[ix]
                            opaque_w += w_sub
                            counts[col] += w_sub
            if opaque_w >= opaque_threshold and counts:
                dst[x, y] = counts.most_common(1)[0][0]

    return out


def squash_stretch(
    img: Image.Image,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    anchor: str = "bottom",
    baseline_y: Optional[int] = None,
) -> Image.Image:
    """Nearest-neighbor squash & stretch anchored to `bottom`, `center`, or `top`."""
    if scale_x <= 0 or scale_y <= 0 or anchor not in ("bottom", "center", "top"):
        raise ValueError("Positive scale_x/scale_y and anchor in ('bottom','center','top') required.")
    rgba = img.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        return rgba.copy()

    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    nw = max(1, round(bw * scale_x))
    nh = max(1, round(bh * scale_y))
    resized = rgba.crop(bbox).resize((nw, nh), Image.Resampling.NEAREST)

    px = x0 + (bw - nw) // 2
    if anchor == "bottom":
        ref_bottom = y1 if baseline_y is None else (baseline_y + 1)
        py = ref_bottom - nh
    elif anchor == "center":
        py = y0 + (bh - nh) // 2
    else:
        py = y0

    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    out.paste(resized, (px, py))
    return out


def auto_outline(
    img: Image.Image,
    color: ColorDef = "#181425",
    connectivity: int = 4,
    mode: str = "outer",
) -> Image.Image:
    """Add a crisp 1px outline around opaque silhouettes (`mode='outer'` or `'inner'`)."""
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    if mode not in ("outer", "inner"):
        raise ValueError("mode must be 'outer' or 'inner'")

    rgba = img.convert("RGBA")
    out = rgba.copy()
    src, dst = rgba.load(), out.load()
    oc = parse_color(color)
    w, h = rgba.size
    offsets = (
        ((-1, 0), (1, 0), (0, -1), (0, 1))
        if connectivity == 4
        else ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1))
    )

    if mode == "outer":
        for y in range(h):
            for x in range(w):
                if src[x, y][3] == 0:
                    if any(
                        0 <= x + dx < w and 0 <= y + dy < h and src[x + dx, y + dy][3] > 0
                        for dx, dy in offsets
                    ):
                        dst[x, y] = oc
    else:
        for y in range(h):
            for x in range(w):
                if src[x, y][3] > 0:
                    if any(
                        not (0 <= x + dx < w and 0 <= y + dy < h) or src[x + dx, y + dy][3] == 0
                        for dx, dy in offsets
                    ):
                        dst[x, y] = oc
    return out


def selective_outline(
    img: Image.Image,
    light_dir: Tuple[float, float] = (-1.0, -1.0),
    dark_color: ColorDef = "#181425",
    tint_mix: float = 0.48,
    connectivity: int = 4,
    snap_palette: Optional[Union[str, Dict[str, ColorDef]]] = None,
) -> Image.Image:
    """Apply studio-style Selective Outlining (Sel-Out) aware of light source direction.

    Edges facing `light_dir` (default top-left `(-1, -1)`) blend their adjacent fill color
    with `dark_color`, while shadow-facing edges receive deep `dark_color`.
    """
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    rgba = img.convert("RGBA")
    out = rgba.copy()
    src, dst = rgba.load(), out.load()
    dc = parse_color(dark_color)
    w, h = rgba.size

    lx, ly = light_dir
    mag = math.hypot(lx, ly) or 1.0
    lx, ly = lx / mag, ly / mag  # Vector pointing toward the light source (e.g. top-left)

    pal_colors: Optional[List[RGBA]] = None
    if snap_palette is not None:
        rev = canonical_char_map(get_palette(snap_palette))
        pal_colors = [c for c in rev if c[3] > 0]

    offsets = (
        ((-1, 0), (1, 0), (0, -1), (0, 1))
        if connectivity == 4
        else ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1))
    )

    for y in range(h):
        for x in range(w):
            if src[x, y][3] > 0:
                continue
            adj: List[Tuple[int, int, RGBA]] = []
            for dx, dy in offsets:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and src[nx, ny][3] > 0:
                    adj.append((-dx, -dy, src[nx, ny]))
            if not adj:
                continue
            # Outward normal from interior pixel(s) toward this outline pixel
            norm_x = sum( item[0] for item in adj ) / len(adj)
            norm_y = sum( item[1] for item in adj ) / len(adj)
            n_mag = math.hypot(norm_x, norm_y) or 1.0
            dot = (norm_x / n_mag) * lx + (norm_y / n_mag) * ly  # [-1, 1], >0 faces light

            # Pick brightest adjacent fill color
            fill_col = max((item[2] for item in adj), key=luminance)
            if dot > 0.05:
                # Blend fill color with dark outline color proportionally to light alignment
                dark_weight = max(0.25, 1.0 - (1.0 - tint_mix) * (0.5 + 0.5 * dot))
                blended: RGBA = (
                    round(fill_col[0] * (1.0 - dark_weight) + dc[0] * dark_weight),
                    round(fill_col[1] * (1.0 - dark_weight) + dc[1] * dark_weight),
                    round(fill_col[2] * (1.0 - dark_weight) + dc[2] * dark_weight),
                    255,
                )
                if pal_colors:
                    blended = min(pal_colors, key=lambda pc: color_distance_sq(blended, pc))
                dst[x, y] = blended
            else:
                dst[x, y] = dc
    return out


def flash_image(
    img: Image.Image,
    flash_color: ColorDef = "#FFFFFF",
    mix: float = 0.85,
) -> Image.Image:
    """Tint opaque pixels toward `flash_color` (hit flash / charge glow), preserving alpha."""
    if not (0.0 <= mix <= 1.0):
        raise ValueError("mix must be in [0.0, 1.0]")
    rgba = img.convert("RGBA")
    fc = parse_color(flash_color)
    out = Image.new("RGBA", rgba.size)
    out.putdata([
        (
            round(p[0] * (1.0 - mix) + fc[0] * mix),
            round(p[1] * (1.0 - mix) + fc[1] * mix),
            round(p[2] * (1.0 - mix) + fc[2] * mix),
            p[3],
        )
        if p[3] > 0
        else (0, 0, 0, 0)
        for p in img_pixels(rgba)
    ])
    return out


def smear_between(
    prev_img: Image.Image,
    curr_img: Image.Image,
    trail_color: Optional[ColorDef] = None,
    steps: int = 3,
    alpha_scale: float = 1.0,
) -> Image.Image:
    """Generate a snappy motion-smear composite bridging `prev_img` -> `curr_img`."""
    if prev_img.size != curr_img.size:
        raise ValueError("prev_img and curr_img must share identical canvas dimensions.")
    p_rgba = prev_img.convert("RGBA")
    c_rgba = curr_img.convert("RGBA")
    p_box = p_rgba.getchannel("A").getbbox()
    c_box = c_rgba.getchannel("A").getbbox()
    if p_box is None or c_box is None:
        return c_rgba.copy()

    # Centroid shift vector
    pcx = 0.5 * (p_box[0] + p_box[2])
    pcy = 0.5 * (p_box[1] + p_box[3])
    ccx = 0.5 * (c_box[0] + c_box[2])
    ccy = 0.5 * (c_box[1] + c_box[3])
    vx = ccx - pcx
    vy = ccy - pcy

    base = Image.new("RGBA", c_rgba.size, (0, 0, 0, 0))
    tc = parse_color(trail_color) if trail_color is not None else None

    for s in range(1, steps + 1):
        t = s / float(steps + 1)
        ox = round(-vx * (1.0 - t))
        oy = round(-vy * (1.0 - t))
        ghost = shift_image(c_rgba, dx=ox, dy=oy)
        if tc is not None:
            ghost = flash_image(ghost, tc, mix=0.92)
        if alpha_scale < 1.0:
            ghost.putdata([
                (r, g, b, round(a * alpha_scale * t)) if a > 0 else (0, 0, 0, 0)
                for r, g, b, a in img_pixels(ghost)
            ])
        # Perforate outermost step slightly for classic pixel speed-line feel
        if s == 1:
            w, h = ghost.size
            gpx = ghost.load()
            for y in range(h):
                for x in range(w):
                    if (x + y) % 2 == 1:
                        gpx[x, y] = (0, 0, 0, 0)
        base = Image.alpha_composite(base, ghost)

    return Image.alpha_composite(base, c_rgba)


def add_ground_shadow(
    img: Image.Image,
    baseline_y: Optional[int] = None,
    width_ratio: float = 0.82,
    height_px: int = 3,
    color: ColorDef = (24, 20, 37, 110),
    center_x: Optional[int] = None,
    fixed_width: Optional[int] = None,
) -> Image.Image:
    """Render a pixel contact shadow ellipse underneath the sprite on `baseline_y`."""
    rgba = img.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        return rgba.copy()

    x0, _, x1, y1 = bbox
    by = (y1 - 1) if baseline_y is None else baseline_y
    cx = ((x0 + x1) // 2) if center_x is None else center_x
    sw = max(2, fixed_width if fixed_width is not None else round((x1 - x0) * width_ratio))
    sh = max(2, height_px)

    shadow = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    sc = parse_color(color)
    sx0 = cx - sw // 2
    sy0 = by - sh // 2 + 1
    draw.ellipse([sx0, sy0, sx0 + sw - 1, sy0 + sh - 1], fill=sc)
    return Image.alpha_composite(shadow, rgba)


def clean_orphan_specks(img: Image.Image, min_neighbors: int = 1) -> Image.Image:
    """Remove completely isolated 1px outer specks (0 opaque 8-neighbors)."""
    rgba = img.convert("RGBA")
    out = rgba.copy()
    src, dst = rgba.load(), out.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            if src[x, y][3] == 0:
                continue
            cnt = 0
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and src[nx, ny][3] > 0:
                        cnt += 1
            if cnt < min_neighbors:
                dst[x, y] = (0, 0, 0, 0)
    return out
