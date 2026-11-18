# PixelForge CLI 命令与 Python API 完整速查手册

## 一、CLI 命令行工具（`scripts/pforge.py`）

| 子命令 | 用途 | 典型调用示例 |
| :--- | :--- | :--- |
| `inspect` | 为任意 PNG/GIF/APNG/WebP/精灵表生成全息自检图与 Linter 报告 | `python3 pforge.py inspect slime.gif -o work/` |
| `decompile` | 逆向拆解已有图片/动图/精灵表为语义调色板 + ASCII 网格 + 可编辑 `.py` 脚本 | `python3 pforge.py decompile sheet.png --cols 6 --rows 1 -o work/dec/` |
| `region-extract` | 按 `X,Y,W,H` 裁切大图局部为轻量 `.txt`/`.json` 与全局坐标自检图 | `python3 pforge.py region-extract boss.png --box 20,8,24,20 -o work/p/` |
| `region-apply` | 将修改后的局部补丁写回原图并输出 `Before/After/Diff` 对比图 | `python3 pforge.py region-apply boss.png --patch work/p/boss_x20_y8_w24_h20.json -o work/out/` |
| `pixelate` | 将高分原画或 AI 伪像素草图降采样、锁色去噪为干净像素工程 | `python3 pforge.py pixelate draft.png --size 48x48 --palette endesga32 -o work/px/` |
| `palette` | 从参考图提取语义色板与明暗色阶分组，或生成色相偏移色阶 | `python3 pforge.py palette ref.png --ramp-from "#E43B44"` |
| `recolor` | 批量替换单图或整段动图的颜色映射并输出 Diff 验证图 | `python3 pforge.py recolor hero.gif --map R=B,r=b -o work/blue/` |
| `lint` | 在终端输出 JSON 或可读像素质量静态检查报告 | `python3 pforge.py lint hero.gif` |
| `tile` | 生成单块网格 + 3x3 无缝平铺预览 + 接缝断层坐标检测看板 | `python3 pforge.py tile water.gif -o work/tile/` |
| `nine-slice` | 按 `L,T,R,B` 边距将九宫格母版扩展为指定尺寸 UI 面板 | `python3 pforge.py nine-slice frame.png --margins 5,5,5,5 --size 160x56 -o panel.png` |
| `autotile` | 从前景/背景两张无缝砖自动合成 47块 Blob 或 16块 Wang 自动拼接图集与测试地图 | `python3 pforge.py autotile --fg grass.png --bg water.png --mode blob47 -o work/at/` |
| `value-check` | 对任意场景或立绘生成纯灰度眯眼图与深/中/浅三阶明度归纳诊断看板 | `python3 pforge.py value-check scene.png -o work/val/` |
| `text` | 使用内置比例像素位图字库生成带描边的锐利像素文字与伤害跳字 PNG | `python3 pforge.py text "HP:32/32 -48!" --color "#FEE761" -o work/txt.png` |
| `normalmap` | 生成 HD-2D 切线法线贴图、自发光遮罩、四向光检图与 360° 火把环绕 GIF | `python3 pforge.py normalmap knight.png --emit "#2CE8F5" -o work/hd2d/` |
| `autorig` | 将纯色底多部件概念图自动去底、连通域拆件、统一锁色并生成可动 `Rig` 脚本 | `python3 pforge.py autorig boss_sheet.png --canvas 56x56 -o work/rig/` |
| `aseprite-inspect` | 解码原生 `.aseprite` 二进制工程，渲染多图层时间轴拆解矩阵并可解包单层 PNG | `python3 pforge.py aseprite-inspect hero.aseprite --unpack-layers -o work/ase/` |
| `print-mcp-config` | 输出（或 `--write` 写入）当前路径解析好的 `mcp_config.json` 配置 | `python3 pforge.py print-mcp-config` |
| `demo` | 运行内置史莱姆王多部件 + Sel-Out + 烟尘特效演示 | `python3 pforge.py demo -o output/demo` |

---

## 二、Python 核心 API（`from pforge import *`）

### 1. 调色板与色彩科学（`palette`）
- 内置色板字典/名称：`"endesga32"`、`PALETTE_ENDESGA32`、`"pico8"`、`"sweetie16"`、`"resurrect64"`、`"gameboy"`、`"mono1bit"`。
- `extract_palette(source, max_colors=32) -> dict[str, str]`：自动提取并分配直观的 HSV 语义字符键。
- `generate_shading_ramp(base_color, steps=4, warm_light=True) -> list[str]`：生成冷暗暖亮的像素色阶。
- `analyze_palette_ramps(palette) -> dict`：按色相家族梳理暗部/中间调/高光角色。
- `recolor_image(img, color_map, palette=None, tolerance=0) -> Image` & `remap_grid_chars(grid, char_map)`。

