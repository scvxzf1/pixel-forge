#!/usr/bin/env python3
"""Example 07: 2:1 Isometric Diorama (`IsoScene`) + 4/8-Direction RPG Character Derivation
1. Builds a multi-elevation 2:1 Isometric Shrine Island with water moat, stepped stone stairs,
   pillars, and glowing crystal altar (zero lattice gaps, 3-face shading + 1px specular ridges).
2. Derives a complete 4-Direction & 8-Direction RPG Walk Sprite Sheet + 360 Turnaround Spin GIF
   from a single front-facing character rig, verified with Head/Baseline alignment rulers.
"""
from pathlib import Path
import sys
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import (
    DIRECTIONS_4,
    DIRECTIONS_8,
    DirectionalRig,
    IsoScene,
    build_pixel_asset,
    export_multidir_sheets,
    render_grid,
)


def main(output_dir: str = "output/examples/07_iso_and_multidir") -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Part A: 2:1 Isometric Shrine Diorama (`IsoScene`, half_h=8 -> 32x16 tiles)
    # -------------------------------------------------------------------------
    iso = IsoScene(half_h=8, bg_color=(0, 0, 0, 0))

    # 4x4 courtyard base: water moat around outer L-edge, lush grass & stone terrace inside
    for gx in range(4):
        for gy in range(4):
            if gx == 3 or gy == 3:
                iso.add_block(
                    gx, gy, gz=0, height_z=6,
                    top_color="#2CE8F5", left_color="#0099DB", right_color="#124E89",
                    ridge_highlight="#73EFF7",
                )
            else:
                iso.add_block(
                    gx, gy, gz=0, height_z=10,
                    top_color="#63C74D", left_color="#8F563B", right_color="#663931",
                    ridge_highlight="#91DB69",
                )

    # Raised 2x2 stone sanctuary platform at (0, 0) on top of terrace (gz=10)
    iso.add_block(
        0, 0, gz=10, u_cells=2, v_cells=2, height_z=8,
        top_color="#C0CBDC", left_color="#8B9BB4", right_color="#5A6988",
        ridge_highlight="#FFFFFF",
    )
    # Stone step leading up at (2, 1)
    iso.add_block(
        2, 1, gz=10, u_cells=1, v_cells=1, height_z=4,
        top_color="#C0CBDC", left_color="#8B9BB4", right_color="#5A6988",
        ridge_highlight="#FFFFFF",
    )
    # Twin stone pillars at (0, 1) and (1, 0)
    for px, py in ((0, 1), (1, 0)):
        iso.add_block(
            px, py, gz=18, u_cells=1, v_cells=1, height_z=18,
            top_color="#FFFFFF", left_color="#C0CBDC", right_color="#5A6988",
        )

    # Floating ruby crystal sprite hovering above altar at (0, 0, gz=26)
    crystal = render_grid([
        "...KK...",
        "..KWWK..",
        ".KWRRWK.",
        "KWRRRRRK",
        "KRRRRrrK",
        ".KrrrrK.",
        "..KrrK..",
        "...KK...",
    ], "endesga32")
    iso.add_sprite(1.35, 1.35, gz=20, sprite=crystal)

    diorama = iso.render(padding=6)
    build_pixel_asset("iso_shrine_diorama", [diorama], palette="endesga32", preview_scale=4, output_dir=out)

    # -------------------------------------------------------------------------
    # Part B: 4-Direction & 8-Direction RPG Explorer Turnaround & Walk Sheets
    # -------------------------------------------------------------------------
    explorer = DirectionalRig(canvas_size=(32, 32), palette="endesga32", outline_mode="selout")
    explorer.add_part(
        "cape",
        [".gggg.", "ggggtt", "ggtttt", ".tttt."],
        role="cape",
        offset=(13, 17),
        z_index=5,
        outline_group=0,
    )
    explorer.add_part(
        "torso",
        [".GGGGGG.", "GYYGGYYG", ".gggggg.", ".LL..LL."],
        role="torso",
        offset=(12, 18),
        z_index=10,
        outline_group=0,
    )
    explorer.add_part(
        "head",
        [
            "..LLLLLL..",
            ".LsLLLLlL.",
            ".SSSSSSSS.",
            ".SKSSSSKS.",
            "..SSSSSS..",
        ],
        role="head",
        offset=(11, 11),
        z_index=20,
        outline_group=0,
        face_chars_to_mask_on_back=("K", "S"),
        back_fill_char="L",
    )
    explorer.add_part(
        "plume",
        ["..RR.", ".RRr."],
        role="plume",
        offset=(14, 9),
        z_index=22,
        outline_group=0,
    )
    explorer.add_part(
        "left_arm",
        [".YYY.", "Y1B2Y", ".YoY."],
        role="left_arm",
        offset=(9, 18),
        z_index=25,
        outline_group=1,
    )
    explorer.add_part(
        "right_arm",
        [".W.", ".1.", "YYY", ".L."],
        role="right_arm",
        offset=(20, 15),
        z_index=26,
        outline_group=1,
    )

    export_multidir_sheets(
        "forest_ranger",
        explorer,
        directions=DIRECTIONS_4,
        baseline_y=23,
        output_dir=out,
    )
    export_multidir_sheets(
        "forest_ranger",
        explorer,
        directions=DIRECTIONS_8,
        baseline_y=23,
        output_dir=out,
    )


if __name__ == "__main__":
    main()
