"""Seamless Tileset 3x3 Verification, Edge Seam Discontinuity Detector,
and Pixel-Perfect 9-Slice UI Panel Builder.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from PIL import Image, ImageDraw, ImageFont

from .canvas import GridLike, render_grid
from .inspector import _auto_scale, _draw_ruled_grid_panel
from .palette import ColorDef, color_distance_sq, normalize_rgba


def tile_grid_repeat(img: Image.Image, cols: int = 3, rows: int = 3) -> Image.Image:
    """Repeat `img` in a `cols x rows` seamless grid."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    out = Image.new("RGBA", (w * cols, h * rows))
    for ry in range(rows):
        for rx in range(cols):
            out.paste(rgba, (rx * w, ry * h))
    return out


def check_tile_seamless(
    img: Image.Image,
    jump_threshold: float = 95.0,
) -> Dict[str, Any]:
    """Detect horizontal (left<->right) and vertical (top<->bottom) wrap-around seam breaks.

    Compares perceptual color difference across the wrap boundary against adjacent interior steps
    so natural noisy textures aren't falsely flagged while broken mortar lines/shores are caught.
    """
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()

    lr_breaks: List[int] = []  # y coordinates where x=w-1 -> x=0 jumps sharply
    tb_breaks: List[int] = []  # x coordinates where y=h-1 -> y=0 jumps sharply

    if w >= 3:
        for y in range(h):
            left0 = normalize_rgba(px[0, y])
            left1 = normalize_rgba(px[1, y])
            right0 = normalize_rgba(px[w - 1, y])
            right1 = normalize_rgba(px[w - 2, y])
            seam_d = math.sqrt(color_distance_sq(left0, right0))
            inner_d = max(
                math.sqrt(color_distance_sq(left0, left1)),
                math.sqrt(color_distance_sq(right0, right1)),
            )
            if seam_d > jump_threshold and seam_d > inner_d * 1.8 + 35.0:
                lr_breaks.append(y)

    if h >= 3:
        for x in range(w):
            top0 = normalize_rgba(px[x, 0])
            top1 = normalize_rgba(px[x, 1])
            bot0 = normalize_rgba(px[x, h - 1])
            bot1 = normalize_rgba(px[x, h - 2])
            seam_d = math.sqrt(color_distance_sq(top0, bot0))
            inner_d = max(
                math.sqrt(color_distance_sq(top0, top1)),
                math.sqrt(color_distance_sq(bot0, bot1)),
            )
            if seam_d > jump_threshold and seam_d > inner_d * 1.8 + 35.0:
                tb_breaks.append(x)

    return {
        "seamless_ok": (len(lr_breaks) == 0 and len(tb_breaks) == 0),
        "left_right_mismatch_rows_y": lr_breaks,
        "top_bottom_mismatch_cols_x": tb_breaks,
    }


