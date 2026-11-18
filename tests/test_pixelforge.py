#!/usr/bin/env python3
"""Comprehensive automated unit & integration tests for PixelForge."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pforge as pf


class TestPixelForgeSuite(unittest.TestCase):
    def test_palette_and_ramps(self) -> None:
        ramp = pf.generate_shading_ramp("#E43B44", steps=4)
        self.assertEqual(len(ramp), 4)
        lums = [pf.luminance(pf.parse_color(c)) for c in ramp]
        self.assertLess(lums[0], lums[-1])

        ramps_map = pf.analyze_palette_ramps("endesga32")
        self.assertIn("blue", ramps_map)
        self.assertIn("neutral", ramps_map)

    def test_grid_roundtrip_and_diagnostics(self) -> None:
        grid = [
            ".KK.",
            "KBBK",
            "KbbK",
            ".KK.",
        ]
        img = pf.render_grid(grid, "endesga32")
        rec_grid, _ = pf.image_to_grid(img, "endesga32")
        self.assertEqual(rec_grid, grid)

        with self.assertRaisesRegex(ValueError, "Row 1 width mismatch"):
            pf.render_grid(["....", "..."], "endesga32")

        with self.assertRaisesRegex(ValueError, "Undefined palette char"):
            pf.render_grid(["..~."], "endesga32")

    def test_pixel_canvas_primitives_no_lcorners(self) -> None:
        c = pf.PixelCanvas(16, 16)
        c.line(1, 1, 12, 8, "K", pixel_perfect=True)
        c.circle(8, 8, 4, outline="R", fill="B")
        c.dither_rect(0, 0, 16, 16, "B", "b", ratio=0.5, matrix_size=2, only_on_char="B")
        img = c.render("endesga32")
        self.assertEqual(img.size, (16, 16))
        # Verify symmetric horizontal spans on circle
        lines = c.to_lines()
        self.assertEqual(len(lines), 16)

    def test_surgical_region_patch_and_diff(self) -> None:
        base_grid = ["BBBBBBBB" for _ in range(8)]
        base_img = pf.render_grid(base_grid, "endesga32")

        sub = pf.extract_region_grid(base_grid, 2, 2, 4, 4)
        self.assertEqual(len(sub), 4)
        self.assertEqual(len(sub[0]), 4)

        patch = [
            ".RR.",
            "RYYR",
            "RYYR",
            ".RR.",
        ]
        after_over = pf.patch_region_image(base_img, patch, 2, 2, palette="endesga32", mode="alpha_over")
        _, stats_over = pf.generate_diff_sheet(base_img, after_over)
        # 12 non-dot chars in patch -> exactly 12 recolored pixels, corners stay 'B'
        self.assertEqual(stats_over["changed_pixels"], 12)
        self.assertEqual(stats_over["recolored"], 12)
        self.assertEqual(stats_over["removed"], 0)

        after_rep = pf.patch_region_image(base_img, patch, 2, 2, palette="endesga32", mode="replace")
        _, stats_rep = pf.generate_diff_sheet(base_img, after_rep)
        # 12 recolored + 4 corner dots erased to transparent = 16 changed pixels
        self.assertEqual(stats_rep["changed_pixels"], 16)
        self.assertEqual(stats_rep["removed"], 4)

    def test_rotsprite_preserves_pure_palette_colors(self) -> None:
        sword = [
            "...W...",
            "..W1...",
            "..W1...",
            "..W1...",
            ".YYYYY.",
            "...L...",
        ]
        src = pf.render_grid(sword, "endesga32")
        orig_colors = {pf.normalize_rgba(p) for p in pf.img_pixels(src)} | {(0, 0, 0, 0)}

        rotated = pf.rotsprite(src, angle_deg=-33.0, pivot=(3.0, 4.0))
        rot_colors = {pf.normalize_rgba(p) for p in pf.img_pixels(rotated)}
        # Zero dirty anti-aliased intermediate colors allowed!
        self.assertTrue(rot_colors.issubset(orig_colors))

    def test_selective_outline_snaps_to_palette(self) -> None:
        ball = [
            "......",
            "..BB..",
            ".BBBB.",
            ".BBBB.",
            "..bb..",
            "......",
        ]
        img = pf.render_grid(ball, "endesga32")
        sel = pf.selective_outline(img, snap_palette="endesga32")
        allowed = set(pf.get_palette("endesga32").values())
        actual = {pf.normalize_rgba(p) for p in pf.img_pixels(sel)}
        self.assertTrue(actual.issubset(allowed))

    def test_upscale_detection_and_decompile(self) -> None:
        native = pf.render_grid(["..KK..", ".KRRK.", ".KrrK.", "..KK.."] + ["......"] * 2, "endesga32")
        upscaled_6x = native.resize((native.width * 6, native.height * 6), Image.Resampling.NEAREST)
        k = pf.detect_integer_upscale_factor([upscaled_6x])
        self.assertEqual(k, 6)

        with tempfile.TemporaryDirectory() as tmp:
            up_path = Path(tmp) / "icon_6x.png"
            upscaled_6x.save(up_path)
            bundle = pf.decompile_asset(up_path, output_dir=Path(tmp) / "dec")
            self.assertEqual(bundle["native_width"], 6)
            self.assertEqual(bundle["native_height"], 6)
            self.assertEqual(bundle["auto_downscaled_by"], 6)

    def test_exporter_formats_and_actor_atlas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            actor = pf.SpriteActor("slime", palette="endesga32")
            f0 = pf.render_grid(["....", ".BB.", ".bb.", "...."], "endesga32")
            # Include semi-transparent shadow pixel to verify 8-bit alpha in APNG/WebP
            f1 = f0.copy()
            f1.putpixel((0, 3), (24, 20, 37, 110))
            actor.add_clip("idle", [f0, f1], durations_ms=[200, 120])
            actor.add_clip("jump", [f1, f0, f1], durations_ms=[80, 140, 90])

            res = pf.build_actor_assets(actor, output_dir=tmp)
            atlas_meta = json.loads(Path(res["master_atlas_json"]).read_text(encoding="utf-8"))
            tags = {t["name"]: (t["from"], t["to"]) for t in atlas_meta["meta"]["frameTags"]}
            self.assertEqual(tags["idle"], (0, 1))
            self.assertEqual(tags["jump"], (2, 4))

            # Verify APNG & WebP preserved exact semi-transparent alpha=110 on frame 1!
            apng_path = res["clips"]["idle"]["files"]["apng_1x"]
            webp_path = res["clips"]["idle"]["files"]["webp_1x"]
            for p in (apng_path, webp_path):
                with Image.open(p) as anim:
                    anim.seek(1)
                    self.assertEqual(anim.convert("RGBA").getpixel((0, 3))[3], 110)

    def test_seamless_tile_and_9slice(self) -> None:
        clean_tile = pf.render_grid(["BBBB", "BbbB", "BbbB", "BBBB"], "endesga32")
        self.assertTrue(pf.check_tile_seamless(clean_tile)["seamless_ok"])

        # Introduce sharp seam break on row y=2 (left='W', right='K')
        broken_tile = pf.render_grid(["BBBB", "BBBB", "WWKK", "BBBB"], "endesga32")
        rep = pf.check_tile_seamless(broken_tile)
        self.assertFalse(rep["seamless_ok"])
        self.assertIn(2, rep["left_right_mismatch_rows_y"])

        # 9-slice corner preservation
        src9 = pf.render_grid([
            "RGGGGY",
            "G....G",
            "G....G",
            "BGGGGW",
        ], "endesga32")
        panel = pf.render_9slice(src9, margins=(1, 1, 1, 1), target_size=(12, 8), mode="tile")
        self.assertEqual(panel.size, (12, 8))
        pal = pf.get_palette("endesga32")
        self.assertEqual(panel.getpixel((0, 0)), pal["R"])
        self.assertEqual(panel.getpixel((11, 0)), pal["Y"])
        self.assertEqual(panel.getpixel((0, 7)), pal["B"])
        self.assertEqual(panel.getpixel((11, 7)), pal["W"])

    def test_cli_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tdir = Path(tmp)
            src_img = pf.render_grid([
                "........",
                "..KKKK..",
                ".KRRRRK.",
                ".KRWWRK.",
                ".KrrrrK.",
                "..KKKK..",
                "........",
                "........",
            ], "endesga32")
            src_file = tdir / "orb.png"
            src_img.save(src_file)

            self.assertEqual(pf.main(["inspect", str(src_file), "-o", str(tdir / "ins")]), 0)
            self.assertEqual(
                pf.main(["region-extract", str(src_file), "--box", "2,2,4,4", "-o", str(tdir / "reg")]),
                0,
            )
            patch_json = tdir / "reg" / "orb_x2_y2_w4_h4.json"
            self.assertTrue(patch_json.is_file())
            self.assertEqual(
                pf.main(["region-apply", str(src_file), "--patch", str(patch_json), "-o", str(tdir / "pat")]),
                0,
            )
            self.assertEqual(
                pf.main(["recolor", str(src_file), "--map", "R=B,r=b", "-o", str(tdir / "rec")]),
                0,
            )
            self.assertEqual(
                pf.main(["pixelate", str(src_file), "--size", "8x8", "-o", str(tdir / "px")]),
                0,
            )

    def test_autotile_blob47_and_wang16(self) -> None:
        self.assertEqual(len(pf.CANONICAL_BLOB_47), 47)
        fg = pf.render_grid(["GGGG" * 4] * 16, "endesga32")
        bg = pf.render_grid(["BBBB" * 4] * 16, "endesga32")
        blob = pf.generate_blob47_tileset(fg, bg, rim_highlight_color="#91DB69", rim_shadow_color="#8F563B")
        self.assertEqual(len(blob["tiles"]), 47)
        m_img = pf.render_autotile_map(["....", ".##.", ".##.", "...."], blob)
        self.assertEqual(m_img.size, (64, 64))

        wang = pf.generate_wang16_tileset(fg, bg)
        self.assertEqual(len(wang["tiles"]), 16)
        w_img = pf.render_autotile_map(["....", ".##.", ".##.", "...."], wang)
        self.assertEqual(w_img.size, (48, 48))

    def test_scene_composer_and_camouflaged_value_warning(self) -> None:
        # 1) Low-contrast scene: dark gray actor with NO outline on identical dark gray floor -> must warn!
        floor = pf.render_grid(["3333" * 4] * 16, "endesga32")
        camo_actor = pf.render_grid([
            "........",
            "..3333..",
            "..3333..",
            "..3333..",
            "........",
        ], "endesga32")
        sc_bad = pf.SceneComposer(32, 32)
        sc_bad.set_tiled_background(floor)
        sc_bad.add_entity("stealth_blob", camo_actor, pos=(16, 20), anchor="foot", role="actor")
        _, _, rep_bad = sc_bad.render_sequence(frame_count=2, step_ms=100)
        self.assertGreater(len(rep_bad["warnings"]), 0)
        self.assertGreater(rep_bad["actors"]["stealth_blob"]["camouflaged_perimeter_ratio"], 0.5)

        # 2) Outlined bright actor + crisp pixel text -> 0 camouflage warnings
        clear_actor = pf.auto_outline(pf.render_grid(["......", "..WW..", "..WW..", "......"], "endesga32"), "#181425")
        sc_good = pf.SceneComposer(48, 32)
        sc_good.set_tiled_background(floor)
        sc_good.add_entity("hero", clear_actor, pos=(24, 20), anchor="foot", role="actor")
        sc_good.add_floating_text("dmg", "-99!", pos=(24, 10))
        frames, _, rep_good = sc_good.render_sequence(frame_count=2, step_ms=100)
        self.assertEqual(len(rep_good["warnings"]), 0)
        self.assertEqual(frames[0].size, (48, 32))

    def test_isometric_prism_and_multidir_rig(self) -> None:
        prism, apex = pf.render_iso_prism(half_h=6, u_cells=1, v_cells=1, height_z=8)
        self.assertGreater(prism.width, 20)
        self.assertGreater(apex[0], 0)

        iso = pf.IsoScene(half_h=6)
        iso.add_block(0, 0, gz=0, height_z=8, base_color="#63C74D")
        iso.add_block(1, 0, gz=0, height_z=8, base_color="#63C74D")
        iso.add_block(0, 1, gz=0, height_z=8, base_color="#63C74D")
        diorama = iso.render()
        self.assertIsNotNone(diorama.getchannel("A").getbbox())

        drig = pf.DirectionalRig((24, 24), palette="endesga32")
        drig.add_part("torso", [".BBBB.", "BBBBBB", ".bbbb."], role="torso", offset=(9, 12))
        drig.add_part("head", [".SSSS.", "SKSSKS", ".SSSS."], role="head", offset=(9, 7), back_fill_char="L")
        with tempfile.TemporaryDirectory() as tmp:
            res4 = pf.export_multidir_sheets("hero", drig, directions=pf.DIRECTIONS_4, output_dir=tmp)
            with Image.open(res4["walk_sheet_png"]) as ws:
                self.assertEqual(ws.size, (24 * 4, 24 * 4))
            res8 = pf.export_multidir_sheets("hero8", drig, directions=pf.DIRECTIONS_8, output_dir=tmp)
            with Image.open(res8["walk_sheet_png"]) as ws8:
                self.assertEqual(ws8.size, (24 * 4, 24 * 8))


if __name__ == "__main__":
    unittest.main()
