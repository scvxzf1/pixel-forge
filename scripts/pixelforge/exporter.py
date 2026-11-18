"""Export pipeline for PixelForge:
- Static & Multi-row Sprite Sheets (PNG)
- Variable-duration GIF (1-bit binary alpha, index 0 reserved, disposal=2)
- Variable-duration APNG (full 8-bit alpha translucency)
- Variable-duration Lossless WebP (full 8-bit alpha translucency, compact size)
- Aseprite-compatible JSON Atlas (`frames`, `meta.frameTags`, `meta.slices`)
- Automated Pixel Linter + Holistic Inspection Sheet generation
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from PIL import Image, PngImagePlugin

from .aseprite_io import write_aseprite
from .canvas import GridLike, render_grid
from .inspector import generate_holistic_sheet
from .linter import format_lint_report, lint_frames
from .palette import ColorDef, img_pixels
from .rig import AnimationClip, SpriteActor


def _validate_asset_name(name: str) -> None:
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError(f"Invalid asset name {name!r}: must be a single filename stem.")


def save_rgba_gif(
    frames: Sequence[Image.Image],
    target: Union[str, Path],
    durations_ms: Sequence[int],
    loop: int = 0,
) -> List[int]:
    """Save RGBA frames to GIF89a with index 0 strictly reserved for transparency (alpha < 128)."""
    if not frames:
        raise ValueError("frames must not be empty")
    gif_durs = [max(20, round(d / 10.0) * 10) for d in durations_ms]

    encoded: List[Image.Image] = []
    for f in frames:
        rgba = f.convert("RGBA")
        quant = rgba.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        raw_pal = (quant.getpalette() or [])[: 255 * 3]
        if len(raw_pal) < 255 * 3:
            raw_pal = raw_pal + [0] * (255 * 3 - len(raw_pal))
        p_img = Image.new("P", rgba.size)
        p_img.putpalette([0, 0, 0] + raw_pal)
        p_img.putdata([
            (q + 1) if a >= 128 else 0
            for q, a in zip(img_pixels(quant), img_pixels(rgba.getchannel("A")))
        ])
        encoded.append(p_img)

    encoded[0].save(
        target,
        format="GIF",
        save_all=True,
        append_images=encoded[1:],
        duration=gif_durs if len(gif_durs) > 1 else gif_durs[0],
        loop=loop,
        disposal=2,
        transparency=0,
        optimize=False,
    )
    return gif_durs


def save_apng(
    frames: Sequence[Image.Image],
    target: Union[str, Path],
    durations_ms: Sequence[int],
    loop: int = 0,
) -> None:
    """Save full 8-bit RGBA animated PNG (APNG) with clean frame background disposal."""
    rgba_frames = [f.convert("RGBA") for f in frames]
    if len(rgba_frames) == 1:
        rgba_frames[0].save(target, format="PNG")
        return
    rgba_frames[0].save(
        target,
        format="PNG",
        save_all=True,
        append_images=rgba_frames[1:],
        duration=list(durations_ms),
        loop=loop,
        disposal=PngImagePlugin.Disposal.OP_BACKGROUND,
    )


def save_animated_webp(
    frames: Sequence[Image.Image],
    target: Union[str, Path],
    durations_ms: Sequence[int],
    loop: int = 0,
) -> None:
    """Save full 8-bit RGBA lossless animated WebP."""
    rgba_frames = [f.convert("RGBA") for f in frames]
    if len(rgba_frames) == 1:
        rgba_frames[0].save(target, format="WEBP", lossless=True, exact=True, quality=100)
        return
    rgba_frames[0].save(
        target,
        format="WEBP",
        save_all=True,
        append_images=rgba_frames[1:],
        duration=list(durations_ms),
        loop=loop,
        lossless=True,
        exact=True,
        quality=100,
    )


def build_aseprite_atlas_json(
    image_filename: str,
    sheet_size: Tuple[int, int],
    entries: Sequence[Dict[str, Any]],
    frame_tags: Sequence[Dict[str, Any]],
    slices: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build standard Aseprite JSON Array metadata compatible with Godot / Phaser / Unity / PixiJS."""
    frames_arr = []
    for ent in entries:
        x, y, w, h = ent["x"], ent["y"], ent["w"], ent["h"]
        frames_arr.append({
            "filename": ent["name"],
            "frame": {"x": x, "y": y, "w": w, "h": h},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
            "sourceSize": {"w": w, "h": h},
            "duration": ent["duration"],
        })

    return {
        "frames": frames_arr,
        "meta": {
            "app": "PixelForge",
            "version": "1.0",
            "image": image_filename,
            "format": "RGBA8888",
            "size": {"w": sheet_size[0], "h": sheet_size[1]},
            "scale": "1",
            "frameTags": list(frame_tags),
            "slices": list(slices or []),
        },
    }


