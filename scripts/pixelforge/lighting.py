"""HD-2D Pixel Normal Map Generator, Auto Emission Mask Extractor,
and Dynamic 2D Point-Light Cel-Shaded Relighting Engine (Godot / Unity OpenGL convention).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from PIL import Image, ImageDraw, ImageFont

from .exporter import save_animated_webp, save_apng, save_rgba_gif
from .palette import ColorDef, RGBA, color_distance_sq, img_pixels, luminance, normalize_rgba, parse_color

# Neutral flat normal (+Z = (0, 0, 1)) in RGBA
FLAT_NORMAL_RGBA: RGBA = (128, 128, 255, 0)


def _exact_edt(mask: List[List[bool]]) -> List[List[float]]:
    """Exact 2D Euclidean Distance Transform inside `mask==True` to nearest `False` pixel."""
    h = len(mask)
    w = len(mask[0]) if h else 0
    inf = 1e9

    # Pass 1: 1D squared distance along columns
    g = [[0.0] * w for _ in range(h)]
    for x in range(w):
        # Top -> Bottom (include implicit False boundary at y = -1)
        d = 0.0
        for y in range(h):
            if mask[y][x]:
                d += 1.0
                g[y][x] = d * d
            else:
                d = 0.0
                g[y][x] = 0.0
        # Bottom -> Top (include implicit False boundary at y = h)
        d = 0.0
        for y in range(h - 1, -1, -1):
            if mask[y][x]:
                d += 1.0
                if d * d < g[y][x]:
                    g[y][x] = d * d
            else:
                d = 0.0

    # Pass 2: 1D lower envelope along rows (with implicit 0 at x=-1 and x=w)
    out = [[0.0] * w for _ in range(h)]
    for y in range(h):
        row_g = g[y]
        for x in range(w):
            if not mask[y][x]:
                out[y][x] = 0.0
                continue
            # Also cap by distance to left/right canvas borders so edge-touching shapes still round
            border_d2 = float(min(x + 1, w - x) ** 2)
            best = min(row_g[x], border_d2)
            max_r = int(math.sqrt(best)) + 1
            lo = max(0, x - max_r)
            hi = min(w - 1, x + max_r)
            for q in range(lo, hi + 1):
                cand = (x - q) * (x - q) + row_g[q]
                if cand < best:
                    best = cand
            out[y][x] = math.sqrt(best)
    return out


def compute_height_map(
    img: Image.Image,
    profile: str = "dome",  # 'dome' | 'bevel' | 'ridge'
    bevel_px: float = 5.0,
    cluster_relief: float = 0.25,
    luminance_relief: float = 0.15,
) -> List[List[float]]:
    """Compute a normalized `[0.0 .. 1.0]` 2.5D relief heightfield for a pixel-art layer or sprite."""
    if profile not in ("dome", "bevel", "ridge"):
        raise ValueError("profile must be 'dome', 'bevel', or 'ridge'")

    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()

    opaque_mask = [[px[x, y][3] >= 32 for x in range(w)] for y in range(h)]
    sil_dist = _exact_edt(opaque_mask)

    max_dist = max((sil_dist[y][x] for y in range(h) for x in range(w)), default=1.0)
    max_dist = max(1.0, max_dist)
    b_rad = max(1.0, bevel_px)

    # Optional internal color-cluster boundary groove detection (adds armor/brick seam relief!)
    cluster_groove = [[0.0] * w for _ in range(h)]
    if cluster_relief > 0.0:
        for y in range(h):
            for x in range(w):
                if not opaque_mask[y][x]:
                    continue
                c = normalize_rgba(px[x, y])
                diff_neighbors = 0
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and opaque_mask[ny][nx]:
                        nc = normalize_rgba(px[nx, ny])
                        if color_distance_sq(c, nc) > 900.0:
                            diff_neighbors += 1
                if diff_neighbors > 0:
                    # Slight bevel dip right at material seams
                    cluster_groove[y][x] = min(1.0, diff_neighbors * 0.35)

    hmap = [[0.0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            if not opaque_mask[y][x]:
                continue
            d = sil_dist[y][x]
            if profile == "dome":
                u = min(1.0, d / b_rad)
                # Spherical dome curve: steep at silhouette edge, smooth crown inside
                base_h = math.sqrt(max(0.0, 1.0 - (1.0 - u) ** 2))
            elif profile == "bevel":
                base_h = min(1.0, d / b_rad)
            else:
                # 'ridge': sharp chisel/blade medial spine
                base_h = min(1.0, d / max_dist)

            lum_term = (luminance(px[x, y]) - 0.5) * luminance_relief
            seam_term = -cluster_groove[y][x] * cluster_relief * 0.45
            hmap[y][x] = max(0.02, min(1.0, base_h + lum_term + seam_term))

    return hmap


def height_to_normal_map(
    height_map: List[List[float]],
    alpha_source: Image.Image,
    bump_strength: float = 2.2,
    invert_y: bool = False,
) -> Image.Image:
    """Convert a heightfield into an OpenGL Tangent-Space Normal Map (`+X=Right, +Y=Up, +Z=Out`)."""
    rgba = alpha_source.convert("RGBA")
    w, h = rgba.size
    apx = rgba.load()

    out = Image.new("RGBA", (w, h), FLAT_NORMAL_RGBA)
    dst = out.load()
    y_sign = -1.0 if invert_y else 1.0

    for y in range(h):
        for x in range(w):
            a = apx[x, y][3]
            if a < 32:
                dst[x, y] = (128, 128, 255, 0)
                continue

            h_l = height_map[y][x - 1] if x > 0 else 0.0
            h_r = height_map[y][x + 1] if x + 1 < w else 0.0
            h_u = height_map[y - 1][x] if y > 0 else 0.0
            h_d = height_map[y + 1][x] if y + 1 < h else 0.0

            # At left edge (h_r > h_l), outward normal points LEFT (-X)
            nx = -(h_r - h_l) * bump_strength
            # At top edge (h_d > h_u), outward normal points UP (+Y in OpenGL)
            ny = (h_d - h_u) * bump_strength * y_sign
            nz = 1.0

            mag = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            nx, ny, nz = nx / mag, ny / mag, nz / mag

            r = max(0, min(255, round((nx * 0.5 + 0.5) * 255.0)))
            g = max(0, min(255, round((ny * 0.5 + 0.5) * 255.0)))
            b = max(128, min(255, round((nz * 0.5 + 0.5) * 255.0)))
            dst[x, y] = (r, g, b, a)

    return out


def generate_normal_map(
    source: Union[Image.Image, Sequence[Tuple[Image.Image, str]]],
    profile: str = "dome",
    bevel_px: float = 4.5,
    bump_strength: float = 2.2,
    cluster_relief: float = 0.25,
    luminance_relief: float = 0.12,
    invert_y: bool = False,
) -> Tuple[Image.Image, Image.Image]:
    """Generate `(normal_map_rgba, height_preview_rgb)` from a single sprite OR a z-ordered list
    of `(part_layer_img, part_profile)` tuples (for true per-part HD-2D relief!).
    """
    if isinstance(source, Image.Image):
        hmap = compute_height_map(
            source,
            profile=profile,
            bevel_px=bevel_px,
            cluster_relief=cluster_relief,
            luminance_relief=luminance_relief,
        )
        nmap = height_to_normal_map(hmap, source, bump_strength=bump_strength, invert_y=invert_y)
        w, h = source.size
        h_vis = Image.new("RGB", (w, h), (16, 18, 24))
        h_vis.putdata([
            (round(hmap[y][x] * 255),) * 3 if hmap[y][x] > 0 else (16, 18, 24)
            for y in range(h)
            for x in range(w)
        ])
        return nmap, h_vis

    if not source:
        raise ValueError("Part layer list must not be empty.")
    w, h = source[0][0].size
    merged_normal = Image.new("RGBA", (w, h), FLAT_NORMAL_RGBA)
    merged_h = [[0.0] * w for _ in range(h)]

    for z_idx, (part_im, part_prof) in enumerate(source):
        rgba_p = part_im.convert("RGBA")
        ph = compute_height_map(
            rgba_p,
            profile=part_prof,
            bevel_px=bevel_px,
            cluster_relief=cluster_relief,
            luminance_relief=luminance_relief,
        )
        pn = height_to_normal_map(ph, rgba_p, bump_strength=bump_strength, invert_y=invert_y)
        merged_normal = Image.alpha_composite(merged_normal, pn)
        ppx = rgba_p.load()
        z_boost = min(0.25, z_idx * 0.05)
        for y in range(h):
            for x in range(w):
                if ppx[x, y][3] >= 32:
                    merged_h[y][x] = min(1.0, ph[y][x] * 0.8 + z_boost)

    h_vis = Image.new("RGB", (w, h), (16, 18, 24))
    h_vis.putdata([
        (round(merged_h[y][x] * 255),) * 3 if merged_h[y][x] > 0 else (16, 18, 24)
        for y in range(h)
        for x in range(w)
    ])
    return merged_normal, h_vis


def generate_emission_map(
    albedo: Image.Image,
    emissive_colors: Optional[Sequence[ColorDef]] = None,
    luminance_threshold: Optional[float] = None,
    tolerance: int = 12,
) -> Image.Image:
    """Extract self-luminous pixels (glowing eyes, runes, fire, potions) into an RGBA emission mask."""
    rgba = albedo.convert("RGBA")
    targets = [normalize_rgba(parse_color(c)) for c in (emissive_colors or [])]
    tol_sq = tolerance * tolerance * 9.0

    out = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    data: List[RGBA] = []
    for p in img_pixels(rgba):
        np = normalize_rgba(p)
        if np[3] < 32:
            data.append((0, 0, 0, 0))
            continue
        emit = False
        if targets and any(color_distance_sq(np, tc) <= tol_sq for tc in targets):
            emit = True
        if luminance_threshold is not None and luminance(np) >= luminance_threshold:
            emit = True
        data.append(np if emit else (0, 0, 0, 0))
    out.putdata(data)
    return out


def relight_sprite(
    albedo: Image.Image,
    normal_map: Image.Image,
    emission_map: Optional[Image.Image] = None,
    light_pos: Tuple[float, float, float] = (8.0, 6.0, 18.0),
    light_color: ColorDef = "#FFC67A",
    ambient_color: ColorDef = "#282E4A",
    intensity: float = 1.45,
    falloff_radius: float = 48.0,
    specular_strength: float = 0.35,
    shininess: float = 14.0,
    cel_bands: Optional[int] = 4,
    draw_light_gizmo: bool = False,
) -> Image.Image:
    """ dynamically relight `albedo` using `normal_map`, `emission_map`, and a 3D point light `(lx, ly, lz)`.
    Uses pixel-art banded cel quantization (`cel_bands=4`) by default for crisp Dead-Cells aesthetics.
    """
    if albedo.size != normal_map.size:
        raise ValueError("albedo and normal_map must have matching dimensions.")
    w, h = albedo.size
    a_px = albedo.convert("RGBA").load()
    n_px = normal_map.convert("RGBA").load()
    e_px = emission_map.convert("RGBA").load() if emission_map is not None else None

    lc = parse_color(light_color)
    ac = parse_color(ambient_color)
    lx, ly, lz = light_pos

    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dst = out.load()

    for y in range(h):
        for x in range(w):
            base = a_px[x, y]
            if base[3] == 0:
                continue

            nr, ng, nb, _ = n_px[x, y]
            nx = (nr / 255.0) * 2.0 - 1.0
            ny = (ng / 255.0) * 2.0 - 1.0  # +Y is UP
            nz = (nb / 255.0) * 2.0 - 1.0
            n_mag = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            nx, ny, nz = nx / n_mag, ny / n_mag, nz / n_mag

            # Vector from pixel (x, y, 0) to light (lx, ly, lz); note screen Y increases downward!
            vx = lx - x
            vy = -(ly - y)  # flip to OpenGL +Y=UP
            vz = lz
            dist = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
            dx, dy, dz = vx / dist, vy / dist, vz / dist

            ndotl = max(0.0, nx * dx + ny * dy + nz * dz)
            atten = 1.0 / (1.0 + (dist / max(4.0, falloff_radius)) ** 2)
            diff = ndotl * atten * intensity

            if cel_bands is not None and cel_bands >= 2:
                diff = round(diff * cel_bands) / float(cel_bands)

            # Blinn-Phong half-vector with camera at (0, 0, 1)
            hx, hy, hz = dx, dy, dz + 1.0
            h_mag = math.sqrt(hx * hx + hy * hy + hz * hz) or 1.0
            ndoth = max(0.0, (nx * hx + ny * hy + nz * hz) / h_mag)
            spec = (ndoth ** shininess) * specular_strength * atten
            if cel_bands is not None:
                spec = specular_strength if spec > specular_strength * 0.52 else 0.0

            rr = base[0] * ((ac[0] / 255.0) + diff * (lc[0] / 255.0)) + spec * lc[0]
            gg = base[1] * ((ac[1] / 255.0) + diff * (lc[1] / 255.0)) + spec * lc[1]
            bb = base[2] * ((ac[2] / 255.0) + diff * (lc[2] / 255.0)) + spec * lc[2]

            if e_px is not None:
                er, eg, eb, ea = e_px[x, y]
                if ea > 0:
                    em_k = ea / 255.0
                    rr = max(rr, er * em_k + rr * 0.25)
                    gg = max(gg, eg * em_k + gg * 0.25)
                    bb = max(bb, eb * em_k + bb * 0.25)

            dst[x, y] = (
                max(0, min(255, round(rr))),
                max(0, min(255, round(gg))),
                max(0, min(255, round(bb))),
                base[3],
            )

    if draw_light_gizmo:
        gx, gy = round(lx), round(ly)
        for ox, oy, alpha_k in ((0, 0, 255), (-1, 0, 180), (1, 0, 180), (0, -1, 180), (0, 1, 180)):
            px_x, px_y = gx + ox, gy + oy
            if 0 <= px_x < w and 0 <= px_y < h:
                dst[px_x, px_y] = (255, 255, 255, 255) if alpha_k == 255 else (lc[0], lc[1], lc[2], 230)

    return out


def export_hd2d_bundle(
    name: str,
    albedo: Image.Image,
    part_layers: Optional[Sequence[Tuple[Image.Image, str]]] = None,
    emissive_colors: Optional[Sequence[ColorDef]] = None,
    profile: str = "dome",
    bevel_px: float = 4.5,
    bump_strength: float = 2.2,
    orbit_frames: int = 12,
    preview_scale: int = 6,
    output_dir: Union[str, Path] = "output/hd2d",
) -> Dict[str, str]:
    """Generate and export Albedo + Normal Map + Emission Mask + 360 Orbiting Torch GIF/WebP + Inspection Sheet."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rgba_albedo = albedo.convert("RGBA")
    w, h = rgba_albedo.size

    src_for_normals: Union[Image.Image, Sequence[Tuple[Image.Image, str]]] = (
        part_layers if part_layers is not None else rgba_albedo
    )
    normal_map, height_vis = generate_normal_map(
        src_for_normals,
        profile=profile,
        bevel_px=bevel_px,
        bump_strength=bump_strength,
    )
    emission_map = generate_emission_map(rgba_albedo, emissive_colors=emissive_colors)

    bbox = rgba_albedo.getchannel("A").getbbox() or (0, 0, w, h)
    cx = 0.5 * (bbox[0] + bbox[2])
    cy = 0.5 * (bbox[1] + bbox[3])
    orbit_rx = max(6.0, (bbox[2] - bbox[0]) * 0.68)
    orbit_ry = max(6.0, (bbox[3] - bbox[1]) * 0.62)
    lz = max(10.0, max(w, h) * 0.36)

    relit_seq: List[Image.Image] = []
    for i in range(orbit_frames):
        ang = -math.pi * 0.75 + (2.0 * math.pi * i) / float(orbit_frames)
        lx = cx + math.cos(ang) * orbit_rx
        ly = cy + math.sin(ang) * orbit_ry
        frame_dark_bg = Image.new("RGBA", (w, h), (18, 20, 30, 255))
        lit = relight_sprite(
            rgba_albedo,
            normal_map,
            emission_map=emission_map,
            light_pos=(lx, ly, lz),
            falloff_radius=max(w, h) * 1.15,
            draw_light_gizmo=True,
        )
        relit_seq.append(Image.alpha_composite(frame_dark_bg, lit))

    albedo_file = out / f"{name}_albedo.png"
    normal_file = out / f"{name}_normal.png"
    emission_file = out / f"{name}_emission.png"
    orbit_gif = out / f"{name}_torch_orbit_{preview_scale}x.gif"
    orbit_webp = out / f"{name}_torch_orbit_{preview_scale}x.webp"
    inspect_file = out / f"{name}_hd2d_inspect.png"

    rgba_albedo.save(albedo_file)
    normal_map.save(normal_file)
    emission_map.save(emission_file)

    scaled_orbit = [
        f.resize((w * preview_scale, h * preview_scale), Image.Resampling.NEAREST)
        for f in relit_seq
    ]
    durs = [100] * orbit_frames
    save_rgba_gif(scaled_orbit, orbit_gif, durs)
    save_animated_webp(scaled_orbit, orbit_webp, durs)

    # Build 2-Row HD-2D Diagnostic Inspection Sheet:
    # Row 1: Albedo | Height Relief | Normal Map (RGB) | Emission Mask
    # Row 2: 4 Cardinal Torch Directions (NW, NE, SE, SW) verifying 3D normal vectors!
    sc = max(3, min(6, preview_scale))
    pw, ph = w * sc, h * sc
    pad = 16
    lbl_h = 18
    sheet_w = max(620, (pw + pad) * 4 + pad)
    sheet_h = 42 + (ph + lbl_h + pad) * 2 + pad

    sheet = Image.new("RGB", (sheet_w, sheet_h), (22, 24, 32))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    draw.text(
        (pad, 10),
        f"HD-2D Lighting Bundle [{name}] ({w}x{h}) : Top = Maps | Bottom = 4-Corner Point-Light Verification",
        fill=(240, 245, 255),
        font=font,
    )

    def _bg_comp(im: Image.Image, bg_rgb: Tuple[int, int, int] = (28, 30, 40)) -> Image.Image:
        bg = Image.new("RGBA", im.size, (*bg_rgb, 255))
        return Image.alpha_composite(bg, im.convert("RGBA")).convert("RGB")

    row1_panels = [
        (_bg_comp(rgba_albedo), "1. Base Albedo"),
        (height_vis, "2. 2.5D Height Relief"),
        (_bg_comp(normal_map, (128, 128, 255)), "3. Tangent Normal Map"),
        (_bg_comp(emission_map, (12, 14, 20)), "4. Emission Glow Mask"),
    ]
    for idx, (pim, plbl) in enumerate(row1_panels):
        ox = pad + idx * (pw + pad)
        oy = 40 + lbl_h
        draw.text((ox, oy - 14), plbl, fill=(185, 200, 230), font=font)
        sheet.paste(pim.resize((pw, ph), Image.Resampling.NEAREST), (ox, oy))
        draw.rectangle([ox - 1, oy - 1, ox + pw, oy + ph], outline=(72, 80, 98))

    # Sample 4 cardinal frames from orbit (NW=0, NE=3, SE=6, SW=9 when orbit_frames=12)
    q_indices = [0, orbit_frames // 4, orbit_frames // 2, (orbit_frames * 3) // 4]
    q_names = ["Torch Top-Left (NW)", "Torch Top-Right (NE)", "Torch Bot-Right (SE)", "Torch Bot-Left (SW)"]
    for idx, (qi, qname) in enumerate(zip(q_indices, q_names)):
        ox = pad + idx * (pw + pad)
        oy = 40 + (ph + lbl_h + pad) + lbl_h
        draw.text((ox, oy - 14), qname, fill=(255, 215, 145), font=font)
        sheet.paste(relit_seq[qi].convert("RGB").resize((pw, ph), Image.Resampling.NEAREST), (ox, oy))
        draw.rectangle([ox - 1, oy - 1, ox + pw, oy + ph], outline=(72, 80, 98))

    sheet.save(inspect_file)
    print(f"Built HD-2D Normal & Lighting Bundle [{name}]:")
    print(f"  - VIEW HD-2D INSPECTION: {inspect_file}")
    print(f"  - 360 Orbiting Torch:    {orbit_gif}")
    return {
        "albedo_png": str(albedo_file),
        "normal_png": str(normal_file),
        "emission_png": str(emission_file),
        "orbit_gif": str(orbit_gif),
        "orbit_webp": str(orbit_webp),
        "inspect_sheet": str(inspect_file),
    }
