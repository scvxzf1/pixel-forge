"""Multimodal Visual Inspection Sheets engineered for Vision LLMs:
1. Palette Swatch Legend ([char] -> color + hex)
2. 10x Coordinate-Ruled Checkerboard Grid (supports global `coord_offset` for Region Patching!)
3. Clean Ungridded Real-Feel Previews on BOTH Dark and Light backgrounds
4. Silhouette & Magenta->Cyan Onion-Skin Motion Trajectory strips for animations
5. Before / After / Changed-Pixel Diff Sheet for surgical pixel edits
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple, Union
from PIL import Image, ImageDraw, ImageFont

from .palette import (
    ColorDef,
    RGBA,
    canonical_char_map,
    get_palette,
    img_pixels,
    normalize_rgba,
    rgba_to_hex,
)


def _auto_scale(w: int, h: int) -> int:
    m = max(w, h)
    if m <= 20:
        return 12
    if m <= 40:
        return 10
    if m <= 72:
        return 8
    if m <= 128:
        return 6
    return 4


def _make_checkerboard(fw: int, fh: int, scale: int) -> Image.Image:
    """Fast vectorized checkerboard background: 2x2 subcells per pixel."""
    c1 = (58, 62, 74, 255)
    c2 = (46, 50, 60, 255)
    sub_w, sub_h = fw * 2, fh * 2
    base = Image.new("RGBA", (sub_w, sub_h))
    base.putdata([
        c1 if ((x + y) & 1) == 0 else c2
        for y in range(sub_h)
        for x in range(sub_w)
    ])
    return base.resize((fw * scale, fh * scale), Image.Resampling.NEAREST)


def _draw_ruled_grid_panel(
    sheet: Image.Image,
    frame: Image.Image,
    ox: int,
    oy: int,
    scale: int,
    label: str,
    coord_offset: Tuple[int, int] = (0, 0),
    baseline_y: Optional[int] = None,
    pivots: Optional[Sequence[Tuple[float, float]]] = None,
) -> None:
    fw, fh = frame.size
    bg = _make_checkerboard(fw, fh, scale)
    enlarged = frame.convert("RGBA").resize((fw * scale, fh * scale), Image.Resampling.NEAREST)
    composited = Image.alpha_composite(bg, enlarged).convert("RGB")
    sheet.paste(composited, (ox, oy))

    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text((ox, oy - 28), label, fill=(235, 240, 250), font=font)

    off_x, off_y = coord_offset
    step = 2 if max(fw, fh) <= 16 else (4 if max(fw, fh) <= 64 else 8)

    # Vertical grid lines + X coordinate labels
    for x in range(fw + 1):
        gx = ox + x * scale
        gx_coord = x + off_x
        major = (gx_coord % step == 0)
        col = (145, 158, 188) if major else (76, 82, 98)
        draw.line((gx, oy, gx, oy + fh * scale), fill=col)
        if x < fw and major:
            draw.text((gx + 1, oy - 13), str(gx_coord), fill=(175, 195, 230), font=font)

    # Horizontal grid lines + Y coordinate labels
    for y in range(fh + 1):
        gy = oy + y * scale
        gy_coord = y + off_y
        major = (gy_coord % step == 0)
        col = (145, 158, 188) if major else (76, 82, 98)
        draw.line((ox, gy, ox + fw * scale, gy), fill=col)
        if y < fh and major:
            txt = str(gy_coord)
            tx = ox - max(18, len(txt) * 6 + 4)
            draw.text((tx, gy + 1), txt, fill=(175, 195, 230), font=font)

    # Optional ground baseline reference (bottom edge of row `baseline_y`)
    if baseline_y is not None:
        local_by = baseline_y - off_y
        if 0 <= local_by < fh:
            by_px = oy + (local_by + 1) * scale
            for dash_x in range(ox, ox + fw * scale, 6):
                draw.line((dash_x, by_px, min(dash_x + 3, ox + fw * scale), by_px), fill=(255, 110, 90), width=2)

    # Optional pivot crosshairs
    if pivots:
        for px, py in pivots:
            cx = round(ox + (px - off_x + 0.5) * scale)
            cy = round(oy + (py - off_y + 0.5) * scale)
            draw.line((cx - 4, cy, cx + 4, cy), fill=(255, 220, 60), width=1)
            draw.line((cx, cy - 4, cx, cy + 4), fill=(255, 220, 60), width=1)


def _render_palette_legend(
    frames: Sequence[Image.Image],
    palette: Optional[Union[str, Dict[str, ColorDef]]],
    target_width: int,
) -> Optional[Image.Image]:
    if palette is None:
        return None

    rev = canonical_char_map(get_palette(palette))
    used_colors = set()
    for f in frames:
        for px in img_pixels(f.convert("RGBA")):
            npx = normalize_rgba(px)
            if npx[3] > 0:
                used_colors.add(npx)

    items: List[Tuple[str, RGBA]] = []
    for col in sorted(used_colors):
        if col in rev:
            items.append((rev[col], col))
    if not items:
        return None

    chip_w, chip_h = 112, 20
    pad_x, pad_y = 14, 8
    cols = max(1, (target_width - pad_x * 2) // chip_w)
    rows = (len(items) + cols - 1) // cols
    bar_h = pad_y * 2 + 16 + rows * (chip_h + 4)

    bar = Image.new("RGB", (target_width, bar_h), (24, 26, 34))
    draw = ImageDraw.Draw(bar)
    font = ImageFont.load_default()
    draw.text((pad_x, pad_y), "Active Palette Legend ([char] #HEX):", fill=(200, 210, 230), font=font)

    for idx, (ch, col) in enumerate(items):
        r_i, c_i = divmod(idx, cols)
        x0 = pad_x + c_i * chip_w
        y0 = pad_y + 16 + r_i * (chip_h + 4)
        draw.rectangle([x0, y0, x0 + 14, y0 + 14], fill=col[:3], outline=(180, 190, 210))
        draw.text((x0 + 19, y0 + 2), f"[{ch}] {rgba_to_hex(col)}", fill=(225, 230, 242), font=font)

    return bar


def _make_silhouette(frame: Image.Image, scale: int) -> Image.Image:
    rgba = frame.convert("RGBA")
    sil = Image.new("RGB", rgba.size, (18, 20, 26))
    sil.putdata([
        (245, 248, 255) if a >= 32 else (18, 20, 26)
        for _, _, _, a in img_pixels(rgba)
    ])
    return sil.resize((rgba.width * scale, rgba.height * scale), Image.Resampling.NEAREST)


def _make_onion_skin(prev_frame: Image.Image, curr_frame: Image.Image, scale: int) -> Image.Image:
    """Magenta = previous frame (N-1), Cyan = current frame (N), Light Silver = static overlap."""
    p_a = [a >= 32 for _, _, _, a in img_pixels(prev_frame.convert("RGBA"))]
    c_a = [a >= 32 for _, _, _, a in img_pixels(curr_frame.convert("RGBA"))]
    out = Image.new("RGB", curr_frame.size)
    data = []
    for p_on, c_on in zip(p_a, c_a):
        if p_on and c_on:
            data.append((215, 222, 235))  # Overlap (stationary anchor mass)
        elif c_on:
            data.append((44, 232, 245))   # Current frame motion front (Cyan)
        elif p_on:
            data.append((245, 65, 145))   # Previous frame trail (Magenta)
        else:
            data.append((18, 20, 26))     # Empty background
    out.putdata(data)
    return out.resize((curr_frame.width * scale, curr_frame.height * scale), Image.Resampling.NEAREST)


def generate_holistic_sheet(
    frames: Sequence[Image.Image],
    title: str = "Pixel Asset",
    palette: Optional[Union[str, Dict[str, ColorDef]]] = None,
    durations_ms: Optional[Sequence[int]] = None,
    scale: Optional[int] = None,
    max_cols: int = 4,
    coord_offset: Tuple[int, int] = (0, 0),
    baseline_y: Optional[int] = None,
    pivots: Optional[Sequence[Tuple[float, float]]] = None,
    include_clean_preview: bool = True,
    include_motion_diagnostics: Optional[bool] = None,
) -> Image.Image:
    """Create the all-in-one Multimodal Diagnostic Sheet for Vision LLMs."""
    if not frames:
        raise ValueError("frames must not be empty")
    fw, fh = frames[0].size
    if any(f.size != (fw, fh) for f in frames):
        raise ValueError("All frames in generate_holistic_sheet must share identical dimensions.")

    sc = _auto_scale(fw, fh) if scale is None else scale
    if sc < 2:
        raise ValueError("scale must be >= 2")

    show_motion = (len(frames) > 1) if include_motion_diagnostics is None else include_motion_diagnostics

    pad = 16
    left_ruler = 32
    top_ruler = 34
    panel_w = left_ruler + fw * sc + pad
    panel_h = top_ruler + fh * sc + pad

    cols = min(len(frames), max(1, max_cols))
    rows = (len(frames) + cols - 1) // cols
    grid_sec_w = max(460, cols * panel_w + pad)
    grid_sec_h = 28 + rows * panel_h + pad

    sections: List[Image.Image] = []

    # Title + Optional Palette Legend Header
    header_h = 30
    header = Image.new("RGB", (grid_sec_w, header_h), (20, 22, 30))
    hdraw = ImageDraw.Draw(header)
    font = ImageFont.load_default()
    hdraw.text(
        (pad, 9),
        f"{title}  |  Canvas: {fw}x{fh}px  |  Frames: {len(frames)}  |  Grid Zoom: {sc}x",
        fill=(240, 245, 255),
        font=font,
    )
    sections.append(header)

    legend = _render_palette_legend(frames, palette, grid_sec_w)
    if legend is not None:
        sections.append(legend)

    # Section 1: Coordinate-ruled inspection grid
    grid_sec = Image.new("RGB", (grid_sec_w, grid_sec_h), (30, 32, 42))
    gdraw = ImageDraw.Draw(grid_sec)
    gdraw.text(
        (pad, 8),
        "1. Coordinate Grid (0-based X/Y; dashed orange = baseline_y)",
        fill=(185, 200, 230),
        font=font,
    )

    auto_by = baseline_y
    if auto_by is None:
        bbox0 = frames[0].convert("RGBA").getchannel("A").getbbox()
        if bbox0 is not None:
            auto_by = bbox0[3] - 1 + coord_offset[1]

    for idx, frame in enumerate(frames):
        r_i, c_i = divmod(idx, cols)
        ox = pad + c_i * panel_w + left_ruler
        oy = 28 + pad + r_i * panel_h + top_ruler
        dur_txt = f" [{durations_ms[idx]}ms]" if durations_ms and idx < len(durations_ms) else ""
        lbl = f"F{idx}{dur_txt}"
        _draw_ruled_grid_panel(
            grid_sec,
            frame,
            ox,
            oy,
            sc,
            lbl,
            coord_offset=coord_offset,
            baseline_y=auto_by,
            pivots=pivots,
        )
    sections.append(grid_sec)

    # Preview scale for clean & motion strips
    prev_sc = max(2, min(6, sc // 2 if sc >= 6 else sc))

    # Section 2: Clean Real-Feel Preview (Dark & Light backgrounds, NO gridlines!)
    if include_clean_preview:
        item_gap = 10
        strip_w = len(frames) * (fw * prev_sc + item_gap) + 12
        box_h = fh * prev_sc + 12
        side_by_side = (strip_w * 2 + pad * 3) <= grid_sec_w

        if side_by_side:
            clean_w = grid_sec_w
            clean_h = 34 + box_h + pad
            half_w = (clean_w - pad * 3) // 2
        else:
            clean_w = max(grid_sec_w, strip_w + pad * 2)
            clean_h = 34 + box_h * 2 + 8 + pad
            half_w = clean_w - pad * 2

        clean_sec = Image.new("RGB", (clean_w, clean_h), (25, 27, 35))
        cdraw = ImageDraw.Draw(clean_sec)
        layout_hint = "Left = Dark BG | Right = Light BG" if side_by_side else "Top = Dark BG | Bottom = Light BG"
        cdraw.text(
            (pad, 8),
            f"2. Ungridded Clean Preview ({prev_sc}x) : {layout_hint}",
            fill=(185, 200, 230),
            font=font,
        )

        dark_box = Image.new("RGBA", (half_w, box_h), (24, 26, 34, 255))
        light_box = Image.new("RGBA", (half_w, box_h), (232, 236, 242, 255))

        for idx, frame in enumerate(frames):
            fx = 8 + idx * (fw * prev_sc + item_gap)
            if fx + fw * prev_sc <= half_w - 4:
                up = frame.convert("RGBA").resize((fw * prev_sc, fh * prev_sc), Image.Resampling.NEAREST)
                sub_d = dark_box.crop((fx, 6, fx + fw * prev_sc, 6 + fh * prev_sc))
                dark_box.paste(Image.alpha_composite(sub_d, up), (fx, 6))
                sub_l = light_box.crop((fx, 6, fx + fw * prev_sc, 6 + fh * prev_sc))
                light_box.paste(Image.alpha_composite(sub_l, up), (fx, 6))

        clean_sec.paste(dark_box.convert("RGB"), (pad, 28))
        if side_by_side:
            clean_sec.paste(light_box.convert("RGB"), (pad * 2 + half_w, 28))
        else:
            clean_sec.paste(light_box.convert("RGB"), (pad, 28 + box_h + 8))
        sections.append(clean_sec)

    # Section 3: Motion Diagnostics (Silhouette + Magenta/Cyan Onion-Skin)
    if show_motion and len(frames) > 1:
        cell_gap = 12
        mot_w = max(grid_sec_w, pad * 2 + len(frames) * (fw * prev_sc + cell_gap))
        row_h = fh * prev_sc + 22
        mot_h = 30 + row_h * 2 + pad
        mot_sec = Image.new("RGB", (mot_w, mot_h), (22, 24, 32))
        mdraw = ImageDraw.Draw(mot_sec)
        mdraw.text(
            (pad, 8),
            "3. Motion Diagnostics : Top = Silhouette Readability | Bottom = Onion-Skin (Magenta=Prev, Cyan=Curr, Gray=Static)",
            fill=(185, 200, 230),
            font=font,
        )

        for idx, frame in enumerate(frames):
            cx = pad + idx * (fw * prev_sc + cell_gap)
            sy = 30 + 14
            oy = 30 + row_h + 14
            sil = _make_silhouette(frame, prev_sc)
            prev_f = frames[(idx - 1) % len(frames)]
            onion = _make_onion_skin(prev_f, frame, prev_sc)

            mdraw.text((cx, sy - 12), f"F{idx}", fill=(165, 175, 195), font=font)
            mot_sec.paste(sil, (cx, sy))
            mdraw.rectangle([cx - 1, sy - 1, cx + fw * prev_sc, sy + fh * prev_sc], outline=(70, 76, 92))

            mdraw.text((cx, oy - 12), f"F{(idx-1)%len(frames)}->F{idx}", fill=(165, 175, 195), font=font)
            mot_sec.paste(onion, (cx, oy))
            mdraw.rectangle([cx - 1, oy - 1, cx + fw * prev_sc, oy + fh * prev_sc], outline=(70, 76, 92))

        sections.append(mot_sec)

    final_w = max(sec.width for sec in sections)
    final_h = sum(sec.height for sec in sections)
    master = Image.new("RGB", (final_w, final_h), (24, 26, 34))
    cur_y = 0
    for sec in sections:
        master.paste(sec, (0, cur_y))
        cur_y += sec.height
    return master


def generate_diff_sheet(
    before_img: Image.Image,
    after_img: Image.Image,
    title: str = "Pixel Edit Diff",
    scale: Optional[int] = None,
    coord_offset: Tuple[int, int] = (0, 0),
) -> Tuple[Image.Image, Dict[str, Union[int, Optional[List[int]]]]]:
    """Generate a 3-panel Before / After / Highlighted-Diff sheet with coordinate rulers."""
    if before_img.size != after_img.size:
        raise ValueError(f"Size mismatch in diff: {before_img.size} vs {after_img.size}")

    fw, fh = before_img.size
    sc = _auto_scale(fw, fh) if scale is None else scale

    b_rgba = before_img.convert("RGBA")
    a_rgba = after_img.convert("RGBA")
    b_data = [normalize_rgba(p) for p in img_pixels(b_rgba)]
    a_data = [normalize_rgba(p) for p in img_pixels(a_rgba)]

    diff_img = Image.new("RGBA", (fw, fh))
    diff_px: List[RGBA] = []
    added = removed = recolored = 0
    changed_xs: List[int] = []
    changed_ys: List[int] = []

    for idx, (bp, ap) in enumerate(zip(b_data, a_data)):
        x = idx % fw
        y = idx // fw
        if bp == ap:
            if ap[3] > 0:
                g = round(0.299 * ap[0] + 0.587 * ap[1] + 0.114 * ap[2])
                diff_px.append((g, g, g, 70))
            else:
                diff_px.append((0, 0, 0, 0))
        else:
            changed_xs.append(x + coord_offset[0])
            changed_ys.append(y + coord_offset[1])
            if bp[3] == 0 and ap[3] > 0:
                added += 1
                diff_px.append((0, 240, 155, 255))    # Bright emerald: Added pixel
            elif bp[3] > 0 and ap[3] == 0:
                removed += 1
                diff_px.append((255, 55, 90, 255))    # Bright crimson: Deleted pixel
            else:
                recolored += 1
                diff_px.append((255, 205, 45, 255))   # Bright amber: Recolored pixel

    diff_img.putdata(diff_px)
    total_changed = added + removed + recolored
    changed_bbox = (
        [min(changed_xs), min(changed_ys), max(changed_xs), max(changed_ys)]
        if changed_xs
        else None
    )

    pad = 16
    left_ruler = 32
    top_ruler = 36
    panel_w = left_ruler + fw * sc + pad
    sheet_w = max(560, panel_w * 3 + pad)
    sheet_h = 44 + top_ruler + fh * sc + pad * 2

    sheet = Image.new("RGB", (sheet_w, sheet_h), (28, 30, 40))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text(
        (pad, 10),
        f"{title} | Changed: {total_changed}px (+{added} added [Green], -{removed} erased [Red], ~{recolored} recolored [Amber])",
        fill=(240, 245, 255),
        font=font,
    )

    panels = [
        (b_rgba, "BEFORE"),
        (a_rgba, "AFTER"),
        (diff_img, f"DIFF ({total_changed}px)"),
    ]
    for p_idx, (p_im, p_lbl) in enumerate(panels):
        ox = pad + p_idx * panel_w + left_ruler
        oy = 40 + top_ruler
        _draw_ruled_grid_panel(sheet, p_im, ox, oy, sc, p_lbl, coord_offset=coord_offset)

    stats = {
        "changed_pixels": total_changed,
        "added": added,
        "removed": removed,
        "recolored": recolored,
        "changed_bbox": changed_bbox,
    }
    return sheet, stats
