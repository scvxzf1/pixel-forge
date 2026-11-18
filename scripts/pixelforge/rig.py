"""Multi-Layer Part Rigging (compact local ASCII parts + RotSprite hinge rotation +
grouped outlining) and Multi-Action SpriteActor state management (idle/walk/attack/...).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from PIL import Image

from .canvas import GridLike, normalize_grid, render_grid
from .palette import ColorDef, get_palette
from .transform import (
    add_ground_shadow,
    auto_outline,
    flash_image,
    flip_image,
    rotsprite,
    selective_outline,
)
from .vfx import composite_vfx, vfx_dust_puff, vfx_hit_spark, vfx_slash_arc

PartSource = Union[Image.Image, GridLike, Mapping[str, Union[Image.Image, GridLike]]]


@dataclass
class Part:
    """A riggable sprite sub-part placed at `offset=(ox, oy)` on the rig canvas."""

    name: str
    source: PartSource
    offset: Tuple[int, int] = (0, 0)
    pivot_local: Optional[Tuple[float, float]] = None
    pivot_canvas: Optional[Tuple[float, float]] = None
    z_index: int = 0
    outline_group: Optional[int] = 0  # Same int -> merged then outlined together; None -> no outline


class Rig:
    """Declarative 2D pixel-art part rig with RotSprite rotation and grouped outlining."""

    def __init__(
        self,
        canvas_size: Tuple[int, int],
        palette: Union[str, Dict[str, ColorDef], None] = "endesga32",
        outline_mode: str = "outer",  # 'outer' | 'selout' | 'none'
        outline_color: ColorDef = "#181425",
        light_dir: Tuple[float, float] = (-1.0, -1.0),
    ) -> None:
        if canvas_size[0] <= 0 or canvas_size[1] <= 0:
            raise ValueError("canvas_size must have positive width and height")
        if outline_mode not in ("outer", "selout", "none"):
            raise ValueError("outline_mode must be 'outer', 'selout', or 'none'")
        self.canvas_size = canvas_size
        self.palette = palette
        self.outline_mode = outline_mode
        self.outline_color = outline_color
        self.light_dir = light_dir
        self.parts: Dict[str, Part] = {}

    def add_part(
        self,
        name: str,
        source: PartSource,
        offset: Optional[Tuple[int, int]] = None,
        pivot_local: Optional[Tuple[float, float]] = None,
        pivot_canvas: Optional[Tuple[float, float]] = None,
        z_index: int = 0,
        outline_group: Optional[int] = 0,
        *,
        at: Optional[str] = None,
        attach_to: Optional[str] = None,
        side: str = "top",
        align: str = "center",
        overlap: int = 1,
        nudge: Tuple[int, int] = (0, 0),
        hinge: Optional[str] = None,
    ) -> "Rig":
        """Register a rig part via explicit `offset=(x, y)` OR zero-math semantic docking:
        e.g. `at='center'` or `attach_to='torso', side='top'|'left'|'right'|'bottom', hinge='grip'`.
        """
        dummy_part = Part(name=name, source=source)
        part_im = self._resolve_part_image(dummy_part)
        w, h = part_im.size
        cw, ch = self.canvas_size

        if offset is not None:
            ox, oy = offset
        elif attach_to is not None:
            if attach_to not in self.parts:
                raise ValueError(f"attach_to parent {attach_to!r} must be added before {name!r}.")
            parent = self.parts[attach_to]
            pim = self._resolve_part_image(parent)
            pw, ph = pim.size
            px0, py0 = parent.offset

            def _align_1d(p0: int, p_len: int, c_len: int) -> int:
                if align == "start":
                    return p0
                if align == "end":
                    return p0 + p_len - c_len
                return p0 + (p_len - c_len) // 2

            s_low = side.lower()
            if s_low == "top":
                ox, oy = _align_1d(px0, pw, w), py0 - h + overlap
            elif s_low == "bottom":
                ox, oy = _align_1d(px0, pw, w), py0 + ph - overlap
            elif s_low == "left":
                ox, oy = px0 - w + overlap, _align_1d(py0, ph, h)
            elif s_low == "right":
                ox, oy = px0 + pw - overlap, _align_1d(py0, ph, h)
            elif s_low == "center":
                ox, oy = px0 + (pw - w) // 2, py0 + (ph - h) // 2
            else:
                raise ValueError(f"Unknown attach side {side!r}; use top|bottom|left|right|center.")
        elif at is not None:
            a_low = at.lower()
            if a_low == "center":
                ox, oy = (cw - w) // 2, (ch - h) // 2
            elif a_low == "bottom_center":
                ox, oy = (cw - w) // 2, max(0, ch - h - 6)
            elif a_low == "top_center":
                ox, oy = (cw - w) // 2, 4
            else:
                raise ValueError(f"Unknown `at` anchor {at!r}; use center|bottom_center|top_center.")
        else:
            ox, oy = (0, 0)

        final_offset = (ox + nudge[0], oy + nudge[1])

        # Resolve semantic hinge if pivot_local not explicitly given
        resolved_pivot_local = pivot_local
        if resolved_pivot_local is None and pivot_canvas is None:
            eff_hinge = hinge
            if eff_hinge is None and attach_to is not None:
                s_low = side.lower()
                if any(k in name.lower() for k in ("sword", "weapon", "staff", "spear", "axe", "hammer")):
                    eff_hinge = "grip"
                elif s_low == "top":
                    eff_hinge = "bottom"
                elif s_low == "bottom":
                    eff_hinge = "top"
                elif s_low == "left":
                    eff_hinge = "right"
                elif s_low == "right":
                    eff_hinge = "left"

            if eff_hinge is not None:
                hl = eff_hinge.lower()
                if hl == "center":
                    resolved_pivot_local = ((w - 1) / 2.0, (h - 1) / 2.0)
                elif hl in ("bottom", "neck"):
                    resolved_pivot_local = ((w - 1) / 2.0, float(max(0, h - 1)))
                elif hl == "top":
                    resolved_pivot_local = ((w - 1) / 2.0, 0.0)
                elif hl in ("left", "shoulder_r"):
                    resolved_pivot_local = (0.0, (h - 1) / 2.0)
                elif hl in ("right", "shoulder_l"):
                    resolved_pivot_local = (float(max(0, w - 1)), (h - 1) / 2.0)
                elif hl == "grip":
                    resolved_pivot_local = ((w - 1) * 0.4, (h - 1) * 0.78)
                else:
                    raise ValueError(f"Unknown hinge {eff_hinge!r}; use center|neck|bottom|top|left|right|grip.")

        self.parts[name] = Part(
            name=name,
            source=source,
            offset=final_offset,
            pivot_local=resolved_pivot_local,
            pivot_canvas=pivot_canvas,
            z_index=z_index,
            outline_group=outline_group,
        )
        return self

    def _resolve_part_image(self, part: Part, variant: str = "default") -> Image.Image:
        src = part.source
        if isinstance(src, Mapping):
            if variant in src:
                chosen = src[variant]
            elif "default" in src:
                chosen = src["default"]
            else:
                chosen = next(iter(src.values()))
        else:
            chosen = src
        if isinstance(chosen, Image.Image):
            return chosen.convert("RGBA")
        return render_grid(chosen, palette=self.palette, pad_ragged=True)

    def _part_canvas_pivot(self, part: Part, part_img: Image.Image) -> Tuple[float, float]:
        if part.pivot_canvas is not None:
            return part.pivot_canvas
        ox, oy = part.offset
        if part.pivot_local is not None:
            return (ox + part.pivot_local[0], oy + part.pivot_local[1])
        return (ox + (part_img.width - 1) / 2.0, oy + (part_img.height - 1) / 2.0)

    def get_canvas_pivots(self) -> List[Tuple[float, float]]:
        pivots: List[Tuple[float, float]] = []
        for p in self.parts.values():
            im = self._resolve_part_image(p)
            pivots.append(self._part_canvas_pivot(p, im))
        return pivots

    def get_named_canvas_pivots(self) -> Dict[str, Tuple[float, float]]:
        out: Dict[str, Tuple[float, float]] = {}
        for pname, p in self.parts.items():
            im = self._resolve_part_image(p)
            out[pname] = self._part_canvas_pivot(p, im)
        return out

    def _apply_group_outline(self, layer_img: Image.Image) -> Image.Image:
        if self.outline_mode == "none":
            return layer_img
        if self.outline_mode == "selout":
            return selective_outline(
                layer_img,
                light_dir=self.light_dir,
                dark_color=self.outline_color,
                snap_palette=self.palette,
            )
        return auto_outline(layer_img, color=self.outline_color, connectivity=4, mode="outer")

    def render_pose(
        self,
        pose: Optional[Mapping[str, Mapping[str, Any]]] = None,
        under_layers: Optional[Sequence[Image.Image]] = None,
        over_layers: Optional[Sequence[Image.Image]] = None,
    ) -> Image.Image:
        """Render a single frame from declarative per-part pose overrides."""
        pose_map = pose or {}
        cw, ch = self.canvas_size

        # Build sorted list of active rendered parts: (z_index, insertion_order, outline_group, canvas_img)
        active_items: List[Tuple[int, int, Optional[int], Image.Image]] = []
        for order_idx, (pname, part) in enumerate(self.parts.items()):
            ov = pose_map.get(pname, {})
            if not ov.get("visible", True):
                continue

            variant = str(ov.get("variant", "default"))
            raw_part = self._resolve_part_image(part, variant=variant)

            if ov.get("flip_h", False) or ov.get("flip_v", False):
                raw_part = flip_image(
                    raw_part,
                    horizontal=bool(ov.get("flip_h", False)),
                    vertical=bool(ov.get("flip_v", False)),
                )

            # Place part onto full-size stage at part.offset
            stage = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            stage.paste(raw_part, part.offset)

            piv = ov.get("pivot", self._part_canvas_pivot(part, raw_part))
            angle = float(ov.get("angle", 0.0))
            dx = int(round(ov.get("dx", 0)))
            dy = int(round(ov.get("dy", 0)))
            sx = float(ov.get("scale_x", 1.0))
            sy = float(ov.get("scale_y", 1.0))

            transformed = rotsprite(
                stage,
                angle_deg=angle,
                pivot=piv,
                dx=dx,
                dy=dy,
                scale_x=sx,
                scale_y=sy,
            )

            f_mix = float(ov.get("flash_mix", 0.0))
            if f_mix > 0.0:
                transformed = flash_image(
                    transformed,
                    flash_color=ov.get("flash_color", "#FFFFFF"),
                    mix=f_mix,
                )

            z = int(ov.get("z_index", part.z_index))
            og = ov.get("outline_group", part.outline_group)
            active_items.append((z, order_idx, og, transformed))

        active_items.sort(key=lambda item: (item[0], item[1]))

        final = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        if under_layers:
            for ul in under_layers:
                final = Image.alpha_composite(final, ul.convert("RGBA"))

        # Merge contiguous runs sharing the same non-None outline_group, outline each run, then composite
        idx = 0
        while idx < len(active_items):
            _, _, og, img_layer = active_items[idx]
            if og is None:
                final = Image.alpha_composite(final, img_layer)
                idx += 1
            else:
                group_buf = img_layer.copy()
                idx += 1
                while idx < len(active_items) and active_items[idx][2] == og:
                    group_buf = Image.alpha_composite(group_buf, active_items[idx][3])
                    idx += 1
                group_buf = self._apply_group_outline(group_buf)
                final = Image.alpha_composite(final, group_buf)

        if over_layers:
            for ol in over_layers:
                final = Image.alpha_composite(final, ol.convert("RGBA"))

        return final

    def render_part_layers(
        self,
        pose: Optional[Mapping[str, Mapping[str, Any]]] = None,
        part_profiles: Optional[Mapping[str, str]] = None,
    ) -> List[Tuple[Image.Image, str]]:
        """Render individual z-sorted `(part_image, relief_profile)` layers for HD-2D Normal Map generation."""
        pose_map = pose or {}
        prof_map = part_profiles or {}
        cw, ch = self.canvas_size
        layers_info: List[Tuple[int, int, Image.Image, str]] = []

        for order_idx, (pname, part) in enumerate(self.parts.items()):
            ov = pose_map.get(pname, {})
            if not ov.get("visible", True):
                continue
            variant = str(ov.get("variant", "default"))
            raw_part = self._resolve_part_image(part, variant=variant)
            if ov.get("flip_h", False) or ov.get("flip_v", False):
                raw_part = flip_image(
                    raw_part,
                    horizontal=bool(ov.get("flip_h", False)),
                    vertical=bool(ov.get("flip_v", False)),
                )
            stage = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            stage.paste(raw_part, part.offset)
            piv = ov.get("pivot", self._part_canvas_pivot(part, raw_part))
            transformed = rotsprite(
                stage,
                angle_deg=float(ov.get("angle", 0.0)),
                pivot=piv,
                dx=int(round(ov.get("dx", 0))),
                dy=int(round(ov.get("dy", 0))),
                scale_x=float(ov.get("scale_x", 1.0)),
                scale_y=float(ov.get("scale_y", 1.0)),
            )
            if part.outline_group is not None:
                transformed = self._apply_group_outline(transformed)

            default_prof = (
                "ridge"
                if any(k in pname.lower() for k in ("sword", "blade", "spear", "dagger", "crystal", "horn"))
                else "dome"
            )
            prof = prof_map.get(pname, default_prof)
            z = int(ov.get("z_index", part.z_index))
            layers_info.append((z, order_idx, transformed, prof))

        layers_info.sort(key=lambda item: (item[0], item[1]))
        return [(im, prof) for _, _, im, prof in layers_info]

    def render_named_layers_sequence(
        self,
        poses: Sequence[Mapping[str, Mapping[str, Any]]],
        include_part_outlines: bool = True,
    ) -> List[Tuple[str, List[Optional[Image.Image]]]]:
        """Render a sequence of poses into bottom-to-top independent named layers for `.aseprite` export."""
        cw, ch = self.canvas_size
        ordered_parts = sorted(
            enumerate(self.parts.values()),
            key=lambda item: (item[1].z_index, item[0]),
        )
        result: List[Tuple[str, List[Optional[Image.Image]]]] = []

        for _, part in ordered_parts:
            pname = part.name
            p_frames: List[Optional[Image.Image]] = []
            for pose in poses:
                ov = pose.get(pname, {})
                if not ov.get("visible", True):
                    p_frames.append(None)
                    continue
                variant = str(ov.get("variant", "default"))
                raw_part = self._resolve_part_image(part, variant=variant)
                if ov.get("flip_h", False) or ov.get("flip_v", False):
                    raw_part = flip_image(
                        raw_part,
                        horizontal=bool(ov.get("flip_h", False)),
                        vertical=bool(ov.get("flip_v", False)),
                    )
                stage = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
                stage.paste(raw_part, part.offset)
                piv = ov.get("pivot", self._part_canvas_pivot(part, raw_part))
                transformed = rotsprite(
                    stage,
                    angle_deg=float(ov.get("angle", 0.0)),
                    pivot=piv,
                    dx=int(round(ov.get("dx", 0))),
                    dy=int(round(ov.get("dy", 0))),
                    scale_x=float(ov.get("scale_x", 1.0)),
                    scale_y=float(ov.get("scale_y", 1.0)),
                )
                f_mix = float(ov.get("flash_mix", 0.0))
                if f_mix > 0.0:
                    transformed = flash_image(
                        transformed,
                        flash_color=ov.get("flash_color", "#FFFFFF"),
                        mix=f_mix,
                    )
                if include_part_outlines and part.outline_group is not None:
                    transformed = self._apply_group_outline(transformed)
                p_frames.append(transformed)
            result.append((pname, p_frames))
        return result

    def animate_preset(
        self,
        preset: str = "idle_breathe",
        include_shadow: bool = True,
        include_vfx: bool = True,
        baseline_y: Optional[int] = None,
    ) -> Tuple[List[Image.Image], List[int], List[Dict[str, Dict[str, Any]]]]:
        """1-line motion generator: inspects registered part names and synthesizes `(frames, durations_ms, poses)`.
        Available presets: `'idle_breathe'`, `'float_bob'`, `'slime_bounce'`, `'melee_attack'`, `'hurt_flash'`.
        """
        p_low = preset.strip().lower()
        cw, ch = self.canvas_size

        def _match(*keywords: str) -> List[str]:
            return [pn for pn in self.parts if any(kw in pn.lower() for kw in keywords)]

        bodies = _match("torso", "body", "hull", "base", "robe", "chest") or [next(iter(self.parts))]
        heads = _match("head", "helmet", "face", "visor")
        crests = _match("plume", "hat", "crown", "hair", "antenna", "horn")
        capes = _match("cape", "cloak", "tail")
        weapons = _match("sword", "weapon", "staff", "axe", "hammer", "spear", "blade", "arm_r", "right_arm")
        shields = _match("shield", "arm_l", "left_arm")
        wings_l = _match("wing_l", "thruster_l")
        wings_r = _match("wing_r", "thruster_r")

        poses: List[Dict[str, Dict[str, Any]]] = []
        durs: List[int] = []

        if p_low == "idle_breathe":
            durs = [260, 180, 260, 180]
            for f_i in range(4):
                p: Dict[str, Dict[str, Any]] = {}
                if f_i == 1:
                    for n in heads + shields + weapons:
                        p[n] = {"dy": 1}
                    for n in wings_l:
                        p[n] = {"angle": 5}
                    for n in wings_r:
                        p[n] = {"angle": -5}
                elif f_i == 2:
                    for n in bodies:
                        p[n] = {"scale_y": 0.94, "dy": 1}
                    for n in heads + shields + weapons + capes:
                        p[n] = {"dy": 1}
                    for n in crests:
                        p[n] = {"dy": 2, "angle": -5}
                    for n in wings_l:
                        p[n] = {"angle": 9}
                    for n in wings_r:
                        p[n] = {"angle": -9}
                elif f_i == 3:
                    for n in crests:
                        p[n] = {"dy": 1, "angle": 3}
                    for n in capes:
                        p[n] = {"angle": 4}
                poses.append(p)

        elif p_low == "float_bob":
            durs = [220, 180, 220, 180]
            dys = [0, -1, -3, -1]
            for f_i, dy in enumerate(dys):
                p = {pn: {"dy": dy} for pn in self.parts}
                for n in crests + capes:
                    p[n] = {"dy": dy + (1 if f_i == 1 else 0), "angle": (-4 if f_i == 2 else 3)}
                for n in wings_l:
                    p[n] = {"dy": dy, "angle": (8 if f_i in (1, 2) else -4)}
                for n in wings_r:
                    p[n] = {"dy": dy, "angle": (-8 if f_i in (1, 2) else 4)}
                poses.append(p)

        elif p_low == "slime_bounce":
            durs = [200, 100, 75, 135, 75, 120]
            specs = [
                (1.0, 1.0, 0, 0),
                (1.16, 0.84, 1, 2),
                (0.88, 1.14, -4, -6),
                (1.0, 1.0, -6, -8),
                (0.95, 1.06, -2, -4),
                (1.12, 0.88, 1, 1),
            ]
            for sx, sy, b_dy, c_dy in specs:
                p = {}
                for n in bodies:
                    p[n] = {"scale_x": sx, "scale_y": sy, "dy": b_dy}
                for n in heads + crests + weapons + shields:
                    p[n] = {"dy": c_dy}
                poses.append(p)

        elif p_low == "melee_attack":
            durs = [130, 150, 190, 45, 65, 150]
            w_angles = [-25, -58, -72, 78, 86, 20]
            body_dxs = [0, -2, -2, 3, 3, 1]
            for f_i in range(6):
                bx = body_dxs[f_i]
                p = {pn: {"dx": bx} for pn in self.parts}
                if f_i in (1, 2):
                    for n in bodies:
                        p[n] = {"dx": bx, "scale_x": 1.06, "scale_y": 0.94}
                for n in heads:
                    src = self.parts[n].source
                    has_fierce = isinstance(src, Mapping) and ("fierce" in src or "alert" in src)
                    var = "fierce" if (isinstance(src, Mapping) and "fierce" in src) else ("alert" if (isinstance(src, Mapping) and "alert" in src) else "default")
                    p[n] = {"dx": bx, **({"variant": var} if has_fierce and f_i in (1, 2, 3, 4) else {})}
                for n in weapons:
                    p[n] = {"dx": bx + (2 if f_i in (3, 4) else -2 if f_i in (1, 2) else 0), "angle": w_angles[f_i]}
                for n in wings_l:
                    p[n] = {"dx": bx, "angle": (18 if f_i in (1, 2) else -12 if f_i in (3, 4) else 0)}
                for n in wings_r:
                    p[n] = {"dx": bx, "angle": (-18 if f_i in (1, 2) else 12 if f_i in (3, 4) else 0)}
                poses.append(p)

        elif p_low == "hurt_flash":
            durs = [45, 75, 110, 140]
            dxs = [-3, -4, -2, 0]
            for f_i, dx in enumerate(dxs):
                p = {}
                for pn in self.parts:
                    p[pn] = {"dx": dx, **({"flash_mix": 0.9} if f_i == 0 else {})}
                poses.append(p)
        else:
            raise ValueError(
                f"Unknown preset {preset!r}. Choose from: idle_breathe, float_bob, slime_bounce, melee_attack, hurt_flash."
            )

        base_f0 = self.render_pose({})
        bbox0 = base_f0.getchannel("A").getbbox() or (0, 0, cw, ch)
        by = baseline_y if baseline_y is not None else (bbox0[3] - 1)
        cx = (bbox0[0] + bbox0[2]) // 2
        base_sw = max(6, round((bbox0[2] - bbox0[0]) * 0.72))

        raw_frames = [self.render_pose(p) for p in poses]
        if include_shadow:
            frames = []
            for idx, rf in enumerate(raw_frames):
                airborne = (p_low == "float_bob" and idx == 2) or (p_low == "slime_bounce" and idx in (2, 3))
                sw = max(4, base_sw - 3) if airborne else base_sw
                frames.append(add_ground_shadow(rf, baseline_y=by, center_x=cx, fixed_width=sw))
        else:
            frames = raw_frames

        if include_vfx:
            if p_low == "melee_attack":
                slash = vfx_slash_arc((cw, ch), center=(min(cw - 8, cx + 4), (bbox0[1] + by) // 2), radius=max(8, cw // 4 + 2))
                dust = vfx_dust_puff((cw, ch), origin=(max(4, cx - 3), by), direction="left")
                frames = composite_vfx(frames, dust, start_frame=2, under=True)
                frames = composite_vfx(frames, slash, start_frame=2, under=False)
            elif p_low == "slime_bounce":
                dust = vfx_dust_puff((cw, ch), origin=(cx, by), direction="both")
                frames = composite_vfx(frames, dust, start_frame=1, under=True)
            elif p_low == "hurt_flash":
                spark = vfx_hit_spark((cw, ch), center=(cx, (bbox0[1] + by) // 2), radius=max(5, cw // 6))
                frames = composite_vfx(frames, spark, start_frame=0, under=False)

        return frames, durs, poses


@dataclass
class AnimationClip:
    """A single named animation state (e.g. 'idle', 'walk', 'attack') with variable frame timing."""

    name: str
    frames: List[Image.Image]
    durations_ms: List[int]
    direction: str = "forward"  # 'forward' | 'reverse' | 'pingpong'
    loop: bool = True

    @classmethod
    def create(
        cls,
        name: str,
        frames: Sequence[Union[Image.Image, GridLike]],
        palette: Union[str, Dict[str, ColorDef], None] = "endesga32",
        durations_ms: Optional[Union[int, Sequence[int]]] = None,
        fps: int = 8,
        direction: str = "forward",
        loop: bool = True,
        pad_ragged: bool = False,
    ) -> "AnimationClip":
        if not frames:
            raise ValueError(f"Clip {name!r} must contain at least 1 frame.")
        proc_frames: List[Union[Image.Image, List[str]]] = []
        if pad_ragged and all(not isinstance(f, Image.Image) for f in frames):
            norm_grids = [normalize_grid(f)[0] for f in frames]  # type: ignore[arg-type]
            max_w = max(len(g[0]) for g in norm_grids)
            max_h = max(len(g) for g in norm_grids)
            for g in norm_grids:
                padded_rows = [r + ("." * (max_w - len(r))) for r in g]
                while len(padded_rows) < max_h:
                    padded_rows.append("." * max_w)
                proc_frames.append(padded_rows)
        else:
            proc_frames = list(frames)  # type: ignore[assignment]

        rendered = [
            f.convert("RGBA")
            if isinstance(f, Image.Image)
            else render_grid(f, palette=palette, frame_index=i, pad_ragged=pad_ragged)
            for i, f in enumerate(proc_frames)
        ]
        fw, fh = rendered[0].size
        if any(im.size != (fw, fh) for im in rendered):
            raise ValueError(f"All frames in clip {name!r} must have equal canvas dimensions.")

        if durations_ms is None:
            if fps <= 0:
                raise ValueError("fps must be > 0")
            durs = [max(10, round(1000.0 / fps)) for _ in rendered]
        elif isinstance(durations_ms, int):
            if durations_ms < 10:
                raise ValueError("Frame duration must be >= 10ms")
            durs = [durations_ms for _ in rendered]
        else:
            durs = [int(d) for d in durations_ms]
            if len(durs) != len(rendered):
                raise ValueError(
                    f"Clip {name!r}: durations_ms length ({len(durs)}) != frame count ({len(rendered)})."
                )
            if any(d < 10 for d in durs):
                raise ValueError("All durations_ms values must be >= 10ms.")

        return cls(name=name, frames=rendered, durations_ms=durs, direction=direction, loop=loop)


class SpriteActor:
    """Multi-state character/object container managing multiple AnimationClips in one atlas."""

    def __init__(
        self,
        name: str,
        palette: Union[str, Dict[str, ColorDef], None] = "endesga32",
    ) -> None:
        self.name = name
        self.palette = palette
        self.clips: Dict[str, AnimationClip] = {}

    def add_clip(
        self,
        clip_name: str,
        frames: Sequence[Union[Image.Image, GridLike]],
        durations_ms: Optional[Union[int, Sequence[int]]] = None,
        fps: int = 8,
        direction: str = "forward",
        loop: bool = True,
    ) -> "SpriteActor":
        clip = AnimationClip.create(
            name=clip_name,
            frames=frames,
            palette=self.palette,
            durations_ms=durations_ms,
            fps=fps,
            direction=direction,
            loop=loop,
        )
        if self.clips:
            first_clip = next(iter(self.clips.values()))
            if clip.frames[0].size != first_clip.frames[0].size:
                raise ValueError(
                    f"Clip {clip_name!r} size {clip.frames[0].size} does not match actor canvas {first_clip.frames[0].size}."
                )
        self.clips[clip_name] = clip
        return self
