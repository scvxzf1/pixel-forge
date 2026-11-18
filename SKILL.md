---
name: pixel-forge
description: >-
  全功能视觉多模态像素画与动图工坊（PixelForge）。用于从零构建像素画/图标/大尺寸分层精灵、
  逆向反编译并局部修改已有 PNG/GIF/精灵表、将高分图或 AI 草图转为干净像素画（Pixelate）、
  提取参考图色板与明暗色阶、制作带 RotSprite 部件旋转与可变帧率节奏的多动作动图（GIF/APNG/WebP/Aseprite 图集）、
  无缝 Tileset 3x3 拼接检测及九宫格 UI。凡涉及像素画创作、像素修改、像素化处理或像素动画时调用此技能。
---

# PixelForge — 视觉大模型像素画构建、精修与动画套件

本技能通过 `./scripts/pforge.py`（同时提供 CLI 命令行与 `pixelforge` Python 库，仅依赖 `Pillow`）赋予视觉 LLM 工业级像素资产生产与逆向精修能力。

## 一、核心铁律（严禁违反）

1. **禁止手写稀疏坐标点列**：严禁堆砌几十行 `putpixel((x, y))`。基础图形必须使用**等宽 ASCII 字符网格**（`.` 和空格固定代表透明）、紧凑局部部件 `Rig`（仅画部件本身并通过 `offset=(ox, oy)` 定位，无需填满整张画布空点），或 `PixelCanvas` 像素级几何原语（抗 L 角直线、对称椭圆、Bayer 有序抖动）。
2. **按分辨率选择正确架构**：
   - `16x16 ~ 32x32`：直接编写全画布 ASCII 网格或轻量 `Rig`。
   - `48x48 ~ 64x64`：**必须分层/分部件**（使用无外描边色块部件 + `Rig(..., outline_mode="selout"|"outer")` 自动统合描边）；修改局部细节时优先使用 **Region Patch 局部切片**而非全图重绘。
   - `64x64 ~ 128x128+`：使用 `PixelCanvas` 几何底稿 + `stamp()` 局部印章 + `dither_rect()` 有序抖动 + 局部 Region Patch 精修。
3. **强制多模态全息视觉闭环**：
   - 每次生成或修改都会输出全息诊断看板 `<name>_inspect.png`（内含：**字符色板图例 `[char] #HEX`** + **0 起始 `(X, Y)` 坐标网格与地面基准线** + **无网格深/浅双底实机预览** + **剪影与红青洋葱皮运动轨迹**）及终端 `Pixel Linter` 报告。
   - **交付前必须调用看图工具（如 `read_file` / `view_image` / `Read`）亲自查看 `<name>_inspect.png`（修改任务还需查看 `<name>_diff.png`）！**
   - 对照图上坐标与 Linter 警告，逐一排查：外轮廓漏口（尤其在浅色底预览下检查深色描边）、斜线/弧线阶梯锯齿（Jaggies）、帧间脚底漂移（`baseline_y`）及非预期改动像素，修完复检通过后方可交付。

---

## 二、四大标准工作流

### 1. 从零构建像素画与多动作动画
1. **选定调色板**：优先选用内置经典色板 `"endesga32"`、`"pico8"`、`"sweetie16"`、`"resurrect64"`、`"gameboy"`，或用 `pforge.py palette <ref.png>` 提取参考图色板与色阶。默认左上光源（左上高光暖移、右下暗部冷移），推荐开启 `outline_mode="selout"`（自适应光源描边）。
2. **构建与绑定**：
   - 拓扑变化大（走路交叉腿、张嘴獠牙变形）→ 用 ASCII 关键帧或 `Part` 多状态字典 `{"closed": ..., "open": ...}`。
   - 刚体旋转/挤压（箱盖绕铰链掀开、挥剑、呼吸弹跳）→ 用 `Rig` + `rotsprite` 绕锚点旋转与 `squash_stretch`。
   - 打击感节奏 → 必须使用非均匀 `durations_ms`（如蓄力 `180ms` → 爆发挥砍 `40ms` → 顿帧 `55ms` → 缓冲 `150ms`），配合 `vfx_slash_arc` / `vfx_dust_puff` / `vfx_hit_spark`。
   - 单角色多动作（`idle` / `walk` / `attack`）→ 使用 `SpriteActor` 一键导出独立动图与合并图集 `<actor>_master_atlas.png/.json`。
3. 运行脚本导出 GIF + 真半透明 APNG + 无损动态 WebP + Aseprite JSON，**读取 `_inspect.png` 视觉自检**并消缺。

### 2. 基于已有像素画做修改（PNG / GIF / 精灵表）
- **先看图诊断**：
  ```bash
  python3 <SKILL_DIR>/scripts/pforge.py inspect input.png -o work/
  ```
  *（注：引擎会自动识别 `4x`/`8x` 整数倍放大预览图并无损还原为 `1x` 原生像素网格；若需保留原尺寸加 `--keep-scale`。）*
