#!/usr/bin/env python3
"""Example 01: Multi-Part Rigging + RotSprite Weapon Rotation + Multi-Action SpriteActor
Builds a 40x40 Pixel Knight with 3 animation states (`idle`, `attack`, `hit`),
non-uniform combat timing (`durations_ms`), crescent slash & dust VFX, and Aseprite Master Atlas.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import (
    Rig,
    SpriteActor,
    add_ground_shadow,
    build_actor_assets,
    composite_vfx,
    vfx_dust_puff,
    vfx_hit_spark,
    vfx_slash_arc,
)


def main(output_dir: str = "output/examples/01_knight") -> None:
    rig = Rig(canvas_size=(40, 40), palette="endesga32", outline_mode="selout")

    # Compact un-outlined part grids (Rig merges by outline_group and adds Sel-out automatically!)
    plume = [
        "..RRR.",
        ".RRRRr",
        "RRrr..",
    ]
    helmet_idle = [
        "..111111..",
        ".1WW11122.",
        ".11111122.",
        ".2KKKKKK2.",
        ".2KCKKCK2.",
        "..222222..",
    ]
    helmet_fierce = [
        "..111111..",
        ".1WW11122.",
        ".11111122.",
        ".2KKKKKK2.",
        ".2YYKKYY2.",
        "..222222..",
    ]
    torso = [
        ".BBBBBBBB.",
        "B11BBBB22B",
        "B11YYYY22B",
        ".bbbbbbbb.",
        ".LL....LL.",
        ".ll....ll.",
    ]
    cape = [
        ".RRRR.",
        "RRRRrr",
        "RRRrrr",
        "RRrrrr",
        ".rrrr.",
    ]
    shield = [
        ".YYYY.",
        "Y1112Y",
        "Y1BB2Y",
        "Y1bb2Y",
        ".YooY.",
        "..oo..",
    ]
    sword = [
        "..W..",
        ".W1..",
        ".W1..",
        ".W1..",
        ".W1..",
        ".12..",
        ".12..",
        "YYYYY",
        "..L..",
        "..l..",
    ]

    rig.add_part("cape", cape, offset=(11, 21), pivot_local=(3, 0), z_index=5, outline_group=0)
    rig.add_part("torso", torso, offset=(14, 22), pivot_local=(5, 3), z_index=10, outline_group=0)
    rig.add_part(
        "helmet",
        {"idle": helmet_idle, "fierce": helmet_fierce},
        offset=(14, 14),
        pivot_local=(5, 5),
        z_index=20,
        outline_group=0,
    )
    rig.add_part("plume", plume, offset=(13, 11), pivot_local=(4, 2), z_index=18, outline_group=0)
    # Foreground equipment in separate outline_group=1 so shield & sword preserve crisp overlap borders!
    rig.add_part("shield", shield, offset=(11, 22), pivot_local=(3, 2), z_index=25, outline_group=1)
    rig.add_part("sword", sword, offset=(24, 14), pivot_local=(2, 8), z_index=30, outline_group=1)

    # 1. IDLE CLIP (4 frames, gentle breathing with secondary plume/cape lag)
    idle_poses = [
        {},
        {"helmet": {"dy": 1}, "plume": {"dy": 0, "angle": -5}, "shield": {"dy": 1}, "sword": {"dy": 1, "angle": 4}},
        {"torso": {"scale_y": 0.94, "dy": 1}, "helmet": {"dy": 1}, "plume": {"dy": 2, "angle": -8}, "cape": {"dy": 1}, "shield": {"dy": 1}, "sword": {"dy": 1, "angle": 6}},
        {"plume": {"dy": 1, "angle": 3}, "cape": {"angle": 4}},
    ]
    idle_frames = [add_ground_shadow(rig.render_pose(p), baseline_y=28, center_x=19, fixed_width=14) for p in idle_poses]

    # 2. ATTACK CLIP (6 frames: anticipation -> hold -> explosive snap + slash -> hitstop -> recover)
    attack_poses = [
        {"helmet": {"variant": "fierce"}, "sword": {"angle": -25, "dx": -2, "dy": -1}},
        {"torso": {"dx": -2, "scale_x": 1.06, "scale_y": 0.94}, "helmet": {"variant": "fierce", "dx": -2, "dy": 1}, "plume": {"dx": -3, "angle": -14}, "cape": {"dx": -2, "angle": 12}, "shield": {"dx": -3, "dy": 1}, "sword": {"angle": -62, "dx": -4, "dy": -2}},
        {"torso": {"dx": -2, "scale_x": 1.08, "scale_y": 0.92}, "helmet": {"variant": "fierce", "dx": -2, "dy": 1}, "plume": {"dx": -3, "angle": -18}, "cape": {"dx": -2, "angle": 16}, "shield": {"dx": -3, "dy": 1}, "sword": {"angle": -75, "dx": -5, "dy": -2}},
        {"torso": {"dx": 3}, "helmet": {"variant": "fierce", "dx": 3}, "plume": {"dx": 1, "angle": 15}, "cape": {"dx": 1, "angle": -18}, "shield": {"dx": 1}, "sword": {"angle": 82, "dx": 4, "dy": 2}},
        {"torso": {"dx": 3}, "helmet": {"variant": "fierce", "dx": 3}, "plume": {"dx": 2, "angle": 8}, "cape": {"dx": 2, "angle": -10}, "shield": {"dx": 1}, "sword": {"angle": 88, "dx": 4, "dy": 3}},
        {"torso": {"dx": 1}, "helmet": {"dx": 1}, "plume": {"dx": 1}, "sword": {"angle": 25, "dx": 1, "dy": 1}},
    ]
    atk_raw = [add_ground_shadow(rig.render_pose(p), baseline_y=28, center_x=20, fixed_width=15) for p in attack_poses]
    slash = vfx_slash_arc((40, 40), center=(23, 21), radius=12, start_deg=-80, end_deg=75, thickness=4)
    dust = vfx_dust_puff((40, 40), origin=(15, 28), direction="left")
    atk_frames = composite_vfx(atk_raw, dust, start_frame=2, under=True)
    atk_frames = composite_vfx(atk_frames, slash, start_frame=2, under=False)

    # 3. HIT CLIP (4 frames: flash + knockback + spark -> settle)
    hit_poses = [
        {"torso": {"dx": -3, "flash_mix": 0.9}, "helmet": {"dx": -3, "dy": -1, "flash_mix": 0.9}, "plume": {"dx": -4, "angle": -20, "flash_mix": 0.9}, "cape": {"dx": -3, "flash_mix": 0.9}, "shield": {"dx": -2, "flash_mix": 0.9}, "sword": {"dx": -2, "angle": -20, "flash_mix": 0.9}},
        {"torso": {"dx": -4}, "helmet": {"dx": -4}, "plume": {"dx": -5, "angle": -15}, "cape": {"dx": -4, "angle": 14}, "shield": {"dx": -3}, "sword": {"dx": -3, "angle": -30}},
        {"torso": {"dx": -2}, "helmet": {"dx": -2}, "plume": {"dx": -2, "angle": -6}, "shield": {"dx": -1}, "sword": {"dx": -1, "angle": -10}},
        {},
    ]
    hit_raw = [add_ground_shadow(rig.render_pose(p), baseline_y=28, center_x=18, fixed_width=14) for p in hit_poses]
    spark = vfx_hit_spark((40, 40), center=(16, 21), radius=6)
    hit_frames = composite_vfx(hit_raw, spark, start_frame=0, under=False)

    actor = SpriteActor("azure_knight", palette="endesga32")
    actor.add_clip("idle", idle_frames, durations_ms=[260, 180, 260, 180])
    actor.add_clip("attack", atk_frames, durations_ms=[120, 140, 190, 45, 65, 150])
    actor.add_clip("hit", hit_frames, durations_ms=[50, 75, 110, 140])

    build_actor_assets(actor, output_dir=output_dir, pivots=rig.get_canvas_pivots())


if __name__ == "__main__":
    main()
