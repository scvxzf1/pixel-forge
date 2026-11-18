"""Multi-Layer Part Rigging (compact local ASCII parts + RotSprite hinge rotation +
grouped outlining) and Multi-Action SpriteActor state management (idle/walk/attack/...).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
from PIL import Image

from .canvas import GridLike, render_grid
from .palette import ColorDef, get_palette
from .transform import (
    auto_outline,
    flash_image,
    flip_image,
    rotsprite,
    selective_outline,
)

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
        offset: Tuple[int, int] = (0, 0),
        pivot_local: Optional[Tuple[float, float]] = None,
        pivot_canvas: Optional[Tuple[float, float]] = None,
        z_index: int = 0,
        outline_group: Optional[int] = 0,
    ) -> "Rig":
        self.parts[name] = Part(
            name=name,
            source=source,
            offset=offset,
            pivot_local=pivot_local,
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
        return render_grid(chosen, palette=self.palette)

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
    ) -> "AnimationClip":
        if not frames:
            raise ValueError(f"Clip {name!r} must contain at least 1 frame.")
        rendered = [
            f.convert("RGBA") if isinstance(f, Image.Image) else render_grid(f, palette=palette, frame_index=i)
            for i, f in enumerate(frames)
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
