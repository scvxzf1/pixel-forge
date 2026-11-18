"""Palette definitions, perceptual color matching, reference palette extraction,
hue-shifted shading ramp generation, and semantic recoloring.
"""
from __future__ import annotations

import colorsys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union
from PIL import Image

RGBA = Tuple[int, int, int, int]
ColorDef = Union[str, Tuple[int, int, int], RGBA]

# Safe single-character pool for auto-generated ASCII grids (excludes '.', ' ', quotes, backslash)
SAFE_ASCII_CHARS = (
    "KW1234567890"
    "RrOoYyGgTtCcBbNnPpMmSsLlEeAaUuIiDd"
    "FGHIJQVXZfghijqvwxz"
    "@#$%&*+=~^?"
)

# 1. Classic Built-in Palettes
_PICO8_HEX = (
    "000000 1D2B53 7E2553 008751 AB5236 5F574F C2C3C7 FFF1E8 "
    "FF004D FFA300 FFEC27 00E436 29ADFF 83769C FF77A8 FFCCAA"
).split()
PALETTE_PICO8: Dict[str, str] = {k: f"#{v}" for k, v in zip("0123456789ABCDEF", _PICO8_HEX)}
PALETTE_PICO8.update({
    "K": "#000000", "N": "#1D2B53", "P": "#7E2553", "g": "#008751",
    "b": "#AB5236", "d": "#5F574F", "s": "#C2C3C7", "W": "#FFF1E8",
    "R": "#FF004D", "O": "#FFA300", "Y": "#FFEC27", "G": "#00E436",
    "U": "#29ADFF", "I": "#83769C", "M": "#FF77A8", "S": "#FFCCAA",
})

PALETTE_ENDESGA32: Dict[str, str] = {
    "K": "#181425", "W": "#FFFFFF", "1": "#C0CBDC", "2": "#8B9BB4",
    "3": "#5A6988", "4": "#3A4466", "5": "#262B44",
    "r": "#A22633", "R": "#E43B44", "O": "#F77622", "Y": "#FEAE34", "y": "#FEE761",
    "G": "#63C74D", "g": "#3E8948", "t": "#265C42", "T": "#193C3E",
    "C": "#2CE8F5", "c": "#73EFF7", "B": "#0099DB", "b": "#124E89", "u": "#257179",
    "P": "#B55088", "p": "#68386C", "M": "#F6757A",
    "S": "#EEC39A", "n": "#E8B796", "s": "#D9A066", "a": "#D77643",
    "o": "#BE4A2F", "L": "#8F563B", "l": "#663931", "e": "#45283C",
}

PALETTE_SWEETIE16: Dict[str, str] = {
    "K": "#1A1C2C", "p": "#5D275D", "r": "#B13E53", "O": "#EF7D57",
    "Y": "#FFCD75", "G": "#A7F070", "g": "#38B764", "t": "#257179",
    "N": "#29366F", "b": "#3B5DC9", "B": "#41A6F6", "C": "#73EFF7",
    "W": "#F4F4F4", "1": "#94B0C2", "2": "#566C86", "3": "#333C57",
}

_RESURRECT64_HEX = (
    "2E222F 3E3546 625565 966C6C AB947A 694F62 7F708A 9BABB2 C7DCD0 FFFFFF "
    "6E2727 B33831 EA4F36 F57D4A AE2334 E83B3B FB6B1D F79617 F9C22B 7A3045 "
    "9E4539 CD683D E6904E FBB954 4C3E24 676633 A2A947 D5E04B FBFF86 165A4C "
    "239063 1EBC73 91DB69 CDDF6C 313638 374E4A 547E64 92A984 B2BA90 0B5E65 "
    "0B8A8F 0EAF9B 30E1B9 8FF8E2 323353 484A77 4D65B4 4D9BE6 8FD3FF 45293F "
    "6B3E75 905EA9 A884F3 EAADED 753C54 A24B6F CF657F ED8099 831C5D C32454 "
    "F04F78 F68181 FCA790 FDCBB0"
).split()
_RES64_KEYS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz@#"
PALETTE_RESURRECT64: Dict[str, str] = {
    k: f"#{v}" for k, v in zip(_RES64_KEYS, _RESURRECT64_HEX)
}

PALETTE_GAMEBOY: Dict[str, str] = {
    "0": "#0F380F", "1": "#306230", "2": "#8BAC0F", "3": "#9BBC0F",
    "K": "#0F380F", "d": "#306230", "g": "#8BAC0F", "W": "#9BBC0F",
}

