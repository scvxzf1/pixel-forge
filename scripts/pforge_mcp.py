#!/usr/bin/env python3
"""PixelForge Zero-Dependency MCP Server (Stdio JSON-RPC 2.0).
Compatible with Google Antigravity, Claude Code, Claude Desktop, Cursor, and Codex.
Requires ONLY Python stdlib + Pillow (no `mcp` pip package needed!).
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from PIL import Image

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pixelforge as pf  # noqa: E402

SERVER_NAME = "pixelforge-mcp"
SERVER_VERSION = "1.5.0"
SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}
DEFAULT_PROTOCOL = "2025-03-26"


def _encode_png_base64(path: Union[str, Path]) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


TOOLS_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "pixelforge_inspect",
        "description": (
            "Generate a Holistic Visual Inspection Sheet (palette legend, 0-based X/Y grid, "
            "dark/light clean previews, silhouette & onion-skin) + Pixel Linter diagnostics for any "
            "PNG, GIF, APNG, WebP, Spritesheet, or .aseprite file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to input image/animation/.aseprite file."},
                "output_dir": {"type": "string", "default": "output/mcp_inspect"},
                "cols": {"type": "integer", "description": "Optional spritesheet columns."},
                "rows": {"type": "integer", "description": "Optional spritesheet rows."},
                "keep_scale": {"type": "boolean", "default": False},
                "include_inline_image": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        },
    },
    {
        "name": "pixelforge_build",
        "description": (
            "Render ASCII character grid frame(s) into PNG, GIF, APNG, Lossless WebP, Aseprite JSON, "
            "native .aseprite project, and Holistic Inspection Sheet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Asset filename stem (e.g. 'fire_slime')."},
                "frames": {
                    "type": "array",
                    "description": "List of ASCII grids (each frame is either a newline-joined string or array of equal-width row strings).",
                    "items": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                },
                "palette": {
                    "oneOf": [{"type": "string"}, {"type": "object"}],
                    "default": "endesga32",
                    "description": "Built-in name (endesga32|pico8|sweetie16|resurrect64|gameboy|mono1bit) or {char: '#HEX'} dict.",
                },
                "durations_ms": {
                    "oneOf": [{"type": "integer"}, {"type": "array", "items": {"type": "integer"}}],
                    "description": "Single ms int or per-frame ms array (e.g. [200, 120, 45, 140]).",
                },
                "output_dir": {"type": "string", "default": "output/mcp_build"},
                "include_inline_image": {"type": "boolean", "default": False},
            },
            "required": ["name", "frames"],
        },
    },
    {
        "name": "pixelforge_decompile",
        "description": (
            "Reverse-decompile an existing PNG, GIF, APNG, WebP, Spritesheet, or .aseprite file "
            "into editable ASCII character grids, semantic palette, shading ramps, and Python script."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "output_dir": {"type": "string", "default": "output/mcp_decompile"},
                "palette": {"type": "string", "default": "auto"},
                "max_colors": {"type": "integer", "default": 48},
                "cols": {"type": "integer"},
                "rows": {"type": "integer"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "pixelforge_region_patch",
        "description": (
            "Surgical sub-region editing on sprites: action='extract' slices a [x,y,w,h] ASCII box "
            "with global-coordinate inspection; action='apply' patches edited ASCII rows back and "
            "generates a Before/After/Diff verification sheet."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["extract", "apply"]},
                "path": {"type": "string", "description": "Base sprite PNG/GIF/.aseprite path."},
                "box": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "[x, y, w, h] for action='extract'.",
                },
                "at": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "[x, y] top-left offset for action='apply'.",
                },
                "patch_grid": {
                    "oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}],
                    "description": "Edited ASCII grid for action='apply'.",
                },
                "mode": {"type": "string", "enum": ["replace", "alpha_over"], "default": "replace"},
                "palette": {"oneOf": [{"type": "string"}, {"type": "object"}]},
                "frame": {"type": "integer", "default": 0},
                "output_dir": {"type": "string", "default": "output/mcp_patch"},
                "include_inline_image": {"type": "boolean", "default": False},
            },
            "required": ["action", "path"],
        },
    },
    {
        "name": "pixelforge_recolor",
        "description": "Swap palette characters or #HEX colors across static or animated assets with Diff verification.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "color_map": {"type": "object", "description": "Mapping e.g. {'R': 'B', 'r': 'b'} or {'#E43B44': '#0099DB'}."},
                "palette": {"type": "string", "default": "endesga32"},
                "tolerance": {"type": "integer", "default": 0},
                "output_dir": {"type": "string", "default": "output/mcp_recolor"},
            },
            "required": ["path", "color_map"],
        },
    },
    {
        "name": "pixelforge_pixelate",
        "description": "Convert a high-res illustration or AI pseudo-pixel draft into clean, palette-locked pixel art.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "width": {"type": "integer", "default": 48},
                "height": {"type": "integer", "default": 48},
                "palette": {"type": "string", "default": "endesga32"},
                "mode": {"type": "string", "enum": ["contrast_box", "dominant_block"], "default": "contrast_box"},
                "outline_color": {"type": "string", "description": "Optional outer outline hex (e.g. '#181425')."},
                "output_dir": {"type": "string", "default": "output/mcp_pixelate"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "pixelforge_autotile",
        "description": "Synthesize a 47-tile Blob or 16-tile Wang Auto-Tileset + rendered test map from fg & bg tiles.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "fg_path": {"type": "string"},
                "bg_path": {"type": "string"},
                "mode": {"type": "string", "enum": ["blob47", "wang16"], "default": "blob47"},
                "outline_color": {"type": "string", "default": "#181425"},
                "rim_highlight_color": {"type": "string"},
                "rim_shadow_color": {"type": "string"},
                "sample_map": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "name": {"type": "string", "default": "terrain"},
                "output_dir": {"type": "string", "default": "output/mcp_autotile"},
            },
            "required": ["fg_path", "bg_path"],
        },
    },
    {
        "name": "pixelforge_hd2d_normal",
        "description": "Generate OpenGL Tangent Normal Map + Emission Mask + 360 Orbiting Torch GIF for any sprite.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "profile": {"type": "string", "enum": ["dome", "bevel", "ridge"], "default": "dome"},
                "emissive_colors": {"type": "array", "items": {"type": "string"}},
                "bevel_px": {"type": "number", "default": 4.5},
                "bump_strength": {"type": "number", "default": 2.2},
                "output_dir": {"type": "string", "default": "output/mcp_hd2d"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "pixelforge_aseprite_inspect",
        "description": (
            "Read a native binary .ase / .aseprite file, inspect its independent layers, frame durations, "
            "tags, and slices, and render a Multi-Layer Timeline Breakdown PNG."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to .ase or .aseprite binary file."},
                "unpack_layers": {"type": "boolean", "default": False},
                "output_dir": {"type": "string", "default": "output/mcp_aseprite"},
                "include_inline_image": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        },
    },
]


def _execute_tool(name: str, args: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str]]:
    """Execute tool logic and return `(json_payload, optional_inline_png_path)`."""
    if name == "pixelforge_inspect":
        frames, durs, dk = pf.load_frames_from_file(
            args["path"],
            cols=args.get("cols"),
            rows=args.get("rows"),
            auto_downscale_native=not args.get("keep_scale", False),
        )
        pal = pf.extract_palette(frames, max_colors=48)
        out = Path(args.get("output_dir", "output/mcp_inspect"))
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(args["path"]).stem
        ins_path = out / f"{stem}_inspect.png"
        pf.generate_holistic_sheet(frames, title=f"Inspect: {stem}", palette=pal, durations_ms=durs).save(ins_path)
        lint_rep = pf.lint_frames(frames)
        payload = {
            "inspect_sheet": str(ins_path),
            "native_size": [frames[0].width, frames[0].height],
            "frame_count": len(frames),
            "auto_downscaled_by": dk,
            "palette": pal,
            "palette_ramps": pf.analyze_palette_ramps(pal),
            "lint": lint_rep,
        }
        return payload, (str(ins_path) if args.get("include_inline_image") else None)

    if name == "pixelforge_build":
        meta = pf.build_pixel_asset(
            name=args["name"],
            frames=args["frames"],
            palette=args.get("palette", "endesga32"),
            durations_ms=args.get("durations_ms"),
            output_dir=args.get("output_dir", "output/mcp_build"),
        )
        ins = meta["files"]["inspect_sheet"]
        return meta, (ins if args.get("include_inline_image") else None)

    if name == "pixelforge_decompile":
        pal_arg = None if args.get("palette") in (None, "auto") else args.get("palette")
        bundle = pf.decompile_asset(
            args["path"],
            output_dir=args.get("output_dir", "output/mcp_decompile"),
            cols=args.get("cols"),
            rows=args.get("rows"),
            palette=pal_arg,
            max_colors=int(args.get("max_colors", 48)),
        )
        return bundle, None

    if name == "pixelforge_region_patch":
        frames, durs, _ = pf.load_frames_from_file(args["path"])
        f_idx = int(args.get("frame", 0))
        base_img = frames[f_idx]
        pal_in = args.get("palette")
        full_grid, pal_dict = pf.image_to_grid(base_img, palette=pal_in if pal_in not in (None, "auto") else None)
        out = Path(args.get("output_dir", "output/mcp_patch"))
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(args["path"]).stem

        if args["action"] == "extract":
            rx, ry, rw, rh = [int(v) for v in args["box"]]
            sub_grid = pf.extract_region_grid(full_grid, rx, ry, rw, rh)
            sub_img = pf.extract_region_image(base_img, rx, ry, rw, rh)
            ins_file = out / f"{stem}_x{rx}_y{ry}_w{rw}_h{rh}_inspect.png"
            pf.generate_holistic_sheet([sub_img], title=f"Slice ({rx},{ry},{rw},{rh})", palette=pal_dict, coord_offset=(rx, ry)).save(ins_file)
            res = {
                "box": [rx, ry, rw, rh],
                "palette": pal_dict,
                "grid": sub_grid,
                "inspect_sheet": str(ins_file),
            }
            return res, (str(ins_file) if args.get("include_inline_image") else None)
        else:
            ax, ay = [int(v) for v in args["at"]]
            patched = pf.patch_region_image(
                base_img,
                args["patch_grid"],
                ax,
                ay,
                palette=pal_dict,
                mode=args.get("mode", "replace"),
            )
            diff_im, diff_stats = pf.generate_diff_sheet(base_img, patched, title=f"Patch Diff: {stem}")
            diff_file = out / f"{stem}_patched_diff.png"
            diff_im.save(diff_file)
            seq = list(frames)
            seq[f_idx] = patched
            meta = pf.build_pixel_asset(f"{stem}_patched", seq, palette=pal_dict, durations_ms=durs, output_dir=out)
            res = {"diff_sheet": str(diff_file), "diff_stats": diff_stats, "asset": meta}
            return res, (str(diff_file) if args.get("include_inline_image") else None)

    if name == "pixelforge_recolor":
        frames, durs, _ = pf.load_frames_from_file(args["path"])
        pal = args.get("palette", "endesga32")
        recolored = [pf.recolor_image(f, args["color_map"], palette=pal, tolerance=int(args.get("tolerance", 0))) for f in frames]
        out = Path(args.get("output_dir", "output/mcp_recolor"))
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(args["path"]).stem
        diff_im, stats = pf.generate_diff_sheet(frames[0], recolored[0], title=f"Recolor: {stem}")
        diff_file = out / f"{stem}_recolor_diff.png"
        diff_im.save(diff_file)
        meta = pf.build_pixel_asset(f"{stem}_recolored", recolored, palette=pal, durations_ms=durs, output_dir=out)
        return {"diff_sheet": str(diff_file), "diff_stats": stats, "asset": meta}, None

    if name == "pixelforge_pixelate":
        pal = None if args.get("palette") in (None, "auto") else args.get("palette")
        px_res = pf.pixelate_image(
            args["path"],
            target_size=(int(args.get("width", 48)), int(args.get("height", 48))),
            palette=pal,
            mode=args.get("mode", "contrast_box"),
            outline_color=args.get("outline_color"),
            output_dir=args.get("output_dir", "output/mcp_pixelate"),
            name=f"{Path(args['path']).stem}_pixelated",
        )
        return {
            "name": px_res["name"],
            "palette": px_res["palette"],
            "grid": px_res["grid"],
            "files": px_res.get("files", {}),
        }, None

    if name == "pixelforge_autotile":
        fg = Image.open(args["fg_path"]).convert("RGBA")
        bg = Image.open(args["bg_path"]).convert("RGBA")
        fn = pf.generate_blob47_tileset if args.get("mode", "blob47") == "blob47" else pf.generate_wang16_tileset
        bundle = fn(
            fg,
            bg,
            outline_color=args.get("outline_color", "#181425"),
            rim_highlight_color=args.get("rim_highlight_color"),
            rim_shadow_color=args.get("rim_shadow_color"),
        )
        files = pf.export_autotile_bundle(
            args.get("name", "terrain"),
            bundle,
            output_dir=args.get("output_dir", "output/mcp_autotile"),
            sample_map=args.get("sample_map"),
        )
        return files, None

    if name == "pixelforge_hd2d_normal":
        frames, _, _ = pf.load_frames_from_file(args["path"])
        files = pf.export_hd2d_bundle(
            name=Path(args["path"]).stem,
            albedo=frames[0],
            emissive_colors=args.get("emissive_colors"),
            profile=args.get("profile", "dome"),
            bevel_px=float(args.get("bevel_px", 4.5)),
            bump_strength=float(args.get("bump_strength", 2.2)),
            output_dir=args.get("output_dir", "output/mcp_hd2d"),
        )
        return files, None

    if name == "pixelforge_aseprite_inspect":
        doc = pf.read_aseprite(args["path"])
        out = Path(args.get("output_dir", "output/mcp_aseprite"))
        out.mkdir(parents=True, exist_ok=True)
        stem = Path(args["path"]).stem
        breakdown_path = out / f"{stem}_layers_inspect.png"
        pf.generate_aseprite_layer_sheet(doc, title=f"Aseprite: {stem}").save(breakdown_path)

        unpacked: Dict[str, List[str]] = {}
        if args.get("unpack_layers", False):
            layers_dir = out / f"{stem}_layers"
            layers_dir.mkdir(parents=True, exist_ok=True)
            for l_idx, layer in enumerate(doc.layers):
                safe_lname = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in layer["name"])
                paths = []
                for f_idx, fim in enumerate(layer["frames"]):
                    lp = layers_dir / f"L{l_idx:02d}_{safe_lname}_F{f_idx:02d}.png"
                    fim.save(lp)
                    paths.append(str(lp))
                unpacked[layer["name"]] = paths

        summary = doc.summary_dict()
        summary["layer_breakdown_sheet"] = str(breakdown_path)
        if unpacked:
            summary["unpacked_layer_files"] = unpacked
        return summary, (str(breakdown_path) if args.get("include_inline_image") else None)

    raise ValueError(f"Unknown MCP tool: {name!r}")


def handle_jsonrpc_message(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process a single JSON-RPC 2.0 request/notification and return response dict (or None for notifications)."""
    method = msg.get("method", "")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    # Notifications have no 'id' -> must not return a response
    if "id" not in msg:
        return None

    if method == "initialize":
        client_ver = str(params.get("protocolVersion", DEFAULT_PROTOCOL))
        negotiated = client_ver if client_ver in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": negotiated,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": TOOLS_SCHEMA},
        }

    if method == "tools/call":
        tool_name = str(params.get("name", ""))
        tool_args = dict(params.get("arguments") or {})
        log_buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(log_buf):
                payload, inline_img = _execute_tool(tool_name, tool_args)
            content: List[Dict[str, Any]] = [
                {"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}
            ]
            if inline_img and Path(inline_img).is_file():
                content.append({
                    "type": "image",
                    "data": _encode_png_base64(inline_img),
                    "mimeType": "image/png",
                })
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"content": content, "isError": False},
            }
        except Exception as exc:
            err_txt = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": err_txt}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def serve_stdio() -> int:
    """Run MCP Stdio loop supporting both newline-delimited JSON (MCP standard) and Content-Length framing."""
    stdin_buf = sys.stdin.buffer
    stdout_buf = sys.stdout.buffer

    while True:
        first_line = stdin_buf.readline()
        if not first_line:
            break
        stripped = first_line.strip()
        if not stripped:
            continue

        use_content_length = False
        if stripped.lower().startswith(b"content-length:"):
            use_content_length = True
            length = int(stripped.split(b":", 1)[1].strip())
            # Consume remaining headers up to blank line
            while True:
                hline = stdin_buf.readline()
                if not hline or hline in (b"\r\n", b"\n"):
                    break
            body_bytes = stdin_buf.read(length)
        else:
            body_bytes = stripped

        try:
            req = json.loads(body_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {exc}"},
            }
            out_raw = json.dumps(err_resp, ensure_ascii=False).encode("utf-8")
            stdout_buf.write(out_raw + b"\n")
            stdout_buf.flush()
            continue

        resp = handle_jsonrpc_message(req)
        if resp is not None:
            out_bytes = json.dumps(resp, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if use_content_length:
                header = f"Content-Length: {len(out_bytes)}\r\n\r\n".encode("ascii")
                stdout_buf.write(header + out_bytes)
            else:
                stdout_buf.write(out_bytes + b"\n")
            stdout_buf.flush()

    return 0


if __name__ == "__main__":
    raise SystemExit(serve_stdio())