def build_pixel_asset(
    name: str,
    frames: Sequence[Union[Image.Image, GridLike]],
    palette: Union[str, Dict[str, ColorDef], None] = "endesga32",
    durations_ms: Optional[Union[int, Sequence[int]]] = None,
    fps: int = 8,
    preview_scale: int = 8,
    inspect_scale: Optional[int] = None,
    baseline_y: Optional[int] = None,
    pivots: Optional[Sequence[Tuple[float, float]]] = None,
    nine_slice_margins: Optional[Tuple[int, int, int, int]] = None,
    named_layers: Optional[Sequence[Tuple[str, Sequence[Optional[Image.Image]]]]] = None,
    formats: Sequence[str] = ("gif", "apng", "webp", "aseprite"),
    output_dir: Union[str, Path] = "output",
) -> Dict[str, Any]:
    """Render, lint, inspect, and export a static or animated pixel-art asset."""
    _validate_asset_name(name)
    if preview_scale < 1:
        raise ValueError("preview_scale must be >= 1")

    clip = AnimationClip.create(
        name=name,
        frames=frames,
        palette=palette,
        durations_ms=durations_ms,
        fps=fps,
    )
    rendered = clip.frames
    durs = clip.durations_ms
    fw, fh = rendered[0].size

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Run automated Pixel Linter
    lint_rep = lint_frames(rendered)

    # 2. Generate Holistic Multimodal Inspection Sheet
    inspect_img = generate_holistic_sheet(
        rendered,
        title=name,
        palette=palette,
        durations_ms=durs,
        scale=inspect_scale,
        baseline_y=baseline_y,
        pivots=pivots,
    )
    inspect_file = out / f"{name}_inspect.png"
    inspect_img.save(inspect_file)

    files: Dict[str, str] = {
        "inspect_sheet": str(inspect_file),
    }

    # 3. Export Sprite Sheet + Static Frame 0 PNGs
    sheet_img = Image.new("RGBA", (fw * len(rendered), fh), (0, 0, 0, 0))
    atlas_entries = []
    for idx, f in enumerate(rendered):
        sheet_img.paste(f, (idx * fw, 0))
        atlas_entries.append({
            "name": f"{name} #{idx}",
            "x": idx * fw,
            "y": 0,
            "w": fw,
            "h": fh,
            "duration": durs[idx],
        })

    spritesheet_file = out / f"{name}_spritesheet.png"
    sheet_img.save(spritesheet_file)
    files["spritesheet"] = str(spritesheet_file)

    png_1x = out / f"{name}.png"
    png_scaled = out / f"{name}_{preview_scale}x.png"
    rendered[0].save(png_1x)
    rendered[0].resize((fw * preview_scale, fh * preview_scale), Image.Resampling.NEAREST).save(png_scaled)
    files["png_1x"] = str(png_1x)
    files["png_scaled"] = str(png_scaled)

    # 4. Export Animated Formats (GIF, APNG, Lossless WebP)
    scaled_frames = [
        f.resize((fw * preview_scale, fh * preview_scale), Image.Resampling.NEAREST)
        for f in rendered
    ]
    fmt_set = {f.lower() for f in formats}
    gif_durs = durs

    if "gif" in fmt_set:
        gif_1x = out / f"{name}.gif"
        gif_sc = out / f"{name}_{preview_scale}x.gif"
        gif_durs = save_rgba_gif(rendered, gif_1x, durs)
        save_rgba_gif(scaled_frames, gif_sc, durs)
        files["gif_1x"] = str(gif_1x)
        files["gif_scaled"] = str(gif_sc)

    if "apng" in fmt_set and len(rendered) > 1:
        apng_1x = out / f"{name}.apng"
        apng_sc = out / f"{name}_{preview_scale}x.apng"
        save_apng(rendered, apng_1x, durs)
        save_apng(scaled_frames, apng_sc, durs)
        files["apng_1x"] = str(apng_1x)
        files["apng_scaled"] = str(apng_sc)

    if "webp" in fmt_set:
        webp_1x = out / f"{name}.webp"
        webp_sc = out / f"{name}_{preview_scale}x.webp"
        save_animated_webp(rendered, webp_1x, durs)
        save_animated_webp(scaled_frames, webp_sc, durs)
        files["webp_1x"] = str(webp_1x)
        files["webp_scaled"] = str(webp_sc)

    if "aseprite" in fmt_set:
        ase_file = out / f"{name}.aseprite"
        ase_layers = list(named_layers) if named_layers is not None else [("Layer 1", rendered)]
        piv_dict = {str(i): p for i, p in enumerate(pivots)} if pivots else None
        write_aseprite(
            ase_file,
            canvas_size=(fw, fh),
            layers=ase_layers,
            durations_ms=durs,
            palette=palette,
            frame_tags=[{"name": "default", "from": 0, "to": len(rendered) - 1, "direction": "forward"}] if len(rendered) > 1 else None,
            nine_slice_margins=nine_slice_margins,
            pivots=piv_dict,
        )
        files["aseprite"] = str(ase_file)

    # 5. Export Aseprite-compatible JSON Atlas + Meta JSON
    slices_meta = []
    if nine_slice_margins is not None:
        ml, mt, mr, mb = nine_slice_margins
        slices_meta.append({
            "name": "9slice_center",
            "color": "#0000ffff",
            "keys": [{
                "frame": 0,
                "bounds": {"x": 0, "y": 0, "w": fw, "h": fh},
                "center": {"x": ml, "y": mt, "w": fw - ml - mr, "h": fh - mt - mb},
            }],
        })

    atlas_json = build_aseprite_atlas_json(
        image_filename=spritesheet_file.name,
        sheet_size=sheet_img.size,
        entries=atlas_entries,
        frame_tags=[{"name": "default", "from": 0, "to": len(rendered) - 1, "direction": "forward"}],
        slices=slices_meta,
    )
    atlas_file = out / f"{name}_atlas.json"
    atlas_file.write_text(json.dumps(atlas_json, indent=2, ensure_ascii=False), encoding="utf-8")
    files["atlas_json"] = str(atlas_file)

    meta = {
        "name": name,
        "frame_width": fw,
        "frame_height": fh,
        "frame_count": len(rendered),
        "durations_ms": durs,
        "gif_durations_ms": gif_durs,
        "lint": lint_rep,
        "files": files,
    }
    meta_file = out / f"{name}_meta.json"
    meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    files["meta_json"] = str(meta_file)

    print(f"Built [{name}] ({fw}x{fh}, {len(rendered)} frame(s)):")
    print(f"  - VIEW INSPECTION SHEET: {inspect_file}")
    print("  - " + format_lint_report(lint_rep).replace("\n", "\n    "))
    return meta


