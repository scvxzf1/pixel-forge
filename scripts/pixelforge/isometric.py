"""2:1 Pixel-Art Isometric Engine (`IsoScene`, lattice-exact 2:1 tessellation & 3-face lit prisms)
and 4/8-Direction RPG Character Derivation (`DirectionalRig` turnaround & walk-cycle generator).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from PIL import Image, ImageDraw, ImageFont

from .canvas import GridLike, parse_grid_lines, render_grid
from .exporter import build_aseprite_atlas_json, save_animated_webp, save_rgba_gif
from .palette import ColorDef, RGBA, generate_shading_ramp, get_palette, parse_color
from .rig import Rig
from .transform import add_ground_shadow, auto_outline, flip_grid, flip_image

DIRECTIONS_4: Tuple[str, ...] = ("s", "e", "n", "w")
DIRECTIONS_8: Tuple[str, ...] = ("s", "se", "e", "ne", "n", "nw", "w", "sw")


# ============================================================================
# Part 1: Lattice-Exact 2:1 Pixel Isometric Engine (`render_iso_prism` & `IsoScene`)
# ============================================================================

def render_iso_prism(
    half_h: int = 8,
    u_cells: int = 1,
    v_cells: int = 1,
    height_z: int = 12,
    top_color: ColorDef = "#63C74D",
    left_color: ColorDef = "#8F563B",
    right_color: ColorDef = "#663931",
    outline_color: Optional[ColorDef] = "#181425",
    ridge_highlight: Optional[ColorDef] = "#91DB69",
) -> Tuple[Image.Image, Tuple[int, int]]:
    """Render a mathematically gap-free 2:1 isometric prism of `(u_cells x v_cells)` footprint
    and `height_z` vertical pixels.

    Returns `(prism_rgba_image, top_origin_offset_xy)` where `top_origin_offset_xy` is the pixel
    coordinate of lattice vertex `(0, 0, z)` inside the returned image.
    """
    if half_h < 2 or u_cells < 1 or v_cells < 1 or height_z < 0:
        raise ValueError("Invalid isometric prism dimensions.")

    half_w = 2 * half_h
    # Screen bounds relative to top apex (0, 0):
    # u steps go (+half_w, +half_h); v steps go (-half_w, +half_h)
    min_lx = -v_cells * half_w
    max_lx = u_cells * half_w - 1
    min_ly = 0
    max_ly = (u_cells + v_cells) * half_h - 1

    pad = 1 if outline_color is not None else 0
    img_w = (max_lx - min_lx + 1) + pad * 2
    img_h = (max_ly - min_ly + 1) + height_z + pad * 2

    apex_x = -min_lx + pad
    apex_y = pad

    tc = parse_color(top_color)
    lc = parse_color(left_color)
    rc = parse_color(right_color)
    hc = parse_color(ridge_highlight) if ridge_highlight is not None else None

    top_pts = set()
    max_u8 = 8 * half_h * u_cells
    max_v8 = 8 * half_h * v_cells

    # Populate exact Z^2 fundamental domain for top diamond
    top_bottom_by_x: Dict[int, int] = {}
    for ly in range(min_ly, max_ly + 1):
        ly2 = 2 * ly + 1
        for lx in range(min_lx, max_lx + 1):
            lx2 = 2 * lx + 1
            u_val = lx2 + 2 * ly2
            v_val = 2 * ly2 - lx2
            if 0 <= u_val < max_u8 and 0 <= v_val < max_v8:
                sx, sy = apex_x + lx, apex_y + ly
                top_pts.add((sx, sy))
                if sx not in top_bottom_by_x or sy > top_bottom_by_x[sx]:
                    top_bottom_by_x[sx] = sy

    out = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    px = out.load()

    # Front corner X coordinate where u == u_cells and v == v_cells meet:
    front_corner_lx = (u_cells - v_cells) * half_w
    front_sx = apex_x + front_corner_lx

    for sx, sy in top_pts:
        px[sx, sy] = tc

    # Extrude vertical walls downward from bottom profile of top face
    if height_z > 0:
        for sx, bot_sy in top_bottom_by_x.items():
            face_col = lc if sx < front_sx else rc
            for dz in range(1, height_z + 1):
                px[sx, bot_sy + dz] = face_col

    # Optional 1px inner specular ridge along front top edges & vertical center corner
    if hc is not None:
        for sx, bot_sy in top_bottom_by_x.items():
            px[sx, bot_sy] = hc
        if height_z > 1 and front_sx in top_bottom_by_x:
            by = top_bottom_by_x[front_sx]
            for dz in range(1, height_z):
                px[front_sx, by + dz] = hc

    if outline_color is not None:
        out = auto_outline(out, color=outline_color, connectivity=4, mode="outer")

    return out, (apex_x, apex_y)


@dataclass
class _IsoPlacement:
    gx: int
    gy: int
    gz: int
    u_cells: int
    v_cells: int
    height_z: int
    img: Image.Image
    apex_offset: Tuple[int, int]


class IsoScene:
    """3D Isometric Grid Composer with automatic Painter's Algorithm back-to-front depth sorting."""

    def __init__(self, half_h: int = 8, bg_color: ColorDef = (0, 0, 0, 0)) -> None:
        self.half_h = half_h
        self.half_w = 2 * half_h
        self.bg_color = parse_color(bg_color)
        self._items: List[_IsoPlacement] = []

    def add_block(
        self,
        gx: int,
        gy: int,
        gz: int = 0,
        u_cells: int = 1,
        v_cells: int = 1,
        height_z: int = 12,
        base_color: Optional[ColorDef] = None,
        top_color: Optional[ColorDef] = None,
        left_color: Optional[ColorDef] = None,
        right_color: Optional[ColorDef] = None,
        outline_color: Optional[ColorDef] = "#181425",
        ridge_highlight: Optional[ColorDef] = None,
    ) -> "IsoScene":
        """Place a 3-face shaded isometric prism at grid `(gx, gy)` and pixel elevation `gz`."""
        if base_color is not None and (top_color is None or left_color is None or right_color is None):
            ramp = generate_shading_ramp(base_color, steps=4)  # [deep, shadow, mid, highlight]
            r_col = right_color or ramp[1]
            l_col = left_color or ramp[2]
            t_col = top_color or ramp[3]
            h_col = ridge_highlight
        else:
            t_col = top_color or "#63C74D"
            l_col = left_color or "#3E8948"
            r_col = right_color or "#265C42"
            h_col = ridge_highlight

        im, apex = render_iso_prism(
            half_h=self.half_h,
            u_cells=u_cells,
            v_cells=v_cells,
            height_z=height_z,
            top_color=t_col,
            left_color=l_col,
            right_color=r_col,
            outline_color=outline_color,
            ridge_highlight=h_col,
        )
        self._items.append(_IsoPlacement(gx, gy, gz, u_cells, v_cells, height_z, im, apex))
        return self

    def add_sprite(
        self,
        gx: float,
        gy: float,
        gz: int,
        sprite: Image.Image,
        foot_anchor: Optional[Tuple[int, int]] = None,
    ) -> "IsoScene":
        """Place a billboard pixel sprite (tree, chest, character) onto isometric tile `(gx, gy, gz)`."""
        rgba = sprite.convert("RGBA")
        if foot_anchor is None:
            bbox = rgba.getchannel("A").getbbox() or (0, 0, rgba.width, rgba.height)
            ax = (bbox[0] + bbox[2]) // 2
            ay = bbox[3] - 1 - self.half_h  # align feet to tile center `(0, +half_h)`
        else:
            ax, ay = foot_anchor[0], foot_anchor[1] - self.half_h

        self._items.append(
            _IsoPlacement(
                int(round(gx * 10)),
                int(round(gy * 10)),
                gz,
                0,
                0,
                rgba.height,
                rgba,
                (ax, ay),
            )
        )
        return self

    def render(self, padding: int = 8) -> Image.Image:
        if not self._items:
            return Image.new("RGBA", (32, 32), self.bg_color)

        # Compute screen position of each placement's apex
        placed: List[Tuple[Tuple[float, float, int], Image.Image, int, int]] = []
        min_x = 10**9
        min_y = 10**9
        max_x = -(10**9)
        max_y = -(10**9)

        for it in self._items:
            gx_f = it.gx / 10.0 if (it.u_cells == 0 and it.v_cells == 0) else float(it.gx)
            gy_f = it.gy / 10.0 if (it.u_cells == 0 and it.v_cells == 0) else float(it.gy)
            scr_apex_x = round((gx_f - gy_f) * self.half_w)
            scr_apex_y = round((gx_f + gy_f) * self.half_h) - it.gz - it.height_z

            x0 = scr_apex_x - it.apex_offset[0]
            y0 = scr_apex_y - it.apex_offset[1]
            min_x = min(min_x, x0)
            min_y = min(min_y, y0)
            max_x = max(max_x, x0 + it.img.width)
            max_y = max(max_y, y0 + it.img.height)

            depth_key = (
                gx_f + gy_f + 0.5 * (it.u_cells + it.v_cells),
                float(it.gz),
                it.height_z,
            )
            placed.append((depth_key, it.img, x0, y0))

        placed.sort(key=lambda p: p[0])

        w = (max_x - min_x) + padding * 2
        h = (max_y - min_y) + padding * 2
        canvas = Image.new("RGBA", (w, h), self.bg_color)

        for _, im, x0, y0 in placed:
            dx = x0 - min_x + padding
            dy = y0 - min_y + padding
            sub = canvas.crop((dx, dy, dx + im.width, dy + im.height))
            canvas.paste(Image.alpha_composite(sub, im), (dx, dy))

        return canvas


