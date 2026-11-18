"""Automated Pixel Art Linter: detects stray specks, silhouette outline leaks,
slope rhythm jaggies, noisy orphan pixels, dirty anti-aliased palettes,
and multi-frame volume/baseline anomalies with zero-based (x, y) coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple
from PIL import Image

from .palette import RGBA, img_pixels, luminance, normalize_rgba


@dataclass
class LintIssue:
    code: str
    severity: str  # "warn" | "info"
    message: str
    coords: List[Tuple[int, int]] = field(default_factory=list)
    frame_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": self.frame_index,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "coords": self.coords[:12],
        }


def _find_profile_jaggies(
    profile: List[Tuple[int, int]],  # list of (axis_pos, boundary_coord)
    is_x_axis: bool,
) -> List[Tuple[int, int]]:
    """Detect non-monotonic or broken run-length steps (e.g. 3-1-3) along a monotonic slope."""
    if len(profile) < 6:
        return []

    # Build contiguous segments of identical boundary_coord
    runs: List[Tuple[int, int, int]] = []  # (start_idx, length, val)
    cur_start = 0
    cur_val = profile[0][1]
    for i in range(1, len(profile)):
        if profile[i][1] != cur_val:
            runs.append((cur_start, i - cur_start, cur_val))
            cur_start = i
            cur_val = profile[i][1]
    runs.append((cur_start, len(profile) - cur_start, cur_val))

    jaggies: List[Tuple[int, int]] = []
    for r_idx in range(1, len(runs) - 1):
        prev_start, prev_len, prev_val = runs[r_idx - 1]
        cur_start_i, cur_len, cur_val = runs[r_idx]
        _, next_len, next_val = runs[r_idx + 1]

        d1 = cur_val - prev_val
        d2 = next_val - cur_val
        # Same monotonic 1px slope direction, but an isolated 1px run sandwiched between >=2px runs
        if d1 == d2 and abs(d1) == 1:
            if cur_len == 1 and prev_len >= 2 and next_len >= 2:
                pos, val = profile[cur_start_i]
                jaggies.append((pos, val) if is_x_axis else (val, pos))
            elif cur_len >= 3 and prev_len == 1 and next_len == 1:
                mid = cur_start_i + cur_len // 2
                pos, val = profile[mid]
                jaggies.append((pos, val) if is_x_axis else (val, pos))
    return jaggies


def lint_frame(img: Image.Image, frame_index: int = 0) -> Tuple[Dict[str, Any], List[LintIssue]]:
    """Analyze a single pixel-art frame and return `(metrics_dict, issues_list)`."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()

    opaque_coords: List[Tuple[int, int]] = []
    semi_transparent_coords: List[Tuple[int, int]] = []
    unique_colors = set()

    for y in range(h):
        for x in range(w):
            c = normalize_rgba(px[x, y])
            if c[3] > 0:
                opaque_coords.append((x, y))
                unique_colors.add(c)
                if c[3] < 255:
                    semi_transparent_coords.append((x, y))

    issues: List[LintIssue] = []
    if not opaque_coords:
        metrics = {
            "frame": frame_index,
            "width": w,
            "height": h,
            "opaque_pixels": 0,
            "unique_colors": 0,
            "bbox": None,
            "baseline_y": None,
            "cog": None,
        }
        issues.append(LintIssue("empty_frame", "warn", "Frame has 0 opaque pixels.", [], frame_index))
        return metrics, issues

    xs = [p[0] for p in opaque_coords]
    ys = [p[1] for p in opaque_coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    cog_x = round(sum(xs) / len(xs), 2)
    cog_y = round(sum(ys) / len(ys), 2)

    metrics = {
        "frame": frame_index,
        "width": w,
        "height": h,
        "opaque_pixels": len(opaque_coords),
        "unique_colors": len(unique_colors),
        "semi_transparent_pixels": len(semi_transparent_coords),
        "bbox": [min_x, min_y, max_x, max_y],
        "baseline_y": max_y,
        "cog": [cog_x, cog_y],
    }

    # 1. Dirty / unquantized palette check
    if len(unique_colors) > 64:
        issues.append(
            LintIssue(
                "dirty_palette",
                "warn",
                f"Detected {len(unique_colors)} unique colors (>64); check for blurry resize or anti-aliasing.",
                [],
                frame_index,
            )
        )

    # 2. Semi-transparency notice (important if targeting GIF)
    if semi_transparent_coords:
        issues.append(
            LintIssue(
                "semi_transparent_alpha",
                "info",
                f"{len(semi_transparent_coords)} semi-transparent pixels present "
                "(preserved in APNG/WebP/PNG, binarized at alpha>=128 in GIF).",
                semi_transparent_coords[:8],
                frame_index,
            )
        )

    # 3. Stray isolated 1px outer specks & interior single-pixel color orphans
    stray_specks: List[Tuple[int, int]] = []
    color_orphans: List[Tuple[int, int]] = []
    perimeter_dark = 0
    perimeter_bright_leaks: List[Tuple[int, int]] = []

    for x, y in opaque_coords:
        c = normalize_rgba(px[x, y])
        lum = luminance(c)
        opaque_8 = 0
        same_8 = 0
        touches_transparent_4 = False

        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    nc = normalize_rgba(px[nx, ny])
                    if nc[3] > 0:
                        opaque_8 += 1
                        if nc == c:
                            same_8 += 1
                    elif abs(dx) + abs(dy) == 1:
                        touches_transparent_4 = True
                elif abs(dx) + abs(dy) == 1:
                    touches_transparent_4 = True

        if opaque_8 == 0:
            stray_specks.append((x, y))
        elif same_8 == 0 and not (lum > 0.80 or lum < 0.18):
            color_orphans.append((x, y))

        if touches_transparent_4:
            if lum <= 0.25:
                perimeter_dark += 1
            elif lum >= 0.45 and y < max_y:  # exclude flat bottom baseline where outlines are sometimes omitted
                perimeter_bright_leaks.append((x, y))

    if stray_specks:
        issues.append(
            LintIssue(
                "stray_specks",
                "warn",
                f"{len(stray_specks)} isolated 1px floating speck(s) with no neighbors.",
                stray_specks,
                frame_index,
            )
        )

    orphan_limit = max(5, len(opaque_coords) // 35)
    if len(color_orphans) > orphan_limit:
        issues.append(
            LintIssue(
                "orphan_noise",
                "warn",
                f"{len(color_orphans)} single-pixel color noise dots; group into >=2px clusters.",
                color_orphans,
                frame_index,
            )
        )

    # 4. Accidental outline leak check (only when sprite clearly uses dark outer outlines)
    total_perim = perimeter_dark + len(perimeter_bright_leaks)
    if total_perim >= 12 and perimeter_dark / total_perim >= 0.80 and 1 <= len(perimeter_bright_leaks) <= 5:
        issues.append(
            LintIssue(
                "outline_gap",
                "warn",
                f"{len(perimeter_bright_leaks)} potential outline gap(s) where bright fill touches transparent bg.",
                perimeter_bright_leaks,
                frame_index,
            )
        )

    # 5. Outer silhouette slope jaggie check (top, bottom, left, right profiles)
    top_prof: List[Tuple[int, int]] = []
    bot_prof: List[Tuple[int, int]] = []
    for x in range(min_x, max_x + 1):
        col_ys = [y for y in range(min_y, max_y + 1) if px[x, y][3] > 0]
        if col_ys:
            top_prof.append((x, col_ys[0]))
            bot_prof.append((x, col_ys[-1]))
    left_prof: List[Tuple[int, int]] = []
    right_prof: List[Tuple[int, int]] = []
    for y in range(min_y, max_y + 1):
        row_xs = [x for x in range(min_x, max_x + 1) if px[x, y][3] > 0]
        if row_xs:
            left_prof.append((y, row_xs[0]))
            right_prof.append((y, row_xs[-1]))

    jaggie_set = set()
    for prof, is_x in ((top_prof, True), (bot_prof, True), (left_prof, False), (right_prof, False)):
        for pt in _find_profile_jaggies(prof, is_x):
            jaggie_set.add(pt)

    if jaggie_set:
        jaggie_list = sorted(jaggie_set)
        issues.append(
            LintIssue(
                "silhouette_jaggies",
                "info",
                f"{len(jaggie_list)} potential slope rhythm jaggie(s) (e.g. 2-1-2 staircase break) on outer contour.",
                jaggie_list,
                frame_index,
            )
        )

    return metrics, issues


def lint_frames(frames: Sequence[Image.Image]) -> Dict[str, Any]:
    """Run pixel quality & temporal consistency diagnostics across an animation sequence."""
    if not frames:
        raise ValueError("frames must not be empty")

    frame_metrics: List[Dict[str, Any]] = []
    all_issues: List[LintIssue] = []

    for idx, f in enumerate(frames):
        m, iss = lint_frame(f, frame_index=idx)
        frame_metrics.append(m)
        all_issues.extend(iss)

    if len(frames) > 1:
        baselines = [m["baseline_y"] for m in frame_metrics]
        for idx in range(1, len(frames)):
            prev_cnt = frame_metrics[idx - 1]["opaque_pixels"]
            curr_cnt = frame_metrics[idx]["opaque_pixels"]
            if prev_cnt > 0:
                ratio = abs(curr_cnt - prev_cnt) / float(prev_cnt)
                if ratio > 0.30:
                    all_issues.append(
                        LintIssue(
                            "volume_spike",
                            "warn",
                            f"Opaque pixel mass changed by {ratio*100:.0f}% between Frame {idx-1} ({prev_cnt}px) "
                            f"and Frame {idx} ({curr_cnt}px).",
                            [],
                            idx,
                        )
                    )
            if img_pixels(frames[idx - 1].convert("RGBA")) == img_pixels(frames[idx].convert("RGBA")):
                all_issues.append(
                    LintIssue(
                        "duplicate_adjacent_frame",
                        "info",
                        f"Frame {idx} is identical to Frame {idx-1}; consider extending durations_ms instead.",
                        [],
                        idx,
                    )
                )

    else:
        baselines = [frame_metrics[0]["baseline_y"]]

    return {
        "frame_count": len(frames),
        "baselines_y": baselines,
        "frames": frame_metrics,
        "issues": [i.to_dict() for i in all_issues],
        "warning_count": sum(1 for i in all_issues if i.severity == "warn"),
    }


def format_lint_report(report: Dict[str, Any]) -> str:
    """Render a compact, agent-friendly summary of lint metrics and coordinate warnings."""
    lines = [
        f"Pixel Linter: {report['frame_count']} frame(s), "
        f"baselines_y={report['baselines_y']}, warnings={report['warning_count']}"
    ]
    for iss in report["issues"]:
        coord_str = ""
        if iss["coords"]:
            pts = ", ".join(f"({x},{y})" for x, y in iss["coords"][:6])
            if len(iss["coords"]) > 6:
                pts += ", ..."
            coord_str = f" @ {pts}"
        prefix = "WARN" if iss["severity"] == "warn" else "INFO"
        lines.append(f"  [{prefix}] Frame {iss['frame']} ({iss['code']}): {iss['message']}{coord_str}")
    if not report["issues"]:
        lines.append("  [OK] Clean pixel clusters, silhouettes, and frame consistency.")
    return "\n".join(lines)