PALETTE_MONO1BIT: Dict[str, str] = {
    "0": "#181425", "1": "#F4F4F4",
    "K": "#181425", "W": "#F4F4F4",
}

for _pal in (
    PALETTE_PICO8,
    PALETTE_ENDESGA32,
    PALETTE_SWEETIE16,
    PALETTE_RESURRECT64,
    PALETTE_GAMEBOY,
    PALETTE_MONO1BIT,
):
    _pal.update({".": "#00000000", " ": "#00000000"})

BUILTIN_PALETTES: Dict[str, Dict[str, str]] = {
    "endesga32": PALETTE_ENDESGA32,
    "pico8": PALETTE_PICO8,
    "sweetie16": PALETTE_SWEETIE16,
    "resurrect64": PALETTE_RESURRECT64,
    "gameboy": PALETTE_GAMEBOY,
    "mono1bit": PALETTE_MONO1BIT,
}


def parse_color(c: ColorDef) -> RGBA:
    """Convert #RRGGBB, #RRGGBBAA, (R,G,B), or (R,G,B,A) into a strict RGBA tuple."""
    if isinstance(c, tuple):
        if len(c) not in (3, 4) or any(
            not isinstance(v, int) or isinstance(v, bool) or not (0 <= v <= 255) for v in c
        ):
            raise ValueError(f"Invalid RGB/RGBA tuple: {c!r}")
        return (c[0], c[1], c[2], 255) if len(c) == 3 else (c[0], c[1], c[2], c[3])
    if isinstance(c, str):
        h = c.strip().removeprefix("#")
        if len(h) == 6:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
        if len(h) == 8:
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
    raise ValueError(f"Invalid color specification: {c!r}")


def rgba_to_hex(c: RGBA, include_alpha: str = "auto") -> str:
    """Format an RGBA tuple as #RRGGBB or #RRGGBBAA."""
    r, g, b, a = c
    if include_alpha == "always" or (include_alpha == "auto" and a < 255):
        return f"#{r:02X}{g:02X}{b:02X}{a:02X}"
    return f"#{r:02X}{g:02X}{b:02X}"


def normalize_rgba(c: RGBA) -> RGBA:
    """Normalize fully transparent pixels to canonical (0, 0, 0, 0)."""
    return (0, 0, 0, 0) if c[3] == 0 else c


def img_pixels(img: Image.Image) -> List[Any]:
    """Pillow 9..14+ compatible flat pixel sequence reader (avoids Pillow 13 getdata deprecation)."""
    if hasattr(img, "get_flattened_data"):
        return list(img.get_flattened_data())
    return list(img.getdata())


def get_palette(palette: Union[str, Dict[str, ColorDef], None] = None) -> Dict[str, RGBA]:
    """Resolve a built-in palette name or user dict into a normalized {char: RGBA} mapping."""
    if palette is None:
        raw: Dict[str, ColorDef] = dict(PALETTE_ENDESGA32)
    elif isinstance(palette, str):
        key = palette.strip().lower().replace("-", "").replace("_", "")
        if key not in BUILTIN_PALETTES:
            raise ValueError(
                f"Unknown built-in palette {palette!r}. Available: {sorted(BUILTIN_PALETTES)}"
            )
        raw = dict(BUILTIN_PALETTES[key])
    elif isinstance(palette, dict):
        raw = dict(palette)
    else:
        raise TypeError(f"Expected palette name, dict, or None; got {type(palette).__name__}")

    out = {k: normalize_rgba(parse_color(v)) for k, v in raw.items()}
    out["."] = (0, 0, 0, 0)
    out[" "] = (0, 0, 0, 0)
    return out


def canonical_char_map(palette: Dict[str, ColorDef]) -> Dict[RGBA, str]:
    """Build a reverse lookup {RGBA: preferred_char}. Prefers semantic letters over digits."""
    rgba_pal = get_palette(palette)
    rev: Dict[RGBA, str] = {(0, 0, 0, 0): "."}
    # Sort keys so semantic alphabetic aliases win over raw hex digits when deduplicating
    ordered_keys = sorted(
        (k for k in rgba_pal if k not in (".", " ")),
        key=lambda ch: (0 if ch.isalpha() else 1, ch),
    )
    for ch in ordered_keys:
        col = rgba_pal[ch]
        if col[3] == 0:
            continue
        if col not in rev:
            rev[col] = ch
    return rev


