"""AI Concept / Exploded Part-Sheet Auto-Segmenter & Sketch-to-Rig Pipeline:
1. Edge-seeded flood-fill background removal (preserves interior white eyes/highlights!)
2. Connected-component part island segmentation & fragment merging
3. Unified-scale shared-palette pixelation across all parts
4. Anatomical role & hinge pivot inference (torso, head, wings, arms/weapons) + socket docking
5. Self-contained executable `rig_<name>.py` code generator + animated verification sheet
"""
from __future__ import annotations

import json
import math
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .canvas import image_to_grid
from .exporter import build_pixel_asset
from .palette import (
    ColorDef,
    RGBA,
    canonical_char_map,
    color_distance_sq,
    extract_palette,
    get_palette,
    img_pixels,
    normalize_rgba,
    rgba_to_hex,
)
from .rig import Rig


def remove_solid_background(
    img: Image.Image,
    tolerance: int = 34,
    defringe_border: bool = True,
) -> Image.Image:
    """Strip solid studio background via edge-seeded flood fill (never pokes holes in interior whites!)."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()

    # Check if corners are already transparent
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    if sum(1 for c in corners if c[3] < 24) >= 3:
        return rgba.copy()

    # Sample border perimeter colors (binned coarsely) to find studio bg color
    border_samples: Counter[Tuple[int, int, int]] = Counter()
    for x in range(w):
        for y in (0, h - 1):
            r, g, b, a = px[x, y]
            if a >= 128:
                border_samples[(r // 4 * 4, g // 4 * 4, b // 4 * 4)] += 1
    for y in range(h):
        for x in (0, w - 1):
            r, g, b, a = px[x, y]
            if a >= 128:
                border_samples[(r // 4 * 4, g // 4 * 4, b // 4 * 4)] += 1

    if not border_samples:
        return rgba.copy()

    bg_rgb = border_samples.most_common(1)[0][0]
    bg_rgba: RGBA = (bg_rgb[0], bg_rgb[1], bg_rgb[2], 255)
    tol_sq = tolerance * tolerance * 9.0

    visited = [[False] * w for _ in range(h)]
    bg_mask = [[False] * w for _ in range(h)]
    q: deque[Tuple[int, int]] = deque()

    def _try_seed(sx: int, sy: int) -> None:
        if not visited[sy][sx]:
            c = px[sx, sy]
            if c[3] < 24 or color_distance_sq((c[0], c[1], c[2], 255), bg_rgba) <= tol_sq:
                visited[sy][sx] = True
                bg_mask[sy][sx] = True
                q.append((sx, sy))

    for x in range(w):
        _try_seed(x, 0)
        _try_seed(x, h - 1)
    for y in range(h):
        _try_seed(0, y)
        _try_seed(w - 1, y)

    while q:
        cx, cy = q.popleft()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx]:
                visited[ny][nx] = True
                nc = px[nx, ny]
                if nc[3] < 24 or color_distance_sq((nc[0], nc[1], nc[2], 255), bg_rgba) <= tol_sq:
                    bg_mask[ny][nx] = True
                    q.append((nx, ny))

    out = rgba.copy()
    dst = out.load()
    defringe_tol_sq = tol_sq * 2.2

    for y in range(h):
        for x in range(w):
            if bg_mask[y][x]:
                dst[x, y] = (0, 0, 0, 0)
            elif defringe_border:
                # Strip 1px anti-aliased bg halo bordering flood-filled background
                touches_bg = any(
                    0 <= x + dx < w and 0 <= y + dy < h and bg_mask[y + dy][x + dx]
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                )
                if touches_bg:
                    c = px[x, y]
                    if color_distance_sq((c[0], c[1], c[2], 255), bg_rgba) <= defringe_tol_sq:
                        dst[x, y] = (0, 0, 0, 0)
    return out


@dataclass
class SegmentedIsland:
    index: int
    bbox: Tuple[int, int, int, int]  # (x0, y0, x1_excl, y1_excl)
    area: int
    centroid: Tuple[float, float]
    crop_rgba: Image.Image
    role: str = "part"
    z_index: int = 10
    outline_group: int = 0


def segment_parts_from_sheet(
    source_img: Image.Image,
    min_area_ratio: float = 0.0025,
    alpha_threshold: int = 64,
    merge_gap_px: int = 4,
) -> Tuple[Image.Image, List[SegmentedIsland]]:
    """Remove solid bg if present and segment connected foreground part islands."""
    clean = remove_solid_background(source_img)
    w, h = clean.size
    px = clean.load()

    visited = [[False] * w for _ in range(h)]
    raw_islands: List[Tuple[List[Tuple[int, int]], List[int]]] = []  # (pts, [x0, y0, x1, y1])

    for y in range(h):
        for x in range(w):
            if not visited[y][x] and px[x, y][3] >= alpha_threshold:
                visited[y][x] = True
                pts: List[Tuple[int, int]] = []
                q = deque([(x, y)])
                bx0, by0, bx1, by1 = x, y, x + 1, y + 1
                while q:
                    cx, cy = q.popleft()
                    pts.append((cx, cy))
                    if cx < bx0:
                        bx0 = cx
                    if cy < by0:
                        by0 = cy
                    if cx + 1 > bx1:
                        bx1 = cx + 1
                    if cy + 1 > by1:
                        by1 = cy + 1
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            if dx == 0 and dy == 0:
                                continue
                            nx, ny = cx + dx, cy + dy
                            if 0 <= nx < w and 0 <= ny < h and not visited[ny][nx] and px[nx, ny][3] >= alpha_threshold:
                                visited[ny][nx] = True
                                q.append((nx, ny))
                raw_islands.append((pts, [bx0, by0, bx1, by1]))

    min_px = max(8, round(w * h * min_area_ratio))
    major = [it for it in raw_islands if len(it[0]) >= min_px]
    minor = [it for it in raw_islands if 3 <= len(it[0]) < min_px]

    # Merge nearby minor fragments (like detached crests/pommels) into nearest major island within `merge_gap_px`
    for m_pts, mb in minor:
        for p_pts, pb in major:
            gx = max(0, max(mb[0] - pb[2], pb[0] - mb[2]))
            gy = max(0, max(mb[1] - pb[3], pb[1] - mb[3]))
            if gx <= merge_gap_px and gy <= merge_gap_px:
                p_pts.extend(m_pts)
                pb[0] = min(pb[0], mb[0])
                pb[1] = min(pb[1], mb[1])
                pb[2] = max(pb[2], mb[2])
                pb[3] = max(pb[3], mb[3])
                break

    islands: List[SegmentedIsland] = []
    for idx, (pts, (x0, y0, x1, y1)) in enumerate(major):
        cw_i, ch_i = x1 - x0, y1 - y0
        crop = Image.new("RGBA", (cw_i, ch_i), (0, 0, 0, 0))
        cpx = crop.load()
        sx_sum = sy_sum = 0.0
        for ux, uy in pts:
            cpx[ux - x0, uy - y0] = px[ux, uy]
            sx_sum += ux
            sy_sum += uy
        n = float(len(pts))
        islands.append(
            SegmentedIsland(
                index=idx,
                bbox=(x0, y0, x1, y1),
                area=len(pts),
                centroid=(sx_sum / n, sy_sum / n),
                crop_rgba=crop,
            )
        )

    # Assign anatomical roles heuristically based on spatial layout relative to central mass
    if islands:
        _assign_anatomical_roles(islands, w, h)

    return clean, islands


def _assign_anatomical_roles(islands: List[SegmentedIsland], sheet_w: int, sheet_h: int) -> None:
    if len(islands) == 1:
        islands[0].role = "body"
        islands[0].z_index = 10
        islands[0].outline_group = 0
        return

    # Torso = large central island (score combines area and proximity to horizontal center)
    mid_x = sheet_w * 0.5
    max_area = max(it.area for it in islands)
    torso = max(
        islands,
        key=lambda it: (it.area / float(max_area)) - 0.55 * abs(it.centroid[0] - mid_x) / max(1.0, mid_x),
    )
    torso.role = "torso"
    torso.z_index = 10
    torso.outline_group = 0

    tx, ty = torso.centroid
    tw = torso.bbox[2] - torso.bbox[0]

    remaining = [it for it in islands if it is not torso]
    used_roles = {"torso"}

    # Head = island above torso, near torso X
    above_cands = [
        it for it in remaining
        if it.centroid[1] < torso.bbox[1] + (torso.bbox[3] - torso.bbox[1]) * 0.25
        and abs(it.centroid[0] - tx) < tw * 0.9
    ]
    if above_cands:
        head = max(above_cands, key=lambda it: it.area)
        head.role = "head"
        head.z_index = 20
        head.outline_group = 0
        used_roles.add("head")
        remaining.remove(head)

    # Classify side parts (left vs right of torso)
    left_parts = sorted([it for it in remaining if it.centroid[0] < tx], key=lambda it: it.centroid[1])
    right_parts = sorted([it for it in remaining if it.centroid[0] >= tx], key=lambda it: it.centroid[1])

    # Check if there's a symmetric pair of upper side wings
    if left_parts and right_parts:
        lp0, rp0 = left_parts[0], right_parts[0]
        area_ratio = min(lp0.area, rp0.area) / float(max(lp0.area, rp0.area))
        both_high = lp0.centroid[1] <= ty and rp0.centroid[1] <= ty
        if area_ratio >= 0.60 and both_high and len(left_parts) + len(right_parts) >= 3:
            lp0.role = "wing_l"
            lp0.z_index = 4
            lp0.outline_group = 0
            rp0.role = "wing_r"
            rp0.z_index = 4
            rp0.outline_group = 0
            left_parts.pop(0)
            right_parts.pop(0)
            used_roles.update(("wing_l", "wing_r"))

    for idx, lp in enumerate(left_parts):
        lp.role = "shield_l" if idx == 0 and "shield_l" not in used_roles else f"part_l{idx}"
        lp.z_index = 25 + idx
        lp.outline_group = 1
        used_roles.add(lp.role)

    for idx, rp in enumerate(right_parts):
        bw = rp.bbox[2] - rp.bbox[0]
        bh = rp.bbox[3] - rp.bbox[1]
        is_elongated = (bh / float(max(1, bw))) >= 1.55
        if idx == 0 and "weapon_r" not in used_roles and is_elongated:
            rp.role = "weapon_r"
        elif idx == 0 and "arm_r" not in used_roles:
            rp.role = "arm_r"
        else:
            rp.role = f"part_r{idx}"
        rp.z_index = 30 + idx
        rp.outline_group = 1
        used_roles.add(rp.role)


def _infer_local_pivot(role: str, pw: int, ph: int) -> Tuple[float, float]:
    if role == "head":
        return ((pw - 1) / 2.0, float(max(0, ph - 1)))  # Neck base
    if role == "wing_l":
        return (float(max(0, pw - 1)), ph * 0.55)       # Right inner shoulder joint
    if role == "wing_r":
        return (0.0, ph * 0.55)                         # Left inner shoulder joint
    if role in ("weapon_r", "arm_r"):
        return (pw * 0.35, ph * 0.75)                   # Hilt / grip hinge
    if role == "shield_l":
        return (pw * 0.6, ph * 0.5)
    return ((pw - 1) / 2.0, (ph - 1) / 2.0)


def _write_generated_rig_script(
    script_path: Path,
    pforge_dir: Path,
    name: str,
    canvas_size: Tuple[int, int],
    palette_dict: Dict[str, str],
    parts_spec: Sequence[Dict[str, Any]],
) -> None:
    pal_json = json.dumps(palette_dict, indent=4, ensure_ascii=False)
    lines = [
        "#!/usr/bin/env python3",
        f'"""Auto-generated PixelForge Rig from segmented concept sheet: {name}."""',
        "import sys",
        f"sys.path.insert(0, {str(pforge_dir)!r})",
        "from pforge import Rig, build_pixel_asset",
        "",
        f"PALETTE = {pal_json}",
        "",
    ]
    for p in parts_spec:
        var = f"PART_{p['role'].upper()}"
        lines.append(f"{var} = [")
        for row in p["grid"]:
            lines.append(f"    {row!r},")
        lines.append("]")
        lines.append("")

    lines.append(f"rig = Rig(canvas_size={canvas_size!r}, palette=PALETTE, outline_mode='outer', outline_color='#181425')")
    for p in parts_spec:
        var = f"PART_{p['role'].upper()}"
        lines.append(
            f"rig.add_part({p['role']!r}, {var}, offset={tuple(p['offset'])!r}, "
            f"pivot_local={tuple(p['pivot_local'])!r}, z_index={p['z_index']}, outline_group={p['outline_group']!r})"
        )

    lines.extend([
        "",
        "POSES = [",
        "    {},",
        "    {'torso': {'dy': 1}, 'head': {'dy': 1}, 'wing_l': {'angle': 12}, 'wing_r': {'angle': -12}, 'weapon_r': {'angle': -18}},",
        "    {'torso': {'dy': 1}, 'head': {'dy': 2}, 'wing_l': {'angle': 20}, 'wing_r': {'angle': -20}, 'weapon_r': {'angle': -32}},",
        "    {'torso': {'dy': 0}, 'head': {'dy': 1}, 'wing_l': {'angle': -10}, 'wing_r': {'angle': 10}, 'weapon_r': {'angle': 45, 'dx': 2}},",
        "]",
        "",
        'if __name__ == "__main__":',
        "    frames = [rig.render_pose({k: v for k, v in p.items() if k in rig.parts}) for p in POSES]",
        f'    build_pixel_asset({name!r}, frames, palette=PALETTE, durations_ms=[220, 140, 180, 120], pivots=rig.get_canvas_pivots(), output_dir="output")',
        "",
    ])
    script_path.write_text("\n".join(lines), encoding="utf-8")


def autorig_from_concept_sheet(
    source: Union[str, Path, Image.Image],
    name: str = "concept_actor",
    canvas_size: Tuple[int, int] = (56, 56),
    part_scale_target: int = 42,
    palette: Optional[Union[str, Dict[str, ColorDef]]] = "endesga32",
    max_colors: int = 28,
    assemble_exploded: bool = True,
    outline_mode: str = "outer",
    output_dir: Union[str, Path] = "output/autorig",
) -> Dict[str, Any]:
    """End-to-end Sketch-to-Rig pipeline:
    High-res exploded concept sheet -> Clean BG -> Segment Islands -> Shared-Palette Pixelate
    -> Socket Assembly & Pivot Inference -> Animated Preview + `rig_<name>.py`!
    """
    src_img = Image.open(source).convert("RGBA") if isinstance(source, (str, Path)) else source.convert("RGBA")
    clean_sheet, islands = segment_parts_from_sheet(src_img)
    if not islands:
        raise ValueError("No foreground part islands detected in concept sheet.")

    # Compute ONE unified downsampling factor so all parts maintain true relative scale!
    all_x0 = min(it.bbox[0] for it in islands)
    all_y0 = min(it.bbox[1] for it in islands)
    all_x1 = max(it.bbox[2] for it in islands)
    all_y1 = max(it.bbox[3] for it in islands)
    span = float(max(all_x1 - all_x0, all_y1 - all_y0, 1))
    scale_f = min(1.0, part_scale_target / span)

    # Resolve shared target palette
    if palette is None or (isinstance(palette, str) and palette.lower() == "auto"):
        pal_dict = extract_palette(clean_sheet, max_colors=max_colors, alpha_threshold=96)
    else:
        resolved = get_palette(palette)
        pal_dict = {k: rgba_to_hex(v) for k, v in resolved.items() if k != " "}
    if "K" not in pal_dict:
        pal_dict["K"] = "#181425"

    rev_pal = canonical_char_map(pal_dict)
    opaque_cols = [c for c in rev_pal if c[3] > 0]

    # Downsample & quantize every part cleanly with uniform `scale_f`
    px_parts: Dict[str, Dict[str, Any]] = {}
    for it in islands:
        pw = max(3, round(it.crop_rgba.width * scale_f))
        ph = max(3, round(it.crop_rgba.height * scale_f))
        rgb = ImageEnhance.Contrast(it.crop_rgba.convert("RGB")).enhance(1.12)
        s_rgb = rgb.resize((pw, ph), Image.Resampling.BOX)
        s_a = it.crop_rgba.getchannel("A").resize((pw, ph), Image.Resampling.BOX)
        merged = Image.merge("RGBA", (*s_rgb.split(), s_a))

        q_data: List[RGBA] = []
        for r, g, b, a in img_pixels(merged):
            if a < 110:
                q_data.append((0, 0, 0, 0))
            else:
                best = min(opaque_cols, key=lambda pc: color_distance_sq((r, g, b, 255), pc))
                q_data.append(best)
        p_im = Image.new("RGBA", (pw, ph))
        p_im.putdata(q_data)
        grid_lines, _ = image_to_grid(p_im, palette=pal_dict)
        piv_loc = _infer_local_pivot(it.role, pw, ph)
        px_parts[it.role] = {
            "role": it.role,
            "island": it,
            "image": p_im,
            "grid": grid_lines,
            "w": pw,
            "h": ph,
            "pivot_local": [round(piv_loc[0], 1), round(piv_loc[1], 1)],
            "z_index": it.z_index,
            "outline_group": it.outline_group,
        }

    cw, ch = canvas_size
    # Compute stage offsets (either anatomical socket docking for exploded sheets, or scaled sheet coords)
    if assemble_exploded and "torso" in px_parts:
        t_spec = px_parts["torso"]
        tw, th = t_spec["w"], t_spec["h"]
        tx = (cw - tw) // 2
        ty = (ch - th) // 2 + 4
        t_spec["offset"] = [tx, ty]

        for role, p in px_parts.items():
            if role == "torso":
                continue
            pw, ph = p["w"], p["h"]
            if role == "head":
                p["offset"] = [tx + (tw - pw) // 2, max(2, ty - ph + 2)]
            elif role == "wing_l":
                p["offset"] = [max(1, tx - pw + 2), max(2, ty - ph // 3)]
            elif role == "wing_r":
                p["offset"] = [min(cw - pw - 1, tx + tw - 2), max(2, ty - ph // 3)]
            elif role == "shield_l":
                p["offset"] = [max(1, tx - pw // 2 - 2), ty + (th - ph) // 2]
            elif role in ("weapon_r", "arm_r"):
                p["offset"] = [min(cw - pw - 1, tx + tw - 2), max(2, ty + th // 2 - round(p["pivot_local"][1]))]
            else:
                # Fallback proportional offset relative to torso centroid
                dx_px = round((p["island"].centroid[0] - t_spec["island"].centroid[0]) * scale_f * 0.65)
                dy_px = round((p["island"].centroid[1] - t_spec["island"].centroid[1]) * scale_f * 0.65)
                p["offset"] = [
                    max(1, min(cw - pw - 1, tx + tw // 2 + dx_px - pw // 2)),
                    max(1, min(ch - ph - 1, ty + th // 2 + dy_px - ph // 2)),
                ]
    else:
        ox_pad = (cw - round((all_x1 - all_x0) * scale_f)) // 2
        oy_pad = (ch - round((all_y1 - all_y0) * scale_f)) // 2
        for p in px_parts.values():
            bx0, by0, _, _ = p["island"].bbox
            p["offset"] = [
                max(0, ox_pad + round((bx0 - all_x0) * scale_f)),
                max(0, oy_pad + round((by0 - all_y0) * scale_f)),
            ]

    # Build live Rig & render 6-frame Idle + Action test animation!
    rig = Rig(canvas_size=canvas_size, palette=pal_dict, outline_mode=outline_mode, outline_color="#181425")
    ordered_specs = sorted(px_parts.values(), key=lambda x: x["z_index"])
    for p in ordered_specs:
        rig.add_part(
            p["role"],
            p["grid"],
            offset=(p["offset"][0], p["offset"][1]),
            pivot_local=(p["pivot_local"][0], p["pivot_local"][1]),
            z_index=p["z_index"],
            outline_group=p["outline_group"],
        )

    raw_test_poses = [
        {},
        {"torso": {"dy": 1}, "head": {"dy": 1}, "wing_l": {"angle": 12}, "wing_r": {"angle": -12}, "shield_l": {"dy": 1}, "weapon_r": {"angle": -18}},
        {"torso": {"dy": 1, "scale_x": 1.05, "scale_y": 0.95}, "head": {"dy": 2}, "wing_l": {"angle": 22}, "wing_r": {"angle": -22}, "shield_l": {"dx": -1, "dy": 1}, "weapon_r": {"angle": -45, "dx": -1}},
        {"torso": {"dx": 2}, "head": {"dx": 2}, "wing_l": {"angle": -14}, "wing_r": {"angle": 14}, "weapon_r": {"angle": 55, "dx": 2, "dy": 1}, "arm_r": {"angle": 35, "dx": 2}},
        {"torso": {"dx": 2}, "head": {"dx": 2}, "wing_l": {"angle": -8}, "wing_r": {"angle": 8}, "weapon_r": {"angle": 62, "dx": 2, "dy": 1}, "arm_r": {"angle": 40, "dx": 2}},
        {"wing_l": {"angle": 4}, "wing_r": {"angle": -4}, "weapon_r": {"angle": 15}},
    ]
    anim_frames = [
        rig.render_pose({k: v for k, v in pose.items() if k in rig.parts})
        for pose in raw_test_poses
    ]

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    asset_meta = build_pixel_asset(
        f"{name}_autorig",
        anim_frames,
        palette=pal_dict,
        durations_ms=[220, 130, 170, 55, 75, 140],
        pivots=rig.get_canvas_pivots(),
        output_dir=out,
    )

    rig_script = out / f"rig_{name}.py"
    pforge_scripts_dir = Path(__file__).resolve().parent.parent
    _write_generated_rig_script(rig_script, pforge_scripts_dir, name, canvas_size, pal_dict, ordered_specs)

    # Build 3-Stage Auto-Rig Pipeline Inspection Sheet!
    pipeline_sheet = _build_autorig_pipeline_sheet(src_img, islands, ordered_specs, anim_frames, name)
    pipeline_path = out / f"{name}_autorig_pipeline.png"
    pipeline_sheet.save(pipeline_path)

    print(f"Auto-Rigged [{name}] ({len(ordered_specs)} segmented parts -> {canvas_size[0]}x{canvas_size[1]}):")
    print(f"  - VIEW PIPELINE SHEET:   {pipeline_path}")
    print(f"  - Editable Rig Script:   {rig_script}")
    return {
        "name": name,
        "parts_detected": [p["role"] for p in ordered_specs],
        "rig": rig,
        "frames": anim_frames,
        "files": {
            "pipeline_sheet": str(pipeline_path),
            "rig_script": str(rig_script),
            **asset_meta["files"],
        },
    }


def _build_autorig_pipeline_sheet(
    src_img: Image.Image,
    islands: Sequence[SegmentedIsland],
    parts_spec: Sequence[Dict[str, Any]],
    anim_frames: Sequence[Image.Image],
    name: str,
) -> Image.Image:
    font = ImageFont.load_default()
    pad = 16

    # Panel 1: Source Sheet with segmented bounding boxes & role tags
    target_h = 220
    s_scale = target_h / float(max(1, src_img.height))
    sw_vis = max(1, round(src_img.width * s_scale))
    p1 = Image.new("RGBA", (sw_vis, target_h), (240, 242, 246, 255))
    p1 = Image.alpha_composite(p1, src_img.resize((sw_vis, target_h), Image.Resampling.LANCZOS)).convert("RGB")
    d1 = ImageDraw.Draw(p1)
    box_colors = [(230, 55, 70), (25, 135, 235), (40, 180, 95), (215, 135, 20), (155, 65, 215), (20, 175, 180)]
    for idx, it in enumerate(islands):
        col = box_colors[idx % len(box_colors)]
        rx0 = round(it.bbox[0] * s_scale)
        ry0 = round(it.bbox[1] * s_scale)
        rx1 = round(it.bbox[2] * s_scale)
        ry1 = round(it.bbox[3] * s_scale)
        d1.rectangle([rx0, ry0, rx1, ry1], outline=col, width=2)
        d1.rectangle([rx0, max(0, ry0 - 12), rx0 + len(it.role) * 6 + 6, ry0], fill=col)
        d1.text((rx0 + 3, max(0, ry0 - 11)), it.role, fill=(255, 255, 255), font=font)

    # Panel 2: Pixelated parts gallery + yellow pivot hinge crosshairs
    part_zoom = 5
    gal_x = 10
    p2_w = sum(p["w"] * part_zoom + 24 for p in parts_spec) + 16
    p2 = Image.new("RGB", (max(200, p2_w), target_h), (34, 38, 48))
    d2 = ImageDraw.Draw(p2)
    for p in parts_spec:
        im_up = p["image"].resize((p["w"] * part_zoom, p["h"] * part_zoom), Image.Resampling.NEAREST)
        oy = (target_h - im_up.height) // 2 + 6
        bg = Image.new("RGBA", im_up.size, (48, 52, 66, 255))
        p2.paste(Image.alpha_composite(bg, im_up).convert("RGB"), (gal_x, oy))
        d2.rectangle([gal_x - 1, oy - 1, gal_x + im_up.width, oy + im_up.height], outline=(85, 95, 118))
        d2.text((gal_x, oy - 14), p["role"], fill=(205, 220, 245), font=font)
        # Yellow pivot crosshair
        px_c = round(gal_x + (p["pivot_local"][0] + 0.5) * part_zoom)
        py_c = round(oy + (p["pivot_local"][1] + 0.5) * part_zoom)
        d2.line((px_c - 4, py_c, px_c + 4, py_c), fill=(255, 225, 55), width=1)
        d2.line((px_c, py_c - 4, px_c, py_c + 4), fill=(255, 225, 55), width=1)
        gal_x += im_up.width + 24

    # Panel 3: Assembled & Rigged Action Strip
    fw, fh = anim_frames[0].size
    azoom = max(2, min(4, (target_h - 24) // max(1, fh)))
    strip_w = len(anim_frames) * (fw * azoom + 10) + 16
    sheet_w = max(660, p1.width + p2.width + pad * 3, strip_w + pad * 2)
    sheet_h = 42 + target_h + 36 + fh * azoom + pad * 2

    sheet = Image.new("RGB", (sheet_w, sheet_h), (22, 24, 32))
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (pad, 10),
        f"Sketch-to-Rig Pipeline [{name}] : 1. AI/Concept Part Segmentation -> 2. Pixel Parts + Hinges -> 3. Live Rigged Poses",
        fill=(240, 245, 255),
        font=font,
    )
    draw.text((pad, 30), "1. Segmented Concept Sheet (Edge-Flood BG Removed)", fill=(185, 200, 230), font=font)
    sheet.paste(p1, (pad, 46))

    x2 = pad * 2 + p1.width
    draw.text((x2, 30), "2. Unified-Scale Pixel Parts (+ Yellow Hinges)", fill=(185, 200, 230), font=font)
    sheet.paste(p2, (x2, 46))

    y3 = 46 + target_h + 26
    draw.text((pad, y3 - 16), f"3. Auto-Docked & Articulated Rig Preview ({azoom}x):", fill=(185, 200, 230), font=font)
    for idx, af in enumerate(anim_frames):
        fx = pad + idx * (fw * azoom + 10)
        up = af.resize((fw * azoom, fh * azoom), Image.Resampling.NEAREST)
        fbg = Image.new("RGBA", up.size, (36, 40, 52, 255))
        sheet.paste(Image.alpha_composite(fbg, up).convert("RGB"), (fx, y3))
        draw.rectangle([fx - 1, y3 - 1, fx + up.width, y3 + up.height], outline=(72, 80, 98))
        draw.text((fx + 2, y3 + 2), f"F{idx}", fill=(180, 195, 220), font=font)

    return sheet
