"""In-Game Scene Mockup Composer, Built-in 3x5 Retro Pixel Bitmap Font,
and 4-Panel Grayscale Value & Silhouette Readability Analyzer.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from PIL import Image, ImageDraw, ImageFont

from .exporter import save_animated_webp, save_apng, save_rgba_gif
from .palette import ColorDef, RGBA, color_distance_sq, img_pixels, luminance, parse_color
from .transform import auto_outline, flip_image, shift_image

# Crisp proportional retro bitmap font (5 rows tall; tuple is (width, row0..row4) MSB on left)
_FONT_3X5: Dict[str, Tuple[int, int, int, int, int, int]] = {
    " ": (2, 0, 0, 0, 0, 0),
    "!": (1, 1, 1, 1, 0, 1),
    "?": (3, 6, 1, 2, 0, 2),
    ".": (1, 0, 0, 0, 0, 1),
    ",": (2, 0, 0, 0, 1, 2),
    ":": (1, 0, 1, 0, 1, 0),
    "-": (3, 0, 0, 7, 0, 0),
    "+": (3, 0, 2, 7, 2, 0),
    "/": (3, 1, 1, 2, 4, 4),
    "%": (4, 9, 2, 4, 9, 0),
    "(": (2, 1, 2, 2, 2, 1),
    ")": (2, 2, 1, 1, 1, 2),
    "[": (2, 3, 2, 2, 2, 3),
    "]": (2, 3, 1, 1, 1, 3),
    "#": (5, 10, 31, 10, 31, 10),
    "'": (1, 1, 1, 0, 0, 0),
    "<": (3, 1, 2, 4, 2, 1),
    ">": (3, 4, 2, 1, 2, 4),
    "0": (3, 7, 5, 5, 5, 7),
    "1": (3, 2, 6, 2, 2, 7),
    "2": (3, 7, 1, 7, 4, 7),
    "3": (3, 7, 1, 3, 1, 7),
    "4": (3, 5, 5, 7, 1, 1),
    "5": (3, 7, 4, 7, 1, 7),
    "6": (3, 7, 4, 7, 5, 7),
    "7": (3, 7, 1, 2, 2, 2),
    "8": (3, 7, 5, 7, 5, 7),
    "9": (3, 7, 5, 7, 1, 7),
    "A": (3, 2, 5, 7, 5, 5),
    "B": (3, 6, 5, 6, 5, 6),
    "C": (3, 3, 4, 4, 4, 3),
    "D": (3, 6, 5, 5, 5, 6),
    "E": (3, 7, 4, 6, 4, 7),
    "F": (3, 7, 4, 6, 4, 4),
    "G": (4, 6, 8, 11, 9, 6),
    "H": (3, 5, 5, 7, 5, 5),
    "I": (3, 7, 2, 2, 2, 7),
    "J": (3, 1, 1, 1, 5, 2),
    "K": (3, 5, 5, 6, 5, 5),
    "L": (3, 4, 4, 4, 4, 7),
    "M": (5, 17, 27, 21, 17, 17),
    "N": (4, 9, 13, 11, 9, 9),
    "O": (3, 2, 5, 5, 5, 2),
    "P": (3, 6, 5, 6, 4, 4),
    "Q": (4, 6, 9, 9, 11, 7),
    "R": (3, 6, 5, 6, 5, 5),
    "S": (3, 3, 4, 2, 1, 6),
    "T": (3, 7, 2, 2, 2, 2),
    "U": (3, 5, 5, 5, 5, 7),
    "V": (3, 5, 5, 5, 2, 2),
    "W": (5, 17, 17, 21, 27, 17),
    "X": (3, 5, 5, 2, 5, 5),
    "Y": (3, 5, 5, 2, 2, 2),
    "Z": (3, 7, 1, 2, 4, 7),
}


def render_pixel_text(
    text: str,
    color: ColorDef = "#FFFFFF",
    outline: Optional[ColorDef] = "#181425",
    shadow: Optional[ColorDef] = None,
    scale: int = 1,
    letter_spacing: int = 1,
) -> Image.Image:
    """Render crisp proportional 5px-tall retro pixel-art text with optional 1px outline/shadow."""
    if scale < 1:
        raise ValueError("scale must be >= 1")
    lines = text.upper().splitlines() or [""]
    fg = parse_color(color)

    def _line_width(s: str) -> int:
        if not s:
            return 1
        return sum(_FONT_3X5.get(ch, _FONT_3X5["?"])[0] for ch in s) + letter_spacing * (len(s) - 1)

    pad = 1 if (outline is not None or shadow is not None) else 0
    raw_w = max(1, max((_line_width(line) for line in lines), default=1) + pad * 2)
    raw_h = max(1, len(lines) * 6 - 1 + pad * 2)

    glyph_layer = Image.new("RGBA", (raw_w, raw_h), (0, 0, 0, 0))
    gpx = glyph_layer.load()

    for l_idx, line in enumerate(lines):
        oy = pad + l_idx * 6
        ox = pad
        for ch in line:
            spec = _FONT_3X5.get(ch, _FONT_3X5["?"])
            gw = spec[0]
            rows = spec[1:]
            for ry, bits in enumerate(rows):
                for rx in range(gw):
                    if (bits >> (gw - 1 - rx)) & 1:
                        gpx[ox + rx, oy + ry] = fg
            ox += gw + letter_spacing

    out = glyph_layer
    if shadow is not None:
        sh_col = parse_color(shadow)
        sh_img = Image.new("RGBA", (raw_w, raw_h), (0, 0, 0, 0))
        spx = sh_img.load()
        for y in range(raw_h - 1):
            for x in range(raw_w - 1):
                if gpx[x, y][3] > 0:
                    spx[x + 1, y + 1] = sh_col
        out = Image.alpha_composite(sh_img, out)

    if outline is not None:
        out = auto_outline(out, color=outline, connectivity=8, mode="outer")

    if scale > 1:
        out = out.resize((out.width * scale, out.height * scale), Image.Resampling.NEAREST)
    return out


@dataclass
class _SceneEntity:
    name: str
    frames: List[Image.Image]
    durations_ms: List[int]
    pos: Tuple[int, int]
    end_pos: Optional[Tuple[int, int]] = None
    anchor: str = "foot"  # 'foot' | 'topleft' | 'center'
    z_index: Optional[int] = None
    role: str = "actor"  # 'actor' | 'prop' | 'fx' | 'ui'


class SceneComposer:
    """Assemble multi-asset gameplay mockups with Y-sorting, motion paths, UI, and Value Readability checks."""

    def __init__(self, width: int, height: int, bg_color: ColorDef = "#181425") -> None:
        if width <= 0 or height <= 0:
            raise ValueError("Positive scene width and height required.")
        self.width = width
        self.height = height
        self.bg_color = parse_color(bg_color)
        self._tiled_bg: Optional[Tuple[List[Image.Image], int, Tuple[int, int]]] = None
        self._bg_layers: List[Tuple[List[Image.Image], int, Tuple[int, int]]] = []
        self._entities: List[_SceneEntity] = []

    @staticmethod
    def _norm_frames(
        src: Union[Image.Image, Sequence[Image.Image]],
        durations_ms: Union[int, Sequence[int]] = 140,
        flip_h: bool = False,
    ) -> Tuple[List[Image.Image], List[int]]:
        frames = [src.convert("RGBA")] if isinstance(src, Image.Image) else [f.convert("RGBA") for f in src]
        if flip_h:
            frames = [flip_image(f, horizontal=True) for f in frames]
        if isinstance(durations_ms, int):
            durs = [max(10, durations_ms)] * len(frames)
        else:
            durs = [max(10, int(d)) for d in durations_ms]
            if len(durs) != len(frames):
                raise ValueError("durations_ms length must match frame count.")
        return frames, durs

    @staticmethod
    def _sample_clip_at_time(frames: Sequence[Image.Image], durs: Sequence[int], t_ms: int) -> Image.Image:
        if len(frames) == 1:
            return frames[0]
        total = sum(durs)
        rem = t_ms % total
        acc = 0
        for f, d in zip(frames, durs):
            acc += d
            if rem < acc:
                return f
        return frames[-1]

    def set_tiled_background(
        self,
        tile: Union[Image.Image, Sequence[Image.Image]],
        frame_ms: int = 150,
        scroll_px_per_cycle: Tuple[int, int] = (0, 0),
    ) -> "SceneComposer":
        frames, _ = self._norm_frames(tile, frame_ms)
        self._tiled_bg = (frames, max(10, frame_ms), scroll_px_per_cycle)
        return self

    def add_background_layer(
        self,
        layer: Union[Image.Image, Sequence[Image.Image]],
        offset: Tuple[int, int] = (0, 0),
        frame_ms: int = 150,
    ) -> "SceneComposer":
        frames, _ = self._norm_frames(layer, frame_ms)
        self._bg_layers.append((frames, max(10, frame_ms), offset))
        return self

    def add_entity(
        self,
        name: str,
        sprite: Union[Image.Image, Sequence[Image.Image]],
        pos: Tuple[int, int],
        durations_ms: Union[int, Sequence[int]] = 120,
        end_pos: Optional[Tuple[int, int]] = None,
        anchor: str = "foot",
        z_index: Optional[int] = None,
        role: str = "actor",
        flip_h: bool = False,
    ) -> "SceneComposer":
        if anchor not in ("foot", "topleft", "center"):
            raise ValueError("anchor must be 'foot', 'topleft', or 'center'")
        if role not in ("actor", "prop", "fx", "ui"):
            raise ValueError("role must be 'actor', 'prop', 'fx', or 'ui'")
        frames, durs = self._norm_frames(sprite, durations_ms, flip_h=flip_h)
        self._entities.append(
            _SceneEntity(
                name=name,
                frames=frames,
                durations_ms=durs,
                pos=pos,
                end_pos=end_pos,
                anchor=anchor,
                z_index=z_index,
                role=role,
            )
        )
        return self

    def add_floating_text(
        self,
        name: str,
        text: str,
        pos: Tuple[int, int],
        color: ColorDef = "#FEE761",
        outline: Optional[ColorDef] = "#181425",
        rise_px: int = 6,
        scale: int = 1,
    ) -> "SceneComposer":
        txt_img = render_pixel_text(text, color=color, outline=outline, scale=scale)
        end_xy = (pos[0], pos[1] - rise_px) if rise_px != 0 else None
        return self.add_entity(
            name=name,
            sprite=txt_img,
            pos=pos,
            end_pos=end_xy,
            anchor="center",
            z_index=10_000,
            role="ui",
        )

    def _render_single_tick(
        self, t_ms: int, total_ms: int
    ) -> Tuple[Image.Image, Image.Image, Dict[str, Image.Image]]:
        """Return `(full_rgba, bg_only_rgba, actor_layers_by_name)` at `t_ms`."""
        u = (t_ms / float(max(1, total_ms))) if total_ms > 0 else 0.0
        bg = Image.new("RGBA", (self.width, self.height), self.bg_color)

        if self._tiled_bg is not None:
            t_frames, f_ms, (sc_x, sc_y) = self._tiled_bg
            tile_im = self._sample_clip_at_time(t_frames, [f_ms] * len(t_frames), t_ms)
            dx = round(sc_x * u)
            dy = round(sc_y * u)
            if dx != 0 or dy != 0:
                tile_im = shift_image(tile_im, dx=dx, dy=dy, wrap=True)
            tw, th = tile_im.size
            for y in range(0, self.height, th):
                for x in range(0, self.width, tw):
                    bg.paste(tile_im, (x, y))

        for l_frames, f_ms, (ox, oy) in self._bg_layers:
            lim = self._sample_clip_at_time(l_frames, [f_ms] * len(l_frames), t_ms)
            stage = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            stage.paste(lim, (ox, oy))
            bg = Image.alpha_composite(bg, stage)

        # Resolve entity positions & sort order (UI always on top; otherwise Y-sort by foot_y)
        resolved_items: List[Tuple[int, int, _SceneEntity, Image.Image, Tuple[int, int]]] = []
        for idx, ent in enumerate(self._entities):
            f_im = self._sample_clip_at_time(ent.frames, ent.durations_ms, t_ms)
            cx = round(ent.pos[0] + ((ent.end_pos[0] - ent.pos[0]) * u if ent.end_pos else 0.0))
            cy = round(ent.pos[1] + ((ent.end_pos[1] - ent.pos[1]) * u if ent.end_pos else 0.0))

            fw, fh = f_im.size
            bbox = f_im.getchannel("A").getbbox() or (0, 0, fw, fh)
            if ent.anchor == "foot":
                foot_local_x = (bbox[0] + bbox[2]) // 2
                foot_local_y = bbox[3] - 1
                tl_x = cx - foot_local_x
                tl_y = cy - foot_local_y
                sort_y = cy
            elif ent.anchor == "center":
                tl_x = cx - fw // 2
                tl_y = cy - fh // 2
                sort_y = tl_y + bbox[3]
            else:
                tl_x, tl_y = cx, cy
                sort_y = tl_y + bbox[3]

            z = ent.z_index if ent.z_index is not None else (9000 if ent.role == "ui" else sort_y)
            resolved_items.append((z, idx, ent, f_im, (tl_x, tl_y)))

        resolved_items.sort(key=lambda item: (item[0], item[1]))

        bg_with_props = bg.copy()
        full = bg.copy()
        actor_layers: Dict[str, Image.Image] = {}

        for _, _, ent, f_im, (tl_x, tl_y) in resolved_items:
            stage = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
            stage.paste(f_im, (tl_x, tl_y))
            full = Image.alpha_composite(full, stage)
            if ent.role == "prop":
                bg_with_props = Image.alpha_composite(bg_with_props, stage)
            elif ent.role == "actor":
                actor_layers[ent.name] = stage

        return full, bg_with_props, actor_layers

    def render_sequence(
        self,
        frame_count: int = 12,
        step_ms: int = 100,
    ) -> Tuple[List[Image.Image], List[int], Dict[str, Any]]:
        """Render the full animated scene plus readability diagnostics on keyframe 0."""
        if frame_count < 1 or step_ms < 10:
            raise ValueError("frame_count >= 1 and step_ms >= 10 required.")
        total_ms = frame_count * step_ms
        frames: List[Image.Image] = []
        f0_bg: Optional[Image.Image] = None
        f0_actors: Optional[Dict[str, Image.Image]] = None

        for i in range(frame_count):
            full, bg_only, actors = self._render_single_tick(i * step_ms, total_ms)
            frames.append(full)
            if i == 0:
                f0_bg = bg_only
                f0_actors = actors

        assert f0_bg is not None and f0_actors is not None
        readability = analyze_scene_readability(frames[0], f0_bg, f0_actors)
        return frames, [step_ms] * frame_count, readability


def analyze_scene_readability(
    full_frame: Image.Image,
    bg_frame: Image.Image,
    actor_layers: Dict[str, Image.Image],
) -> Dict[str, Any]:
    """Evaluate grayscale value distribution and foreground-vs-background silhouette separation."""
    w, h = full_frame.size
    bg_px = bg_frame.load()
    full_lums = [luminance(p) for p in img_pixels(full_frame.convert("RGBA"))]

    dark_pct = round(sum(1 for l in full_lums if l < 0.30) * 100.0 / len(full_lums), 1)
    mid_pct = round(sum(1 for l in full_lums if 0.30 <= l <= 0.70) * 100.0 / len(full_lums), 1)
    light_pct = round(100.0 - dark_pct - mid_pct, 1)

    actor_reports: Dict[str, Any] = {}
    warnings: List[str] = []
    camouflaged_pts_all: List[Tuple[int, int]] = []
    clear_pts_all: List[Tuple[int, int]] = []

    for aname, alayer in actor_layers.items():
        apx = alayer.load()
        fg_lums: List[float] = []
        edge_contrasts: List[float] = []
        camo_pts: List[Tuple[int, int]] = []
        good_pts: List[Tuple[int, int]] = []

        for y in range(h):
            for x in range(w):
                ac = apx[x, y]
                if ac[3] < 128:
                    continue
                al = luminance(ac)
                fg_lums.append(al)

                # Check adjacent exterior background pixels around silhouette border
                ext_bgs: List[RGBA] = []
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and apx[nx, ny][3] < 32:
                        ext_bgs.append(bg_px[nx, ny])
                if ext_bgs:
                    avg_contrast = sum(abs(al - luminance(bc)) for bc in ext_bgs) / len(ext_bgs)
                    avg_cdist = sum(math.sqrt(color_distance_sq(ac, bc)) for bc in ext_bgs) / len(ext_bgs)
                    edge_contrasts.append(avg_contrast)
                    if avg_contrast < 0.12 and avg_cdist < 85.0:
                        camo_pts.append((x, y))
                        camouflaged_pts_all.append((x, y))
                    else:
                        good_pts.append((x, y))
                        clear_pts_all.append((x, y))

        if not fg_lums:
            continue
        total_edge = max(1, len(edge_contrasts))
        camo_ratio = round(len(camo_pts) / float(total_edge), 3)
        mean_edge_c = round(sum(edge_contrasts) / float(total_edge), 3)
        actor_reports[aname] = {
            "mean_luminance": round(sum(fg_lums) / len(fg_lums), 3),
            "mean_silhouette_value_contrast": mean_edge_c,
            "camouflaged_perimeter_ratio": camo_ratio,
            "camouflaged_sample_coords": camo_pts[:8],
        }
        if camo_ratio > 0.35:
            warnings.append(
                f"Actor {aname!r} has {camo_ratio*100:.0f}% camouflaged silhouette border against background "
                f"(mean value delta={mean_edge_c}); consider stronger outline/Sel-out or darker/lighter floor."
            )

    return {
        "value_distribution_pct": {"dark": dark_pct, "mid": mid_pct, "light": light_pct},
        "actors": actor_reports,
        "warnings": warnings,
        "_heatmap_clear_pts": clear_pts_all,
        "_heatmap_camo_pts": camouflaged_pts_all,
    }


def generate_scene_value_sheet(
    scene_frame: Image.Image,
    readability: Dict[str, Any],
    actor_layers: Optional[Dict[str, Image.Image]] = None,
    title: str = "Scene Mockup & Value Readability Check",
    scale: int = 2,
) -> Image.Image:
    """Create a 2x2 Art-Direction Diagnostic Sheet:
    1. Color Mockup  |  2. Pure Grayscale Squint Test
    3. 3-Band Value Posterization  |  4. Actor Silhouette Contrast Heatmap
    """
    rgba = scene_frame.convert("RGBA")
    w, h = rgba.size
    sc = max(1, scale)

    raw_px = img_pixels(rgba)
    gray_img = Image.new("RGB", (w, h))
    band_img = Image.new("RGB", (w, h))
    heat_img = Image.new("RGB", (w, h))

    gray_data: List[Tuple[int, int, int]] = []
    band_data: List[Tuple[int, int, int]] = []
    heat_data: List[Tuple[int, int, int]] = []

    actor_mask = [False] * (w * h)
    if actor_layers:
        for al in actor_layers.values():
            for idx, p in enumerate(img_pixels(al.convert("RGBA"))):
                if p[3] >= 128:
                    actor_mask[idx] = True

    for idx, p in enumerate(raw_px):
        lum = luminance(p)
        g = round(lum * 255)
        gray_data.append((g, g, g))

        if lum < 0.30:
            band_data.append((28, 32, 44))     # Dark value slab
        elif lum <= 0.70:
            band_data.append((124, 134, 156))  # Midtone value slab
        else:
            band_data.append((238, 243, 252))  # Light value slab

        if actor_mask[idx]:
            heat_data.append((p[0], p[1], p[2]))
        else:
            dg = round(g * 0.38)
            heat_data.append((dg, dg, dg))

    gray_img.putdata(gray_data)
    band_img.putdata(band_data)
    heat_img.putdata(heat_data)

    hpx = heat_img.load()
    for x, y in readability.get("_heatmap_clear_pts", []):
        if 0 <= x < w and 0 <= y < h:
            hpx[x, y] = (0, 240, 155)
    for x, y in readability.get("_heatmap_camo_pts", []):
        if 0 <= x < w and 0 <= y < h:
            hpx[x, y] = (255, 55, 85)

    pw, ph = w * sc, h * sc
    pad = 16
    top_lbl = 22
    sheet_w = max(580, pw * 2 + pad * 3)
    sheet_h = 44 + (ph + top_lbl + pad) * 2 + pad

    sheet = Image.new("RGB", (sheet_w, sheet_h), (22, 24, 32))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    vd = readability["value_distribution_pct"]
    status = "READABILITY OK" if not readability["warnings"] else f"{len(readability['warnings'])} CONTRAST WARNING(S)"
    draw.text(
        (pad, 10),
        f"{title} ({w}x{h}) | Values: Dark {vd['dark']}% / Mid {vd['mid']}% / Light {vd['light']}% | {status}",
        fill=(240, 245, 255),
        font=font,
    )

    panels = [
        (rgba.convert("RGB"), f"1. Live Color Mockup ({sc}x)"),
        (gray_img, "2. Pure Grayscale Squint Test"),
        (band_img, "3. 3-Slab Value Grouping (Dark / Mid / Light)"),
        (heat_img, "4. Silhouette Readability (Green=Clear, Red=Camouflaged)"),
    ]

    for idx, (pim, plbl) in enumerate(panels):
        r_i, c_i = divmod(idx, 2)
        ox = pad + c_i * (pw + pad)
        oy = 42 + r_i * (ph + top_lbl + pad) + top_lbl
        draw.text((ox, oy - 16), plbl, fill=(185, 200, 230), font=font)
        up = pim.resize((pw, ph), Image.Resampling.NEAREST)
        sheet.paste(up, (ox, oy))
        draw.rectangle([ox - 1, oy - 1, ox + pw, oy + ph], outline=(70, 78, 96))

    return sheet


def build_scene_mockup(
    name: str,
    composer: SceneComposer,
    frame_count: int = 12,
    step_ms: int = 100,
    preview_scale: int = 3,
    output_dir: Union[str, Path] = "output/scene",
) -> Dict[str, Any]:
    """Render and export an animated in-game mockup GIF/WebP/APNG + 4-Panel Value Inspection Sheet."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    frames, durs, readability = composer.render_sequence(frame_count=frame_count, step_ms=step_ms)
    _, _, f0_actors = composer._render_single_tick(0, frame_count * step_ms)

    inspect_sheet = generate_scene_value_sheet(
        frames[0],
        readability,
        actor_layers=f0_actors,
        title=f"Scene: {name}",
        scale=max(2, preview_scale),
    )
    inspect_path = out / f"{name}_scene_inspect.png"
    inspect_sheet.save(inspect_path)

    fw, fh = frames[0].size
    scaled = [
        f.resize((fw * preview_scale, fh * preview_scale), Image.Resampling.NEAREST)
        for f in frames
    ]

    gif_scaled = out / f"{name}_{preview_scale}x.gif"
    webp_scaled = out / f"{name}_{preview_scale}x.webp"
    apng_1x = out / f"{name}.apng"
    png_scaled = out / f"{name}_{preview_scale}x.png"

    save_rgba_gif(scaled, gif_scaled, durs)
    save_animated_webp(scaled, webp_scaled, durs)
    save_apng(frames, apng_1x, durs)
    scaled[0].save(png_scaled)

    clean_rep = {k: v for k, v in readability.items() if not k.startswith("_")}
    meta_path = out / f"{name}_scene_report.json"
    meta_path.write_text(json.dumps(clean_rep, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Built Scene Mockup [{name}] ({fw}x{fh}, {frame_count} frame(s)):")
    print(f"  - VIEW 4-PANEL VALUE SHEET: {inspect_path}")
    print(f"  - Animated Gameplay GIF:    {gif_scaled}")
    for w_msg in clean_rep["warnings"]:
        print(f"  - [WARN] {w_msg}")

    return {
        "name": name,
        "readability": clean_rep,
        "files": {
            "inspect_sheet": str(inspect_path),
            "gif_scaled": str(gif_scaled),
            "webp_scaled": str(webp_scaled),
            "apng_1x": str(apng_1x),
            "png_scaled": str(png_scaled),
            "report_json": str(meta_path),
        },
    }
