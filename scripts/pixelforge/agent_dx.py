"""Agent Developer Experience (DX) & Zero-Friction Ergonomics for Vision LLMs:
1. `format_palette_guide`: Instant single-char semantic palette & shading ramp cheat-sheet.
2. `build_agent_checklist`: Translates Linter / Readability diagnostics into concrete (x, y) fix recipes.
3. `build_from_spec`: Declarative JSON/dict builder for both ASCII sprites and multi-part/multi-clip
   rigged `.aseprite` characters (with auto canvas sizing, ragged row healing, semantic part docking,
   1-line motion presets, and optional HD-2D normal map export).
4. `scaffold_script`: Generates ready-to-run Python templates (`rig`, `sprite`, `scene`, `iso`) with
   portable relative `sys.path` wiring.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from PIL import Image

from .aseprite_io import generate_aseprite_layer_sheet, read_aseprite
from .canvas import GridLike, normalize_grid
from .exporter import build_actor_assets, build_pixel_asset
from .lighting import export_hd2d_bundle
from .palette import (
    BUILTIN_PALETTES,
    ColorDef,
    analyze_palette_ramps,
    canonical_char_map,
    extract_palette,
    get_palette,
    luminance,
    rgba_to_hex,
)
from .rig import Part, Rig, SpriteActor
from .transform import add_ground_shadow, auto_outline, selective_outline


def format_palette_guide(
    palette: Union[str, Dict[str, ColorDef], Path, None] = "endesga32",
    max_colors: int = 32,
) -> Dict[str, Any]:
    """Return a structured + human/LLM-readable single-char palette & shading ramp cheat-sheet."""
    pal_label = "endesga32"
    resolved_dict: Dict[str, ColorDef]

    if palette is None:
        resolved_dict = dict(BUILTIN_PALETTES["endesga32"])
    elif isinstance(palette, Path) or (isinstance(palette, str) and Path(palette).is_file()):
        p_path = Path(palette)
        pal_label = f"extracted:{p_path.name}"
        resolved_dict = extract_palette(p_path, max_colors=max_colors)
    elif isinstance(palette, str):
        key = palette.strip().lower().replace("-", "").replace("_", "")
        if key not in BUILTIN_PALETTES:
            raise ValueError(
                f"Unknown built-in palette {palette!r} (and file not found). "
                f"Built-in choices: {sorted(BUILTIN_PALETTES)}"
            )
        pal_label = key
        resolved_dict = dict(BUILTIN_PALETTES[key])
    elif isinstance(palette, Mapping):
        pal_label = "custom"
        resolved_dict = dict(palette)
    else:
        raise TypeError(f"Unsupported palette type: {type(palette).__name__}")

    rev = canonical_char_map(resolved_dict)
    opaque_items = [(col, ch) for col, ch in rev.items() if col[3] > 0]
    opaque_items.sort(key=lambda item: luminance(item[0]))

    darkest = opaque_items[0] if opaque_items else ((24, 20, 37, 255), "K")
    brightest = opaque_items[-1] if opaque_items else ((255, 255, 255, 255), "W")
    ramps = analyze_palette_ramps(resolved_dict)

    lines = [
        f"Palette [{pal_label}] ({len(opaque_items)} opaque colors; '.' or ' ' = transparent)",
        f"  Darkest Outline : {darkest[1]!r} ({rgba_to_hex(darkest[0])}) | "
        f"Brightest Highlight : {brightest[1]!r} ({rgba_to_hex(brightest[0])})",
        "  Hue Shading Ramps (Shadow -> Midtone -> Highlight):",
    ]
    for fam, entries in ramps.items():
        chain = " -> ".join(f"{e['char']!r}({e['hex']})" for e in entries)
        lines.append(f"    [{fam:<18}] {chain}")

    char_to_hex = {ch: rgba_to_hex(col) for col, ch in opaque_items}
    return {
        "palette_name": pal_label,
        "color_count": len(opaque_items),
        "transparent_chars": [".", " "],
        "darkest_outline": {"char": darkest[1], "hex": rgba_to_hex(darkest[0])},
        "brightest_highlight": {"char": brightest[1], "hex": rgba_to_hex(brightest[0])},
        "char_to_hex": char_to_hex,
        "ramps": ramps,
        "cheat_sheet": "\n".join(lines),
    }


_ISSUE_FIX_RECIPES: Dict[str, str] = {
    "outline_gap": (
        "Bright interior pixel touches transparent background; seal with dark outline char "
        "(e.g. 'K') or set outline_mode='selout'."
    ),
    "stray_specks": (
        "Isolated 1px floating speck detached from silhouette; replace with '.' or run clean_orphan_specks()."
    ),
    "orphan_noise": (
        "Single-pixel interior noise dots; group shading into >=2px clusters (avoid random checkerboard)."
    ),
    "dirty_palette": (
        "Too many unique colors (>64), likely from anti-aliased resize; run pixelate_image() with a locked palette."
    ),
    "silhouette_jaggies": (
        "Broken staircase rhythm (e.g. 2-1-2) on outer contour; smooth step run-lengths monotonically."
    ),
    "volume_spike": (
        "Large opaque pixel mass jump (>30%) between adjacent frames "
        "(expected on slash/explosion VFX frames; otherwise check squash/stretch conservation)."
    ),
    "duplicate_adjacent_frame": (
        "Identical consecutive frames; merge them and add their time to durations_ms."
    ),
    "empty_frame": "Frame has 0 opaque pixels; verify part visibility or grid characters.",
}


def build_agent_checklist(
    must_view_files: Sequence[Union[str, Path]],
    lint_report: Optional[Mapping[str, Any]] = None,
    auto_fixes: Optional[Sequence[str]] = None,
    readability: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an actionable multimodal QA checklist for Vision LLM Agents."""
    view_list = [str(p) for p in must_view_files if p]
    fixes: List[str] = []
    warn_count = 0

    if lint_report:
        warn_count += int(lint_report.get("warning_count", 0))
        for iss in lint_report.get("issues", []):
            code = str(iss.get("code", ""))
            sev = str(iss.get("severity", "info")).upper()
            f_idx = iss.get("frame", 0)
            coords = iss.get("coords", [])
            coord_txt = ""
            if coords:
                pts = ", ".join(f"({c[0]},{c[1]})" for c in coords[:5])
                if len(coords) > 5:
                    pts += ", ..."
                coord_txt = f" @ {pts}"
            recipe = _ISSUE_FIX_RECIPES.get(code, str(iss.get("message", "")))
            fixes.append(f"[{sev}] Frame {f_idx} `{code}`{coord_txt}: {recipe}")

    if readability:
        for w_msg in readability.get("warnings", []):
            warn_count += 1
            fixes.append(
                f"[WARN] Scene Readability: {w_msg} -> Increase foreground/background luminance slab gap "
                "(darken floor mortar, add ground shadow, or add selective rim highlight)."
            )

    healed = list(auto_fixes or [])
    status = "READY_AFTER_VISUAL_CHECK" if warn_count == 0 else "NEEDS_REFINEMENT"
    return {
        "status": status,
        "warning_count": warn_count,
        "must_view_images": view_list,
        "visual_verification_rule": (
            "MANDATORY: Open every file in `must_view_images` with your vision/read_file tool to verify "
            "silhouette, eye/weapon clarity on both dark & light backgrounds, and baseline stability before delivery."
        ),
        "auto_healed": healed,
        "actionable_fixes": fixes,
    }


