#!/usr/bin/env python3
"""Example 03: High-Res Concept Draft -> Pixelate & Clean -> LLM Polish & Sparkle Animation
Synthesizes a smooth 256x256 anti-aliased magic potion illustration, runs `pixelate_image`
to quantize into a crisp 32x32 Sweetie-16 pixel base, polishes highlights, and adds twinkles.
"""
from pathlib import Path
import sys
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import (
    build_pixel_asset,
    composite_vfx,
    patch_region_image,
    pixelate_image,
    vfx_twinkle_stars,
)


def _create_mock_highres_concept(path: Path) -> None:
    """Create a smooth 256x256 soft-shaded concept illustration with gradients & blur."""
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    # Round flask body with smooth gradient rings
    for r in range(78, 0, -2):
        t = 1.0 - (r / 78.0)
        col = (
            int(40 + 40 * t),
            int(120 + 115 * t),
            int(215 + 40 * t),
            255,
        )
        draw.ellipse([128 - r, 154 - r, 128 + r, 154 + r], fill=col)

    # Glowing magenta-red potion liquid inside lower half
    liquid = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ldraw = ImageDraw.Draw(liquid)
    ldraw.pieslice([62, 88, 194, 220], start=5, end=175, fill=(195, 52, 92, 255))
    ldraw.ellipse([66, 140, 190, 166], fill=(245, 115, 105, 255))
    im = Image.alpha_composite(im, liquid.filter(ImageFilter.GaussianBlur(2)))

    # Re-bind Draw to the composited image for flask neck, rim & wooden cork!
    draw = ImageDraw.Draw(im)
    draw.rectangle([104, 54, 152, 92], fill=(160, 225, 245, 255))
    draw.rounded_rectangle([92, 46, 164, 62], radius=8, fill=(225, 245, 255, 255))
    draw.polygon([(108, 18), (148, 18), (144, 48), (112, 48)], fill=(215, 130, 75, 255))
    # Specular soft highlight
    spec = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(spec).ellipse([82, 108, 108, 148], fill=(255, 255, 255, 210))
    im = Image.alpha_composite(im, spec.filter(ImageFilter.GaussianBlur(3)))

    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def main(output_dir: str = "output/examples/03_pixelate") -> None:
    out = Path(output_dir)
    concept_path = out / "highres_potion_concept.png"
    _create_mock_highres_concept(concept_path)

    # 1. Convert smooth 256x256 illustration -> clean 32x32 Sweetie-16 pixel art
    px_res = pixelate_image(
        concept_path,
        target_size=(32, 32),
        palette="sweetie16",
        mode="contrast_box",
        outline_color="#1A1C2C",
        output_dir=out,
        name="mana_ruby_potion",
    )
    base_px = px_res["image"]

    # 2. Surgical LLM polish: crisp curved glass reflection on top-left of flask
    shine_patch = [
        ".WW.",
        "WW..",
        "W...",
        "W...",
        ".C..",
    ]
    polished = patch_region_image(base_px, shine_patch, 10, 14, palette="sweetie16", mode="alpha_over")

    # 3. Add looping magic twinkle stars around the potion
    base_seq = [polished.copy() for _ in range(6)]
    stars = vfx_twinkle_stars((32, 32), centers=[(6, 10), (26, 14), (24, 25)], frames_count=6)
    anim_frames = composite_vfx(base_seq, stars, start_frame=0)

    build_pixel_asset(
        "mana_ruby_potion_polished",
        anim_frames,
        palette="sweetie16",
        durations_ms=[160, 120, 140, 160, 120, 140],
        output_dir=out,
    )


if __name__ == "__main__":
    main()