def luminance(c: RGBA) -> float:
    """Perceptual relative luminance in [0.0, 1.0]."""
    r, g, b, _ = c
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def color_distance_sq(c1: RGBA, c2: RGBA) -> float:
    """Redmean weighted perceptual RGB+Alpha squared distance."""
    if c1[3] == 0 and c2[3] == 0:
        return 0.0
    if (c1[3] == 0) != (c2[3] == 0):
        return 1e9
    rmean = 0.5 * (c1[0] + c2[0])
    dr = c1[0] - c2[0]
    dg = c1[1] - c2[1]
    db = c1[2] - c2[2]
    da = c1[3] - c2[3]
    return (
        (2.0 + rmean / 256.0) * dr * dr
        + 4.0 * dg * dg
        + (2.0 + (255.0 - rmean) / 256.0) * db * db
        + 2.0 * da * da
    )


def nearest_palette_char(
    rgba: RGBA,
    palette: Dict[str, ColorDef],
    alpha_threshold: int = 16,
) -> str:
    """Find the closest character in `palette` for `rgba` using perceptual distance."""
    if rgba[3] < alpha_threshold:
        return "."
    rev = canonical_char_map(palette)
    opaque_candidates = [(col, ch) for col, ch in rev.items() if col[3] > 0]
    if not opaque_candidates:
        return "."
    best_col, best_ch = min(opaque_candidates, key=lambda item: color_distance_sq(rgba, item[0]))
    return best_ch


def _preferred_candidates_for_color(c: RGBA) -> List[str]:
    """Suggest intuitive single-character mnemonics based on HSV hue/saturation/value."""
    r, g, b, _ = c
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    deg = h * 360.0

    if v < 0.16:
        return ["K", "0", "5", "e"]
    if s < 0.14:
        if v > 0.90:
            return ["W", "7", "1"]
        if v > 0.68:
            return ["1", "s", "6"]
        if v > 0.42:
            return ["2", "3", "d"]
        return ["4", "5", "K"]

    # Chromatic hue families: uppercase for brighter/vivid, lowercase for darker/shadow
    bright = v >= 0.58
    if deg < 18 or deg >= 342:
        return ["R", "M", "r", "o"] if bright else ["r", "R", "e", "p"]
    if deg < 44:
        if s < 0.55 and v > 0.65:
            return ["S", "n", "s", "a"]
        return ["O", "a", "S", "o"] if bright else ["L", "l", "o", "s"]
    if deg < 72:
        return ["Y", "y", "S", "O"] if bright else ["s", "L", "l", "Y"]
    if deg < 160:
        return ["G", "g", "t", "T"] if bright else ["g", "t", "T", "G"]
    if deg < 200:
        return ["C", "c", "u", "B"] if bright else ["u", "t", "c", "b"]
    if deg < 255:
        return ["B", "U", "b", "N"] if bright else ["b", "N", "4", "B"]
    if deg < 305:
        return ["P", "I", "p", "M"] if bright else ["p", "P", "e", "N"]
    return ["M", "P", "R", "p"] if bright else ["p", "r", "M", "e"]


def assign_semantic_chars(colors: Sequence[RGBA]) -> Dict[str, str]:
    """Assign intuitive single-character ASCII keys to a list of RGBA colors."""
    unique_opaque: List[RGBA] = []
    seen = set()
    for col in colors:
        nc = normalize_rgba(col)
        if nc[3] == 0 or nc in seen:
            continue
        seen.add(nc)
        unique_opaque.append(nc)

    if len(unique_opaque) > len(SAFE_ASCII_CHARS):
        raise ValueError(
            f"Too many unique colors ({len(unique_opaque)}) for single-char ASCII grid "
            f"(max {len(SAFE_ASCII_CHARS)}). Quantize with max_colors<=64 first."
        )

    # Sort darkest first so 'K' naturally claims the deepest outline color, and brightest claims 'W'
    sorted_cols = sorted(unique_opaque, key=luminance)
    used_chars = {".", " "}
    result: Dict[str, str] = {".": "#00000000"}

    # Reserve 'W' for brightest if very bright
    brightest_char_override: Dict[RGBA, str] = {}
    if len(sorted_cols) >= 2 and luminance(sorted_cols[-1]) > 0.82:
        brightest_char_override[sorted_cols[-1]] = "W"

    for col in sorted_cols:
        chosen = None
        if col in brightest_char_override and brightest_char_override[col] not in used_chars:
            chosen = brightest_char_override[col]
        else:
            for cand in _preferred_candidates_for_color(col):
                if cand not in used_chars and (cand != "W" or col in brightest_char_override):
                    chosen = cand
                    break
        if chosen is None:
            for fallback in SAFE_ASCII_CHARS:
                if fallback not in used_chars:
                    chosen = fallback
                    break
        if chosen is None:
            raise RuntimeError("Exhausted SAFE_ASCII_CHARS")
        used_chars.add(chosen)
        result[chosen] = rgba_to_hex(col)

    return result


