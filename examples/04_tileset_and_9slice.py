#!/usr/bin/env python3
"""Example 04: Seamless 3x3 Animated Water Tileset + 9-Slice Ornate RPG Dialogue Window
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import (
    PixelCanvas,
    build_pixel_asset,
    generate_holistic_sheet,
    generate_tileset_sheet,
    render_9slice,
    render_grid,
    save_rgba_gif,
    shift_grid,
    tile_grid_repeat,
)
from PIL import Image


def main(output_dir: str = "output/examples/04_tileset_and_ui") -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Seamless 16x16 Animated Water Tile (wrapping wave crests smoothly across x=15 -> x=0!)
    water_base = [
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
    water_frames = [
        render_grid(shift_grid(water_base, dx=step * 2, dy=(1 if step in (3, 4) else 0), wrap=True), palette="endesga32")
        for step in range(8)
    ]

    sheet, seam_rep = generate_tileset_sheet(water_frames, title="Seamless Water Tile")
    sheet.save(out / "water_tile_3x3_inspect.png")
    print("Water tile seamless report:", seam_rep)

    # Export 3x3 tiled animated GIF preview
    tiled_3x3 = [
        tile_grid_repeat(f, 3, 3).resize((16 * 3 * 4, 16 * 3 * 4), Image.Resampling.NEAREST)
        for f in water_frames
    ]
    save_rgba_gif(tiled_3x3, out / "water_tile_3x3_anim_4x.gif", [130] * len(water_frames))

    # 2. 20x20 Ornate Gold & Royal-Blue 9-Slice UI Window Source
    ui_canvas = PixelCanvas(20, 20, fill="5")
    ui_canvas.dither_rect(3, 3, 14, 14, "5", "4", ratio=0.5, matrix_size=2)
    ui_canvas.rect(0, 0, 20, 20, outline="K")
    ui_canvas.rect(1, 1, 18, 18, outline="Y")
    ui_canvas.rect(2, 2, 16, 16, outline="o")
    ui_canvas.rect(3, 3, 14, 14, outline="K")
    # Decorative 5x5 gold corner clasps (symmetric)
    corner = [
        "KYYYK",
        "YyyYY",
        "YyCKo",
        "YYoKo",
        "KoooK",
    ]
    ui_canvas.stamp(corner, 0, 0)
    ui_canvas.stamp(corner, 15, 0, mirror_h=True)
    ui_canvas.stamp(corner, 0, 15, mirror_v=True)
    ui_canvas.stamp(corner, 15, 15, mirror_h=True, mirror_v=True)

    ui_src = ui_canvas.render("endesga32")
    build_pixel_asset(
        "rpg_window_9slice_src",
        [ui_src],
        palette="endesga32",
        nine_slice_margins=(5, 5, 5, 5),
        output_dir=out,
    )

    # Expand 20x20 master -> 160x56 RPG dialogue box with crisp tiled edges & untouched 5x5 corners!
    expanded = render_9slice(ui_src, margins=(5, 5, 5, 5), target_size=(160, 56), mode="tile")
    expanded.save(out / "rpg_dialogue_160x56_1x.png")
    expanded.resize((160 * 4, 56 * 4), Image.Resampling.NEAREST).save(out / "rpg_dialogue_160x56_4x.png")
    generate_holistic_sheet([expanded], title="Expanded 9-Slice RPG Dialogue Panel (160x56)", palette="endesga32").save(
        out / "rpg_dialogue_160x56_inspect.png"
    )


if __name__ == "__main__":
    main()
