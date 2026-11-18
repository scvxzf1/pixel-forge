#!/usr/bin/env python3
"""Example 09: AI Concept Exploded Sheet -> Auto-Segment -> Pixelate -> Articulated Rig + HD-2D
Synthesizes a 380x260 solid-white-background exploded concept sheet of a 5-part Winged Seraph Boss
(including interior pure-white eyes & blade shine to test edge-seeded flood-fill safety!),
auto-segments & docks all 5 parts into an animated 56x56 pixel Rig, and lights it in HD-2D!
"""
from pathlib import Path
import sys
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import autorig_from_concept_sheet, export_hd2d_bundle


def _create_mock_exploded_concept_sheet(path: Path) -> None:
    """Create a 380x260 solid off-white studio concept sheet with 5 separated high-res boss parts."""
    sheet = Image.new("RGB", (380, 260), (246, 248, 252))
    d = ImageDraw.Draw(sheet)

    # 1. Central Armored Torso (centered at ~185, 150)
    d.polygon([(152, 108), (218, 108), (210, 195), (160, 195)], fill=(36, 92, 168), outline=(24, 20, 37), width=4)
    d.rectangle([166, 118, 204, 156], fill=(95, 168, 235), outline=(24, 20, 37), width=3)
    d.rectangle([162, 162, 208, 176], fill=(250, 178, 52), outline=(24, 20, 37), width=3)

    # 2. Crowned Helmet Head ABOVE torso (centered at ~185, 52) -- WITH PURE WHITE EYES INSIDE!
    d.ellipse([158, 26, 212, 80], fill=(190, 202, 222), outline=(24, 20, 37), width=4)
    d.polygon([(164, 30), (174, 12), (185, 26), (196, 12), (206, 30)], fill=(252, 182, 50), outline=(24, 20, 37), width=3)
    d.rectangle([168, 48, 202, 64], fill=(24, 20, 37))
    # Interior pure white glowing eyes (must NOT be erased when white bg is removed!)
    d.rectangle([172, 52, 180, 60], fill=(255, 255, 255))
    d.rectangle([190, 52, 198, 60], fill=(255, 255, 255))

    # 3. Left Golden/Azure Wing (upper-left island ~30..124, 48..148)
    d.polygon([(122, 86), (82, 46), (26, 62), (44, 108), (76, 138), (120, 118)], fill=(250, 180, 54), outline=(24, 20, 37), width=4)
    d.polygon([(114, 96), (62, 82), (56, 110), (84, 128)], fill=(255, 232, 102))

    # 4. Right Golden/Azure Wing (upper-right island ~246..340, 48..148)
    d.polygon([(248, 86), (288, 46), (344, 62), (326, 108), (294, 138), (250, 118)], fill=(250, 180, 54), outline=(24, 20, 37), width=4)
    d.polygon([(256, 96), (308, 82), (314, 110), (286, 128)], fill=(255, 232, 102))

    # 5. Tall Crimson/Silver Greatsword on far right (~315..362, 148..248, elongated aspect > 2.0!)
    d.polygon([(338, 144), (350, 162), (350, 218), (326, 218), (326, 162)], fill=(232, 62, 68), outline=(24, 20, 37), width=4)
    d.rectangle([335, 156, 341, 214], fill=(255, 255, 255))  # Interior pure-white blade core!
    d.rectangle([316, 216, 360, 226], fill=(250, 178, 52), outline=(24, 20, 37), width=3)
    d.rectangle([333, 226, 343, 248], fill=(140, 84, 56), outline=(24, 20, 37), width=3)

    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def main(output_dir: str = "output/examples/09_sketch_to_rig") -> None:
    out = Path(output_dir)
    concept_sheet = out / "seraph_exploded_concept.png"
    _create_mock_exploded_concept_sheet(concept_sheet)

    # 1. Auto-segment white-bg concept sheet -> 5 pixel parts -> docked & articulated 56x56 Rig!
    res = autorig_from_concept_sheet(
        concept_sheet,
        name="seraph_guardian",
        canvas_size=(56, 56),
        part_scale_target=46,
        palette="endesga32",
        assemble_exploded=True,
        outline_mode="outer",
        output_dir=out,
    )
    print("Detected & rigged parts:", res["parts_detected"])

    # 2. Chain directly into HD-2D Normal Map + 360 Torch Relighting!
    rig = res["rig"]
    albedo = res["frames"][0]
    part_layers = rig.render_part_layers({}, part_profiles={"weapon_r": "ridge"})
    export_hd2d_bundle(
        name="seraph_guardian_hd2d",
        albedo=albedo,
        part_layers=part_layers,
        emissive_colors=["#FFFFFF", "#2CE8F5", "#F6757A", "#FEE761"],
        orbit_frames=12,
        preview_scale=5,
        output_dir=out / "hd2d",
    )


if __name__ == "__main__":
    main()