def extract_palette(
    source: Union[str, Path, Image.Image, Sequence[Image.Image]],
    max_colors: int = 32,
    alpha_threshold: int = 16,
) -> Dict[str, str]:
    """Extract a clean single-char semantic palette from an image, GIF, or frame list."""
    if not (2 <= max_colors <= len(SAFE_ASCII_CHARS)):
        raise ValueError(f"max_colors must be in [2, {len(SAFE_ASCII_CHARS)}]")

    frames: List[Image.Image] = []
    if isinstance(source, (str, Path)):
        with Image.open(source) as im:
            n_frames = getattr(im, "n_frames", 1)
            for idx in range(n_frames):
                im.seek(idx)
                frames.append(im.convert("RGBA"))
    elif isinstance(source, Image.Image):
        frames.append(source.convert("RGBA"))
    else:
        frames = [f.convert("RGBA") for f in source]

    opaque_pixels: List[RGBA] = []
    unique_set = set()
    for f in frames:
        for r, g, b, a in img_pixels(f):
            if a >= alpha_threshold:
                # Preserve exact alpha if semi-transparent, otherwise opaque
                px = (r, g, b, a)
                opaque_pixels.append(px)
                unique_set.add(px)

    if not opaque_pixels:
        return {".": "#00000000", "K": "#181425"}

    if len(unique_set) <= max_colors:
        return assign_semantic_chars(list(unique_set))

    # Quantize RGB of opaque pixels via Median Cut without dithering
    strip = Image.new("RGB", (len(opaque_pixels), 1))
    strip.putdata([(p[0], p[1], p[2]) for p in opaque_pixels])
    quant = strip.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    raw_pal = quant.getpalette() or []
    used_indices = sorted(set(img_pixels(quant)))
    quant_colors: List[RGBA] = []
    for idx in used_indices:
        base = idx * 3
        if base + 2 < len(raw_pal):
            quant_colors.append((raw_pal[base], raw_pal[base + 1], raw_pal[base + 2], 255))
    return assign_semantic_chars(quant_colors)


def generate_shading_ramp(
    base_color: ColorDef,
    steps: int = 4,
    warm_light: bool = True,
) -> List[str]:
    """Generate a hue-shifted pixel-art shading ramp from darkest outline/shadow to highlight.

    Shadows shift toward cool blue/indigo (~250 deg) with boosted saturation;
    highlights shift toward warm sunlight (~55 deg) with crisp brightness.
    """
    if not (2 <= steps <= 8):
        raise ValueError("steps must be between 2 and 8")
    r, g, b, _ = parse_color(base_color)
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    base_deg = h * 360.0

    shadow_target = 250.0 if warm_light else 55.0
    light_target = 55.0 if warm_light else 205.0

    def _shortest_angle_delta(src: float, dst: float) -> float:
        return ((dst - src + 540.0) % 360.0) - 180.0

    ramp: List[str] = []
    mid_pos = (steps - 1) * 0.55
    for i in range(steps):
        t = (i - mid_pos) / max(1.0, steps - 1)  # negative = shadow, positive = highlight
        if t < 0:
            amt = abs(t)
            delta = _shortest_angle_delta(base_deg, shadow_target) * (0.28 * amt)
            nh = ((base_deg + delta) % 360.0) / 360.0
            ns = min(1.0, s + 0.18 * amt) if s > 0.05 else min(0.22, 0.15 * amt)
            nv = max(0.08, v * (1.0 - 0.72 * amt))
        else:
            amt = t
            delta = _shortest_angle_delta(base_deg, light_target) * (0.24 * amt)
            nh = ((base_deg + delta) % 360.0) / 360.0
            ns = max(0.05, s * (1.0 - 0.38 * amt)) if s > 0.05 else 0.04
            nv = min(0.99, v + (1.0 - v) * min(0.92, 0.85 * amt))
        rr, gg, bb = colorsys.hsv_to_rgb(nh, ns, nv)
        ramp.append(rgba_to_hex((round(rr * 255), round(gg * 255), round(bb * 255), 255)))
    return ramp


