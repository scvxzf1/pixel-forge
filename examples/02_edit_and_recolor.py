#!/usr/bin/env python3
"""Example 02: Reverse Decompile + Surgical Region Patch + Diff Sheet + Semantic Recolor
Demonstrates taking an existing 8x-upscaled PNG/GIF asset, auto-recovering native 1x grid,
slicing only the helmet region to install golden horns & glowing red visor, verifying with Diff,
and producing a Crimson Guard color variant.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import (
    build_pixel_asset,
    decompile_asset,
    extract_region_grid,
    generate_diff_sheet,
    generate_holistic_sheet,
    image_to_grid,
    load_frames_from_file,
    patch_region_image,
    recolor_image,
)


def main(
    source_png: str = "output/examples/01_knight/azure_knight_idle_8x.png",
    output_dir: str = "output/examples/02_edit_and_recolor",
) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not Path(source_png).is_file():
        import importlib.util
        ex01_path = Path(__file__).resolve().parent / "01_knight_multi_anim.py"
        spec = importlib.util.spec_from_file_location("ex01", ex01_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()

    # 1. Load an 8x-upscaled preview PNG -> auto-recovers 40x40 native 1x resolution!
    frames, _, downscale_k = load_frames_from_file(source_png, auto_downscale_native=True)
    base_img = frames[0]
    print(f"Loaded {source_png} -> auto-downscaled by {downscale_k}x to native {base_img.size}")

    # Also test full decompile pipeline
    decompile_asset(source_png, output_dir=out / "decompiled", name="knight_recovered", palette="endesga32")

    # 2. Extract ONLY the head/helmet region (x=11, y=9, w=16, h=13)
    rx, ry, rw, rh = 11, 9, 16, 13
    full_grid, _ = image_to_grid(base_img, palette="endesga32")
    head_slice = extract_region_grid(full_grid, rx, ry, rw, rh)
    generate_holistic_sheet(
        [base_img.crop((rx, ry, rx + rw, ry + rh))],
        title="Extracted Helmet Slice (Global Coords)",
        palette="endesga32",
        coord_offset=(rx, ry),
    ).save(out / "helmet_slice_inspect.png")

    # Modify the 16x13 patch: add outlined golden horns on sides & glowing crimson eye slit
    edited_rows = [list(r) for r in head_slice]
    horns = [
        # Left outlined horn
        (1, 1, "K"), (0, 2, "K"), (1, 2, "y"), (2, 2, "K"),
        (0, 3, "K"), (1, 3, "Y"), (2, 3, "Y"), (3, 3, "K"),
        (1, 4, "K"), (2, 4, "o"),
        # Right outlined horn
        (14, 1, "K"), (15, 2, "K"), (14, 2, "y"), (13, 2, "K"),
        (15, 3, "K"), (14, 3, "Y"), (13, 3, "Y"), (12, 3, "K"),
        (14, 4, "K"), (13, 4, "o"),
    ]
    for hx, hy, ch in horns:
        edited_rows[hy][hx] = ch
    # Turn cyan eye pixels ('C') in helmet into glowing crimson ('R')
    for y in range(rh):
        for x in range(rw):
            if edited_rows[y][x] == "C":
                edited_rows[y][x] = "R"
    edited_patch = ["".join(r) for r in edited_rows]

    patched_img = patch_region_image(base_img, edited_patch, rx, ry, palette="endesga32", mode="replace")
    diff_sheet, stats = generate_diff_sheet(base_img, patched_img, title="Horned Visor Surgical Patch")
    diff_sheet.save(out / "horned_patch_diff.png")
    print(f"Surgical patch applied -> changed {stats['changed_pixels']}px inside bbox {stats['changed_bbox']}")

    build_pixel_asset("horned_knight", [patched_img], palette="endesga32", output_dir=out)

    # 3. Generate Crimson Legion Variant via semantic ramp swap
    crimson_img = recolor_image(
        patched_img,
        {"B": "r", "b": "e", "1": "s", "2": "L"},
        palette="endesga32",
    )
    build_pixel_asset("crimson_legion_knight", [crimson_img], palette="endesga32", output_dir=out)


if __name__ == "__main__":
    main()