def build_actor_assets(
    actor: SpriteActor,
    output_dir: Union[str, Path] = "output",
    preview_scale: int = 8,
    inspect_scale: Optional[int] = None,
    pivots: Optional[Sequence[Tuple[float, float]]] = None,
    named_layers_by_clip: Optional[Mapping[str, Sequence[Tuple[str, Sequence[Optional[Image.Image]]]]]] = None,
    formats: Sequence[str] = ("gif", "apng", "webp", "aseprite"),
) -> Dict[str, Any]:
    """Export all AnimationClips of a multi-action `SpriteActor` plus a combined Atlas & JSON."""
    _validate_asset_name(actor.name)
    if not actor.clips:
        raise ValueError(f"SpriteActor {actor.name!r} has no animation clips.")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    clip_List = list(actor.clips.values())
    fw, fh = clip_List[0].frames[0].size
    max_len = max(len(c.frames) for c in clip_List)
    atlas_img = Image.new("RGBA", (fw * max_len, fh * len(clip_List)), (0, 0, 0, 0))

    atlas_entries: List[Dict[str, Any]] = []
    frame_tags: List[Dict[str, Any]] = []
    clip_summaries: Dict[str, Any] = {}
    global_idx = 0

    for row_idx, clip in enumerate(clip_List):
        clip_asset_name = f"{actor.name}_{clip.name}"
        clip_layers = named_layers_by_clip.get(clip.name) if named_layers_by_clip else None
        clip_meta = build_pixel_asset(
            name=clip_asset_name,
            frames=clip.frames,
            palette=actor.palette,
            durations_ms=clip.durations_ms,
            preview_scale=preview_scale,
            inspect_scale=inspect_scale,
            pivots=pivots,
            named_layers=clip_layers,
            formats=formats,
            output_dir=out,
        )
        clip_summaries[clip.name] = clip_meta

        tag_start = global_idx
        for col_idx, f in enumerate(clip.frames):
            atlas_img.paste(f, (col_idx * fw, row_idx * fh))
            atlas_entries.append({
                "name": f"{actor.name} ({clip.name}) #{col_idx}",
                "x": col_idx * fw,
                "y": row_idx * fh,
                "w": fw,
                "h": fh,
                "duration": clip.durations_ms[col_idx],
            })
            global_idx += 1

        frame_tags.append({
            "name": clip.name,
            "from": tag_start,
            "to": global_idx - 1,
            "direction": clip.direction,
        })

    atlas_png = out / f"{actor.name}_master_atlas.png"
    atlas_img.save(atlas_png)

    atlas_json_path = out / f"{actor.name}_master_atlas.json"
    atlas_data = build_aseprite_atlas_json(
        image_filename=atlas_png.name,
        sheet_size=atlas_img.size,
        entries=atlas_entries,
        frame_tags=frame_tags,
    )
    atlas_json_path.write_text(json.dumps(atlas_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Master scaled atlas preview for quick overview
    atlas_scaled_png = out / f"{actor.name}_master_atlas_{preview_scale}x.png"
    atlas_img.resize(
        (atlas_img.width * preview_scale, atlas_img.height * preview_scale),
        Image.Resampling.NEAREST,
    ).save(atlas_scaled_png)

    master_ase_path: Optional[Path] = None
    if "aseprite" in {f.lower() for f in formats}:
        master_ase_path = out / f"{actor.name}_master.aseprite"
        all_durs = [d for c in clip_List for d in c.durations_ms]
        if named_layers_by_clip and all(c.name in named_layers_by_clip for c in clip_List):
            layer_names_order: List[str] = []
            for c in clip_List:
                for lname, _ in named_layers_by_clip[c.name]:
                    if lname not in layer_names_order:
                        layer_names_order.append(lname)
            merged_layers: List[Tuple[str, List[Optional[Image.Image]]]] = []
            for lname in layer_names_order:
                cat_frames: List[Optional[Image.Image]] = []
                for c in clip_List:
                    cmap = dict(named_layers_by_clip[c.name])
                    if lname in cmap:
                        cat_frames.extend(cmap[lname])
                    else:
                        cat_frames.extend([None] * len(c.frames))
                merged_layers.append((lname, cat_frames))
        else:
            all_flat = [f for c in clip_List for f in c.frames]
            merged_layers = [("Actor", all_flat)]

        piv_dict = {str(i): p for i, p in enumerate(pivots)} if pivots else None
        write_aseprite(
            master_ase_path,
            canvas_size=(fw, fh),
            layers=merged_layers,
            durations_ms=all_durs,
            palette=actor.palette,
            frame_tags=frame_tags,
            pivots=piv_dict,
        )

    print(f"Built Multi-Action Actor [{actor.name}] ({len(clip_List)} clips -> {atlas_png})")
    res_out: Dict[str, Any] = {
        "actor": actor.name,
        "clips": clip_summaries,
        "master_atlas_png": str(atlas_png),
        "master_atlas_scaled_png": str(atlas_scaled_png),
        "master_atlas_json": str(atlas_json_path),
    }
    if master_ase_path is not None:
        res_out["master_aseprite"] = str(master_ase_path)
    return res_out
