#!/usr/bin/env python3
"""Example 06: Multi-Asset In-Game Scene Mockup Composer & 4-Panel Value Readability Check
Combines an auto-tiled grass/water battle arena, animated Knight vs King Slime combat,
9-Slice HUD panel, crisp 3x5 retro pixel bitmap text + floating '-48!' damage popup,
and verifies foreground-vs-background Grayscale Value Separation.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import (
    PixelCanvas,
    Rig,
    SceneComposer,
    add_ground_shadow,
    build_scene_mockup,
    composite_vfx,
    generate_blob47_tileset,
    render_9slice,
    render_autotile_map,
    render_grid,
    render_pixel_text,
    vfx_hit_spark,
    vfx_slash_arc,
)
from PIL import Image


def main(output_dir: str = "output/examples/06_scene_mockup") -> None:
    # 1. Build 160x112 Auto-Tiled Arena Map (10x7 tiles of 16x16)
    grass = render_grid(["ggggGGGG" * 2, "ggGGGGGG" * 2, "GGGGgggg" * 2, "ggggGGGG" * 2] * 4, "endesga32")
    water = render_grid(["BBBBbbbb" * 2, "BBCCBBBB" * 2, "BBBBBBBB" * 2, "bbbbBBBB" * 2] * 4, "endesga32")
    at = generate_blob47_tileset(
        grass, water, outline_color="#181425", rim_highlight_color="#63C74D", rim_shadow_color="#8F563B"
    )
    arena_ascii = [
        "..........",
        ".########.",
        ".########.",
        ".########.",
        ".########.",
        "..######..",
        "..........",
    ]
    arena_bg = render_autotile_map(arena_ascii, at)  # 160x112

    # 2. Knight Attack Sequence (facing right)
    k_rig = Rig((40, 40), palette="endesga32", outline_mode="selout")
    k_rig.add_part("cape", [".RRRR.", "RRRRrr", "RRrrrr"], offset=(11, 21), z_index=5, outline_group=0)
    k_rig.add_part("torso", [".BBBBBBBB.", "B11YYYY22B", ".bbbbbbbb.", ".LL....LL."], offset=(14, 22), z_index=10, outline_group=0)
    k_rig.add_part("head", ["..111111..", ".1WW11122.", ".2KKKKKK2.", ".2YYKKYY2."], offset=(14, 15), z_index=20, outline_group=0)
    k_rig.add_part("sword", [".W.", "W1.", "W1.", "W1.", "YYY", ".L."], offset=(24, 15), pivot_local=(1, 4), z_index=30, outline_group=1)

    k_poses = [
        {"sword": {"angle": -45, "dx": -2}},
        {"torso": {"dx": 2}, "head": {"dx": 2}, "sword": {"angle": 75, "dx": 3, "dy": 2}},
        {"torso": {"dx": 2}, "head": {"dx": 2}, "sword": {"angle": 82, "dx": 3, "dy": 2}},
        {"sword": {"angle": 15}},
    ]
    knight_frames = [add_ground_shadow(k_rig.render_pose(p), baseline_y=27, center_x=19, fixed_width=13) for p in k_poses]
    slash = vfx_slash_arc((40, 40), center=(23, 21), radius=11, start_deg=-70, end_deg=70, thickness=3)
    knight_frames = composite_vfx(knight_frames, slash, start_frame=1)

    # 3. Enemy Crimson Slime (taking hit on frame 1-2!)
    s_rig = Rig((32, 32), palette="endesga32", outline_mode="outer")
    s_rig.add_part(
        "body",
        ["..MMMM..", ".MWWRRR.", "MWWRRRRR", "RRKRRKRR", "RRRRRRRR", ".rrrrrr."],
        offset=(12, 18),
        z_index=10,
        outline_group=0,
    )
    s_poses = [
        {},
        {"body": {"dx": 3, "scale_x": 0.86, "scale_y": 1.14, "flash_mix": 0.85}},
        {"body": {"dx": 4, "scale_x": 1.15, "scale_y": 0.85}},
        {"body": {"dx": 1}},
    ]
    slime_frames = [add_ground_shadow(s_rig.render_pose(p), baseline_y=24, center_x=16, fixed_width=10) for p in s_poses]
    spark = vfx_hit_spark((32, 32), center=(14, 21), radius=6)
    slime_frames = composite_vfx(slime_frames, spark, start_frame=1)

    # 4. 9-Slice HUD Top Bar + Crisp 3x5 Pixel Bitmap Text
    hud_src = PixelCanvas(12, 12, fill="5").rect(0, 0, 12, 12, outline="K").rect(1, 1, 10, 10, outline="Y").render("endesga32")
    hud_bar = render_9slice(hud_src, margins=(3, 3, 3, 3), target_size=(152, 18), mode="tile")
    hud_txt = render_pixel_text("KNIGHT HP:32/32   SLIME -48!", color="#FFFFFF", outline="#181425", scale=1)
    hud_bar.paste(hud_txt, (6, 5), hud_txt)

    # 5. Compose Scene & Run 4-Panel Grayscale Value / Readability Check
    scene = SceneComposer(160, 112, bg_color="#0099DB")
    scene.add_background_layer(arena_bg, offset=(0, 0))
    scene.add_entity("azure_knight", knight_frames, pos=(62, 68), durations_ms=[220, 90, 130, 200], anchor="foot", role="actor")
    scene.add_entity("crimson_slime", slime_frames, pos=(98, 70), durations_ms=[220, 90, 130, 200], anchor="foot", role="actor", flip_h=True)
    scene.add_entity("hud", hud_bar, pos=(4, 3), anchor="topleft", role="ui")
    scene.add_floating_text("dmg_popup", "-48!", pos=(98, 48), color="#FEE761", outline="#181425", rise_px=8)

    build_scene_mockup("island_skirmish", scene, frame_count=8, step_ms=80, preview_scale=3, output_dir=output_dir)


if __name__ == "__main__":
    main()
