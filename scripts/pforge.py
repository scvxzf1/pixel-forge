#!/usr/bin/env python3
"""PixelForge Unified Entrypoint:
1. Importable Python API: `from pforge import *`
2. Zero-friction CLI tool: `python3 pforge.py <subcommand> ...`
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from PIL import Image

# Ensure local `pixelforge` package is always importable regardless of working directory
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from pixelforge import *  # noqa: E402,F401,F403


def _parse_wh(spec: str) -> Tuple[int, int]:
    parts = spec.lower().split("x")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"Expected WxH (e.g. 48x48), got {spec!r}")
    return int(parts[0]), int(parts[1])


def _parse_box(spec: str) -> Tuple[int, int, int, int]:
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(f"Expected X,Y,W,H (e.g. 12,8,24,24), got {spec!r}")
    return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])


def _parse_xy(spec: str) -> Tuple[int, int]:
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"Expected X,Y (e.g. 12,8), got {spec!r}")
    return int(parts[0]), int(parts[1])


def _load_palette_arg(pal_arg: Optional[str]) -> Optional[Dict[str, str] | str]:
    if not pal_arg or pal_arg.lower() == "auto":
        return None
    p = Path(pal_arg)
    if p.is_file():
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("palette", data)
    return pal_arg


def _cmd_inspect(args: argparse.Namespace) -> int:
    fw, fh = _parse_wh(args.frame_size) if args.frame_size else (None, None)
    frames, durs, downscale_k = load_frames_from_file(
        args.input,
        frame_w=fw,
        frame_h=fh,
        cols=args.cols,
        rows=args.rows,
        auto_downscale_native=not args.keep_scale,
    )
    pal = extract_palette(frames, max_colors=min(48, len(SAFE_ASCII_CHARS))) if len(frames) else None
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem
    inspect_path = out_dir / f"{stem}_inspect.png"
    title = f"Inspect: {stem}" + (f" (auto {downscale_k}x->1x)" if downscale_k > 1 else "")
    sheet = generate_holistic_sheet(frames, title=title, palette=pal, durations_ms=durs, scale=args.scale)
    sheet.save(inspect_path)
    rep = lint_frames(frames)
    print(f"Saved Holistic Inspection Sheet -> {inspect_path}")
    print(format_lint_report(rep))
    return 0


def _cmd_decompile(args: argparse.Namespace) -> int:
    fw, fh = _parse_wh(args.frame_size) if args.frame_size else (None, None)
    pal = _load_palette_arg(args.palette)
    decompile_asset(
        args.input,
        output_dir=args.output_dir,
        name=args.name,
        frame_w=fw,
        frame_h=fh,
        cols=args.cols,
        rows=args.rows,
        palette=pal,
        max_colors=args.max_colors,
        auto_downscale_native=not args.keep_scale,
    )
    return 0


def _cmd_region_extract(args: argparse.Namespace) -> int:
    rx, ry, rw, rh = _parse_box(args.box)
    frames, _, _ = load_frames_from_file(args.input, auto_downscale_native=not args.keep_scale)
    base_img = frames[args.frame]
    pal_arg = _load_palette_arg(args.palette)
    full_grid, pal_dict = image_to_grid(base_img, palette=pal_arg)
    sub_grid = extract_region_grid(full_grid, rx, ry, rw, rh)
    sub_img = extract_region_image(base_img, rx, ry, rw, rh)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem
    tag = f"{stem}_x{rx}_y{ry}_w{rw}_h{rh}"

    ascii_file = out_dir / f"{tag}.txt"
    json_file = out_dir / f"{tag}.json"
    inspect_file = out_dir / f"{tag}_inspect.png"

    ascii_file.write_text("\n".join(sub_grid) + "\n", encoding="utf-8")
    meta = {
        "source": str(args.input),
        "frame": args.frame,
        "box": [rx, ry, rw, rh],
        "palette": pal_dict,
        "grid": sub_grid,
        "ascii_file": str(ascii_file),
    }
    json_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    sheet = generate_holistic_sheet(
        [sub_img],
        title=f"Region Slice ({rx},{ry},{rw},{rh}) of {stem}",
        palette=pal_dict,
        coord_offset=(rx, ry),
        include_clean_preview=True,
    )
    sheet.save(inspect_file)
    print(f"Extracted region ({rx},{ry},{rw},{rh}):")
    print(f"  - Editable ASCII Grid:      {ascii_file}")
    print(f"  - Patch Metadata + Palette: {json_file}")
    print(f"  - Global-Coord Inspection:  {inspect_file}")
    return 0


def _cmd_region_apply(args: argparse.Namespace) -> int:
    frames, durs, _ = load_frames_from_file(args.base, auto_downscale_native=not args.keep_scale)
    base_img = frames[args.frame]
    patch_path = Path(args.patch)

    pal = _load_palette_arg(args.palette)
    at_xy: Optional[Tuple[int, int]] = _parse_xy(args.at) if args.at else None

    if patch_path.suffix.lower() == ".json":
        pdata = json.loads(patch_path.read_text(encoding="utf-8"))
        if pal is None:
            pal = pdata.get("palette")
        if at_xy is None and "box" in pdata:
            at_xy = (int(pdata["box"][0]), int(pdata["box"][1]))
        txt_ref = pdata.get("ascii_file")
        if txt_ref and Path(txt_ref).is_file() and args.prefer_txt:
            patch_src = Path(txt_ref).read_text(encoding="utf-8")
        else:
            patch_src = pdata["grid"]
        patched_img = patch_region_image(base_img, patch_src, at_xy[0], at_xy[1], palette=pal, mode=args.mode)
    elif patch_path.suffix.lower() in (".png", ".webp", ".gif"):
        if at_xy is None:
            raise ValueError("--at X,Y is required when patching with an image file.")
        p_img = Image.open(patch_path).convert("RGBA")
        patched_img = patch_region_image(base_img, p_img, at_xy[0], at_xy[1], mode=args.mode)
    else:
        if at_xy is None:
            raise ValueError("--at X,Y is required when patching with a plain .txt ASCII file.")
        if pal is None:
            _, pal = image_to_grid(base_img)
        grid_text = patch_path.read_text(encoding="utf-8")
        patched_img = patch_region_image(base_img, grid_text, at_xy[0], at_xy[1], palette=pal, mode=args.mode)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"{Path(args.base).stem}_patched"

    diff_sheet, diff_stats = generate_diff_sheet(base_img, patched_img, title=f"Diff: {name}")
    diff_path = out_dir / f"{name}_diff.png"
    diff_sheet.save(diff_path)

    out_frames = list(frames)
    out_frames[args.frame] = patched_img
    build_pixel_asset(name, out_frames, palette=pal, durations_ms=durs, output_dir=out_dir)
    print(f"  - VISUAL DIFF SHEET: {diff_path} (changed={diff_stats['changed_pixels']}px)")
    return 0


def _cmd_pixelate(args: argparse.Namespace) -> int:
    tw, th = _parse_wh(args.size)
    pal = _load_palette_arg(args.palette)
    name = args.name or f"{Path(args.input).stem}_px{tw}x{th}"
    pixelate_image(
        args.input,
        target_size=(tw, th),
        palette=pal,
        max_colors=args.max_colors,
        mode=args.mode,
        dither_strength=args.dither,
        despeckle=not args.no_despeckle,
        outline_color=args.outline,
        output_dir=args.output_dir,
        name=name,
    )
    return 0


def _cmd_palette(args: argparse.Namespace) -> int:
    result: Dict[str, object] = {}
    if args.input:
        pal = extract_palette(args.input, max_colors=args.max_colors)
        result["extracted_palette"] = pal
        result["hue_ramps"] = analyze_palette_ramps(pal)
    if args.ramp_from:
        result["generated_ramp"] = generate_shading_ramp(args.ramp_from, steps=args.steps)
    text = json.dumps(result, indent=2, ensure_ascii=False)
    print(text)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


def _cmd_recolor(args: argparse.Namespace) -> int:
    pairs = [item.strip() for item in args.map.split(",") if item.strip()]
    cmap: Dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"Expected SRC=DST in --map, got {pair!r}")
        k, v = pair.split("=", 1)
        cmap[k.strip()] = v.strip()

    pal = _load_palette_arg(args.palette)
    frames, durs, _ = load_frames_from_file(args.input, auto_downscale_native=not args.keep_scale)
    recolored = [recolor_image(f, cmap, palette=pal, tolerance=args.tolerance) for f in frames]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or f"{Path(args.input).stem}_recolored"
    diff_sheet, stats = generate_diff_sheet(frames[0], recolored[0], title=f"Recolor Diff: {name}")
    diff_path = out_dir / f"{name}_diff.png"
    diff_sheet.save(diff_path)

    build_pixel_asset(name, recolored, palette=pal, durations_ms=durs, output_dir=out_dir)
    print(f"  - RECOLOR DIFF SHEET: {diff_path} ({stats['changed_pixels']}px changed in Frame 0)")
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    frames, _, _ = load_frames_from_file(args.input, auto_downscale_native=not args.keep_scale)
    rep = lint_frames(frames)
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
    else:
        print(format_lint_report(rep))
    return 0


def _cmd_tile(args: argparse.Namespace) -> int:
    frames, durs, _ = load_frames_from_file(args.input, auto_downscale_native=not args.keep_scale)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem

    sheet, seam_rep = generate_tileset_sheet(frames, title=f"Tile Check: {stem}")
    sheet_path = out_dir / f"{stem}_tile3x3_inspect.png"
    sheet.save(sheet_path)

    if len(frames) > 1:
        tiled_frames = [tile_grid_repeat(f, 3, 3) for f in frames]
        save_rgba_gif(
            [tf.resize((tf.width * 4, tf.height * 4), Image.Resampling.NEAREST) for tf in tiled_frames],
            out_dir / f"{stem}_tile3x3_4x.gif",
            durs,
        )

    print(f"Saved 3x3 Seamless Tile Inspection -> {sheet_path}")
    print(json.dumps(seam_rep, indent=2))
    return 0


def _cmd_nine_slice(args: argparse.Namespace) -> int:
    margins = _parse_box(args.margins)
    target = _parse_wh(args.size)
    src = Image.open(args.input).convert("RGBA")
    panel = render_9slice(src, margins=margins, target_size=target, mode=args.mode)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel.save(out_path)
    print(f"Saved 9-Slice UI Panel ({target[0]}x{target[1]}) -> {out_path}")
    return 0


def _cmd_autotile(args: argparse.Namespace) -> int:
    fg = Image.open(args.fg).convert("RGBA")
    bg = Image.open(args.bg).convert("RGBA")
    name = args.name or f"{Path(args.fg).stem}_on_{Path(args.bg).stem}"
    if args.mode == "blob47":
        bundle = generate_blob47_tileset(
            fg,
            bg,
            outline_color=args.outline if args.outline != "none" else None,
            rim_highlight_color=args.rim_light,
            rim_shadow_color=args.rim_shadow,
        )
    else:
        bundle = generate_wang16_tileset(
            fg,
            bg,
            outline_color=args.outline if args.outline != "none" else None,
            rim_highlight_color=args.rim_light,
            rim_shadow_color=args.rim_shadow,
        )
    smap = Path(args.map).read_text(encoding="utf-8") if args.map else None
    export_autotile_bundle(name, bundle, output_dir=args.output_dir, sample_map=smap)
    return 0


def _cmd_value_check(args: argparse.Namespace) -> int:
    frames, _, _ = load_frames_from_file(args.input, auto_downscale_native=False)
    frame0 = frames[0]
    rep = analyze_scene_readability(frame0, frame0, {})
    sheet = generate_scene_value_sheet(frame0, rep, title=f"Value Check: {Path(args.input).stem}", scale=args.scale)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{Path(args.input).stem}_value_check.png"
    sheet.save(out_path)
    print(f"Saved 4-Panel Value Check Sheet -> {out_path}")
    print(json.dumps({k: v for k, v in rep.items() if not k.startswith("_")}, indent=2))
    return 0


def _cmd_text(args: argparse.Namespace) -> int:
    im = render_pixel_text(
        args.text,
        color=args.color,
        outline=None if args.outline == "none" else args.outline,
        scale=args.scale,
    )
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    print(f"Saved Pixel Text ({im.width}x{im.height}) -> {out_path}")
    return 0


def _cmd_normalmap(args: argparse.Namespace) -> int:
    frames, _, _ = load_frames_from_file(args.input, auto_downscale_native=not args.keep_scale)
    em_cols = [c.strip() for c in args.emit.split(",") if c.strip()] if args.emit else None
    name = args.name or Path(args.input).stem
    export_hd2d_bundle(
        name=name,
        albedo=frames[0],
        emissive_colors=em_cols,
        profile=args.profile,
        bevel_px=args.bevel,
        bump_strength=args.bump,
        output_dir=args.output_dir,
    )
    return 0


def _cmd_autorig(args: argparse.Namespace) -> int:
    cw, ch = _parse_wh(args.canvas)
    pal = _load_palette_arg(args.palette)
    name = args.name or Path(args.input).stem
    autorig_from_concept_sheet(
        args.input,
        name=name,
        canvas_size=(cw, ch),
        part_scale_target=args.part_scale,
        palette=pal,
        assemble_exploded=not args.keep_layout,
        output_dir=args.output_dir,
    )
    return 0


def _cmd_aseprite_inspect(args: argparse.Namespace) -> int:
    doc = read_aseprite(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.input).stem
    sheet_path = out_dir / f"{stem}_layers_inspect.png"
    generate_aseprite_layer_sheet(doc, title=f"Aseprite Binary: {stem}", scale=args.scale).save(sheet_path)

    if args.unpack_layers:
        ldir = out_dir / f"{stem}_layers"
        ldir.mkdir(parents=True, exist_ok=True)
        for l_idx, layer in enumerate(doc.layers):
            safe_name = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in layer["name"])
            for f_idx, fim in enumerate(layer["frames"]):
                fim.save(ldir / f"L{l_idx:02d}_{safe_name}_F{f_idx:02d}.png")

    print(f"Decoded .aseprite [{stem}] -> {sheet_path}")
    print(json.dumps(doc.summary_dict(), indent=2, ensure_ascii=False))
    return 0


def _cmd_print_mcp_config(args: argparse.Namespace) -> int:
    mcp_script = str((_SCRIPTS_DIR / "pforge_mcp.py").resolve())
    cfg = {
        "mcpServers": {
            "pixelforge": {
                "command": sys.executable or "python3",
                "args": [mcp_script],
            }
        }
    }
    txt = json.dumps(cfg, indent=2, ensure_ascii=False)
    print(txt)
    if args.write:
        out_p = Path(args.write)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(txt + "\n", encoding="utf-8")
        print(f"Wrote MCP config -> {out_p}", file=sys.stderr)
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    out_dir = Path(args.output_dir)
    rig = Rig((32, 32), palette="endesga32", outline_mode="selout")
    body = [
        "..CCCCCC..",
        ".CCWWBBBB.",
        "CCWWBBBBBB",
        "BBBBKBBKBB",
        "BBBBKBBKBB",
        "BBBBBBBBBB",
        ".bbbbbbbb.",
    ]
    crown = [
        "Y..Y..Y",
        "YYYYYYY",
        "ooooooo",
    ]
    rig.add_part("body", body, offset=(11, 18), pivot_local=(5, 6), z_index=10, outline_group=0)
    rig.add_part("crown", crown, offset=(12, 14), pivot_local=(3, 2), z_index=20, outline_group=1)

    poses = [
        {},
        {"body": {"scale_x": 1.18, "scale_y": 0.82, "dy": 1}, "crown": {"dy": 2, "angle": -6}},
        {"body": {"scale_x": 0.88, "scale_y": 1.15, "dy": -5}, "crown": {"dy": -7, "angle": 10}},
        {"body": {"dy": -7}, "crown": {"dy": -10, "angle": -8}},
        {"body": {"dy": -2}, "crown": {"dy": -5, "angle": 6}},
        {"body": {"scale_x": 1.14, "scale_y": 0.86, "dy": 1}, "crown": {"dy": 1}},
    ]
    raw_frames = [rig.render_pose(p) for p in poses]
    shadow_widths = [10, 12, 8, 6, 8, 12]
    shadowed = [
        add_ground_shadow(f, baseline_y=25, center_x=16, fixed_width=sw)
        for f, sw in zip(raw_frames, shadow_widths)
    ]
    dust = vfx_dust_puff((32, 32), origin=(16, 25), direction="both")
    final_frames = composite_vfx(shadowed, dust, start_frame=1, under=True)

    build_pixel_asset(
        "king_slime_demo",
        final_frames,
        palette="endesga32",
        durations_ms=[220, 110, 80, 140, 80, 130],
        baseline_y=25,
        pivots=rig.get_canvas_pivots(),
        output_dir=out_dir,
    )
    return 0


def build_cli_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pforge",
        description="PixelForge CLI: Multimodal Pixel Art Creation, Editing, Pixelation & Inspection Suite.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # inspect
    s_ins = sub.add_parser("inspect", help="Generate Holistic Inspection Sheet + Lint report for any image/GIF.")
    s_ins.add_argument("input", help="Path to PNG / GIF / APNG / WebP / Spritesheet")
    s_ins.add_argument("-o", "--output-dir", default="output/inspect")
    s_ins.add_argument("--scale", type=int, default=None)
    s_ins.add_argument("--frame-size", default=None, help="Slice spritesheet by WxH (e.g. 32x32)")
    s_ins.add_argument("--cols", type=int, default=None)
    s_ins.add_argument("--rows", type=int, default=None)
    s_ins.add_argument("--keep-scale", action="store_true", help="Disable auto native downscaling of 4x/8x previews")
    s_ins.set_defaults(func=_cmd_inspect)

    # decompile
    s_dec = sub.add_parser("decompile", help="Reverse-decompile PNG/GIF/Spritesheet into editable ASCII + Python script.")
    s_dec.add_argument("input")
    s_dec.add_argument("-o", "--output-dir", default="output/decompiled")
    s_dec.add_argument("--name", default=None)
    s_dec.add_argument("--frame-size", default=None)
    s_dec.add_argument("--cols", type=int, default=None)
    s_dec.add_argument("--rows", type=int, default=None)
    s_dec.add_argument("--palette", default="auto", help="Built-in palette name, JSON path, or 'auto'")
    s_dec.add_argument("--max-colors", type=int, default=48)
    s_dec.add_argument("--keep-scale", action="store_true")
    s_dec.set_defaults(func=_cmd_decompile)

    # region-extract
    s_re = sub.add_parser("region-extract", help="Slice a (X,Y,W,H) sub-region for surgical editing on large sprites.")
    s_re.add_argument("input")
    s_re.add_argument("--box", required=True, help="X,Y,W,H (0-based coordinates)")
    s_re.add_argument("--frame", type=int, default=0)
    s_re.add_argument("--palette", default="auto")
    s_re.add_argument("--keep-scale", action="store_true")
    s_re.add_argument("-o", "--output-dir", default="output/patches")
    s_re.set_defaults(func=_cmd_region_extract)

    # region-apply
    s_ra = sub.add_parser("region-apply", help="Write an edited ASCII/PNG region back and generate a Visual Diff sheet.")
    s_ra.add_argument("base", help="Base PNG/GIF/WebP file")
    s_ra.add_argument("--patch", required=True, help="Edited .txt, .json, or .png patch")
    s_ra.add_argument("--at", default=None, help="X,Y target coordinate (auto-read if --patch is .json)")
    s_ra.add_argument("--frame", type=int, default=0)
    s_ra.add_argument("--mode", choices=["replace", "alpha_over"], default="replace")
    s_ra.add_argument("--palette", default=None)
    s_ra.add_argument("--prefer-txt", action="store_true", default=True)
    s_ra.add_argument("--name", default=None)
    s_ra.add_argument("--keep-scale", action="store_true")
    s_ra.add_argument("-o", "--output-dir", default="output/patched")
    s_ra.set_defaults(func=_cmd_region_apply)

    # pixelate
    s_px = sub.add_parser("pixelate", help="Convert high-res or AI draft image into clean, palette-locked pixel art.")
    s_px.add_argument("input")
    s_px.add_argument("--size", default="48x48", help="Target WxH (e.g. 32x32, 64x64)")
    s_px.add_argument("--palette", default="endesga32", help="endesga32|pico8|sweetie16|resurrect64|gameboy|auto")
    s_px.add_argument("--max-colors", type=int, default=24)
    s_px.add_argument("--mode", choices=["contrast_box", "dominant_block"], default="contrast_box")
    s_px.add_argument("--dither", type=float, default=0.0, help="Bayer 2x2 dither strength [0.0..0.4]")
    s_px.add_argument("--outline", default=None, help="Optional outer outline hex (e.g. #181425)")
    s_px.add_argument("--no-despeckle", action="store_true")
    s_px.add_argument("--name", default=None)
    s_px.add_argument("-o", "--output-dir", default="output/pixelated")
    s_px.set_defaults(func=_cmd_pixelate)

    # palette
    s_pal = sub.add_parser("palette", help="Extract palette & shading ramps from an image or generate hue-shifted ramps.")
    s_pal.add_argument("input", nargs="?", default=None, help="Optional reference image")
    s_pal.add_argument("--max-colors", type=int, default=32)
    s_pal.add_argument("--ramp-from", default=None, help="Base hex color (e.g. #E43B44) to generate a shading ramp")
    s_pal.add_argument("--steps", type=int, default=4)
    s_pal.add_argument("-o", "--output", default=None)
    s_pal.set_defaults(func=_cmd_palette)

    # recolor
    s_rec = sub.add_parser("recolor", help="Swap colors/ramps across static or animated sprites with Diff verification.")
    s_rec.add_argument("input")
    s_rec.add_argument("--map", required=True, help="Comma-separated swaps, e.g. R=B,r=b or #E43B44=#0099DB")
    s_rec.add_argument("--palette", default="endesga32")
    s_rec.add_argument("--tolerance", type=int, default=0)
    s_rec.add_argument("--name", default=None)
    s_rec.add_argument("--keep-scale", action="store_true")
    s_rec.add_argument("-o", "--output-dir", default="output/recolored")
    s_rec.set_defaults(func=_cmd_recolor)

    # lint
    s_lnt = sub.add_parser("lint", help="Run automated Pixel Linter diagnostics.")
    s_lnt.add_argument("input")
    s_lnt.add_argument("--json", action="store_true")
    s_lnt.add_argument("--keep-scale", action="store_true")
    s_lnt.set_defaults(func=_cmd_lint)

    # tile
    s_til = sub.add_parser("tile", help="Verify seamless 3x3 tiling & edge continuity.")
    s_til.add_argument("input")
    s_til.add_argument("--keep-scale", action="store_true")
    s_til.add_argument("-o", "--output-dir", default="output/tiles")
    s_til.set_defaults(func=_cmd_tile)

    # nine-slice
    s_ns = sub.add_parser("nine-slice", help="Expand a 9-slice UI border frame to target WxH.")
    s_ns.add_argument("input")
    s_ns.add_argument("--margins", required=True, help="Left,Top,Right,Bottom (e.g. 4,4,4,4)")
    s_ns.add_argument("--size", required=True, help="Target WxH (e.g. 160x56)")
    s_ns.add_argument("--mode", choices=["tile", "stretch"], default="tile")
    s_ns.add_argument("-o", "--output", default="output/ui_panel.png")
    s_ns.set_defaults(func=_cmd_nine_slice)

    # autotile
    s_at = sub.add_parser("autotile", help="Synthesize 47-tile Blob or 16-tile Wang Auto-Tileset + Mock Map.")
    s_at.add_argument("--fg", required=True, help="Foreground seamless tile PNG")
    s_at.add_argument("--bg", required=True, help="Background seamless tile PNG")
    s_at.add_argument("--mode", choices=["blob47", "wang16"], default="blob47")
    s_at.add_argument("--outline", default="#181425", help="Border outline color or 'none'")
    s_at.add_argument("--rim-light", default=None, help="Top-left rim highlight hex")
    s_at.add_argument("--rim-shadow", default=None, help="Bottom-right cliff/lip shadow hex")
    s_at.add_argument("--map", default=None, help="Optional ASCII map .txt file ('#'=fg, '.'=bg)")
    s_at.add_argument("--name", default=None)
    s_at.add_argument("-o", "--output-dir", default="output/autotile")
    s_at.set_defaults(func=_cmd_autotile)

    # value-check
    s_vc = sub.add_parser("value-check", help="Generate Grayscale + 3-Slab Value Posterization check for any scene/sprite.")
    s_vc.add_argument("input")
    s_vc.add_argument("--scale", type=int, default=2)
    s_vc.add_argument("-o", "--output-dir", default="output/value_check")
    s_vc.set_defaults(func=_cmd_value_check)

    # text
    s_tx = sub.add_parser("text", help="Render crisp 3x5 retro pixel bitmap text PNG.")
    s_tx.add_argument("text")
    s_tx.add_argument("--color", default="#FFFFFF")
    s_tx.add_argument("--outline", default="#181425", help="Outline hex or 'none'")
    s_tx.add_argument("--scale", type=int, default=2)
    s_tx.add_argument("-o", "--output", default="output/pixel_text.png")
    s_tx.set_defaults(func=_cmd_text)

    # normalmap
    s_nm = sub.add_parser("normalmap", help="Generate HD-2D Normal Map + Emission Mask + 360 Torch Orbit GIF.")
    s_nm.add_argument("input")
    s_nm.add_argument("--profile", choices=["dome", "bevel", "ridge"], default="dome")
    s_nm.add_argument("--bevel", type=float, default=4.5)
    s_nm.add_argument("--bump", type=float, default=2.2)
    s_nm.add_argument("--emit", default=None, help="Comma-separated emissive hex colors, e.g. #2CE8F5,#FEE761")
    s_nm.add_argument("--name", default=None)
    s_nm.add_argument("--keep-scale", action="store_true")
    s_nm.add_argument("-o", "--output-dir", default="output/hd2d")
    s_nm.set_defaults(func=_cmd_normalmap)

    # autorig
    s_ar = sub.add_parser("autorig", help="Segment exploded AI/concept sheet into pixel parts + articulated Rig.")
    s_ar.add_argument("input")
    s_ar.add_argument("--canvas", default="56x56", help="Assembled stage WxH (e.g. 56x56)")
    s_ar.add_argument("--part-scale", type=int, default=42, help="Target pixel span across segmented parts")
    s_ar.add_argument("--palette", default="endesga32", help="endesga32|sweetie16|pico8|resurrect64|auto")
    s_ar.add_argument("--keep-layout", action="store_true", help="Do not dock exploded parts onto torso sockets")
    s_ar.add_argument("--name", default=None)
    s_ar.add_argument("-o", "--output-dir", default="output/autorig")
    s_ar.set_defaults(func=_cmd_autorig)

    # aseprite-inspect
    s_ase = sub.add_parser("aseprite-inspect", help="Decode a binary .aseprite file and render its Layer/Timeline matrix.")
    s_ase.add_argument("input", help="Path to .ase or .aseprite file")
    s_ase.add_argument("--scale", type=int, default=3)
    s_ase.add_argument("--unpack-layers", action="store_true", help="Export individual layer cel PNGs")
    s_ase.add_argument("-o", "--output-dir", default="output/aseprite_inspect")
    s_ase.set_defaults(func=_cmd_aseprite_inspect)

    # print-mcp-config
    s_mcp = sub.add_parser("print-mcp-config", help="Print or write ready-to-use mcp_config.json for PixelForge MCP Server.")
    s_mcp.add_argument("--write", default=None, help="Optional path to write mcp_config.json")
    s_mcp.set_defaults(func=_cmd_print_mcp_config)

    # demo
    s_dem = sub.add_parser("demo", help="Run built-in King Slime rig + Sel-out + VFX showcase.")
    s_dem.add_argument("-o", "--output-dir", default="output/demo")
    s_dem.set_defaults(func=_cmd_demo)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
