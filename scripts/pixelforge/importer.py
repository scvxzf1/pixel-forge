"""Reverse Decompiler (PNG / GIF / APNG / WebP / Spritesheet -> Editable ASCII Project)
and High-Res / AI Concept Image Pixelator ('Pixelate & Clean').
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
from PIL import Image, ImageEnhance, ImageFilter

from .aseprite_io import read_aseprite
from .canvas import image_to_grid
from .inspector import generate_holistic_sheet
from .linter import format_lint_report, lint_frames
from .palette import (
    ColorDef,
    RGBA,
    analyze_palette_ramps,
    canonical_char_map,
    color_distance_sq,
    extract_palette,
    get_palette,
    img_pixels,
    normalize_rgba,
    rgba_to_hex,
)
from .transform import auto_outline, clean_orphan_specks

_BAYER_2X2 = ((0, 2), (3, 1))


def detect_integer_upscale_factor(frames: Sequence[Image.Image]) -> int:
    """Detect if `frames` are an exact lossless Nearest-Neighbor integer upscale (e.g. 4x or 8x).
    Returns k >= 1 (1 means already native 1x resolution).
    """
    if not frames:
        return 1
    w, h = frames[0].size
    if w < 4 or h < 4:
        return 1

    g = 0
    for f in frames:
        rgba = f.convert("RGBA")
        if rgba.size != (w, h):
            return 1
        data = [normalize_rgba(p) for p in img_pixels(rgba)]

        # Horizontal run lengths
        for y in range(h):
            row_off = y * w
            run = 1
            prev = data[row_off]
            for x in range(1, w):
                cur = data[row_off + x]
                if cur == prev:
                    run += 1
                else:
                    g = math.gcd(g, run)
                    if g == 1:
                        return 1
                    run = 1
                    prev = cur
            g = math.gcd(g, run)
            if g == 1:
                return 1

        # Vertical run lengths
        for x in range(w):
            run = 1
            prev = data[x]
            for y in range(1, h):
                cur = data[y * w + x]
                if cur == prev:
                    run += 1
                else:
                    g = math.gcd(g, run)
                    if g == 1:
                        return 1
                    run = 1
                    prev = cur
            g = math.gcd(g, run)
            if g == 1:
                return 1

    return max(1, g)


def load_frames_from_file(
    path: Union[str, Path],
    frame_w: Optional[int] = None,
    frame_h: Optional[int] = None,
    cols: Optional[int] = None,
    rows: Optional[int] = None,
    auto_downscale_native: bool = True,
) -> Tuple[List[Image.Image], List[int], int]:
    """Load static, animated (GIF/APNG/WebP), or spritesheet image into `(frames, durations_ms, downscale_k)`."""
    src_path = Path(path)
    raw_frames: List[Image.Image] = []
    durations: List[int] = []

    if src_path.suffix.lower() in (".ase", ".aseprite"):
        doc = read_aseprite(src_path)
        raw_frames = [f.copy() for f in doc.composited_frames]
        durations = list(doc.durations_ms)
    else:
        with Image.open(src_path) as im:
            n_frames = getattr(im, "n_frames", 1)
            if n_frames > 1:
                for idx in range(n_frames):
                    im.seek(idx)
                    raw_frames.append(im.convert("RGBA"))
                    dur = int(round(im.info.get("duration", 100) or 100))
                    durations.append(max(10, dur))
            else:
                sheet = im.convert("RGBA")
                sw, sh = sheet.size
                if cols is not None or rows is not None:
                    c = cols or 1
                    r = rows or 1
                    if sw % c != 0 or sh % r != 0:
                        raise ValueError(f"Image {sw}x{sh} not evenly divisible by cols={c}, rows={r}.")
                    fw, fh = sw // c, sh // r
                    for ry in range(r):
                        for rx in range(c):
                            cell = sheet.crop((rx * fw, ry * fh, (rx + 1) * fw, (ry + 1) * fh))
                            if cell.getchannel("A").getbbox() is not None or len(raw_frames) == 0:
                                raw_frames.append(cell)
                                durations.append(120)
                elif frame_w is not None or frame_h is not None:
                    fw = frame_w or sw
                    fh = frame_h or sh
                    if sw % fw != 0 or sh % fh != 0:
                        raise ValueError(f"Image {sw}x{sh} not evenly divisible by frame {fw}x{fh}.")
                    for ry in range(sh // fh):
                        for rx in range(sw // fw):
                            cell = sheet.crop((rx * fw, ry * fh, (rx + 1) * fw, (ry + 1) * fh))
                            if cell.getchannel("A").getbbox() is not None or len(raw_frames) == 0:
                                raw_frames.append(cell)
                                durations.append(120)
                else:
                    raw_frames.append(sheet)
                    durations.append(120)

    downscale_k = 1
    if auto_downscale_native:
        k = detect_integer_upscale_factor(raw_frames)
        # Only auto-downscale when native canvas remains at least 4x4 (avoids collapsing solid color blocks)
        if k > 1 and (raw_frames[0].width // k) >= 4 and (raw_frames[0].height // k) >= 4:
            downscale_k = k
            fw_n = raw_frames[0].width // k
            fh_n = raw_frames[0].height // k
            raw_frames = [
                f.resize((fw_n, fh_n), Image.Resampling.NEAREST) for f in raw_frames
            ]

    return raw_frames, durations, downscale_k


def _write_editable_project_script(
    script_path: Path,
    pforge_dir: Path,
    asset_name: str,
    palette_dict: Dict[str, str],
    ascii_frames: Sequence[Sequence[str]],
    durations_ms: Sequence[int],
) -> None:
    pal_json = json.dumps(palette_dict, indent=4, ensure_ascii=False)
    lines = [
        "#!/usr/bin/env python3",
        f'"""Editable PixelForge project decompiled from {asset_name}."""',
        "import sys",
        f"sys.path.insert(0, {str(pforge_dir)!r})",
        "from pforge import build_pixel_asset",
        "",
        f"PALETTE = {pal_json}",
        "",
        f"DURATIONS_MS = {list(durations_ms)!r}",
        "",
        "FRAMES = [",
    ]
    for idx, grid in enumerate(ascii_frames):
        lines.append(f"    # Frame {idx} ({durations_ms[idx]}ms)")
        lines.append("    [")
        for row in grid:
            lines.append(f"        {row!r},")
        lines.append("    ],")
    lines.extend([
        "]",
        "",
        'if __name__ == "__main__":',
        f'    build_pixel_asset({asset_name!r}, FRAMES, palette=PALETTE, durations_ms=DURATIONS_MS, output_dir="output")',
        "",
    ])
    script_path.write_text("\n".join(lines), encoding="utf-8")


def decompile_asset(
    source_path: Union[str, Path],
    output_dir: Union[str, Path] = "output/decompiled",
    name: Optional[str] = None,
    frame_w: Optional[int] = None,
    frame_h: Optional[int] = None,
    cols: Optional[int] = None,
    rows: Optional[int] = None,
    palette: Optional[Union[str, Dict[str, ColorDef]]] = None,
    max_colors: int = 48,
    auto_downscale_native: bool = True,
) -> Dict[str, Any]:
    """Reverse-engineer any PNG / GIF / APNG / WebP / Spritesheet into an editable ASCII project."""
    src = Path(source_path)
    asset_name = name or src.stem
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    frames, durations_ms, downscale_k = load_frames_from_file(
        src,
        frame_w=frame_w,
        frame_h=frame_h,
        cols=cols,
        rows=rows,
        auto_downscale_native=auto_downscale_native,
    )

    if palette is None:
        pal_dict = extract_palette(frames, max_colors=max_colors)
    else:
        resolved = get_palette(palette)
        pal_dict = {k: rgba_to_hex(v) for k, v in resolved.items() if k != " "}

    ascii_frames: List[List[str]] = []
    for f in frames:
        grid_lines, _ = image_to_grid(f, palette=pal_dict)
        ascii_frames.append(grid_lines)

    inspect_img = generate_holistic_sheet(
        frames,
        title=f"Decompiled: {asset_name}" + (f" (auto {downscale_k}x->1x)" if downscale_k > 1 else ""),
        palette=pal_dict,
        durations_ms=durations_ms,
    )
    inspect_file = out_dir / f"{asset_name}_inspect.png"
    inspect_img.save(inspect_file)

    lint_rep = lint_frames(frames)
    ramps = analyze_palette_ramps(pal_dict)

    pforge_scripts_dir = Path(__file__).resolve().parent.parent
    edit_script = out_dir / f"edit_{asset_name}.py"
    _write_editable_project_script(
        edit_script, pforge_scripts_dir, asset_name, pal_dict, ascii_frames, durations_ms
    )

    bundle = {
        "name": asset_name,
        "source": str(src),
        "native_width": frames[0].width,
        "native_height": frames[0].height,
        "frame_count": len(frames),
        "auto_downscaled_by": downscale_k,
        "durations_ms": durations_ms,
        "palette": pal_dict,
        "palette_ramps": ramps,
        "lint": lint_rep,
        "files": {
            "inspect_sheet": str(inspect_file),
            "edit_script": str(edit_script),
            "project_json": str(out_dir / f"{asset_name}_decompiled.json"),
        },
        "frames_ascii": ascii_frames,
    }
    Path(bundle["files"]["project_json"]).write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Decompiled [{asset_name}] ({frames[0].width}x{frames[0].height}, {len(frames)} frame(s)):")
    print(f"  - Holistic Inspection Sheet: {inspect_file}")
    print(f"  - Editable Python Script:    {edit_script}")
    print("  - " + format_lint_report(lint_rep).replace("\n", "\n    "))
    return bundle


def pixelate_image(
    source: Union[str, Path, Image.Image],
    target_size: Tuple[int, int] = (48, 48),
    palette: Optional[Union[str, Dict[str, ColorDef]]] = "endesga32",
    max_colors: int = 24,
    mode: str = "contrast_box",
    keep_aspect: bool = True,
    alpha_threshold: int = 112,
    dither_strength: float = 0.0,
    despeckle: bool = True,
    outline_color: Optional[ColorDef] = None,
    output_dir: Optional[Union[str, Path]] = None,
    name: str = "pixelated",
) -> Dict[str, Any]:
    """Convert a high-res illustration, icon, or AI draft into clean, editable pixel art.

    mode='contrast_box': Contrast-boosted area downsampling for smooth illustrations/photos.
    mode='dominant_block': Center-weighted block mode voting for noisy/uneven AI pseudo-pixel art.
    """
    if mode not in ("contrast_box", "dominant_block"):
        raise ValueError("mode must be 'contrast_box' or 'dominant_block'")
    tw, th = target_size
    if tw < 4 or th < 4:
        raise ValueError("target_size dimensions must be >= 4")

    src_img = Image.open(source).convert("RGBA") if isinstance(source, (str, Path)) else source.convert("RGBA")
    sw, sh = src_img.size

    if keep_aspect:
        scale = min(tw / float(sw), th / float(sh))
        fit_w = max(1, round(sw * scale))
        fit_h = max(1, round(sh * scale))
    else:
        fit_w, fit_h = tw, th

    if mode == "contrast_box":
        rgb = src_img.convert("RGB")
        rgb = ImageEnhance.Contrast(rgb).enhance(1.15)
        rgb = ImageEnhance.Sharpness(rgb).enhance(1.35)
        small_rgb = rgb.resize((fit_w, fit_h), Image.Resampling.BOX)
        small_a = src_img.getchannel("A").resize((fit_w, fit_h), Image.Resampling.BOX)
        canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ox, oy = (tw - fit_w) // 2, (th - fit_h) // 2
        merged_small = Image.merge("RGBA", (*small_rgb.split(), small_a))
        canvas.paste(merged_small, (ox, oy))
    else:
        # Dominant block mode voting (cleans blurry AI pixel boundaries)
        canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ox, oy = (tw - fit_w) // 2, (th - fit_h) // 2
        src_px = src_img.load()
        dst_px = canvas.load()
        for py in range(fit_h):
            y0 = int(py * sh / fit_h)
            y1 = max(y0 + 1, int((py + 1) * sh / fit_h))
            # Focus inner 60% of block to avoid blurred cell borders
            ym0 = y0 + (y1 - y0) // 5
            ym1 = max(ym0 + 1, y1 - (y1 - y0) // 5)
            for px in range(fit_w):
                x0 = int(px * sw / fit_w)
                x1 = max(x0 + 1, int((px + 1) * sw / fit_w))
                xm0 = x0 + (x1 - x0) // 5
                xm1 = max(xm0 + 1, x1 - (x1 - x0) // 5)
                bucket: Counter[Tuple[int, int, int]] = Counter()
                alpha_sum = 0
                total_n = 0
                for sy in range(ym0, ym1):
                    for sx in range(xm0, xm1):
                        r, g, b, a = src_px[sx, sy]
                        alpha_sum += a
                        total_n += 1
                        if a >= alpha_threshold:
                            # Coarsely bin by 8 to group JPEG/diffusion noise before palette snap
                            bucket[(r // 8 * 8, g // 8 * 8, b // 8 * 8)] += 1
                if total_n > 0 and (alpha_sum / total_n) >= alpha_threshold and bucket:
                    br, bg, bb = bucket.most_common(1)[0][0]
                    dst_px[ox + px, oy + py] = (br, bg, bb, 255)

    # Harden alpha to crisp binary pixel-art mask
    hard_data: List[RGBA] = [
        (r, g, b, 255) if a >= alpha_threshold else (0, 0, 0, 0)
        for r, g, b, a in img_pixels(canvas)
    ]
    canvas.putdata(hard_data)

    # Resolve target palette or extract N colors
    if palette is None:
        pal_dict = extract_palette(canvas, max_colors=max_colors, alpha_threshold=alpha_threshold)
    else:
        resolved = get_palette(palette)
        pal_dict = {k: rgba_to_hex(v) for k, v in resolved.items() if k != " "}

    rev_pal = canonical_char_map(pal_dict)
    opaque_pal_colors = [col for col in rev_pal if col[3] > 0]

    # Snap pixels to palette (with optional subtle ordered Bayer 2x2 dithering)
    quant_data: List[RGBA] = []
    raw_px = img_pixels(canvas)
    for idx, p in enumerate(raw_px):
        if p[3] == 0:
            quant_data.append((0, 0, 0, 0))
            continue
        if dither_strength > 0.0:
            x, y = idx % tw, idx // tw
            b_val = (_BAYER_2X2[y % 2][x % 2] / 3.0) - 0.5  # [-0.5, +0.5]
            shift = round(b_val * 48.0 * dither_strength)
            p = (
                max(0, min(255, p[0] + shift)),
                max(0, min(255, p[1] + shift)),
                max(0, min(255, p[2] + shift)),
                255,
            )
        best = min(opaque_pal_colors, key=lambda pc: color_distance_sq(p, pc))
        quant_data.append(best)
    canvas.putdata(quant_data)

    if despeckle:
        canvas = clean_orphan_specks(canvas, min_neighbors=1)
    if outline_color is not None:
        canvas = auto_outline(canvas, color=outline_color, connectivity=4, mode="outer")
        # Ensure outline color is in pal_dict
        oc_rgba = normalize_rgba(get_palette({"K": outline_color})["K"])
        if oc_rgba not in rev_pal:
            pal_dict["K"] = rgba_to_hex(oc_rgba)

    grid_lines, final_pal = image_to_grid(canvas, palette=pal_dict)
    result: Dict[str, Any] = {
        "name": name,
        "image": canvas,
        "grid": grid_lines,
        "palette": final_pal,
    }

    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        png_1x = out_dir / f"{name}_1x.png"
        png_8x = out_dir / f"{name}_8x.png"
        inspect_file = out_dir / f"{name}_inspect.png"
        compare_file = out_dir / f"{name}_compare.png"
        edit_script = out_dir / f"edit_{name}.py"

        canvas.save(png_1x)
        canvas.resize((tw * 8, th * 8), Image.Resampling.NEAREST).save(png_8x)
        generate_holistic_sheet([canvas], title=f"Pixelated: {name}", palette=final_pal).save(inspect_file)

        # Side-by-side Original vs Pixelated comparison
        comp_h = max(240, th * 6)
        comp_src_w = max(1, round(sw * (comp_h / float(sh))))
        comp_pix_w = round(tw * (comp_h / float(th)))
        comp = Image.new("RGB", (comp_src_w + comp_pix_w + 36, comp_h + 24), (28, 30, 38))
        s_thumb = src_img.resize((comp_src_w, comp_h), Image.Resampling.LANCZOS)
        p_thumb = canvas.resize((comp_pix_w, comp_h), Image.Resampling.NEAREST)
        bg1 = Image.new("RGBA", s_thumb.size, (42, 46, 58, 255))
        bg2 = Image.new("RGBA", p_thumb.size, (42, 46, 58, 255))
        comp.paste(Image.alpha_composite(bg1, s_thumb).convert("RGB"), (12, 12))
        comp.paste(Image.alpha_composite(bg2, p_thumb).convert("RGB"), (24 + comp_src_w, 12))
        comp.save(compare_file)

        pforge_scripts_dir = Path(__file__).resolve().parent.parent
        _write_editable_project_script(
            edit_script, pforge_scripts_dir, name, final_pal, [grid_lines], [150]
        )
        result["files"] = {
            "png_1x": str(png_1x),
            "png_8x": str(png_8x),
            "inspect_sheet": str(inspect_file),
            "compare_sheet": str(compare_file),
            "edit_script": str(edit_script),
        }
        print(f"Pixelated [{name}] ({sw}x{sh} -> {tw}x{th}):")
        print(f"  - Holistic Inspection Sheet: {inspect_file}")
        print(f"  - Original vs Pixelated:     {compare_file}")
        print(f"  - Editable Polish Script:    {edit_script}")

    return result
