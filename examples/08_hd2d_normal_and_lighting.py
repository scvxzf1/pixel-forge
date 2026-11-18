#!/usr/bin/env python3
"""Example 08: HD-2D Pixel Normal Map + Emission Glow Mask + 360 Orbiting Torch Relighting
Builds per-part normal maps ('dome' on armor/shield + sharp 'ridge' spine on sword blade)
and exports Godot/Unity-ready Albedo, Normal, Emission PNGs + 12-frame Orbiting Torch GIF.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import Rig, export_hd2d_bundle


def main(output_dir: str = "output/examples/08_hd2d_lighting") -> None:
    rig = Rig(canvas_size=(40, 40), palette="endesga32", outline_mode="outer")

    rig.add_part("cape", [".RRRR.", "RRRRrr", "RRRrrr", "RRrrrr", ".rrrr."], offset=(11, 21), z_index=5, outline_group=0)
    rig.add_part("torso", [".BBBBBBBB.", "B11BBBB22B", "B11YYYY22B", ".bbbbbbbb.", ".LL....LL.", ".ll....ll."], offset=(14, 22), z_index=10, outline_group=0)
    rig.add_part("plume", ["..RRR.", ".RRRRr", "RRrr.."], offset=(13, 11), z_index=18, outline_group=0)
    rig.add_part("helmet", ["..111111..", ".1WW11122.", ".11111122.", ".2KKKKKK2.", ".2KCKKCK2.", "..222222.."], offset=(14, 14), z_index=20, outline_group=0)
    rig.add_part("shield", [".YYYY.", "Y1112Y", "Y1CC2Y", "Y1BB2Y", ".YooY.", "..oo.."], offset=(10, 22), z_index=25, outline_group=1)
    rig.add_part("sword", ["..W..", ".W1..", ".W1..", ".W1..", ".W1..", ".12..", ".12..", "YYYYY", "..L..", "..l.."], offset=(25, 13), z_index=30, outline_group=1)

    albedo = rig.render_pose({})
    part_layers = rig.render_part_layers(
        {},
        part_profiles={
            "sword": "ridge",   # Sharp 2-plane blade spine so torch glints cleanly across edge!
            "shield": "dome",
            "helmet": "dome",
            "torso": "dome",
        },
    )

    # Extract glowing cyan visor eyes & shield gem ('#2CE8F5') as self-luminous emission mask!
    export_hd2d_bundle(
        name="hd2d_azure_knight",
        albedo=albedo,
        part_layers=part_layers,
        emissive_colors=["#2CE8F5"],
        bevel_px=4.5,
        bump_strength=2.4,
        orbit_frames=12,
        preview_scale=6,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    main()