def _collect_part_source_and_notes(
    part_spec: Mapping[str, Any],
    part_name: str,
    pad_ragged: bool,
) -> Tuple[Any, List[str]]:
    notes: List[str] = []
    if "variants" in part_spec and isinstance(part_spec["variants"], Mapping):
        out_vars: Dict[str, List[str]] = {}
        for v_name, v_grid in part_spec["variants"].items():
            if pad_ragged:
                lines, p_notes = normalize_grid(v_grid)
                out_vars[str(v_name)] = lines
                notes.extend(f"Part {part_name!r}[{v_name}] {n}" for n in p_notes)
            else:
                out_vars[str(v_name)] = v_grid
        return out_vars, notes

    raw = part_spec.get("grid", part_spec.get("source"))
    if raw is None:
        raise ValueError(f"Part {part_name!r} must define 'grid', 'source', or 'variants'.")
    if isinstance(raw, Image.Image):
        return raw, notes
    if pad_ragged:
        lines, p_notes = normalize_grid(raw)
        notes.extend(f"Part {part_name!r} {n}" for n in p_notes)
        return lines, notes
    return raw, notes


def _populate_rig_parts(
    rig: Rig,
    parts_spec: Sequence[Mapping[str, Any]],
    pad_ragged: bool,
) -> List[str]:
    all_notes: List[str] = []
    for idx, p_spec in enumerate(parts_spec):
        pname = str(p_spec["name"])
        src, p_notes = _collect_part_source_and_notes(p_spec, pname, pad_ragged=pad_ragged)
        all_notes.extend(p_notes)

        offset = tuple(int(v) for v in p_spec["offset"]) if p_spec.get("offset") is not None else None
        piv_loc = tuple(float(v) for v in p_spec["pivot_local"]) if p_spec.get("pivot_local") is not None else None
        piv_can = tuple(float(v) for v in p_spec["pivot_canvas"]) if p_spec.get("pivot_canvas") is not None else None
        nudge = tuple(int(v) for v in p_spec.get("nudge", (0, 0)))

        # Default first part to `at='center'` when neither offset nor attach_to nor at is given
        at_val = p_spec.get("at")
        if offset is None and p_spec.get("attach_to") is None and at_val is None and idx == 0:
            at_val = "center"

        rig.add_part(
            name=pname,
            source=src,  # type: ignore[arg-type]
            offset=offset,  # type: ignore[arg-type]
            pivot_local=piv_loc,  # type: ignore[arg-type]
            pivot_canvas=piv_can,  # type: ignore[arg-type]
            z_index=int(p_spec.get("z_index", idx * 10)),
            outline_group=p_spec.get("outline_group", 0),
            at=at_val,
            attach_to=p_spec.get("attach_to"),
            side=str(p_spec.get("side", "top")),
            align=str(p_spec.get("align", "center")),
            overlap=int(p_spec.get("overlap", 1)),
            nudge=nudge,  # type: ignore[arg-type]
            hinge=p_spec.get("hinge"),
        )
    return all_notes


