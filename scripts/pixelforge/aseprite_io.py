"""Pure-Python Native `.aseprite` / `.ase` Binary Encoder & Decoder (v1.3 spec compliant).
Supports:
- Multi-layer RGBA timelines (`0x2004` Layer chunks + `0x2005` Zlib Compressed & Linked Cels)
- Variable per-frame millisecond durations (`0xF1FA` frame headers)
- Animation Frame Tags (`0x2018`: forward / reverse / pingpong / pingpong_reverse)
- Embedded Named RGBA Color Palettes (`0x2019` + sRGB Color Profile `0x2007`)
- 9-Slice UI Patches & Hinge Pivot Slices (`0x2022`)
- Full lossless round-trip reading (`32-bit RGBA`, `16-bit Grayscale`, `8-bit Indexed`)
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from PIL import Image, ImageDraw, ImageFont

from .palette import (
    ColorDef,
    RGBA,
    canonical_char_map,
    get_palette,
    normalize_rgba,
    parse_color,
    rgba_to_hex,
)

ASE_FILE_MAGIC = 0xA5E0
ASE_FRAME_MAGIC = 0xF1FA

CHUNK_OLD_PALETTE_4 = 0x0004
CHUNK_OLD_PALETTE_11 = 0x0011
CHUNK_LAYER = 0x2004
CHUNK_CEL = 0x2005
CHUNK_COLOR_PROFILE = 0x2007
CHUNK_TAGS = 0x2018
CHUNK_PALETTE = 0x2019
CHUNK_SLICE = 0x2022

_DIR_TO_BYTE = {
    "forward": 0,
    "reverse": 1,
    "pingpong": 2,
    "pingpong_reverse": 3,
}
_BYTE_TO_DIR = {v: k for k, v in _DIR_TO_BYTE.items()}

_TAG_COLORS: Tuple[Tuple[int, int, int], ...] = (
    (65, 166, 246),
    (228, 59, 68),
    (99, 199, 77),
    (254, 174, 52),
    (181, 80, 136),
    (44, 232, 245),
)


def _pack_ase_string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<H", len(raw)) + raw


def _unpack_ase_string(buf: bytes, offset: int) -> Tuple[str, int]:
    (slen,) = struct.unpack_from("<H", buf, offset)
    start = offset + 2
    end = start + slen
    return buf[start:end].decode("utf-8", errors="replace"), end


def _wrap_chunk(chunk_type: int, payload: bytes) -> bytes:
    total_size = 6 + len(payload)
    return struct.pack("<IH", total_size, chunk_type) + payload


def _build_srgb_chunk() -> bytes:
    # WORD type=1 (sRGB), WORD flags=0, FIXED gamma=0, BYTE[8] reserved=0
    payload = struct.pack("<HHi8s", 1, 0, 0, b"\x00" * 8)
    return _wrap_chunk(CHUNK_COLOR_PROFILE, payload)


def _build_palette_chunk(
    palette: Optional[Union[str, Dict[str, ColorDef]]],
    frames_fallback: Sequence[Image.Image],
) -> Tuple[bytes, int]:
    entries: List[Tuple[RGBA, Optional[str]]] = [((0, 0, 0, 0), "transparent")]

    if palette is not None:
        rev = canonical_char_map(get_palette(palette))
        for col, ch in rev.items():
            if col[3] > 0:
                entries.append((col, f"[{ch}] {rgba_to_hex(col)}"))
    else:
        seen = {(0, 0, 0, 0)}
        for f in frames_fallback:
            raw = f.convert("RGBA").tobytes()
            for i in range(0, len(raw), 4):
                col = normalize_rgba((raw[i], raw[i + 1], raw[i + 2], raw[i + 3]))
                if col not in seen and len(entries) < 256:
                    seen.add(col)
                    entries.append((col, None))

    n = len(entries)
    parts = [struct.pack("<III8s", n, 0, max(0, n - 1), b"\x00" * 8)]
    for (r, g, b, a), cname in entries:
        if cname:
            parts.append(struct.pack("<HBBBB", 1, r, g, b, a))
            parts.append(_pack_ase_string(cname))
        else:
            parts.append(struct.pack("<HBBBB", 0, r, g, b, a))
    return _wrap_chunk(CHUNK_PALETTE, b"".join(parts)), n


def _build_layer_chunk(
    name: str,
    visible: bool = True,
    opacity: int = 255,
    layer_type: int = 0,
    child_level: int = 0,
    blend_mode: int = 0,
) -> bytes:
    flags = (1 if visible else 0) | 2  # Visible | Editable
    payload = (
        struct.pack("<HHHHHHB3s", flags, layer_type, child_level, 0, 0, blend_mode, opacity, b"\x00" * 3)
        + _pack_ase_string(name)
    )
    return _wrap_chunk(CHUNK_LAYER, payload)


def _build_tags_chunk(tags: Sequence[Mapping[str, Any]]) -> bytes:
    parts = [struct.pack("<H8s", len(tags), b"\x00" * 8)]
    for idx, t in enumerate(tags):
        f_from = int(t["from"])
        f_to = int(t["to"])
        d_byte = _DIR_TO_BYTE.get(str(t.get("direction", "forward")).lower(), 0)
        repeat = int(t.get("repeat", 0))
        if "color" in t and t["color"] is not None:
            cr, cg, cb, _ = parse_color(t["color"])
        else:
            cr, cg, cb = _TAG_COLORS[idx % len(_TAG_COLORS)]
        name = str(t["name"])
        parts.append(
            struct.pack("<HHBH6sBBBB", f_from, f_to, d_byte, repeat, b"\x00" * 6, cr, cg, cb, 0)
            + _pack_ase_string(name)
        )
    return _wrap_chunk(CHUNK_TAGS, b"".join(parts))


def _build_slice_chunk(
    name: str,
    bounds: Tuple[int, int, int, int],  # (x, y, w, h)
    center: Optional[Tuple[int, int, int, int]] = None,  # (cx, cy, cw, ch) relative to bounds
    pivot: Optional[Tuple[int, int]] = None,             # (px, py) relative to bounds
) -> bytes:
    flags = (1 if center is not None else 0) | (2 if pivot is not None else 0)
    bx, by, bw, bh = bounds
    parts = [
        struct.pack("<III", 1, flags, 0),
        _pack_ase_string(name),
        struct.pack("<IiiII", 0, bx, by, bw, bh),
    ]
    if center is not None:
        parts.append(struct.pack("<iiII", center[0], center[1], center[2], center[3]))
    if pivot is not None:
        parts.append(struct.pack("<ii", pivot[0], pivot[1]))
    return _wrap_chunk(CHUNK_SLICE, b"".join(parts))


def _build_cel_chunk(
    layer_index: int,
    img: Image.Image,
    opacity: int = 255,
    linked_frame: Optional[int] = None,
) -> Optional[bytes]:
    if linked_frame is not None:
        # Cel type 1 = Linked Cel (16B cel header + WORD linked_frame)
        payload = struct.pack("<HhhBHh5sH", layer_index, 0, 0, opacity, 1, 0, b"\x00" * 5, linked_frame)
        return _wrap_chunk(CHUNK_CEL, payload)

    rgba = img.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        # Empty transparent cel -> omit chunk (standard Aseprite sparse timeline behavior)
        return None

    x0, y0, x1, y1 = bbox
    cw, ch = x1 - x0, y1 - y0
    cropped = rgba.crop(bbox)
    compressed = zlib.compress(cropped.tobytes(), level=6)
    header = struct.pack("<HhhBHh5sHH", layer_index, x0, y0, opacity, 2, 0, b"\x00" * 5, cw, ch)
    return _wrap_chunk(CHUNK_CEL, header + compressed)


def write_aseprite(
    target: Union[str, Path],
    canvas_size: Tuple[int, int],
    layers: Sequence[Tuple[str, Sequence[Optional[Image.Image]]]],
    durations_ms: Sequence[int],
    palette: Optional[Union[str, Dict[str, ColorDef]]] = None,
    frame_tags: Optional[Sequence[Mapping[str, Any]]] = None,
    nine_slice_margins: Optional[Tuple[int, int, int, int]] = None,
    pivots: Optional[Mapping[str, Tuple[float, float]]] = None,
    use_linked_cels: bool = False,
) -> Path:
    """Write a native multi-layer, tagged, palette-embedded `.aseprite` binary file.

    `layers`: ordered bottom-to-top, e.g. `[("cape", [f0, f1]), ("torso", [f0, f1]), ("sword", [f0, f1])]`.
    """
    w, h = canvas_size
    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid canvas_size {canvas_size}")
    if not layers:
        raise ValueError("layers must contain at least one layer.")

    n_frames = len(durations_ms)
    if n_frames < 1:
        raise ValueError("durations_ms must contain at least 1 frame duration.")
    for lname, lframes in layers:
        if len(lframes) != n_frames:
            raise ValueError(
                f"Layer {lname!r} has {len(lframes)} frames, expected {n_frames} from durations_ms."
            )

    sample_imgs = [im for _, lfs in layers for im in lfs if im is not None]
    pal_chunk, num_pal_colors = _build_palette_chunk(palette, sample_imgs)

    frame_blobs: List[bytes] = []
    # Optional cache for linked cel deduplication: (layer_idx, raw_bytes) -> first_frame_idx
    seen_cels: Dict[Tuple[int, bytes], int] = {}

    for f_idx in range(n_frames):
        chunks: List[bytes] = []
        if f_idx == 0:
            chunks.append(_build_srgb_chunk())
            chunks.append(pal_chunk)
            for lname, _ in layers:
                chunks.append(_build_layer_chunk(lname))

        for l_idx, (_, lframes) in enumerate(layers):
            cel_im = lframes[f_idx]
            if cel_im is None:
                continue
            if cel_im.size != (w, h):
                raise ValueError(
                    f"Cel size {cel_im.size} on layer {l_idx} frame {f_idx} != canvas {(w, h)}."
                )

            linked_to: Optional[int] = None
            if use_linked_cels:
                raw_b = cel_im.convert("RGBA").tobytes()
                key = (l_idx, raw_b)
                if key in seen_cels:
                    linked_to = seen_cels[key]
                else:
                    seen_cels[key] = f_idx

            c_chunk = _build_cel_chunk(l_idx, cel_im, linked_frame=linked_to)
            if c_chunk is not None:
                chunks.append(c_chunk)

        # Tags & Slices go after Layer/Cel chunks in Frame 0
        if f_idx == 0:
            if frame_tags:
                chunks.append(_build_tags_chunk(frame_tags))
            if nine_slice_margins is not None:
                ml, mt, mr, mb = nine_slice_margins
                chunks.append(
                    _build_slice_chunk(
                        "9slice_center",
                        bounds=(0, 0, w, h),
                        center=(ml, mt, max(1, w - ml - mr), max(1, h - mt - mb)),
                    )
                )
            if pivots:
                for pname, (px, py) in pivots.items():
                    chunks.append(
                        _build_slice_chunk(
                            f"pivot_{pname}",
                            bounds=(0, 0, w, h),
                            pivot=(round(px), round(py)),
                        )
                    )

        body = b"".join(chunks)
        n_chunks = len(chunks)
        old_chunks = min(n_chunks, 0xFFFF)
        dur = max(1, min(65535, int(round(durations_ms[f_idx]))))
        f_header = struct.pack(
            "<IHHH2sI",
            16 + len(body),
            ASE_FRAME_MAGIC,
            old_chunks,
            dur,
            b"\x00\x00",
            n_chunks,
        )
        frame_blobs.append(f_header + body)

    all_frames_bytes = b"".join(frame_blobs)
    total_file_size = 128 + len(all_frames_bytes)
    grid_w = min(w, 16)
    grid_h = min(h, 16)

    file_header = struct.pack(
        "<IHHHHHIHIIB3sHBBhhHH84s",
        total_file_size,
        ASE_FILE_MAGIC,
        n_frames,
        w,
        h,
        32,                         # 32-bit RGBA color depth
        1,                          # Flags: 1 = layer opacity is valid
        max(1, int(durations_ms[0])),
        0,
        0,
        0,                          # Transparent palette index
        b"\x00\x00\x00",
        min(65535, num_pal_colors),
        1,                          # Pixel width
        1,                          # Pixel height
        0,                          # Grid X
        0,                          # Grid Y
        grid_w,
        grid_h,
        b"\x00" * 84,
    )
    assert len(file_header) == 128

    out_path = Path(target)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(file_header + all_frames_bytes)
    return out_path


@dataclass
class AsepriteDocument:
    width: int
    height: int
    color_depth: int
    frame_count: int
    durations_ms: List[int]
    layers: List[Dict[str, Any]]           # [{"name", "visible", "opacity", "layer_type", "frames": List[Image]}]
    composited_frames: List[Image.Image]   # Flattened visible RGBA frames
    tags: List[Dict[str, Any]] = field(default_factory=list)
    palette: List[RGBA] = field(default_factory=list)
    slices: List[Dict[str, Any]] = field(default_factory=list)

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "color_depth": self.color_depth,
            "frame_count": self.frame_count,
            "durations_ms": self.durations_ms,
            "layers": [
                {
                    "index": idx,
                    "name": l["name"],
                    "visible": l["visible"],
                    "opacity": l["opacity"],
                    "is_group": l["layer_type"] == 1,
                }
                for idx, l in enumerate(self.layers)
            ],
            "tags": self.tags,
            "palette_size": len(self.palette),
            "slices": self.slices,
        }


def _decode_raw_cel_pixels(
    raw: bytes,
    cw: int,
    ch: int,
    color_depth: int,
    palette: Sequence[RGBA],
    transparent_idx: int,
) -> Image.Image:
    if color_depth == 32:
        expected = cw * ch * 4
        if len(raw) < expected:
            raw = raw + b"\x00" * (expected - len(raw))
        return Image.frombytes("RGBA", (cw, ch), raw[:expected])

    if color_depth == 16:
        # Grayscale + Alpha (2 bytes/px)
        px_out: List[RGBA] = []
        for i in range(0, min(len(raw), cw * ch * 2), 2):
            v, a = raw[i], raw[i + 1]
            px_out.append((v, v, v, a))
        im = Image.new("RGBA", (cw, ch))
        im.putdata(px_out)
        return im

    if color_depth == 8:
        px_out = []
        for i in range(min(len(raw), cw * ch)):
            idx = raw[i]
            if idx == transparent_idx:
                px_out.append((0, 0, 0, 0))
            elif idx < len(palette):
                px_out.append(palette[idx])
            else:
                px_out.append((0, 0, 0, 255))
        im = Image.new("RGBA", (cw, ch))
        im.putdata(px_out)
        return im

    raise ValueError(f"Unsupported .aseprite color depth: {color_depth}")


def read_aseprite(source: Union[str, Path, bytes]) -> AsepriteDocument:
    """Parse a binary `.ase` / `.aseprite` file into layers, cels, tags, slices, palette, and RGBA frames."""
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    if len(data) < 128:
        raise ValueError("Invalid .aseprite file: shorter than 128-byte header.")

    (
        _fsize,
        magic,
        n_frames,
        width,
        height,
        color_depth,
        flags,
        speed_fallback,
        _z1,
        _z2,
        transparent_idx,
        _ign,
        _num_colors,
    ) = struct.unpack_from("<IHHHHHIHIIB3sH", data, 0)

    if magic != ASE_FILE_MAGIC:
        raise ValueError(f"Invalid .aseprite magic: 0x{magic:04X} (expected 0xA5E0).")

    opacity_valid = bool(flags & 1)
    palette: List[RGBA] = [(0, 0, 0, 255)] * 256
    layers: List[Dict[str, Any]] = []
    durations_ms: List[int] = []
    tags: List[Dict[str, Any]] = []
    slices: List[Dict[str, Any]] = []

    # Store per-layer, per-frame `(canvas_rgba, cel_opacity)`
    cels_grid: Dict[Tuple[int, int], Tuple[Image.Image, int]] = {}

    pos = 128
    for f_idx in range(n_frames):
        if pos + 16 > len(data):
            break
        f_bytes, f_magic, old_chunks, f_dur, _fut, new_chunks = struct.unpack_from("<IHHH2sI", data, pos)
        if f_magic != ASE_FRAME_MAGIC:
            raise ValueError(f"Invalid frame {f_idx} magic: 0x{f_magic:04X}")

        durations_ms.append(f_dur if f_dur > 0 else max(10, speed_fallback or 100))
        chunk_count = new_chunks if new_chunks != 0 else old_chunks

        c_pos = pos + 16
        frame_end = pos + f_bytes

        for _ in range(chunk_count):
            if c_pos + 6 > frame_end:
                break
            c_size, c_type = struct.unpack_from("<IH", data, c_pos)
            payload_start = c_pos + 6
            payload_end = c_pos + max(6, c_size)

            if c_type == CHUNK_PALETTE:
                p_size, first_idx, last_idx = struct.unpack_from("<III", data, payload_start)
                if p_size > len(palette):
                    palette.extend([(0, 0, 0, 255)] * (p_size - len(palette)))
                p_cur = payload_start + 20
                for pidx in range(first_idx, last_idx + 1):
                    if p_cur + 6 > payload_end:
                        break
                    eflags, r, g, b, a = struct.unpack_from("<HBBBB", data, p_cur)
                    p_cur += 6
                    if eflags & 1:
                        _, p_cur = _unpack_ase_string(data, p_cur)
                    if 0 <= pidx < len(palette):
                        palette[pidx] = (r, g, b, a)

            elif c_type in (CHUNK_OLD_PALETTE_4, CHUNK_OLD_PALETTE_11) and not any(
                c != (0, 0, 0, 255) for c in palette[:16]
            ):
                scale = 4 if c_type == CHUNK_OLD_PALETTE_11 else 1
                (packets,) = struct.unpack_from("<H", data, payload_start)
                p_cur = payload_start + 2
                c_idx = 0
                for _ in range(packets):
                    skip, cnt = struct.unpack_from("<BB", data, p_cur)
                    p_cur += 2
                    c_idx += skip
                    actual_cnt = 256 if cnt == 0 else cnt
                    for _ in range(actual_cnt):
                        r, g, b = struct.unpack_from("<BBB", data, p_cur)
                        p_cur += 3
                        if c_idx < len(palette):
                            palette[c_idx] = (min(255, r * scale), min(255, g * scale), min(255, b * scale), 255)
                        c_idx += 1

            elif c_type == CHUNK_LAYER:
                l_flags, l_type, child_lvl, _dw, _dh, blend, l_op = struct.unpack_from(
                    "<HHHHHHB", data, payload_start
                )
                l_name, _ = _unpack_ase_string(data, payload_start + 16)
                layers.append({
                    "name": l_name,
                    "visible": bool(l_flags & 1),
                    "layer_type": l_type,
                    "child_level": child_lvl,
                    "blend_mode": blend,
                    "opacity": l_op if opacity_valid else 255,
                    "frames": [],
                })

            elif c_type == CHUNK_CEL:
                l_idx, cx, cy, c_op, cel_type, _z = struct.unpack_from("<HhhBHh", data, payload_start)
                cel_body = payload_start + 16
                if cel_type == 1:
                    (linked_f,) = struct.unpack_from("<H", data, cel_body)
                    if (l_idx, linked_f) in cels_grid:
                        prev_im, _ = cels_grid[(l_idx, linked_f)]
                        cels_grid[(l_idx, f_idx)] = (prev_im.copy(), c_op)
                elif cel_type in (0, 2):
                    cw, ch = struct.unpack_from("<HH", data, cel_body)
                    raw_stream = data[cel_body + 4 : payload_end]
                    if cel_type == 2:
                        raw_px = zlib.decompress(raw_stream)
                    else:
                        raw_px = raw_stream
                    patch = _decode_raw_cel_pixels(raw_px, cw, ch, color_depth, palette, transparent_idx)
                    full_cel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
                    full_cel.paste(patch, (cx, cy))
                    cels_grid[(l_idx, f_idx)] = (full_cel, c_op)

            elif c_type == CHUNK_TAGS:
                (num_tags,) = struct.unpack_from("<H", data, payload_start)
                t_cur = payload_start + 10
                for _ in range(num_tags):
                    if t_cur + 17 > payload_end:
                        break
                    t_from, t_to, d_byte, repeat, _f6, tr, tg, tb, _z = struct.unpack_from(
                        "<HHBH6sBBBB", data, t_cur
                    )
                    t_name, t_cur = _unpack_ase_string(data, t_cur + 17)
                    tags.append({
                        "name": t_name,
                        "from": t_from,
                        "to": t_to,
                        "direction": _BYTE_TO_DIR.get(d_byte, "forward"),
                        "repeat": repeat,
                        "color": f"#{tr:02X}{tg:02X}{tb:02X}",
                    })

            elif c_type == CHUNK_SLICE:
                num_keys, s_flags, _res = struct.unpack_from("<III", data, payload_start)
                s_name, s_cur = _unpack_ase_string(data, payload_start + 12)
                s_keys = []
                for _ in range(num_keys):
                    if s_cur + 20 > payload_end:
                        break
                    kf, sx, sy, sw, sh = struct.unpack_from("<IiiII", data, s_cur)
                    s_cur += 20
                    k_entry: Dict[str, Any] = {"frame": kf, "bounds": {"x": sx, "y": sy, "w": sw, "h": sh}}
                    if s_flags & 1 and s_cur + 16 <= payload_end:
                        ccx, ccy, ccw, cch = struct.unpack_from("<iiII", data, s_cur)
                        s_cur += 16
                        k_entry["center"] = {"x": ccx, "y": ccy, "w": ccw, "h": cch}
                    if s_flags & 2 and s_cur + 8 <= payload_end:
                        ppx, ppy = struct.unpack_from("<ii", data, s_cur)
                        s_cur += 8
                        k_entry["pivot"] = {"x": ppx, "y": ppy}
                    s_keys.append(k_entry)
                slices.append({"name": s_name, "flags": s_flags, "keys": s_keys})

            c_pos = payload_end
        pos = frame_end

    # Populate each layer's frame list & composite visible image layers bottom-to-top
    if not layers:
        layers.append({"name": "Layer 1", "visible": True, "layer_type": 0, "child_level": 0, "blend_mode": 0, "opacity": 255, "frames": []})

    for l_idx, layer in enumerate(layers):
        l_frames: List[Image.Image] = []
        for f_idx in range(len(durations_ms)):
            if (l_idx, f_idx) in cels_grid:
                cel_im, c_op = cels_grid[(l_idx, f_idx)]
                eff_alpha = (c_op / 255.0) * (layer["opacity"] / 255.0)
                if eff_alpha < 0.999:
                    r, g, b, a = cel_im.split()
                    a = a.point(lambda v, k=eff_alpha: round(v * k))
                    cel_im = Image.merge("RGBA", (r, g, b, a))
                l_frames.append(cel_im)
            else:
                l_frames.append(Image.new("RGBA", (width, height), (0, 0, 0, 0)))
        layer["frames"] = l_frames

    composited: List[Image.Image] = []
    for f_idx in range(len(durations_ms)):
        comp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for layer in layers:
            if layer["visible"] and layer["layer_type"] == 0:
                comp = Image.alpha_composite(comp, layer["frames"][f_idx])
        composited.append(comp)

    return AsepriteDocument(
        width=width,
        height=height,
        color_depth=color_depth,
        frame_count=len(durations_ms),
        durations_ms=durations_ms,
        layers=layers,
        composited_frames=composited,
        tags=tags,
        palette=palette,
        slices=slices,
    )


def generate_aseprite_layer_sheet(
    doc: AsepriteDocument,
    title: str = "Decoded .aseprite Binary Layer & Timeline Breakdown",
    scale: int = 3,
    max_frames: int = 12,
) -> Image.Image:
    """Render an Aseprite-Timeline-style visual matrix decoded directly from an `AsepriteDocument`."""
    sc = max(2, scale)
    fw, fh = doc.width, doc.height
    cw, ch = fw * sc, fh * sc
    shown_frames = min(doc.frame_count, max_frames)

    # Display layers top-to-bottom (matching Aseprite's visual layer stack, highest index on top)
    vis_layers = list(reversed([l for l in doc.layers if l["layer_type"] == 0]))

    pad = 16
    left_col_w = 136
    cell_gap = 6
    tag_bar_h = 22 if doc.tags else 0
    header_h = 54 + tag_bar_h

    total_rows = len(vis_layers) + 1  # +1 for bottom Master Composite row
    sheet_w = max(620, pad * 2 + left_col_w + shown_frames * (cw + cell_gap))
    sheet_h = header_h + total_rows * (ch + cell_gap) + pad + 12

    sheet = Image.new("RGB", (sheet_w, sheet_h), (24, 26, 34))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    draw.text(
        (pad, 10),
        f"{title} | {fw}x{fh}px | {len(vis_layers)} Layers | {doc.frame_count} Frames | {len(doc.tags)} Tags",
        fill=(240, 245, 255),
        font=font,
    )

    # Draw Frame Tag Colored Banners across timeline columns
    if doc.tags:
        ty = 30
        for idx, t in enumerate(doc.tags):
            f0 = max(0, int(t["from"]))
            f1 = min(shown_frames - 1, int(t["to"]))
            if f0 > f1:
                continue
            x0 = pad + left_col_w + f0 * (cw + cell_gap)
            x1 = pad + left_col_w + f1 * (cw + cell_gap) + cw - 1
            tc = parse_color(t.get("color", "#41A6F6"))[:3]
            draw.rectangle([x0, ty, x1, ty + 16], fill=tc, outline=(230, 235, 245))
            draw.text((x0 + 4, ty + 3), f"{t['name']} [{t['from']}..{t['to']}]", fill=(18, 20, 28), font=font)

    col_lbl_y = header_h - 16
    for f_idx in range(shown_frames):
        fx = pad + left_col_w + f_idx * (cw + cell_gap)
        draw.text((fx + 2, col_lbl_y), f"F{f_idx} ({doc.durations_ms[f_idx]}ms)", fill=(175, 190, 220), font=font)

    def _paste_cell(im: Image.Image, x: int, y: int, highlight: bool = False) -> None:
        bg = Image.new("RGBA", (cw, ch), (44, 48, 62, 255) if highlight else (34, 38, 48, 255))
        up = im.convert("RGBA").resize((cw, ch), Image.Resampling.NEAREST)
        sheet.paste(Image.alpha_composite(bg, up).convert("RGB"), (x, y))
        border_c = (120, 185, 245) if highlight else (68, 74, 92)
        draw.rectangle([x - 1, y - 1, x + cw, y + ch], outline=border_c)

    # Individual Layer Rows
    for r_idx, layer in enumerate(vis_layers):
        ry = header_h + r_idx * (ch + cell_gap)
        draw.rectangle([pad, ry, pad + left_col_w - 8, ry + ch], fill=(34, 38, 48), outline=(72, 80, 98))
        eye = "V" if layer["visible"] else "H"
        draw.text((pad + 6, ry + ch // 2 - 5), f"[{eye}] {layer['name']}", fill=(220, 230, 245), font=font)
        for f_idx in range(shown_frames):
            fx = pad + left_col_w + f_idx * (cw + cell_gap)
            _paste_cell(layer["frames"][f_idx], fx, ry)

    # Bottom Composited Result Row
    comp_y = header_h + len(vis_layers) * (ch + cell_gap) + 6
    draw.rectangle([pad, comp_y, pad + left_col_w - 8, comp_y + ch], fill=(42, 56, 78), outline=(120, 185, 245))
    draw.text((pad + 6, comp_y + ch // 2 - 5), "[*] COMPOSITED", fill=(255, 245, 190), font=font)
    for f_idx in range(shown_frames):
        fx = pad + left_col_w + f_idx * (cw + cell_gap)
        _paste_cell(doc.composited_frames[f_idx], fx, comp_y, highlight=True)

    return sheet
