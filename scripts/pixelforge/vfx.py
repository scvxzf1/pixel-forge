"""Pixel-Art Visual Effects (VFX) Prefabs:
Crescent weapon slash arcs, cel-shaded dust puffs, impact hit sparks, and looping twinkles.
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple
from PIL import Image

from .canvas import PixelCanvas
from .palette import ColorDef, parse_color, rgba_to_hex


def vfx_slash_arc(
    canvas_size: Tuple[int, int],
    center: Tuple[int, int],
    radius: int = 12,
    start_deg: float = -75.0,
    end_deg: float = 65.0,
    thickness: int = 4,
    core_color: ColorDef = "#FFFFFF",
    edge_color: ColorDef = "#2CE8F5",
    trail_color: ColorDef = "#0099DB",
) -> List[Image.Image]:
    """Generate a 4-frame pixel-art crescent weapon slash sequence."""
    w, h = canvas_size
    cx, cy = center
    pal = {
        "W": rgba_to_hex(parse_color(core_color)),
        "C": rgba_to_hex(parse_color(edge_color)),
        "B": rgba_to_hex(parse_color(trail_color)),
    }

    total_span = end_deg - start_deg
    # Frame specs: (sub_start_ratio, sub_end_ratio, peak_thick_scale, erode_checker)
    specs = [
        (0.00, 0.55, 0.75, False),  # F0: Initial fast swing lead-in
        (0.05, 1.00, 1.00, False),  # F1: Full wide crescent impact
        (0.42, 1.04, 0.60, False),  # F2: Follow-through thinning arc
        (0.72, 1.06, 0.35, True),   # F3: Dissipating pixel shards
    ]

    frames: List[Image.Image] = []
    for s_rat, e_rat, t_scale, erode in specs:
        c = PixelCanvas(w, h)
        a0 = start_deg + total_span * s_rat
        a1 = start_deg + total_span * e_rat
        steps = max(24, int(abs(a1 - a0) * 1.5))

        for i in range(steps + 1):
            u = i / float(steps)  # 0 (tail) -> 1 (tip)
            ang = math.radians(a0 + (a1 - a0) * u)
            # Taper crescent thickness smoothly at both ends, thickest near 65% toward tip
            profile = math.sin(math.pi * (u ** 0.8))
            local_thick = thickness * t_scale * profile
            if local_thick < 0.45:
                continue

            r_in = radius - local_thick * 0.65
            r_out = radius + local_thick * 0.35
            r_steps = max(2, int((r_out - r_in) * 2.5))
            for ri in range(r_steps + 1):
                rv = ri / float(r_steps)
                rr = r_in + (r_out - r_in) * rv
                px = round(cx + math.cos(ang) * rr)
                py = round(cy + math.sin(ang) * rr)
                if erode and ((px + py) % 2 == 0):
                    continue
                if rv > 0.58 and u > 0.25:
                    ch = "W"
                elif rv > 0.22:
                    ch = "C"
                else:
                    ch = "B"
                # Don't overwrite hotter core pixels with outer trail pixels
                cur = c.get_px(px, py)
                if cur == "." or (cur == "B" and ch in ("C", "W")) or (cur == "C" and ch == "W"):
                    c.set_px(px, py, ch)

        frames.append(c.render(pal))
    return frames


def vfx_dust_puff(
    canvas_size: Tuple[int, int],
    origin: Tuple[int, int],
    direction: str = "both",  # 'both' | 'left' | 'right'
    light_color: ColorDef = "#FFFFFF",
    mid_color: ColorDef = "#C0CBDC",
    dark_color: ColorDef = "#8B9BB4",
) -> List[Image.Image]:
    """Generate a 4-frame cel-shaded landing/dash dust burst anchored at `origin=(x, baseline_y)`."""
    if direction not in ("both", "left", "right"):
        raise ValueError("direction must be 'both', 'left', or 'right'")
    w, h = canvas_size
    ox, oy = origin
    pal = {
        "W": rgba_to_hex(parse_color(light_color)),
        "1": rgba_to_hex(parse_color(mid_color)),
        "2": rgba_to_hex(parse_color(dark_color)),
    }

    dirs = [-1, 1] if direction == "both" else ([-1] if direction == "left" else [1])
    # (dx_base, dy_base, radius, dissipate)
    stage_puffs = [
        [(2, 0, 2, False), (0, -1, 1, False)],
        [(4, -1, 3, False), (2, 0, 2, False)],
        [(7, -2, 2, False), (4, -3, 1, False)],
        [(9, -3, 1, True), (6, -4, 1, True)],
    ]

    frames: List[Image.Image] = []
    for puffs in stage_puffs:
        c = PixelCanvas(w, h)
        for sgn in dirs:
            for dx, dy, rad, dissipate in puffs:
                px = ox + sgn * dx
                py = oy + dy - rad
                if rad <= 1:
                    if not dissipate or (px + py) % 2 == 0:
                        c.set_px(px, py, "1")
                        c.set_px(px, py - 1, "W")
                else:
                    c.circle(px, py, rad, fill="1")
                    # Top highlight & bottom shadow for classic cel-shaded puffball look
                    c.circle(px - sgn * 0, py - 1, max(1, rad - 1), fill="W")
                    for sx in range(px - rad, px + rad + 1):
                        if c.get_px(sx, py + rad) != ".":
                            c.set_px(sx, py + rad, "2")
        frames.append(c.render(pal))
    return frames


def vfx_hit_spark(
    canvas_size: Tuple[int, int],
    center: Tuple[int, int],
    radius: int = 7,
    core_color: ColorDef = "#FFFFFF",
    accent_color: ColorDef = "#FEAE34",
) -> List[Image.Image]:
    """Generate a 4-frame crisp arcade impact cross-spark."""
    w, h = canvas_size
    cx, cy = center
    pal = {
        "W": rgba_to_hex(parse_color(core_color)),
        "Y": rgba_to_hex(parse_color(accent_color)),
    }

    frames: List[Image.Image] = []
    # Frame 0: Tight bright flash diamond
    c0 = PixelCanvas(w, h)
    r0 = max(2, radius // 2)
    c0.polygon([(cx, cy - r0), (cx + r0, cy), (cx, cy + r0), (cx - r0, cy)], fill="W", outline="W")
    frames.append(c0.render(pal))

    # Frame 1: Full cardinal + diagonal star burst
    c1 = PixelCanvas(w, h)
    c1.line(cx - radius, cy, cx + radius, cy, "Y", pixel_perfect=False)
    c1.line(cx, cy - radius, cx, cy + radius, "Y", pixel_perfect=False)
    d_rad = max(2, round(radius * 0.6))
    c1.line(cx - d_rad, cy - d_rad, cx + d_rad, cy + d_rad, "Y")
    c1.line(cx - d_rad, cy + d_rad, cx + d_rad, cy - d_rad, "Y")
    c1.circle(cx, cy, max(1, radius // 3), fill="W")
    frames.append(c1.render(pal))

    # Frame 2: Hollowed outward tips
    c2 = PixelCanvas(w, h)
    inner = max(2, radius // 2)
    outer = radius + 1
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        c2.line(cx + dx * inner, cy + dy * inner, cx + dx * outer, cy + dy * outer, "W")
    for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        c2.set_px(cx + dx * d_rad, cy + dy * d_rad, "Y")
    frames.append(c2.render(pal))

    # Frame 3: Final outer pinpoint embers
    c3 = PixelCanvas(w, h)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        c3.set_px(cx + dx * (outer + 1), cy + dy * (outer + 1), "Y")
    frames.append(c3.render(pal))

    return frames


def vfx_twinkle_stars(
    canvas_size: Tuple[int, int],
    centers: Sequence[Tuple[int, int]],
    frames_count: int = 6,
    core_color: ColorDef = "#FFFFFF",
    glow_color: ColorDef = "#FEE761",
) -> List[Image.Image]:
    """Generate a seamless looping sparkle overlay across multiple `(x, y)` points."""
    w, h = canvas_size
    pal = {
        "W": rgba_to_hex(parse_color(core_color)),
        "Y": rgba_to_hex(parse_color(glow_color)),
    }
    frames: List[Image.Image] = []
    for f_idx in range(frames_count):
        c = PixelCanvas(w, h)
        for p_idx, (cx, cy) in enumerate(centers):
            phase = (f_idx + p_idx * 2) % frames_count
            if phase == 0:
                c.set_px(cx, cy, "Y")
            elif phase == 1:
                c.set_px(cx, cy, "W")
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    c.set_px(cx + dx, cy + dy, "Y")
            elif phase == 2:
                c.set_px(cx, cy, "W")
                for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-1, 0), (1, 0), (0, -1), (0, 1)):
                    c.set_px(cx + dx, cy + dy, "W" if abs(dx) + abs(dy) == 1 else "Y")
            elif phase == 3:
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    c.set_px(cx + dx, cy + dy, "Y")
        frames.append(c.render(pal))
    return frames


def composite_vfx(
    base_frames: Sequence[Image.Image],
    vfx_frames: Sequence[Image.Image],
    start_frame: int = 0,
    under: bool = False,
) -> List[Image.Image]:
    """Overlay (or underlay) `vfx_frames` onto `base_frames` beginning at `start_frame`."""
    out = [f.convert("RGBA").copy() for f in base_frames]
    for i, vf in enumerate(vfx_frames):
        target_idx = start_frame + i
        if 0 <= target_idx < len(out):
            v_rgba = vf.convert("RGBA")
            if v_rgba.size != out[target_idx].size:
                raise ValueError("VFX canvas size must match base frame size.")
            out[target_idx] = (
                Image.alpha_composite(v_rgba, out[target_idx])
                if under
                else Image.alpha_composite(out[target_idx], v_rgba)
            )
    return out