def generate_tileset_sheet(
    tile: Union[Image.Image, Sequence[Image.Image]],
    title: str = "Seamless Tile 3x3 Inspection",
    scale: Optional[int] = None,
) -> Tuple[Image.Image, Dict[str, Any]]:
    """Create a 3-panel inspection sheet: 10x Ruled Tile | Clean 3x3 Repeat | 3x3 Seam Overlay."""
    first = tile[0].convert("RGBA") if isinstance(tile, Sequence) else tile.convert("RGBA")
    fw, fh = first.size
    sc = _auto_scale(fw, fh) if scale is None else scale
    rep_sc = max(2, min(5, sc // 2))

    seam_report = check_tile_seamless(first)
    rep_3x3 = tile_grid_repeat(first, 3, 3)
    rep_up = rep_3x3.resize((fw * 3 * rep_sc, fh * 3 * rep_sc), Image.Resampling.NEAREST)

    # Build Seam Diagnostic Overlay
    overlay = rep_up.copy().convert("RGB")
    odraw = ImageDraw.Draw(overlay)
    for k in (1, 2):
        bx = k * fw * rep_sc
        by = k * fh * rep_sc
        for gy in range(0, fh * 3 * rep_sc, 6):
            odraw.line((bx, gy, bx, min(gy + 3, fh * 3 * rep_sc)), fill=(120, 140, 180))
        for gx in range(0, fw * 3 * rep_sc, 6):
            odraw.line((gx, by, min(gx + 3, fw * 3 * rep_sc), by), fill=(120, 140, 180))

    # Highlight detected seam mismatches in bright red along internal 3x3 borders
    for y_err in seam_report["left_right_mismatch_rows_y"]:
        for k in (1, 2):
            bx = k * fw * rep_sc
            for ry in range(3):
                yy = (ry * fh + y_err) * rep_sc
                odraw.rectangle([bx - 2, yy, bx + 2, yy + rep_sc - 1], fill=(255, 50, 80))

    for x_err in seam_report["top_bottom_mismatch_cols_x"]:
        for k in (1, 2):
            by = k * fh * rep_sc
            for rx in range(3):
                xx = (rx * fw + x_err) * rep_sc
                odraw.rectangle([xx, by - 2, xx + rep_sc - 1, by + 2], fill=(255, 50, 80))

    pad = 18
    left_ruler = 32
    top_ruler = 36
    p1_w = left_ruler + fw * sc + pad
    p2_w = rep_up.width + pad
    p3_w = overlay.width + pad
    sheet_w = max(620, p1_w + p2_w + p3_w + pad)
    sheet_h = 44 + max(top_ruler + fh * sc, top_ruler + rep_up.height) + pad * 2

    sheet = Image.new("RGB", (sheet_w, sheet_h), (26, 28, 36))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    status = "SEAMLESS OK" if seam_report["seamless_ok"] else (
        f"SEAM WARNINGS (LR rows={seam_report['left_right_mismatch_rows_y']}, "
        f"TB cols={seam_report['top_bottom_mismatch_cols_x']})"
    )
    draw.text((pad, 10), f"{title} ({fw}x{fh})  |  {status}", fill=(240, 245, 255), font=font)

    oy = 42 + top_ruler
    _draw_ruled_grid_panel(sheet, first, pad + left_ruler, oy, sc, "1. Single Tile Grid")

    x2 = pad + p1_w
    draw.text((x2, oy - 28), f"2. Clean 3x3 Tiled ({rep_sc}x)", fill=(235, 240, 250), font=font)
    bg_clean = Image.new("RGBA", rep_up.size, (34, 38, 48, 255))
    sheet.paste(Image.alpha_composite(bg_clean, rep_up).convert("RGB"), (x2, oy))

    x3 = x2 + p2_w
    draw.text((x3, oy - 28), "3. Seam Borders (Red = Mismatch)", fill=(235, 240, 250), font=font)
    sheet.paste(overlay, (x3, oy))

    return sheet, seam_report


def _tile_fill_region(patch: Image.Image, target_w: int, target_h: int, mode: str) -> Image.Image:
    if target_w <= 0 or target_h <= 0:
        return Image.new("RGBA", (max(1, target_w), max(1, target_h)), (0, 0, 0, 0))
    if mode == "stretch":
        return patch.resize((target_w, target_h), Image.Resampling.NEAREST)
    pw, ph = patch.size
    out = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    for y in range(0, target_h, ph):
        for x in range(0, target_w, pw):
            cw = min(pw, target_w - x)
            ch = min(ph, target_h - y)
            sub = patch if (cw == pw and ch == ph) else patch.crop((0, 0, cw, ch))
            out.paste(sub, (x, y))
    return out


def render_9slice(
    source: Union[Image.Image, GridLike],
    margins: Tuple[int, int, int, int],  # (left, top, right, bottom)
    target_size: Tuple[int, int],
    palette: Union[str, Dict[str, ColorDef], None] = "endesga32",
    mode: str = "tile",  # 'tile' (crisp pixel repeat) | 'stretch'
) -> Image.Image:
    """Expand a 9-slice UI border asset (`margins=(left, top, right, bottom)`) to `target_size`."""
    if mode not in ("tile", "stretch"):
        raise ValueError("mode must be 'tile' or 'stretch'")
    img = source.convert("RGBA") if isinstance(source, Image.Image) else render_grid(source, palette=palette)
    sw, sh = img.size
    ml, mt, mr, mb = margins
    tw, th = target_size

    if ml < 0 or mt < 0 or mr < 0 or mb < 0 or ml + mr >= sw or mt + mb >= sh:
        raise ValueError(f"Invalid 9-slice margins {margins} for {sw}x{sh} source.")
    if tw < ml + mr or th < mt + mb:
        raise ValueError(f"target_size {target_size} smaller than corner sum ({ml+mr}, {mt+mb}).")

    cw_src = sw - ml - mr
    ch_src = sh - mt - mb
    cw_dst = tw - ml - mr
    ch_dst = th - mt - mb

    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    # 4 Corners
    if ml > 0 and mt > 0:
        out.paste(img.crop((0, 0, ml, mt)), (0, 0))
    if mr > 0 and mt > 0:
        out.paste(img.crop((sw - mr, 0, sw, mt)), (tw - mr, 0))
    if ml > 0 and mb > 0:
        out.paste(img.crop((0, sh - mb, ml, sh)), (0, th - mb))
    if mr > 0 and mb > 0:
        out.paste(img.crop((sw - mr, sh - mb, sw, sh)), (tw - mr, th - mb))

    # 4 Edges
    if cw_dst > 0 and mt > 0:
        top_edge = _tile_fill_region(img.crop((ml, 0, ml + cw_src, mt)), cw_dst, mt, mode)
        out.paste(top_edge, (ml, 0))
    if cw_dst > 0 and mb > 0:
        bot_edge = _tile_fill_region(img.crop((ml, sh - mb, ml + cw_src, sh)), cw_dst, mb, mode)
        out.paste(bot_edge, (ml, th - mb))
    if ml > 0 and ch_dst > 0:
        left_edge = _tile_fill_region(img.crop((0, mt, ml, mt + ch_src)), ml, ch_dst, mode)
        out.paste(left_edge, (0, mt))
    if mr > 0 and ch_dst > 0:
        right_edge = _tile_fill_region(img.crop((sw - mr, mt, sw, mt + ch_src)), mr, ch_dst, mode)
        out.paste(right_edge, (tw - mr, mt))

    # Center
    if cw_dst > 0 and ch_dst > 0:
        center_patch = _tile_fill_region(
            img.crop((ml, mt, ml + cw_src, mt + ch_src)), cw_dst, ch_dst, mode
        )
        out.paste(center_patch, (ml, mt))

    return out
