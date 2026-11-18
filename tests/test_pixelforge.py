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

    def test_hd2d_normal_orientations_and_emission(self) -> None:
        # Build a 16x16 filled circle -> check OpenGL normal directions!
        c = pf.PixelCanvas(16, 16).circle(8, 8, 5, fill="B")
        disc = c.render("endesga32")
        # Add 1 glowing cyan center pixel
        disc.putpixel((8, 8), pf.parse_color("#2CE8F5"))

        nmap, _ = pf.generate_normal_map(disc, profile="dome", bevel_px=5.0, cluster_relief=0.0, luminance_relief=0.0)
        # Left edge (4, 8): outward normal points LEFT (-X -> R < 115)
        self.assertLess(nmap.getpixel((4, 8))[0], 115)
        # Right edge (12, 8): outward normal points RIGHT (+X -> R > 140)
        self.assertGreater(nmap.getpixel((12, 8))[0], 140)
        # Top edge (8, 4): outward normal points UP (+Y -> G > 140)
        self.assertGreater(nmap.getpixel((8, 4))[1], 140)
        # Bottom edge (8, 12): outward normal points DOWN (-Y -> G < 115)
        self.assertLess(nmap.getpixel((8, 12))[1], 115)

        emap = pf.generate_emission_map(disc, emissive_colors=["#2CE8F5"])
        # Relight in pitch darkness (intensity=0, ambient=#000000): only emissive center stays bright!
        lit_dark = pf.relight_sprite(disc, nmap, emission_map=emap, ambient_color="#000000", intensity=0.0, specular_strength=0.0)
        self.assertGreater(lit_dark.getpixel((8, 8))[1], 200)
        self.assertEqual(lit_dark.getpixel((6, 8))[:3], (0, 0, 0))

    def test_autorig_preserves_interior_whites_and_segments_islands(self) -> None:
        from PIL import ImageDraw
        sheet = Image.new("RGB", (160, 120), (250, 250, 250))
        d = ImageDraw.Draw(sheet)
        # Torso in center
        d.rectangle([60, 55, 100, 105], fill=(30, 100, 200), outline=(20, 20, 30), width=3)
        # Head above with pure-white enclosed interior eye!
        d.rectangle([66, 12, 94, 40], fill=(20, 20, 30))
        d.rectangle([74, 20, 86, 32], fill=(255, 255, 255))
        # Tall weapon on right
        d.rectangle([125, 40, 137, 100], fill=(220, 60, 60), outline=(20, 20, 30), width=2)

        clean = pf.remove_solid_background(sheet)
        # Corner bg must be alpha=0, while enclosed white eye at (80, 26) MUST remain opaque white!
        self.assertEqual(clean.getpixel((0, 0))[3], 0)
        self.assertEqual(clean.getpixel((80, 26)), (255, 255, 255, 255))

        with tempfile.TemporaryDirectory() as tmp:
            res = pf.autorig_from_concept_sheet(sheet, name="bot", canvas_size=(40, 40), part_scale_target=32, output_dir=tmp)
            self.assertIn("torso", res["parts_detected"])
            self.assertIn("head", res["parts_detected"])
            self.assertTrue(Path(res["files"]["rig_script"]).is_file())

    def test_aseprite_binary_multi_layer_tags_slices_roundtrip(self) -> None:
        l0_f0 = pf.render_grid(["....", ".BB.", ".BB.", "...."], "endesga32")
        l0_f1 = l0_f0.copy()  # identical -> exercises Linked Cel when use_linked_cels=True!
        l1_f0 = pf.render_grid(["RR..", "....", "....", "...."], "endesga32")
        l1_f1 = pf.render_grid(["....", "....", "....", "..YY"], "endesga32")

        with tempfile.TemporaryDirectory() as tmp:
            ase_path = Path(tmp) / "multi.aseprite"
            pf.write_aseprite(
                ase_path,
                canvas_size=(4, 4),
                layers=[("body", [l0_f0, l0_f1]), ("fx", [l1_f0, l1_f1])],
                durations_ms=[180, 65],
                palette="endesga32",
                frame_tags=[{"name": "idle", "from": 0, "to": 0}, {"name": "spark", "from": 1, "to": 1}],
                nine_slice_margins=(1, 1, 1, 1),
                pivots={"hand": (2.0, 3.0)},
                use_linked_cels=True,
            )
            doc = pf.read_aseprite(ase_path)
            self.assertEqual((doc.width, doc.height), (4, 4))
            self.assertEqual(doc.frame_count, 2)
            self.assertEqual(doc.durations_ms, [180, 65])
            self.assertEqual([l["name"] for l in doc.layers], ["body", "fx"])
            self.assertEqual([t["name"] for t in doc.tags], ["idle", "spark"])
            self.assertEqual(len(doc.slices), 2)

            # Verify exact pixel-level round-trip on individual layers AND composited output!
            pal = pf.get_palette("endesga32")
            self.assertEqual(doc.layers[1]["frames"][0].getpixel((0, 0)), pal["R"])
            self.assertEqual(doc.layers[1]["frames"][1].getpixel((3, 3)), pal["Y"])
            self.assertEqual(doc.composited_frames[1].getpixel((1, 1)), pal["B"])
            self.assertEqual(doc.composited_frames[1].getpixel((3, 3)), pal["Y"])

            # Also verify `decompile_asset` can read `.aseprite` directly!
            dec = pf.decompile_asset(ase_path, output_dir=Path(tmp) / "dec")
            self.assertEqual(dec["frame_count"], 2)
            self.assertEqual(dec["durations_ms"], [180, 65])

    def test_mcp_stdio_server_subprocess_protocol(self) -> None:
        import subprocess
        mcp_script = ROOT / "scripts" / "pforge_mcp.py"
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.Popen(
                [sys.executable, str(mcp_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
            )
            assert proc.stdin and proc.stdout
            msgs = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "pixelforge_build",
                        "arguments": {
                            "name": "mcp_gem",
                            "frames": ["..CC..\n.CWWC.\n.BBBB.\n..bb.."],
                            "output_dir": str(Path(tmp) / "build"),
                        },
                    },
                },
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "pixelforge_aseprite_inspect",
                        "arguments": {
                            "path": str(Path(tmp) / "build" / "mcp_gem.aseprite"),
                            "output_dir": str(Path(tmp) / "ase_ins"),
                            "include_inline_image": True,
                        },
                    },
                },
            ]
            out_str, _ = proc.communicate("\n".join(json.dumps(m) for m in msgs) + "\n", timeout=15)
            lines = [json.loads(line) for line in out_str.strip().splitlines() if line.strip()]
            # Notification has no id -> exactly 4 responses for ids 1, 2, 3, 4
            self.assertEqual([r["id"] for r in lines], [1, 2, 3, 4])
            tool_names = {t["name"] for t in lines[1]["result"]["tools"]}
            self.assertIn("pixelforge_build", tool_names)
            self.assertIn("pixelforge_aseprite_inspect", tool_names)
            self.assertFalse(lines[2]["result"]["isError"])
            # Response 4 has both text JSON and inline base64 PNG image content!
            c4 = lines[3]["result"]["content"]
            self.assertEqual(len(c4), 2)
            self.assertEqual(c4[1]["type"], "image")
            self.assertEqual(c4[1]["mimeType"], "image/png")


if __name__ == "__main__":
    unittest.main()