# ============================================================================
# Part 2: 4-Direction & 8-Direction RPG Character Derivation (`DirectionalRig`)
# ============================================================================

@dataclass
class _DirPartSpec:
    name: str
    role: str  # 'torso' | 'head' | 'plume' | 'cape' | 'left_arm' | 'right_arm' | 'prop'
    grids: Dict[str, List[str]]
    offset: Tuple[int, int]
    z_index: int
    outline_group: Optional[int]
    face_chars_to_mask_on_back: Tuple[str, ...]
    back_fill_char: str


class DirectionalRig:
    """Derive consistent 4-direction (`s,e,n,w`) or 8-direction RPG turnaround & walk animations
    from a front-facing (`s`) part specification (with optional explicit overrides per direction).
    """

    def __init__(
        self,
        canvas_size: Tuple[int, int],
        palette: Union[str, Dict[str, ColorDef], None] = "endesga32",
        outline_mode: str = "selout",
        outline_color: ColorDef = "#181425",
    ) -> None:
        self.canvas_size = canvas_size
        self.palette = palette
        self.outline_mode = outline_mode
        self.outline_color = outline_color
        self._parts: List[_DirPartSpec] = []

    def add_part(
        self,
        name: str,
        source: Union[GridLike, Mapping[str, GridLike]],
        role: str = "torso",
        offset: Tuple[int, int] = (0, 0),
        z_index: int = 10,
        outline_group: Optional[int] = 0,
        face_chars_to_mask_on_back: Tuple[str, ...] = ("K", "C", "R", "W"),
        back_fill_char: str = "2",
    ) -> "DirectionalRig":
        if isinstance(source, Mapping):
            gmap = {k.lower(): parse_grid_lines(v) for k, v in source.items()}
        else:
            gmap = {"s": parse_grid_lines(source)}
        if "s" not in gmap:
            raise ValueError(f"Part {name!r} must define at least front direction 's'.")
        self._parts.append(
            _DirPartSpec(
                name=name,
                role=role,
                grids=gmap,
                offset=offset,
                z_index=z_index,
                outline_group=outline_group,
                face_chars_to_mask_on_back=face_chars_to_mask_on_back,
                back_fill_char=back_fill_char,
            )
        )
        return self

    @staticmethod
    def _mask_back_head(lines: Sequence[str], face_chars: Tuple[str, ...], fill_ch: str) -> List[str]:
        h = len(lines)
        out: List[str] = []
        for y, row in enumerate(lines):
            # Only mask lower 65% of head where eyes/visor sit, preserving top highlights
            if y >= h // 3:
                out.append("".join(fill_ch if ch in face_chars else ch for ch in row))
            else:
                out.append(row)
        return out

    @staticmethod
    def _profile_head(lines: Sequence[str], back_fill_char: str, face_right: bool = True) -> List[str]:
        """Convert a symmetric front head into a true 1-eye side profile with hair/helm wrapping back."""
        h = len(lines)
        w = len(lines[0])
        shifted: List[str] = []
        for y, row in enumerate(lines):
            chars = list(row)
            if w >= 6 and y >= h // 3:
                # Wrap hair/helmet down the back third of the head & hide the rear eye
                if face_right:
                    for x in range(1, w // 2):
                        if chars[x] != ".":
                            chars[x] = back_fill_char
                else:
                    for x in range(w - w // 2, w - 1):
                        if chars[x] != ".":
                            chars[x] = back_fill_char
            s_row = "".join(chars)
            if w >= 6:
                cropped = s_row[1:] if face_right else s_row[:-1]
                pad_row = ("." + cropped) if face_right else (cropped + ".")
                shifted.append(pad_row)
            else:
                shifted.append(s_row)
        return shifted

    def _build_rig_for_direction(self, direction: str) -> Rig:
        d = direction.lower()
        cw, ch = self.canvas_size
        rig = Rig(
            canvas_size=self.canvas_size,
            palette=self.palette,
            outline_mode=self.outline_mode,
            outline_color=self.outline_color,
        )

        is_north = d in ("n", "ne", "nw")
        is_east = d in ("e", "se", "ne")
        is_west = d in ("w", "sw", "nw")
        is_pure_side = d in ("e", "w")
        is_diag = d in ("se", "sw", "ne", "nw")

        for sp in self._parts:
            ox, oy = sp.offset
            z = sp.z_index
            og = sp.outline_group
            base_s = sp.grids["s"]
            pw = len(base_s[0])

            if d in sp.grids:
                grid = sp.grids[d]
            elif is_west and "e" in sp.grids:
                grid = flip_grid(sp.grids["e"], horizontal=True)
                ox = cw - pw - ox
            else:
                grid = list(base_s)
                if sp.role == "head":
                    if d == "n":
                        grid = self._mask_back_head(grid, sp.face_chars_to_mask_on_back, sp.back_fill_char)
                    elif is_north and is_diag:
                        grid = self._mask_back_head(grid, sp.face_chars_to_mask_on_back, sp.back_fill_char)
                    elif is_pure_side:
                        grid = self._profile_head(grid, sp.back_fill_char, face_right=is_east)
                    elif is_diag:
                        ox += 1 if is_east else -1

                elif sp.role == "torso":
                    if is_pure_side and pw >= 6:
                        # Narrow profile torso by 2px centered
                        trimmed = [ "." + r[1:-1] + "." for r in grid ]
                        grid = trimmed

                elif sp.role == "cape":
                    if is_north:
                        # Back view: cape covers the character's back in the foreground!
                        z = 28
                        ox = (cw - pw) // 2
                    elif is_east:
                        ox -= 2 if is_pure_side else 1
                        z = 4
                    elif is_west:
                        grid = flip_grid(grid, horizontal=True)
                        ox = (cw - pw - ox) + (2 if is_pure_side else 1)
                        z = 4

                elif sp.role == "plume":
                    if is_east:
                        ox -= 1
                    elif is_west:
                        grid = flip_grid(grid, horizontal=True)
                        ox = (cw - pw - ox) + 1
                    elif d == "n":
                        ox = (cw - pw) // 2

                elif sp.role in ("left_arm", "right_arm"):
                    is_left_item = (sp.role == "left_arm")
                    if d == "n":
                        # Looking from behind: left & right swap screen sides!
                        grid = flip_grid(grid, horizontal=True)
                        ox = cw - pw - ox
                        z = 6  # tuck slightly behind shoulders/cape
                    elif d == "e":
                        if is_left_item:
                            # Far arm tucked partially behind chest on right side
                            ox = (cw // 2) - 1
                            z = 6
                            og = 0
                        else:
                            # Near arm prominent in foreground
                            ox = (cw // 2) - pw // 2
                            z = 32
                            og = 1
                    elif d == "w":
                        grid = flip_grid(grid, horizontal=True)
                        if not is_left_item:
                            # Sword/right arm is now on far side
                            ox = (cw // 2) - pw + 1
                            z = 6
                            og = 0
                        else:
                            # Shield/left arm is now near side in foreground!
                            ox = (cw // 2) - pw // 2
                            z = 32
                            og = 1
                    elif is_diag:
                        if is_west:
                            grid = flip_grid(grid, horizontal=True)
                            ox = cw - pw - ox
                        if is_north:
                            z = 8 if (is_left_item == is_east) else 26

            rig.add_part(
                sp.name,
                grid,
                offset=(ox, oy),
                z_index=z,
                outline_group=og,
            )
        return rig

    def render_direction_idle(
        self,
        direction: str,
        baseline_y: Optional[int] = None,
        shadow_width: int = 14,
    ) -> Image.Image:
        rig = self._build_rig_for_direction(direction)
        im = rig.render_pose({})
        if baseline_y is not None:
            im = add_ground_shadow(im, baseline_y=baseline_y, center_x=self.canvas_size[0] // 2, fixed_width=shadow_width)
        return im

    def render_walk_cycle(
        self,
        direction: str,
        baseline_y: Optional[int] = None,
        shadow_width: int = 14,
    ) -> List[Image.Image]:
        """Generate a snappy 4-frame RPG walk cycle (`contact_L -> pass_up -> contact_R -> pass_up`)."""
        d = direction.lower()
        rig = self._build_rig_for_direction(d)
        is_side = d in ("e", "w", "se", "sw", "ne", "nw")
        sgn = -1 if d in ("w", "nw", "sw") else 1

        # 4-frame walk poses: alternating arm/weapon swing + head/torso stride bob
        poses: List[Dict[str, Dict[str, Any]]] = [
            # F0: Stride 1 (body slightly down, arms swung opposite)
            {
                "torso": {"dy": 1},
                "head": {"dy": 1},
                "plume": {"dy": 1, "angle": -5 * sgn},
                "cape": {"dy": 1, "angle": 6 * sgn},
                "left_arm": {"dx": (2 * sgn if is_side else 0), "dy": (0 if is_side else 1), "angle": -10 * sgn},
                "right_arm": {"dx": (-2 * sgn if is_side else 0), "dy": (1 if is_side else 0), "angle": 12 * sgn},
            },
            # F1: Passing high point
            {
                "torso": {"dy": 0},
                "head": {"dy": 0},
                "plume": {"dy": 1},
                "cape": {"dy": 0},
            },
            # F2: Stride 2 (opposite swing)
            {
                "torso": {"dy": 1},
                "head": {"dy": 1},
                "plume": {"dy": 1, "angle": 5 * sgn},
                "cape": {"dy": 1, "angle": -6 * sgn},
                "left_arm": {"dx": (-2 * sgn if is_side else 0), "dy": (1 if is_side else 0), "angle": 10 * sgn},
                "right_arm": {"dx": (2 * sgn if is_side else 0), "dy": (0 if is_side else 1), "angle": -12 * sgn},
            },
            # F3: Passing high point
            {
                "torso": {"dy": 0},
                "head": {"dy": 0},
                "plume": {"dy": 0},
            },
        ]

        frames: List[Image.Image] = []
        for idx, p in enumerate(poses):
            filtered = {k: v for k, v in p.items() if k in rig.parts}
            im = rig.render_pose(filtered)
            if baseline_y is not None:
                sw = shadow_width + (1 if idx in (0, 2) else -1)
                im = add_ground_shadow(im, baseline_y=baseline_y, center_x=self.canvas_size[0] // 2, fixed_width=sw)
            frames.append(im)
        return frames


def export_multidir_sheets(
    name: str,
    dir_rig: DirectionalRig,
    directions: Sequence[str] = DIRECTIONS_4,
    baseline_y: Optional[int] = None,
    walk_frame_ms: int = 135,
    preview_scale: int = 6,
    output_dir: Union[str, Path] = "output/multidir",
) -> Dict[str, str]:
    """Export 4-dir or 8-dir RPG Walk Sprite Sheet, Aseprite JSON, 360 Spin GIF, and Alignment Sheet."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    cw, ch = dir_rig.canvas_size
    cols = 4  # 4-frame walk cycle per row
    rows = len(directions)

    sheet = Image.new("RGBA", (cw * cols, ch * rows), (0, 0, 0, 0))
    atlas_entries: List[Dict[str, Any]] = []
    frame_tags: List[Dict[str, Any]] = []
    spin_frames: List[Image.Image] = []
    global_idx = 0

    for r_idx, d in enumerate(directions):
        walk_frames = dir_rig.render_walk_cycle(d, baseline_y=baseline_y)
        spin_frames.append(dir_rig.render_direction_idle(d, baseline_y=baseline_y))
        tag_start = global_idx
        for c_idx, wf in enumerate(walk_frames):
            sheet.paste(wf, (c_idx * cw, r_idx * ch))
            atlas_entries.append({
                "name": f"{name}_walk_{d} #{c_idx}",
                "x": c_idx * cw,
                "y": r_idx * ch,
                "w": cw,
                "h": ch,
                "duration": walk_frame_ms,
            })
            global_idx += 1
        frame_tags.append({
            "name": f"walk_{d}",
            "from": tag_start,
            "to": global_idx - 1,
            "direction": "forward",
        })

    atlas_png = out / f"{name}_{rows}dir_walk_sheet.png"
    atlas_scaled_png = out / f"{name}_{rows}dir_walk_sheet_{preview_scale}x.png"
    atlas_json = out / f"{name}_{rows}dir_walk_atlas.json"
    spin_gif = out / f"{name}_{rows}dir_turnaround_{preview_scale}x.gif"
    inspect_png = out / f"{name}_{rows}dir_alignment_inspect.png"

    sheet.save(atlas_png)
    sheet.resize((sheet.width * preview_scale, sheet.height * preview_scale), Image.Resampling.NEAREST).save(
        atlas_scaled_png
    )

    adata = build_aseprite_atlas_json(
        image_filename=atlas_png.name,
        sheet_size=sheet.size,
        entries=atlas_entries,
        frame_tags=frame_tags,
    )
    atlas_json.write_text(json.dumps(adata, indent=2, ensure_ascii=False), encoding="utf-8")

    spin_scaled = [
        sf.resize((cw * preview_scale, ch * preview_scale), Image.Resampling.NEAREST)
        for sf in spin_frames
    ]
    save_rgba_gif(spin_scaled, spin_gif, [240] * len(spin_scaled))

    # Build Horizontal Head-Top & Foot-Baseline Alignment Diagnostic Sheet
    sc = max(4, preview_scale)
    pad = 16
    cell_gap = 10
    turn_w = len(directions) * (cw * sc + cell_gap) + pad * 2
    sheet_up = sheet.resize((sheet.width * (sc // 2), sheet.height * (sc // 2)), Image.Resampling.NEAREST)
    diag_w = max(560, turn_w, sheet_up.width + pad * 2)
    diag_h = 44 + (ch * sc + 24) + 32 + sheet_up.height + pad * 2

    diag = Image.new("RGB", (diag_w, diag_h), (24, 26, 34))
    ddraw = ImageDraw.Draw(diag)
    font = ImageFont.load_default()
    ddraw.text(
        (pad, 10),
        f"Multi-Dir Alignment [{name}] ({rows}-Dir, {cw}x{ch}) : Cyan = Head Top | Orange = Foot Baseline",
        fill=(240, 245, 255),
        font=font,
    )

    # Measure front ('s') head top & foot baseline
    s_bbox = spin_frames[0].getchannel("A").getbbox() or (0, 0, cw, ch)
    head_top_y = s_bbox[1]
    foot_bot_y = baseline_y if baseline_y is not None else (s_bbox[3] - 1)

    row1_y = 44 + 16
    for idx, (d, sf) in enumerate(zip(directions, spin_frames)):
        cx = pad + idx * (cw * sc + cell_gap)
        box_bg = Image.new("RGBA", (cw * sc, ch * sc), (38, 42, 54, 255))
        up = sf.resize((cw * sc, ch * sc), Image.Resampling.NEAREST)
        diag.paste(Image.alpha_composite(box_bg, up).convert("RGB"), (cx, row1_y))
        ddraw.rectangle([cx - 1, row1_y - 1, cx + cw * sc, row1_y + ch * sc], outline=(75, 84, 104))
        ddraw.text((cx + 2, row1_y - 13), d.upper(), fill=(195, 210, 240), font=font)

    # Draw continuous horizontal alignment ruler lines across all turnaround views!
    line_x1 = pad + len(directions) * (cw * sc + cell_gap) - cell_gap
    hy_px = row1_y + head_top_y * sc
    fy_px = row1_y + (foot_bot_y + 1) * sc
    ddraw.line((pad, hy_px, line_x1, hy_px), fill=(44, 232, 245), width=1)
    ddraw.line((pad, fy_px, line_x1, fy_px), fill=(255, 115, 85), width=1)

    row2_y = row1_y + ch * sc + 32
    ddraw.text(
        (pad, row2_y - 18),
        f"Full {rows}x{cols} Walk Cycle Atlas ({sc // 2}x):",
        fill=(185, 200, 230),
        font=font,
    )
    atlas_bg = Image.new("RGBA", sheet_up.size, (34, 38, 48, 255))
    diag.paste(Image.alpha_composite(atlas_bg, sheet_up).convert("RGB"), (pad, row2_y))
    diag.save(inspect_png)

    print(f"Built {rows}-Direction Character [{name}]:")
    print(f"  - VIEW ALIGNMENT SHEET: {inspect_png}")
    print(f"  - Turnaround Spin GIF:  {spin_gif}")
    print(f"  - Walk Cycle Atlas:     {atlas_png}")
    return {
        "walk_sheet_png": str(atlas_png),
        "walk_sheet_scaled_png": str(atlas_scaled_png),
        "walk_atlas_json": str(atlas_json),
        "turnaround_gif": str(spin_gif),
        "inspect_sheet": str(inspect_png),
    }