### 2. 画布、局部切片与几何原语（`canvas`）
- `render_grid(grid, palette="endesga32") -> Image` / `image_to_grid(img, palette=None) -> (lines, pal_dict)`。
- `extract_region_grid(grid, x, y, w, h)` / `patch_region_grid(base, patch, x, y, mode="replace"|"alpha_over")`。
- `extract_region_image(img, x, y, w, h)` / `patch_region_image(base_img, patch, x, y, palette=..., mode=...)`。
- `PixelCanvas(width, height, fill=".")`：
  - `.line(x0, y0, x1, y1, ch, pixel_perfect=True)`（自动剔除 L 角双像素锯齿）
  - `.rect(x, y, w, h, outline=None, fill=None)`
  - `.ellipse(cx, cy, rx, ry, outline=None, fill=None)` / `.circle(cx, cy, r, ...)`
  - `.polygon(points, outline=None, fill=None)`
  - `.flood_fill(x, y, ch)`
  - `.dither_rect(x, y, w, h, ch_primary, ch_secondary, ratio=0.5, matrix_size=4, only_on_char=None)`
  - `.stamp(sub_grid, x, y, mirror_h=False, mirror_v=False)` / `.mirror_symmetrize(source_half="left")`
  - `.to_lines()` / `.render(palette)`

### 3. 像素专用变换与描边（`transform`）
- `rotsprite(img, angle_deg, pivot=None, dx=0, dy=0, scale_x=1.0, scale_y=1.0)`：3 阶 Scale2x + 众数池化保色旋转。
- `selective_outline(img, light_dir=(-1, -1), dark_color="#181425", snap_palette=None)`：自适应光源描边（Sel-out）。
- `auto_outline(img, color="#181425", connectivity=4, mode="outer"|"inner")`。
- `squash_stretch(img, scale_x, scale_y, anchor="bottom", baseline_y=None)`。
- `shift_grid(grid, dx, dy, wrap=False)` / `shift_image(img, dx, dy, wrap=False)`。
- `smear_between(prev_img, curr_img, trail_color=None, steps=3)`：帧间高速运动拖影。
- `add_ground_shadow(img, baseline_y=None, center_x=None, fixed_width=None)`。

### 4. 多部件骨骼与多状态角色导出（`rig`, `vfx`, `exporter`）
- `Rig(canvas_size, palette="endesga32", outline_mode="selout"|"outer"|"none")`：
  - `.add_part(name, source_or_variants_dict, offset=(x, y), pivot_local=(px, py), z_index=0, outline_group=0)`
  - `.render_pose(pose_dict, under_layers=None, over_layers=None) -> Image`
- `SpriteActor(name, palette="endesga32")`：
  - `.add_clip(clip_name, frames, durations_ms=[...], direction="forward")`
- `build_pixel_asset(name, frames, palette="endesga32", durations_ms=None, fps=8, formats=("gif","apng","webp"), output_dir="output")`。
- `build_actor_assets(actor, output_dir="output")`：导出所有独立动作 + 合并图集 `*_master_atlas.png` 与 Aseprite `*_master_atlas.json`。

### 5. 自动地形、场景明度沙盒、等轴测与多朝向角色（`autotile`, `scene`, `isometric`）
- `generate_blob47_tileset(fg_tile, bg_tile, outline_color="#181425", rim_highlight_color=None, rim_shadow_color=None)` / `generate_wang16_tileset(...)`。
- `render_autotile_map(terrain_map, autotile_bundle)` / `export_autotile_bundle(name, bundle, output_dir=..., sample_map=...)`。
- `render_pixel_text(text, color="#FFFFFF", outline="#181425", shadow=None, scale=1)`：内置比例像素字库。
- `SceneComposer(width, height)` + `build_scene_mockup(name, composer, frame_count=12, step_ms=100, output_dir=...)`：Y 轴深度排序实机合成与 4 联灰度明度/轮廓对比度热力诊断。
- `render_iso_prism(...)` & `IsoScene(half_h=8)`：`2:1` 零裂缝等轴测三维场景搭建。
- `DirectionalRig(canvas_size, palette="endesga32")` + `export_multidir_sheets(name, dir_rig, directions=DIRECTIONS_4|DIRECTIONS_8)`：四向/八向转身与行走图集自动派生。

### 6. HD-2D 动态法线光影与设定图自动拆件绑骨（`lighting`, `autorig`）
- `Rig.render_part_layers(pose=None, part_profiles={"sword": "ridge", ...})`：导出逐部件浮雕法线源。
- `generate_normal_map(source, profile="dome"|"bevel"|"ridge", bevel_px=4.5, bump_strength=2.2)`。
- `generate_emission_map(albedo, emissive_colors=[...])` / `relight_sprite(albedo, normal_map, emission_map=..., light_pos=(lx,ly,lz), cel_bands=4)`。
- `export_hd2d_bundle(name, albedo, part_layers=..., emissive_colors=..., output_dir="output/hd2d")`。
- `remove_solid_background(img)` / `segment_parts_from_sheet(img)` / `autorig_from_concept_sheet(source, name=..., canvas_size=(56,56), palette="endesga32", output_dir="output/autorig")`。

### 7. 原生 `.aseprite` 二进制读写与分层导出（`aseprite_io`）
- `Rig.render_named_layers_sequence(poses)` / `Rig.get_named_canvas_pivots()`：生成按深度排序的独立部件图层序列与命名轴心。
- `write_aseprite(target, canvas_size, layers, durations_ms, palette=None, frame_tags=None, nine_slice_margins=None, pivots=None, use_linked_cels=False)`。
- `read_aseprite(source) -> AsepriteDocument`：解析 `32/16/8-bit` `.ase`/`.aseprite` 二进制工程的图层、关联/压缩 Cel、帧时长、标签、色板与切片。
- `generate_aseprite_layer_sheet(doc, title=..., scale=3) -> Image`：渲染可视化多图层时间轴拆解矩阵看板。
