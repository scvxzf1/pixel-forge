#!/usr/bin/env python3
"""Example 05: Procedural 47-Tile Blob & 16-Tile Wang Auto-Tileset Generator
Synthesizes a complete Lush Grass-Over-Water archipelago tileset (all 47 outer corners,
inner bays, 1-tile bridges, and islands) from just two 16x16 base tiles!
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import (
    export_autotile_bundle,
    generate_blob47_tileset,
    generate_wang16_tileset,
    render_grid,
)


def main(output_dir: str = "output/examples/05_autotile") -> None:
    grass_16 = [
        "ggggGGGGggggGGGG",
        "ggGGGGGGGGggggGG",
        "gGGyGGGGGGGGgggG",
        "ggggGGGGGGgggggg",
        "GGGGggggGGGGGGGG",
        "GGGGGGggggGGyGGG",
        "GGggggggggGGGGGG",
        "ggggGGGGGGGGgggg",
        "ggGGGGGGGGGGGGgg",
        "gGGGGggggGGGGGGg",
        "ggggggggggGGGGgg",
        "GGGGGGGGgggggggg",
        "GGyGGGGGGGggggGG",
        "GGGGGGGGGGGGgggG",
        "ggggGGGGGGgggggg",
        "ggggggGGGGggggGG",
    ]
    water_16 = [
        "BBBBBBBBBBBBBBBB",
        "BBCCCCBBBBbbbbBB",
        "BCWWWWCBBbbbbbbB",
        "BBBBBBBBBBBBBBBB",
        "CCBBbbbbBBBBBBCC",
        "WWCbbbbbbBBBBCWW",
        "BBBBBBBBBBBBBBBB",
        "BBBBBBbbbbBBBBBB",
        "BCWWCBbbbbbBBBBB",
        "BCCCCBBBBBBBBBBB",
        "BBBBBBBBBBBBBBBB",
        "BBBBBBBBCCWWCCBB",
        "bBBBBBBBCCCCCCBb",
        "bbBBBBBBBBBBBBbb",
        "bBBBBBBBBBBBBBBb",
        "BBBBBBBBBBBBBBBB",
    ]

    fg_img = render_grid(grass_16, "endesga32")
    bg_img = render_grid(water_16, "endesga32")

    archipelago_map = [
        "................",
        "..#####....###..",
        ".#######..#####.",
        ".###..#########.",
        "..##....###.##..",
        "...#........#...",
        "..####....####..",
        ".######..######.",
        ".###.######.###.",
        "..##..####..##..",
        ".......##.......",
        "................",
    ]

    # 1. Full 47-tile 8-neighbor Blob Auto-Tileset (with top-left sunlit grass rim & earthy cliff lip!)
    blob47 = generate_blob47_tileset(
        fg_img,
        bg_img,
        outline_color="#181425",
        rim_highlight_color="#91DB69",
        rim_shadow_color="#8F563B",
    )
    export_autotile_bundle(
        "emerald_coast",
        blob47,
        output_dir=output_dir,
        sample_map=archipelago_map,
        preview_scale=3,
    )

    # 2. Compact 16-tile Dual-Grid Corner Wang Auto-Tileset
    wang16 = generate_wang16_tileset(
        fg_img,
        bg_img,
        outline_color="#181425",
        rim_highlight_color="#91DB69",
        rim_shadow_color="#8F563B",
    )
    export_autotile_bundle(
        "emerald_coast",
        wang16,
        output_dir=output_dir,
        sample_map=archipelago_map,
        preview_scale=3,
    )


if __name__ == "__main__":
    main()
