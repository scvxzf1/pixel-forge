# 自动拼接地图（Auto-Tile）、实机场景明度自检与等轴测/多朝向指南

## 1. 47块 Blob 与 16块 Wang 自动拼接地形（`autotile.py`）

制作草地↔水面、泥土↔石板、地牢墙↔地板等交界地图时，**严禁手写 47 张转角网格**！只需准备两张同尺寸偶数正方形无缝底砖（如 `16x16` 的 `fg_tile` 与 `bg_tile`）：

```python
from pforge import generate_blob47_tileset, generate_wang16_tileset, render_autotile_map, export_autotile_bundle

blob = generate_blob47_tileset(
    fg_tile=grass_img,
    bg_tile=water_img,
    outline_color="#181425",
    rim_highlight_color="#91DB69",  # 左上受光草棱高光（自动保持全局左上光源，绝不倒置！）
    rim_shadow_color="#8F563B",     # 右下背光泥土断崖边与投影
)
export_autotile_bundle("emerald_coast", blob, sample_map=ASCII_MAP, output_dir="output/autotile")
```

- **自检要点**：必须打开生成的 `*_blob47_inspect.png` 或 `*_wang16_inspect.png`，同时核对上方带掩码编号的图集与下方由 `#/.` 地图渲染出的实机群岛/地牢（重点观察内凹海湾、外凸圆角与单格窄桥是否连续）。

---

## 2. 多资产实机场景沙盒与灰度明度自检（`scene.py`）

单看角色在灰底上清晰，不代表放进草地或地牢里看得清。交付多资产或带背景作品前，使用 `SceneComposer` 合成实机画面并执行 **4 联明度可读性诊断**：

```python
from pforge import SceneComposer, build_scene_mockup, render_pixel_text

scene = SceneComposer(160, 112, bg_color="#181425")
scene.add_background_layer(arena_map_img)
# anchor="foot" 按角色脚底坐标放置，并自动按脚底 Y 坐标执行 RPG 前后遮挡排序！
scene.add_entity("hero", hero_frames, pos=(62, 68), durations_ms=[220, 90, 130], anchor="foot", role="actor")
scene.add_entity("slime", slime_frames, pos=(98, 70), anchor="foot", role="actor", flip_h=True)
scene.add_floating_text("crit", "-48!", pos=(98, 48), color="#FEE761", outline="#181425", rise_px=8)

build_scene_mockup("battle_mockup", scene, frame_count=8, step_ms=80, output_dir="output/scene")
```

- **必须查看 `*_scene_inspect.png` 的四个象限**：
  1. `Live Color Mockup`：检查角色与环境比例、UI 排版与像素跳字。
  2. `Pure Grayscale Squint Test`（纯灰度眯眼测试）：检查前景角色与地板是否拉开了明度层次。
  3. `3-Slab Value Grouping`（深/中/浅三阶色块归纳）：检查画面是否糊成一片灰中调。
  4. `Silhouette Readability Heatmap`：绿色代表轮廓清晰跳脱，**若出现大量红色像素（`camouflaged_perimeter_ratio > 0.35`）**，说明角色融入了背景，需压暗/提亮地板或强化角色外轮廓（如切换 `outline_mode="outer"`）。

---

## 3. 严格 `2:1` 等轴测场景（`IsoScene`）与四/八向角色派生（`DirectionalRig`）

### A. `2:1` 等轴测体块搭建（零接缝格点代数）
像素等轴测严禁使用 `30°` 三角函数硬算斜线，必须严格遵循“横 `2px`、竖 `1px`”阶梯。使用 `IsoScene(half_h=8)`（对应 `32x16` 标准菱形砖）按 `(gx, gy, gz)` 三维坐标摆放体块，自动执行画家算法前后遮挡排序、三面受光（顶亮/左中/右暗）与前棱 `1px` 高光脊线：

```python
from pforge import IsoScene, build_pixel_asset

iso = IsoScene(half_h=8)
iso.add_block(gx=0, gy=0, gz=0, u_cells=2, v_cells=2, height_z=10, base_color="#63C74D", ridge_highlight="#91DB69")
iso.add_sprite(gx=0.5, gy=0.5, gz=10, sprite=chest_img)
build_pixel_asset("shrine", [iso.render()], output_dir="output/iso")
```

### B. 俯视角 RPG 四向（`S/E/N/W`）与八向行走图派生
使用 `DirectionalRig` 注册正面（`s`）各部件并标注解剖角色（`role="head" | "torso" | "cape" | "left_arm" | "right_arm" | "plume"`），引擎自动完成：
- **背面（`n`）**：遮蔽面部眼睛字符、将披风提至前景遮住后背、左右手持物按真实空间镜像交换。
- **侧面（`e` / `w`）**：收窄躯干、自动将正面双目转换为单目侧脸轮廓并用发色包裹后脑、近侧手臂前置而远侧手臂后置。
- **强制查看 `*_alignment_inspect.png`**：核对横贯全方向的青色头顶线（Head Top）与橙色脚底基准线（Foot Baseline）是否严丝合缝！