- **小图/全帧反编译修改**：
  ```bash
  python3 <SKILL_DIR>/scripts/pforge.py decompile walk.gif -o work/walk_proj/
  ```
  自动拆解所有帧与帧时长，生成带语义字符色板的 `edit_walk.py` 与 `_inspect.png`，修改脚本后重跑即可。
- **大图局部手术式精修（Region Patch，强烈推荐 48x48+ 使用）**：
  ```bash
  # 1) 按 0 起始坐标框 (X,Y,W,H) 切出局部网格，生成的自检图自动保留全局 X/Y 坐标刻度！
  python3 <SKILL_DIR>/scripts/pforge.py region-extract hero.png --box 14,6,20,18 -o work/patch/
  # 2) 编辑切出的 .txt 字符网格后回写，自动输出 Before | After | Diff 三联对比图
  python3 <SKILL_DIR>/scripts/pforge.py region-apply hero.png --patch work/patch/hero_x14_y6_w20_h18.json -o work/out/
  ```
  **必须读取生成的 `*_diff.png`**，确认改动严格落在目标区域且边缘衔接自然。
- **一键语义换色 / 阵营变体**：
  ```bash
  python3 <SKILL_DIR>/scripts/pforge.py recolor slime.gif --map B=R,b=r,C=Y -o work/fire_slime/
  ```

### 3. 高分图 / AI 概念草图转像素画（Pixelate & Clean）
当用户提供高分辨率插画、照片或边缘糊乱的 AI“伪像素图”时：
```bash
# 插画/概念图用 contrast_box；AI 伪像素图用 --mode dominant_block 消除歪斜网格与杂色
python3 <SKILL_DIR>/scripts/pforge.py pixelate draft.png --size 48x48 --palette endesga32 --outline "#181425" -o work/px/
```
读取生成的 `*_compare.png` 与 `*_inspect.png`，在自动生成的 `edit_*.py` 中手工点亮眼睛高光、修顺轮廓阶梯后再交付。

### 4. 无缝地图块、47块自动地形（Auto-Tile）、九宫格 UI、等轴测与实机场景明度自检
- **无缝单砖与九宫格 UI**：`pforge.py tile grass.png`（3x3 接缝断层标红检测）；`pforge.py nine-slice frame.png --margins 4,4,4,4 --size 160x56`。
- **47块 Blob / 16块 Wang 自动拼接地形**：仅提供前景/背景两张底砖，调用 `pforge.py autotile --fg grass.png --bg water.png --mode blob47`（或 Python `generate_blob47_tileset`），自动合成全部内外转角并铺出测试群岛地图 `*_blob47_inspect.png`。
- **`2:1` 等轴测建筑与 4/8 向 RPG 角色**：使用 `IsoScene` 构建零裂缝 `2:1` 三面受光等轴测体块场景；使用 `DirectionalRig` + `export_multidir_sheets` 从正面部件派生 `S/E/N/W` 四向或八向旋转与行走图集，并读取 `*_alignment_inspect.png` 核对头顶/脚底水平对齐线。
- **多资产实机场景沙盒与灰度明度自检**：使用 `SceneComposer` + `render_pixel_text`（内置紧凑像素字库）+ `build_scene_mockup` 合成带 Y 轴遮挡排序与跳字 UI 的实机战斗/探索动图，**必须读取 `*_scene_inspect.png` 检查纯灰度眯眼图与轮廓对比度热力图**，消除角色融入背景的明度打架问题。

---

## 三、Python 快速调用模板

```python
import sys
sys.path.insert(0, "/path/to/pixel-forge/scripts")
from pforge import Rig, SpriteActor, build_pixel_asset, build_actor_assets, vfx_slash_arc, composite_vfx

# 单资产极速构建
build_pixel_asset("gem", ["..CC..\n.CWWC.\nCBBBBc\n.bbbb."], palette="endesga32", output_dir="output")
```

---

## 四、进阶参考手册（按需读取，渐进式披露）

执行具体细分任务前，请按需查阅本技能目录下的专题指南：
- **像素画造型、色簇抗锯齿、明暗色阶与抖动技法**：[craft_and_shading.md](./references/craft_and_shading.md)
- **逆向拆解、大图局部 Patch 手术与 AI 图像素化精修**：[edit_and_pixelate.md](./references/edit_and_pixelate.md)
- **多部件骨骼 Rig、RotSprite 旋转、打击感帧长配方与特效库**：[animation_and_rigging.md](./references/animation_and_rigging.md)
- **无缝 Tileset 3x3 拼接设计与 9-Slice UI 规范**：[tileset_and_ui.md](./references/tileset_and_ui.md)
- **47块自动地形、实机场景明度自检、2:1 等轴测与 4/8 向角色派生**：[world_iso_and_scene.md](./references/world_iso_and_scene.md)
- **完整 CLI 参数与 Python API 速查字典**：[cli_and_api.md](./references/cli_and_api.md)
- **可运行实战范例脚本**：参见 `./examples/` 目录下的 7 个端到端脚本（`01`～`07`）。
