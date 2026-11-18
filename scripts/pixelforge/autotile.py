"""Procedural 47-Tile Blob & 16-Tile Corner Wang Auto-Tileset Generator,
ASCII Terrain Map Auto-Tiler, and Seamless Mock-Map Visual Inspector.

Synthesizes full Godot / Tiled / LDtk / RPG-Maker compatible auto-tilesets from just
two base seamless tiles (`fg_tile` and `bg_tile`) plus directional rim lighting colors.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from PIL import Image, ImageDraw, ImageFont

from .canvas import GridLike, parse_grid_lines, render_grid
from .palette import ColorDef, RGBA, parse_color

# 8-neighbor bit flags (clockwise from North)
BIT_N = 1
BIT_NE = 2
BIT_E = 4
BIT_SE = 8
BIT_S = 16
BIT_SW = 32
BIT_W = 64
BIT_NW = 128


def canonicalize_blob_mask(raw_mask: int) -> int:
    """Mask out diagonal neighbor bits unless BOTH adjacent cardinal bits are set.
    Maps all 256 8-neighbor combinations onto the exact 47 canonical Blob masks.
    """
    n = bool(raw_mask & BIT_N)
    e = bool(raw_mask & BIT_E)
    s = bool(raw_mask & BIT_S)
    w = bool(raw_mask & BIT_W)
    out = (BIT_N if n else 0) | (BIT_E if e else 0) | (BIT_S if s else 0) | (BIT_W if w else 0)
    if n and e and (raw_mask & BIT_NE):
        out |= BIT_NE
    if s and e and (raw_mask & BIT_SE):
        out |= BIT_SE
    if s and w and (raw_mask & BIT_SW):
        out |= BIT_SW
    if n and w and (raw_mask & BIT_NW):
        out |= BIT_NW
    return out


CANONICAL_BLOB_47: Tuple[int, ...] = tuple(
    sorted({canonicalize_blob_mask(m) for m in range(256)})
)


def _quadrant_fg_test(
    lx: int,
    ly: int,
    q: int,
    card_v: bool,
    card_h: bool,
    diag: bool,
    inset: int,
    outer_r: int,
) -> bool:
    """Evaluate foreground membership at quadrant-local `(lx, ly)` where `(0, 0)` is the outer corner
    and `(q-1, q-1)` is the tile center. Guarantees exact seam continuity at `lx=0` and `ly=0`.
    """
    if card_v and card_h:
        if diag:
            return True
        # Clean concave inner corner notch at (0..inset-1, 0..inset-1)
        if lx < inset and ly < inset:
            return False
        return True

    if (not card_v) and card_h:
        # Horizontal straight edge along top/bottom (`ly == inset`)
        return ly >= inset

    if card_v and (not card_h):
        # Vertical straight edge along left/right (`lx == inset`)
        return lx >= inset

    # Outer convex corner (`card_v == False` and `card_h == False`)
    if lx < inset or ly < inset:
        return False
    cx = inset + outer_r
    cy = inset + outer_r
    if lx < cx and ly < cy:
        # Euclidean pixel circle corner rounding
        dist_sq = (cx - lx - 0.35) ** 2 + (cy - ly - 0.35) ** 2
        return dist_sq <= (outer_r ** 2)
    return True


def _build_blob_tile_mask(tile_size: int, mask: int, inset: int, outer_r: int) -> List[List[bool]]:
    """Build a `(tile_size + 2) x (tile_size + 2)` boolean mask (`-1..T`) with true cross-seam continuity."""
    cm = canonicalize_blob_mask(mask)
    n = bool(cm & BIT_N)
    ne = bool(cm & BIT_NE)
    e = bool(cm & BIT_E)
    se = bool(cm & BIT_SE)
    s = bool(cm & BIT_S)
    sw = bool(cm & BIT_SW)
    w = bool(cm & BIT_W)
    nw = bool(cm & BIT_NW)

    q = tile_size // 2

    def eval_single(px: int, py: int, cn: bool, ce: bool, cs: bool, cw: bool,
                    cne: bool, cse: bool, csw: bool, cnw: bool) -> bool:
        if py < q:
            if px < q:
                return _quadrant_fg_test(px, py, q, cn, cw, cnw, inset, outer_r)
            return _quadrant_fg_test(tile_size - 1 - px, py, q, cn, ce, cne, inset, outer_r)
        else:
            by = tile_size - 1 - py
            if px < q:
                return _quadrant_fg_test(px, by, q, cs, cw, csw, inset, outer_r)
            return _quadrant_fg_test(tile_size - 1 - px, by, q, cs, ce, cse, inset, outer_r)

    padded = [[False] * (tile_size + 2) for _ in range(tile_size + 2)]
    for py in range(-1, tile_size + 1):
        for px in range(-1, tile_size + 1):
            if 0 <= px < tile_size and 0 <= py < tile_size:
                val = eval_single(px, py, n, e, s, w, ne, se, sw, nw)
            elif px == -1 and 0 <= py < tile_size:
                val = False if not w else eval_single(
                    tile_size - 1, py, nw, True, sw, True, n, s, sw, nw
                )
            elif px == tile_size and 0 <= py < tile_size:
                val = False if not e else eval_single(
                    0, py, ne, True, se, True, ne, se, s, n
                )
            elif py == -1 and 0 <= px < tile_size:
                val = False if not n else eval_single(
                    px, tile_size - 1, True, ne, True, nw, ne, e, w, nw
                )
            elif py == tile_size and 0 <= px < tile_size:
                val = False if not s else eval_single(
                    px, 0, True, se, True, sw, e, se, sw, w
                )
            else:
                val = False
            padded[py + 1][px + 1] = val
    return padded


def _render_masked_tile(
    fg_img: Image.Image,
    bg_img: Image.Image,
    padded_mask: List[List[bool]],
    outline_color: Optional[ColorDef] = "#181425",
    rim_highlight_color: Optional[ColorDef] = None,
    rim_shadow_color: Optional[ColorDef] = None,
    drop_shadow_alpha: int = 75,
) -> Image.Image:
    """Composite `fg_img` over `bg_img` using `padded_mask` (`(T+2)x(T+2)`) and top-left directional rims."""
    ts = fg_img.width
    fg_px = fg_img.load()
    bg_px = bg_img.load()
    out = Image.new("RGBA", (ts, ts))
    dst = out.load()

    oc: Optional[RGBA] = parse_color(outline_color) if outline_color is not None else None
    hc: Optional[RGBA] = parse_color(rim_highlight_color) if rim_highlight_color is not None else None
    sc: Optional[RGBA] = parse_color(rim_shadow_color) if rim_shadow_color is not None else None

    for y in range(ts):
        my = y + 1
        for x in range(ts):
            mx = x + 1
            is_fg = padded_mask[my][mx]
            if is_fg:
                up_bg = not padded_mask[my - 1][mx]
                dn_bg = not padded_mask[my + 1][mx]
                lf_bg = not padded_mask[my][mx - 1]
                rt_bg = not padded_mask[my][mx + 1]
                on_edge = up_bg or dn_bg or lf_bg or rt_bg

                if on_edge and oc is not None:
                    dst[x, y] = oc
                else:
                    # Check 1px interior rim adjacent to outline/edge
                    up2_bg = up_bg or (oc is not None and not padded_mask[max(0, my - 2)][mx] if my >= 2 else False)
                    lf2_bg = lf_bg or (oc is not None and not padded_mask[my][max(0, mx - 2)] if mx >= 2 else False)
                    dn2_bg = dn_bg or (oc is not None and not padded_mask[min(ts + 1, my + 2)][mx] if my <= ts - 1 else False)
                    rt2_bg = rt_bg or (oc is not None and not padded_mask[my][min(ts + 1, mx + 2)] if mx <= ts - 1 else False)

                    if hc is not None and (up2_bg or lf2_bg) and not (dn_bg or rt_bg):
                        dst[x, y] = hc
                    elif sc is not None and (dn2_bg or rt2_bg):
                        dst[x, y] = sc
                    else:
                        dst[x, y] = fg_px[x, y]
            else:
                base_c = bg_px[x, y]
                # Subtle south/east overhang contact shadow onto background
                cast_from_top_left = padded_mask[my - 1][mx] or padded_mask[my - 1][mx - 1]
                if drop_shadow_alpha > 0 and cast_from_top_left and base_c[3] > 0:
                    k = 1.0 - (drop_shadow_alpha / 255.0)
                    dst[x, y] = (
                        round(base_c[0] * k),
                        round(base_c[1] * k),
                        round(base_c[2] * k),
                        base_c[3],
                    )
                else:
                    dst[x, y] = base_c
    return out


def generate_blob47_tileset(
    fg_tile: Union[Image.Image, GridLike],
    bg_tile: Union[Image.Image, GridLike],
    palette: Union[str, Dict[str, ColorDef], None] = "endesga32",
    outline_color: Optional[ColorDef] = "#181425",
    rim_highlight_color: Optional[ColorDef] = None,
    rim_shadow_color: Optional[ColorDef] = None,
    inset: Optional[int] = None,
    outer_radius: Optional[int] = None,
    atlas_cols: int = 12,
) -> Dict[str, Any]:
    """Synthesize a complete 47-tile 8-neighbor Blob Auto-Tileset + Atlas from `fg_tile` & `bg_tile`."""
    fg_img = fg_tile.convert("RGBA") if isinstance(fg_tile, Image.Image) else render_grid(fg_tile, palette)
    bg_img = bg_tile.convert("RGBA") if isinstance(bg_tile, Image.Image) else render_grid(bg_tile, palette)

    if fg_img.size != bg_img.size or fg_img.width != fg_img.height or fg_img.width % 2 != 0:
        raise ValueError(
            f"fg_tile ({fg_img.size}) and bg_tile ({bg_img.size}) must be equal-sized even square tiles (e.g. 16x16, 32x32)."
        )

    ts = fg_img.width
    ins = max(1, ts // 8) if inset is None else inset
    rad = max(2, ts // 5) if outer_radius is None else outer_radius

    tiles_by_mask: Dict[int, Image.Image] = {}
    for mask in CANONICAL_BLOB_47:
        pmask = _build_blob_tile_mask(ts, mask, inset=ins, outer_r=rad)
        tiles_by_mask[mask] = _render_masked_tile(
            fg_img,
            bg_img,
            pmask,
            outline_color=outline_color,
            rim_highlight_color=rim_highlight_color,
            rim_shadow_color=rim_shadow_color,
        )

    # Pack into `atlas_cols x rows` sprite sheet (slot 47 = pure bg_tile for convenience!)
    rows = (len(CANONICAL_BLOB_47) + 1 + atlas_cols - 1) // atlas_cols
    atlas = Image.new("RGBA", (atlas_cols * ts, rows * ts), (0, 0, 0, 0))
    atlas_map: Dict[str, Dict[str, int]] = {}

    for idx, mask in enumerate(CANONICAL_BLOB_47):
        r, c = divmod(idx, atlas_cols)
        atlas.paste(tiles_by_mask[mask], (c * ts, r * ts))
        atlas_map[str(mask)] = {"index": idx, "col": c, "row": r, "x": c * ts, "y": r * ts}

    # Final slot holds pure background tile (`bg`)
    bg_idx = len(CANONICAL_BLOB_47)
    br, bc = divmod(bg_idx, atlas_cols)
    atlas.paste(bg_img, (bc * ts, br * ts))
    atlas_map["bg"] = {"index": bg_idx, "col": bc, "row": br, "x": bc * ts, "y": br * ts}

    return {
        "type": "blob47",
        "tile_size": ts,
        "tiles": tiles_by_mask,
        "bg_tile": bg_img,
        "fg_tile": fg_img,
        "atlas": atlas,
        "atlas_map": atlas_map,
    }


def generate_wang16_tileset(
    fg_tile: Union[Image.Image, GridLike],
    bg_tile: Union[Image.Image, GridLike],
    palette: Union[str, Dict[str, ColorDef], None] = "endesga32",
    outline_color: Optional[ColorDef] = "#181425",
    rim_highlight_color: Optional[ColorDef] = None,
    rim_shadow_color: Optional[ColorDef] = None,
) -> Dict[str, Any]:
    """Synthesize a compact 16-tile Corner Wang (Dual-Grid) Auto-Tileset (`4x4` atlas).
    Corner index bits: `NW=8, NE=4, SW=2, SE=1` (`0..15`).
    """
    fg_img = fg_tile.convert("RGBA") if isinstance(fg_tile, Image.Image) else render_grid(fg_tile, palette)
    bg_img = bg_tile.convert("RGBA") if isinstance(bg_tile, Image.Image) else render_grid(bg_tile, palette)
    if fg_img.size != bg_img.size or fg_img.width != fg_img.height or fg_img.width % 2 != 0:
        raise ValueError("fg_tile and bg_tile must be equal even square dimensions.")

    ts = fg_img.width
    half = ts // 2
    rad = max(2, half - 1)
    tiles: Dict[int, Image.Image] = {}
    atlas = Image.new("RGBA", (ts * 4, ts * 4), (0, 0, 0, 0))
    atlas_map: Dict[str, Dict[str, int]] = {}

    for wmask in range(16):
        nw = bool(wmask & 8)
        ne = bool(wmask & 4)
        sw = bool(wmask & 2)
        se = bool(wmask & 1)

        padded = [[False] * (ts + 2) for _ in range(ts + 2)]
        for py in range(-1, ts + 1):
            for px in range(-1, ts + 1):
                # Bilinear signed distance from the 4 tile corners creates smooth connected dual-grid shapes
                u = (px + 0.5) / float(ts)
                v = (py + 0.5) / float(ts)
                u = max(0.0, min(1.0, u))
                v = max(0.0, min(1.0, v))
                w_val = (
                    (1.0 - u) * (1.0 - v) * (1.0 if nw else 0.0)
                    + u * (1.0 - v) * (1.0 if ne else 0.0)
                    + (1.0 - u) * v * (1.0 if sw else 0.0)
                    + u * v * (1.0 if se else 0.0)
                )
                padded[py + 1][px + 1] = w_val >= 0.5

        tile_im = _render_masked_tile(
            fg_img,
            bg_img,
            padded,
            outline_color=outline_color,
            rim_highlight_color=rim_highlight_color,
            rim_shadow_color=rim_shadow_color,
        )
        tiles[wmask] = tile_im
        r, c = divmod(wmask, 4)
        atlas.paste(tile_im, (c * ts, r * ts))
        atlas_map[str(wmask)] = {"index": wmask, "col": c, "row": r, "x": c * ts, "y": r * ts}
        _ = rad  # keep deterministic

    return {
        "type": "wang16",
        "tile_size": ts,
        "tiles": tiles,
        "bg_tile": bg_img,
        "fg_tile": fg_img,
        "atlas": atlas,
        "atlas_map": atlas_map,
    }


DEFAULT_SAMPLE_MAP: Tuple[str, ...] = (
    "............",
    "..####..##..",
    ".######.###.",
    ".###..#####.",
    "..##....##..",
    "...#....#...",
    "..###..###..",
    ".##########.",
    "..###..###..",
    "............",
)


def render_autotile_map(
    terrain_map: Union[GridLike, Sequence[Sequence[int]]],
    autotile_bundle: Dict[str, Any],
    fg_chars: Tuple[str, ...] = ("#", "1", "X", "@"),
    out_of_bounds_is_fg: bool = False,
) -> Image.Image:
    """Render an ASCII or 0/1 2D terrain map into a seamless pixel map using `autotile_bundle`."""
    if isinstance(terrain_map, (str, list, tuple)) and terrain_map and isinstance(
        terrain_map[0] if not isinstance(terrain_map, str) else terrain_map, str
    ):
        lines = parse_grid_lines(terrain_map)  # type: ignore[arg-type]
        grid_bool = [[ch in fg_chars for ch in row] for row in lines]
    else:
        grid_bool = [[bool(cell) for cell in row] for row in terrain_map]  # type: ignore[union-attr]

    mh = len(grid_bool)
    mw = len(grid_bool[0])
    ts = int(autotile_bundle["tile_size"])
    out = Image.new("RGBA", (mw * ts, mh * ts))

    def is_fg(gx: int, gy: int) -> bool:
        if 0 <= gx < mw and 0 <= gy < mh:
            return grid_bool[gy][gx]
        return out_of_bounds_is_fg

    if autotile_bundle["type"] == "blob47":
        tiles = autotile_bundle["tiles"]
        bg_tile = autotile_bundle["bg_tile"]
        for gy in range(mh):
            for gx in range(mw):
                if not is_fg(gx, gy):
                    out.paste(bg_tile, (gx * ts, gy * ts))
                    continue
                raw = 0
                if is_fg(gx, gy - 1):
                    raw |= BIT_N
                if is_fg(gx + 1, gy - 1):
                    raw |= BIT_NE
                if is_fg(gx + 1, gy):
                    raw |= BIT_E
                if is_fg(gx + 1, gy + 1):
                    raw |= BIT_SE
                if is_fg(gx, gy + 1):
                    raw |= BIT_S
                if is_fg(gx - 1, gy + 1):
                    raw |= BIT_SW
                if is_fg(gx - 1, gy):
                    raw |= BIT_W
                if is_fg(gx - 1, gy - 1):
                    raw |= BIT_NW
                cm = canonicalize_blob_mask(raw)
                out.paste(tiles[cm], (gx * ts, gy * ts))
    elif autotile_bundle["type"] == "wang16":
        # Dual-grid: render `(mw - 1) x (mh - 1)` dual cells from corner vertices
        tiles = autotile_bundle["tiles"]
        out = Image.new("RGBA", (max(1, mw - 1) * ts, max(1, mh - 1) * ts))
        for gy in range(max(1, mh - 1)):
            for gx in range(max(1, mw - 1)):
                wmask = (
                    (8 if is_fg(gx, gy) else 0)
                    | (4 if is_fg(gx + 1, gy) else 0)
                    | (2 if is_fg(gx, gy + 1) else 0)
                    | (1 if is_fg(gx + 1, gy + 1) else 0)
                )
                out.paste(tiles[wmask], (gx * ts, gy * ts))
    else:
        raise ValueError(f"Unsupported autotile type: {autotile_bundle.get('type')!r}")

    return out


def export_autotile_bundle(
    name: str,
    autotile_bundle: Dict[str, Any],
    output_dir: Union[str, Path] = "output/autotile",
    sample_map: Optional[GridLike] = None,
    preview_scale: int = 3,
) -> Dict[str, str]:
    """Export Auto-Tile Atlas PNG, Bitmask JSON, Sample Rendered Map, and Holistic Diagnostic Sheet."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    atlas: Image.Image = autotile_bundle["atlas"]
    ts = int(autotile_bundle["tile_size"])
    kind = str(autotile_bundle["type"])

    atlas_png = out / f"{name}_{kind}_atlas.png"
    atlas_json = out / f"{name}_{kind}_atlas.json"
    map_png = out / f"{name}_{kind}_sample_map.png"
    map_scaled_png = out / f"{name}_{kind}_sample_map_{preview_scale}x.png"
    inspect_png = out / f"{name}_{kind}_inspect.png"

    atlas.save(atlas_png)
    meta = {
        "name": name,
        "type": kind,
        "tile_size": ts,
        "atlas_width": atlas.width,
        "atlas_height": atlas.height,
        "tiles": autotile_bundle["atlas_map"],
    }
    atlas_json.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    smap = sample_map if sample_map is not None else DEFAULT_SAMPLE_MAP
    rendered_map = render_autotile_map(smap, autotile_bundle)
    rendered_map.save(map_png)
    map_up = rendered_map.resize(
        (rendered_map.width * preview_scale, rendered_map.height * preview_scale),
        Image.Resampling.NEAREST,
    )
    map_up.save(map_scaled_png)

    # Build Visual Inspection Sheet (Top: Atlas with subtle cell grid + mask IDs; Bottom: Clean Mock Map)
    at_sc = max(2, min(4, 32 // max(8, ts) * 2))
    atlas_up = atlas.resize((atlas.width * at_sc, atlas.height * at_sc), Image.Resampling.NEAREST)
    adraw = ImageDraw.Draw(atlas_up)
    font = ImageFont.load_default()
    for key, info in autotile_bundle["atlas_map"].items():
        x0 = info["x"] * at_sc
        y0 = info["y"] * at_sc
        adraw.rectangle([x0, y0, x0 + ts * at_sc - 1, y0 + ts * at_sc - 1], outline=(70, 80, 100, 180))
        adraw.text((x0 + 2, y0 + 1), str(key), fill=(255, 245, 180, 255), font=font)

    pad = 16
    sheet_w = max(atlas_up.width + pad * 2, map_up.width + pad * 2, 540)
    sheet_h = 36 + atlas_up.height + 34 + map_up.height + pad * 2
    sheet = Image.new("RGB", (sheet_w, sheet_h), (24, 26, 34))
    sdraw = ImageDraw.Draw(sheet)
    sdraw.text(
        (pad, 10),
        f"Auto-Tileset [{name}] ({kind.upper()}, {ts}x{ts}px) : Top = Indexed Atlas | Bottom = Live Mock Map ({preview_scale}x)",
        fill=(240, 245, 255),
        font=font,
    )
    sheet.paste(atlas_up.convert("RGB"), (pad, 32))
    map_y = 32 + atlas_up.height + 28
    sdraw.text(
        (pad, map_y - 18),
        "Mock Terrain Verification Map (checks outer corners, inner corners, 1-tile bridges & islands):",
        fill=(185, 200, 230),
        font=font,
    )
    sheet.paste(map_up.convert("RGB"), (pad, map_y))
    sheet.save(inspect_png)

    print(f"Built Auto-Tileset [{name}] ({kind}, {ts}x{ts}):")
    print(f"  - VIEW AUTOTILE INSPECTION: {inspect_png}")
    print(f"  - Atlas PNG + JSON:         {atlas_png}")
    return {
        "atlas_png": str(atlas_png),
        "atlas_json": str(atlas_json),
        "sample_map_png": str(map_png),
        "sample_map_scaled_png": str(map_scaled_png),
        "inspect_sheet": str(inspect_png),
    }