def analyze_palette_ramps(palette: Dict[str, ColorDef]) -> Dict[str, List[Dict[str, Union[str, float]]]]:
    """Group a palette into hue families sorted from shadow/outline -> midtone -> highlight."""
    rev = canonical_char_map(palette)
    groups: Dict[str, List[Tuple[float, str, RGBA]]] = {
        "neutral": [],
        "red_pink": [],
        "orange_brown_skin": [],
        "yellow": [],
        "green": [],
        "cyan_teal": [],
        "blue": [],
        "purple": [],
    }
    for col, ch in rev.items():
        if col[3] == 0:
            continue
        r, g, b, _ = col
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        lum = round(luminance(col), 3)
        deg = h * 360.0
        if s < 0.15 or v < 0.14:
            fam = "neutral"
        elif deg < 18 or deg >= 335:
            fam = "red_pink"
        elif deg < 46:
            fam = "orange_brown_skin"
        elif deg < 72:
            fam = "yellow"
        elif deg < 162:
            fam = "green"
        elif deg < 200:
            fam = "cyan_teal"
        elif deg < 260:
            fam = "blue"
        elif deg < 335:
            fam = "purple"
        else:
            fam = "red_pink"
        groups[fam].append((lum, ch, col))

    roles_by_len = {
        1: ["base"],
        2: ["shadow", "highlight"],
        3: ["shadow", "midtone", "highlight"],
        4: ["outline_or_deep_shadow", "shadow", "midtone", "highlight"],
    }
    summary: Dict[str, List[Dict[str, Union[str, float]]]] = {}
    for fam, items in groups.items():
        if not items:
            continue
        items.sort(key=lambda x: x[0])
        n = len(items)
        entries = []
        for idx, (lum, ch, col) in enumerate(items):
            if n in roles_by_len:
                role = roles_by_len[n][idx]
            elif idx == 0:
                role = "deep_shadow"
            elif idx == n - 1:
                role = "highlight"
            elif idx < n // 2:
                role = "shadow"
            else:
                role = "midtone"
            entries.append({
                "char": ch,
                "hex": rgba_to_hex(col),
                "luminance": lum,
                "suggested_role": role,
            })
        summary[fam] = entries
    return summary


def remap_grid_chars(
    grid: Union[str, Sequence[str]],
    char_map: Dict[str, str],
) -> List[str]:
    """Simultaneously swap characters in an ASCII grid (safe for cyclic swaps like R<->B)."""
    lines = grid.strip("\r\n").splitlines() if isinstance(grid, str) else list(grid)
    for k, v in char_map.items():
        if len(k) != 1 or len(v) != 1:
            raise ValueError(f"Grid character map keys/values must be single chars: {k!r}->{v!r}")
    return ["".join(char_map.get(ch, ch) for ch in row) for row in lines]


def recolor_image(
    img: Image.Image,
    color_map: Dict[ColorDef, ColorDef],
    palette: Optional[Union[str, Dict[str, ColorDef]]] = None,
    tolerance: int = 0,
) -> Image.Image:
    """Recolor an RGBA image using either palette keys (e.g. {'R': 'B'}) or hex/RGBA values."""
    pal = get_palette(palette) if palette is not None else None
    resolved_map: List[Tuple[RGBA, RGBA]] = []
    for src_spec, dst_spec in color_map.items():
        src_rgba = (
            pal[src_spec]
            if (pal is not None and isinstance(src_spec, str) and src_spec in pal)
            else normalize_rgba(parse_color(src_spec))
        )
        dst_rgba = (
            pal[dst_spec]
            if (pal is not None and isinstance(dst_spec, str) and dst_spec in pal)
            else normalize_rgba(parse_color(dst_spec))
        )
        resolved_map.append((src_rgba, dst_rgba))

    rgba_img = img.convert("RGBA")
    exact_lookup = {src: dst for src, dst in resolved_map}
    tol_sq = tolerance * tolerance * 9.0
    new_data: List[RGBA] = []

    for px in img_pixels(rgba_img):
        npx = normalize_rgba(px)
        if npx in exact_lookup:
            new_data.append(exact_lookup[npx])
        elif tolerance > 0 and npx[3] > 0:
            best_dst = None
            best_d = tol_sq + 1.0
            for src, dst in resolved_map:
                d = color_distance_sq(npx, src)
                if d <= tol_sq and d < best_d:
                    best_d = d
                    best_dst = dst
            new_data.append(best_dst if best_dst is not None else npx)
        else:
            new_data.append(npx)

    out = Image.new("RGBA", rgba_img.size)
    out.putdata(new_data)
    return out