def build_from_spec(
    spec: Union[str, Path, Mapping[str, Any]],
    output_dir: Optional[Union[str, Path]] = None,
) -> Dict[str, Any]:
    """Zero-script declarative asset & rigged character builder from a dict or `.json` file."""
    if isinstance(spec, (str, Path)):
        spec_data: Dict[str, Any] = json.loads(Path(spec).read_text(encoding="utf-8"))
    else:
        spec_data = dict(spec)

    name = str(spec_data["name"])
    palette = spec_data.get("palette", "endesga32")
    out_dir = Path(output_dir if output_dir is not None else spec_data.get("output_dir", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    pad_ragged = bool(spec_data.get("pad_ragged", True))
    preview_scale = int(spec_data.get("preview_scale", 8))
    formats = tuple(spec_data.get("formats", ("gif", "apng", "webp", "aseprite")))

    auto_fixes: List[str] = []
    must_view: List[str] = []

    # ------------------------------------------------------------------
    # Mode A: Simple ASCII / Image Frames (`"frames"` provided)
    # ------------------------------------------------------------------
    if "frames" in spec_data and "parts" not in spec_data:
        raw_frames = spec_data["frames"]
        norm_frames: List[Any] = []
        if pad_ragged:
            for f_idx, f_item in enumerate(raw_frames):
                if isinstance(f_item, Image.Image):
                    norm_frames.append(f_item)
                else:
                    lines, notes = normalize_grid(f_item)
                    norm_frames.append(lines)
                    auto_fixes.extend(f"Frame {f_idx} {n}" for n in notes)
        else:
            norm_frames = list(raw_frames)

        # Optional post-effects on simple frames (outline_mode / add_shadow)
        outline_mode = str(spec_data.get("outline_mode", "none")).lower()
        outline_color = spec_data.get("outline_color", "#181425")
        add_shadow = bool(spec_data.get("add_shadow", False))

        if outline_mode in ("outer", "selout") or add_shadow:
            from .rig import AnimationClip

            tmp_clip = AnimationClip.create(name, norm_frames, palette=palette, pad_ragged=pad_ragged)
            imgs = tmp_clip.frames
            if outline_mode == "selout":
                imgs = [
                    selective_outline(im, dark_color=outline_color, snap_palette=palette)
                    for im in imgs
                ]
            elif outline_mode == "outer":
                imgs = [auto_outline(im, color=outline_color) for im in imgs]
            if add_shadow:
                # Pad 3px bottom if sprite touches bottom row so shadow fits cleanly
                imgs = [add_ground_shadow(im) for im in imgs]
            norm_frames = imgs

        meta = build_pixel_asset(
            name=name,
            frames=norm_frames,
            palette=palette,
            durations_ms=spec_data.get("durations_ms"),
            fps=int(spec_data.get("fps", 8)),
            preview_scale=preview_scale,
            baseline_y=spec_data.get("baseline_y"),
            nine_slice_margins=tuple(spec_data["nine_slice_margins"]) if spec_data.get("nine_slice_margins") else None,  # type: ignore[arg-type]
            formats=formats,
            output_dir=out_dir,
            pad_ragged=pad_ragged,
        )
        must_view.append(meta["files"]["inspect_sheet"])

        if spec_data.get("hd2d"):
            hd_cfg = spec_data["hd2d"] if isinstance(spec_data["hd2d"], Mapping) else {}
            first_im = Image.open(meta["files"]["png_1x"]).convert("RGBA")
            hd_files = export_hd2d_bundle(
                name=f"{name}_hd2d",
                albedo=first_im,
                emissive_colors=hd_cfg.get("emissive_colors"),
                profile=str(hd_cfg.get("profile", "dome")),
                output_dir=out_dir,
            )
            meta["hd2d_files"] = hd_files
            must_view.append(hd_files["inspect_sheet"])

        meta["agent_checklist"] = build_agent_checklist(
            must_view_files=must_view,
            lint_report=meta["lint"],
            auto_fixes=auto_fixes,
        )
        return meta

    # ------------------------------------------------------------------
    # Mode B: Articulated Multi-Part Rig (`"parts"` provided)
    # ------------------------------------------------------------------
    if "parts" not in spec_data:
        raise ValueError("Spec must contain either 'frames' (simple sprite) or 'parts' (articulated rig).")

    outline_mode = str(spec_data.get("outline_mode", "selout"))
    outline_color = spec_data.get("outline_color", "#181425")
    light_dir = tuple(float(v) for v in spec_data.get("light_dir", (-1.0, -1.0)))
    raw_csize = spec_data.get("canvas_size", "auto")

    if raw_csize in (None, "auto"):
        # Stage parts on a generous virtual canvas, measure tight bounding box, and crop with swing margin
        stage_rig = Rig(
            (160, 160),
            palette=palette,
            outline_mode=outline_mode,
            outline_color=outline_color,
            light_dir=light_dir,  # type: ignore[arg-type]
        )
        auto_fixes.extend(_populate_rig_parts(stage_rig, spec_data["parts"], pad_ragged=pad_ragged))
        probe = stage_rig.render_pose({})
        bbox = probe.getchannel("A").getbbox() or (64, 64, 96, 96)
        margin = int(spec_data.get("margin", 10))
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        cw = bw + margin * 2
        ch = bh + margin * 2
        if cw % 2 == 1:
            cw += 1
        if ch % 2 == 1:
            ch += 1
        shift_x = bbox[0] - (cw - bw) // 2
        shift_y = bbox[1] - (ch - bh) // 2

        rig = Rig(
            (cw, ch),
            palette=palette,
            outline_mode=outline_mode,
            outline_color=outline_color,
            light_dir=light_dir,  # type: ignore[arg-type]
        )
        for pname, part in stage_rig.parts.items():
            new_off = (part.offset[0] - shift_x, part.offset[1] - shift_y)
            new_pcan = (
                (part.pivot_canvas[0] - shift_x, part.pivot_canvas[1] - shift_y)
                if part.pivot_canvas is not None
                else None
            )
            rig.parts[pname] = Part(
                name=part.name,
                source=part.source,
                offset=new_off,
                pivot_local=part.pivot_local,
                pivot_canvas=new_pcan,
                z_index=part.z_index,
                outline_group=part.outline_group,
            )
        auto_fixes.append(f"Canvas auto-sized to {cw}x{ch} (margin={margin}px around assembled parts).")
    else:
        cw, ch = int(raw_csize[0]), int(raw_csize[1])
        rig = Rig(
            (cw, ch),
            palette=palette,
            outline_mode=outline_mode,
            outline_color=outline_color,
            light_dir=light_dir,  # type: ignore[arg-type]
        )
        auto_fixes.extend(_populate_rig_parts(rig, spec_data["parts"], pad_ragged=pad_ragged))

    clips_spec = spec_data.get("clips") or {"idle": "idle_breathe"}
    if isinstance(clips_spec, str):
        clips_spec = {"default": clips_spec}

    resolved_clips: Dict[str, Tuple[List[Image.Image], List[int], List[Tuple[str, List[Optional[Image.Image]]]]]] = {}
    for clip_name, c_entry in clips_spec.items():
        if isinstance(c_entry, str):
            frames, durs, poses = rig.animate_preset(
                preset=c_entry,
                include_shadow=bool(spec_data.get("include_shadow", True)),
                include_vfx=bool(spec_data.get("include_vfx", True)),
            )
            named_layers = rig.render_named_layers_sequence(poses)
        elif isinstance(c_entry, Mapping) and "preset" in c_entry:
            frames, durs, poses = rig.animate_preset(
                preset=str(c_entry["preset"]),
                include_shadow=bool(c_entry.get("include_shadow", spec_data.get("include_shadow", True))),
                include_vfx=bool(c_entry.get("include_vfx", spec_data.get("include_vfx", True))),
                baseline_y=c_entry.get("baseline_y"),
            )
            named_layers = rig.render_named_layers_sequence(poses)
        elif isinstance(c_entry, Mapping) and "poses" in c_entry:
            poses = list(c_entry["poses"])
            raw_frames = [rig.render_pose(p) for p in poses]
            if c_entry.get("include_shadow", spec_data.get("include_shadow", True)):
                frames = [add_ground_shadow(f) for f in raw_frames]
            else:
                frames = raw_frames
            raw_durs = c_entry.get("durations_ms", 140)
            durs = [int(raw_durs)] * len(frames) if isinstance(raw_durs, int) else [int(x) for x in raw_durs]
            named_layers = rig.render_named_layers_sequence(poses)
        else:
            raise ValueError(
                f"Clip {clip_name!r} must be a preset string (e.g. 'idle_breathe', 'melee_attack') "
                "or a dict with 'preset' or 'poses'."
            )
        resolved_clips[str(clip_name)] = (frames, durs, named_layers)

    pivots = rig.get_canvas_pivots()

    # Single-clip vs Multi-clip export
    if len(resolved_clips) == 1 and not spec_data.get("force_actor_atlas", False):
        only_cname, (frames, durs, named_layers) = next(iter(resolved_clips.items()))
        result = build_pixel_asset(
            name=name,
            frames=frames,
            palette=palette,
            durations_ms=durs,
            preview_scale=preview_scale,
            pivots=pivots,
            named_layers=named_layers,
            formats=formats,
            output_dir=out_dir,
        )
        must_view.append(result["files"]["inspect_sheet"])
        if "aseprite" in result["files"]:
            ase_doc = read_aseprite(result["files"]["aseprite"])
            layer_sheet_path = out_dir / f"{name}_layers_inspect.png"
            generate_aseprite_layer_sheet(ase_doc, title=f"Layers: {name} ({only_cname})").save(layer_sheet_path)
            result["files"]["aseprite_layers_inspect"] = str(layer_sheet_path)
            must_view.append(str(layer_sheet_path))
        agg_lint = result["lint"]
    else:
        actor = SpriteActor(name, palette=palette)
        layers_by_clip: Dict[str, Sequence[Tuple[str, Sequence[Optional[Image.Image]]]]] = {}
        for cname, (frames, durs, named_layers) in resolved_clips.items():
            actor.add_clip(cname, frames, durations_ms=durs)
            layers_by_clip[cname] = named_layers

        result = build_actor_assets(
            actor,
            output_dir=out_dir,
            preview_scale=preview_scale,
            pivots=pivots,
            named_layers_by_clip=layers_by_clip,
            formats=formats,
        )
        for c_meta in result["clips"].values():
            must_view.append(c_meta["files"]["inspect_sheet"])
        if "master_aseprite" in result:
            ase_doc = read_aseprite(result["master_aseprite"])
            layer_sheet_path = out_dir / f"{name}_master_layers_inspect.png"
            generate_aseprite_layer_sheet(ase_doc, title=f"Master Layers: {name}").save(layer_sheet_path)
            result["master_layers_inspect"] = str(layer_sheet_path)
            must_view.append(str(layer_sheet_path))

        # Aggregate lint reports across all clips for unified checklist
        combined_issues = []
        total_warns = 0
        for cname, c_meta in result["clips"].items():
            c_lint = c_meta["lint"]
            total_warns += int(c_lint.get("warning_count", 0))
            for iss in c_lint.get("issues", []):
                iss_copy = dict(iss)
                iss_copy["message"] = f"[{cname}] {iss_copy.get('message', '')}"
                combined_issues.append(iss_copy)
        agg_lint = {"warning_count": total_warns, "issues": combined_issues}

    # Optional 1-step HD-2D Normal Map + Torch Orbit bundle using per-part relief profiles
    if spec_data.get("hd2d"):
        hd_cfg = spec_data["hd2d"] if isinstance(spec_data["hd2d"], Mapping) else {}
        base_albedo = rig.render_pose({})
        part_layers = rig.render_part_layers({}, part_profiles=hd_cfg.get("part_profiles"))
        hd_files = export_hd2d_bundle(
            name=f"{name}_hd2d",
            albedo=base_albedo,
            part_layers=part_layers,
            emissive_colors=hd_cfg.get("emissive_colors"),
            bevel_px=float(hd_cfg.get("bevel_px", 4.5)),
            bump_strength=float(hd_cfg.get("bump_strength", 2.2)),
            output_dir=out_dir,
        )
        result["hd2d_files"] = hd_files
        must_view.append(hd_files["inspect_sheet"])

    result["canvas_size"] = list(rig.canvas_size)
    result["part_offsets"] = {pn: list(pt.offset) for pn, pt in rig.parts.items()}
    result["part_pivots"] = {pn: [round(v, 2) for v in pv] for pn, pv in rig.get_named_canvas_pivots().items()}
    result["agent_checklist"] = build_agent_checklist(
        must_view_files=must_view,
        lint_report=agg_lint,
        auto_fixes=auto_fixes,
    )
    return result


def scaffold_script(
    target_path: Union[str, Path],
    template: str = "rig",
    name: str = "my_asset",
    palette: str = "endesga32",
) -> Dict[str, str]:
    """Write a ready-to-run starter `.py` script (`rig`, `sprite`, `scene`, or `iso`) with portable `sys.path`."""
    tpl = template.strip().lower()
    out_file = Path(target_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    scripts_dir = Path(__file__).resolve().parents[1]
    try:
        rel_scripts = os.path.relpath(scripts_dir, out_file.resolve().parent)
        path_expr = f"(Path(__file__).resolve().parent / {rel_scripts!r}).resolve()"
    except ValueError:
        path_expr = f"Path({str(scripts_dir)!r})"

    header = (
        "#!/usr/bin/env python3\n"
        f'"""PixelForge {tpl} script for [{name}]. Run: python3 {out_file.name}"""\n'
        "import sys\n"
        "from pathlib import Path\n\n"
        f"_PFORGE_SCRIPTS = {path_expr}\n"
        "if str(_PFORGE_SCRIPTS) not in sys.path:\n"
        "    sys.path.insert(0, str(_PFORGE_SCRIPTS))\n\n"
    )

    if tpl == "rig":
        body = (
            "import pixelforge as pf\n\n"
            "OUT_DIR = Path(__file__).resolve().parent / 'output'\n\n"
            "SPEC = {\n"
            f"    'name': {name!r},\n"
            f"    'palette': {palette!r},\n"
            "    'canvas_size': 'auto',\n"
            "    'outline_mode': 'selout',\n"
            "    'parts': [\n"
            "        {\n"
            "            'name': 'torso',\n"
            "            'at': 'center',\n"
            "            'z_index': 10,\n"
            "            'grid': [\n"
            "                '|..BBBB..|  # chestplate top',\n"
            "                '|.BCCCCB.|  # glowing core',\n"
            "                '|BBBBBBBB|',\n"
            "                '|.bbbbbb.|',\n"
            "            ],\n"
            "        },\n"
            "        {\n"
            "            'name': 'head',\n"
            "            'attach_to': 'torso',\n"
            "            'side': 'top',\n"
            "            'z_index': 20,\n"
            "            'grid': [\n"
            "                '|.1111.|',\n"
            "                '|11WW11|',\n"
            "                '|1KKKK1|  # visor',\n"
            "                '|.2222.|',\n"
            "            ],\n"
            "        },\n"
            "        {\n"
            "            'name': 'sword',\n"
            "            'attach_to': 'torso',\n"
            "            'side': 'right',\n"
            "            'hinge': 'grip',\n"
            "            'z_index': 30,\n"
            "            'outline_group': 1,\n"
            "            'grid': [\n"
            "                '|.W.|',\n"
            "                '|.1.|',\n"
            "                '|.2.|',\n"
            "                '|YYY|',\n"
            "                '|.o.|',\n"
            "            ],\n"
            "        },\n"
            "    ],\n"
            "    'clips': {\n"
            "        'idle': 'idle_breathe',\n"
            "        'attack': 'melee_attack',\n"
            "    },\n"
            "}\n\n"
            "if __name__ == '__main__':\n"
            "    res = pf.build_from_spec(SPEC, output_dir=OUT_DIR)\n"
            "    print('MUST VIEW:', res['agent_checklist']['must_view_images'])\n"
        )
    elif tpl == "sprite":
        body = (
            "import pixelforge as pf\n\n"
            "OUT_DIR = Path(__file__).resolve().parent / 'output'\n\n"
            "FRAME_0 = [\n"
            "    '|..KKKK..|',\n"
            "    '|.KCCCCK.|',\n"
            "    '|KCWWWWCK|',\n"
            "    '|KCBBBBCK|',\n"
            "    '|.KbbbbK.|',\n"
            "    '|..KKKK..|',\n"
            "]\n\n"
            "if __name__ == '__main__':\n"
            f"    res = pf.build_pixel_asset({name!r}, [FRAME_0], palette={palette!r}, output_dir=OUT_DIR, pad_ragged=True)\n"
            "    print('MUST VIEW:', res['files']['inspect_sheet'])\n"
        )
    elif tpl == "scene":
        body = (
            "import pixelforge as pf\n\n"
            "OUT_DIR = Path(__file__).resolve().parent / 'output'\n\n"
            "if __name__ == '__main__':\n"
            "    floor = pf.PixelCanvas(16, 16, fill='5').dither_rect(0, 0, 16, 16, '5', '4', 0.25).render('endesga32')\n"
            "    comp = pf.SceneComposer(128, 96)\n"
            "    comp.set_tiled_background(floor)\n"
            "    hero = pf.render_grid(['..KKKK..', '.KCCCCK.', 'KBBBBBBK', '.KbbbbK.'], palette='endesga32')\n"
            "    comp.add_entity('hero', hero, pos=(64, 58), anchor='foot', role='actor')\n"
            "    comp.add_floating_text('dmg', '-42!', pos=(64, 34))\n"
            f"    res = pf.build_scene_mockup({name!r}, comp, frame_count=6, output_dir=OUT_DIR)\n"
            "    print('MUST VIEW:', res['files']['inspect_sheet'])\n"
        )
    elif tpl == "iso":
        body = (
            "import pixelforge as pf\n\n"
            "OUT_DIR = Path(__file__).resolve().parent / 'output'\n\n"
            "if __name__ == '__main__':\n"
            "    iso = pf.IsoScene(half_h=8)\n"
            "    for gx in range(3):\n"
            "        for gy in range(3):\n"
            "            iso.add_block(gx, gy, gz=0, height_z=5, base_color='#63C74D')\n"
            "    iso.add_block(1, 1, gz=5, height_z=14, base_color='#C0CBDC')\n"
            "    im = iso.render()\n"
            f"    res = pf.build_pixel_asset({name!r}, [im], preview_scale=4, output_dir=OUT_DIR)\n"
            "    print('MUST VIEW:', res['files']['inspect_sheet'])\n"
        )
    else:
        raise ValueError(f"Unknown template {template!r}. Choose from: rig, sprite, scene, iso.")

    out_file.write_text(header + body, encoding="utf-8")
    return {
        "script_path": str(out_file),
        "template": tpl,
        "run_command": f"python3 {out_file}",
    }
