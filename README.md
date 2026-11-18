# PixelForge — 面向多模态视觉 LLM 的全栈像素画创作、精修与动画套件

`PixelForge` 是一套轻量级、零重型外部依赖（仅依赖 Python 标准库与 `Pillow` 9～14+）的像素资产工程库与 Agent Skill。专为具备多模态视觉能力的编码智能体（Antigravity、Claude Code、Codex 等）打造，打通了**从零构建 → 已有像素资产逆向拆解与局部手术精修 → 高分原画/AI 草图像素化 → 多部件骨骼动画 → 游戏引擎图集导出 → 全息视觉自检**的完整闭环。

---

## 核心特性与实测展示

### 1. 多部件骨骼 Rig + RotSprite 抗破碎旋转 + 多动作状态图集
支持紧凑局部组件组装、按分组自动包覆光源自适应描边（Sel-out）、3 阶 `Scale2x` 保色 `RotSprite` 旋转、非均匀帧率节奏（`durations_ms`）以及刀光/烟尘/受击星芒等预制粒子特效，一键导出 `GIF` / 真 8 位半透明 `APNG` / 无损动态 `WebP` 与 Aseprite 兼容 `JSON` 图集。

| 挥砍动作 (`attack`) | 待机呼吸 (`idle`) | 受击硬直 (`hit`) |
| :---: | :---: | :---: |
| ![attack](docs/showcase/azure_knight_attack_8x.gif) | ![idle](docs/showcase/azure_knight_idle_8x.gif) | ![hit](docs/showcase/azure_knight_hit_8x.gif) |

**全息多模态视觉自检看板**（集成了字符色板图例、`0` 起始坐标网格、无网格深/浅双底实机预览、纯白剪影与红青洋葱皮运动轨迹）：

![Holistic Inspection Sheet](docs/showcase/azure_knight_attack_inspect.png)

---

### 2. 已有像素画逆向拆解 + 大图局部手术精修（Region Patch）+ 语义换色
- 自动通过横纵游程 GCD 检测 `4x`/`8x` 整数倍放大预览图并无损还原为 `1x` 原生像素画布。
- 支持按 `(X, Y, W, H)` 切出局部区域（自检标尺自动保留全局坐标），修补后输出 **Before / After / Diff** 三联像素级对比看板。

| 局部手术精修三联 Diff 看板 | 语义色阶重映射变体 |
| :---: | :---: |
| ![Surgical Diff](docs/showcase/horned_patch_diff.png) | ![Crimson Variant](docs/showcase/crimson_legion_knight_8x.png) |

---

### 3. 高分概念图 / AI 草图转真像素（Pixelate & Clean）
内置 `contrast_box`（面向平滑原画）与 `dominant_block`（面向网格歪斜发糊的 AI 伪像素图）双模式降采样、经典色板锁色与孤立杂点清理，生成可继续由视觉 LLM 逐像素点睛的干净工程。

| 左：256x256 柔光原画草图 → 右：32x32 锁色像素底稿 | 逐像素点睛玻璃高光 + 星芒动画成品 |
| :---: | :---: |
| ![Pixelate Compare](docs/showcase/mana_ruby_potion_compare.png) | ![Polished Potion](docs/showcase/mana_ruby_potion_polished_8x.gif) |

---

### 4. 无缝地图块（Tileset 3x3 接缝检验）与九宫格 UI（9-Slice）
自动比对跨边界色差与内部梯度，精准标红接缝断层行/列坐标；支持将迷你母版整数平铺扩展为任意尺寸的复古 UI 窗口并导出 `slices` 元数据。

| 3x3 无缝水面拼接自检看板 | 3x3 动态水面预览 | 9-Slice 整数平铺 RPG 对话框 |
| :---: | :---: | :---: |
| ![Tile Check](docs/showcase/water_tile_3x3_inspect.png) | ![Water Anim](docs/showcase/water_tile_3x3_anim_4x.gif) | ![9-Slice Dialog](docs/showcase/rpg_dialogue_160x56_4x.png) |

---

### 5. 自动地形拼接系统（47-Tile Blob & 16-Tile Wang Auto-Tileset）
仅输入两张同尺寸无缝底砖（如 `16x16` 草地与水面），自动按四象限子块与全局左上光源合成全部 **47 张八邻域 Blob 转角砖**（或 **16 张双网格 Wang 转角砖**），并铺出包含外圆角、内海湾与单格窄桥的实机测试群岛供视觉自检。

| 47-Tile Blob 自动图集与实机测试群岛 | 16-Tile Dual-Grid Wang 自动图集与群岛 |
| :---: | :---: |
| ![Blob47](docs/showcase/emerald_coast_blob47_inspect.png) | ![Wang16](docs/showcase/emerald_coast_wang16_inspect.png) |

---

### 6. 多资产实机场景沙盒与四联明度可读性自检（Scene Mockup & Value Check）
内置 `SceneComposer`（支持脚底 Y 轴自动遮挡排序、运动轨迹与比例像素字库 `render_pixel_text`），一键导出伪实机游玩 GIF 并生成**彩色实机 / 纯灰度眯眼图 / 深中浅三阶明度归纳 / 角色轮廓对比度热力图**四联诊断看板。

| 实机战斗场景合成 GIF (`island_skirmish`) | 四联灰度明度与前景可读性热力看板 |
| :---: | :---: |
| ![Scene GIF](docs/showcase/island_skirmish_3x.gif) | ![Scene Value Check](docs/showcase/island_skirmish_scene_inspect.png) |

---

### 7. 严格 `2:1` 等轴测场景（`IsoScene`）与四/八向 RPG 角色自动派生（`DirectionalRig`）
- **`IsoScene`**：基于 $\mathbb{Z}^2$ 格点基本域的零裂缝 `2:1` 等轴测体块引擎，内置三面受光、前棱 `1px` 高光脊线与画家算法深度排序。
- **`DirectionalRig`**：从正面（`S`）部件自动推导侧面单目轮廓、背面披风前置与武器左右空间交换，输出 4 向或 8 向行走图集与头顶/脚底对齐标尺看板。

| 2:1 等轴测圣坛微缩场景 | 8 向自动派生转身预览 | 8 向头顶/脚底对齐标尺与 8x4 行走图集 |
| :---: | :---: | :---: |
| ![Iso Shrine](docs/showcase/iso_shrine_diorama_4x.png) | ![8Dir Spin](docs/showcase/forest_ranger_8dir_turnaround_6x.gif) | ![8Dir Align](docs/showcase/forest_ranger_8dir_alignment_inspect.png) |

---

### 8. HD-2D 像素法线贴图、自发光遮罩与 360° 动态火把打光（`lighting.py`）
支持按部件几何特征独立生成浮雕高度场与 OpenGL 标准切线空间法线贴图（如盔甲/圆盾用球面 `dome`、剑刃用双斜面锋脊 `ridge`），提取自发光层（`emission`），并渲染赛璐璐色阶量化的 360° 环绕点光源验证 GIF。

| 360° 动态火把环绕受光 (`hd2d_azure_knight`) | 切线法线 + 高度浮雕 + 发光层 + 四向光检看板 |
| :---: | :---: |
| ![Torch Orbit](docs/showcase/hd2d_azure_knight_torch_orbit_6x.gif) | ![HD2D Inspect](docs/showcase/hd2d_azure_knight_hd2d_inspect.png) |

---

### 9. “生图概念爆炸图 → 自动拆件像素化 → 可动 Rig 绑骨”混合管线（`autorig.py`）
针对纯色底部件分解原画，通过边缘泛洪安全去底（保留内部纯白眼睛与剑芯）、8 邻域连通域分割、统一比例共享调色板锁色与肩/颈/剑柄轴心自动推断，一键拼装出可动角色并导出 `rig_<name>.py` 源码，还可直接串联 HD-2D 动态光影。

| 三阶段拆件绑骨全链路看板 | 自动拼装振翅挥剑动图 | 串联 HD-2D 火把动态光影 |
| :---: | :---: | :---: |
| ![AutoRig Pipeline](docs/showcase/seraph_guardian_autorig_pipeline.png) | ![AutoRig Anim](docs/showcase/seraph_guardian_autorig_8x.gif) | ![AutoRig HD2D](docs/showcase/seraph_guardian_hd2d_torch_orbit_5x.gif) |

---

### 10. 原生 `.aseprite` 二进制分层工程双向读写 + 零依赖 MCP Server（`aseprite_io.py` / `pforge_mcp.py`）
- **双向 `.aseprite` 二进制引擎**：无需本机安装 Aseprite，纯 Python 按 v1.3 规范直接读写 `.ase` / `.aseprite` 源文件，完整保留**独立部件图层（`0x2004`）、Zlib 压缩与关联 Cel（`0x2005`）、可变帧毫秒时长、动作标签（`idle` / `attack`）、命名 RGBA 调色板与关节轴心 Slice（`0x2022`）**。示例生成的 8 图层源文件见 [`docs/showcase/azure_knight_layered.aseprite`](docs/showcase/azure_knight_layered.aseprite)。
- **零外部依赖 MCP Server**：`scripts/pforge_mcp.py` 原生实现 JSON-RPC 2.0 Stdio 协议（无需额外安装 `mcp` 包），向智能体暴露 `pixelforge_build`、`pixelforge_inspect`、`pixelforge_region_patch`、`pixelforge_aseprite_inspect` 等 9 个工具。

![Decoded Aseprite 8-Layer Timeline Matrix](docs/showcase/azure_knight_layered_layers_inspect.png)

---

## 一键安装（作为 Agent Skill）

确保环境已安装 `Pillow`（`pip install Pillow`），直接克隆到对应智能体的技能目录即可自动生效：

```bash
# Google Antigravity（全局）
git clone https://github.com/scvxzf1/pixel-forge.git ~/.gemini/config/skills/pixel-forge

# Claude Code（全局）
git clone https://github.com/scvxzf1/pixel-forge.git ~/.claude/skills/pixel-forge

# Codex CLI（全局）
git clone https://github.com/scvxzf1/pixel-forge.git ~/.codex/skills/pixel-forge

# 或挂载到任意项目级工作区
mkdir -p .agents/skills && git clone https://github.com/scvxzf1/pixel-forge.git .agents/skills/pixel-forge

# （可选）生成 MCP Server 配置并写入 Antigravity / Claude Code
python3 ~/.gemini/config/skills/pixel-forge/scripts/pforge.py print-mcp-config --write ~/.gemini/config/mcp_config.json
```

---

## 目录结构

```text
pixel-forge/
├── SKILL.md                        # 核心 Agent 技能入口（渐进式披露，精炼工作流铁律）
├── mcp_config.example.json         # MCP Server 配置模板
├── scripts/
│   ├── pforge.py                   # 统一 CLI 命令行工具 & Python 顶层 API 入口
│   ├── pforge_mcp.py               # 零外部依赖 MCP Stdio Server（暴露 9 个原生像素工具）
│   └── pixelforge/                 # 模块化核心引擎
│       ├── palette.py              # 6套经典色板、参考图吸色、HSV语义键分配、色相偏移明暗色阶、一键换色
│       ├── canvas.py               # ASCII网格编解码、局部切片精修(Patch)、抗锯齿几何画布与Bayer有序抖动
│       ├── importer.py             # PNG/GIF/APNG/WebP/精灵表逆向反编译、8x预览图自动无损还原、AI图像素化
│       ├── transform.py            # Scale2x + RotSprite 抗破碎像素旋转、Sel-out 光源描边、挤压拉伸、帧间拖影
│       ├── rig.py                  # 紧凑局部部件骨骼绑定(Rig)、分组描边、多动作状态角色(SpriteActor)
│       ├── vfx.py                  # 预制像素特效库（弯月刀光、赛璐璐烟尘、受击十字星芒、魔法闪烁）
│       ├── tileset.py              # Tileset 3x3 无缝拼接边缘断层检测、滚动水面、9-Slice 九宫格 UI 面板
│       ├── autotile.py             # 47块 Blob 与 16块 Wang 自动拼接地形合成器及实机地图渲染器
│       ├── scene.py                # 实机场景 Y 轴遮挡合成器、内置比例像素位图字库、4联灰度明度与轮廓对比热力诊断
│       ├── isometric.py            # 零裂缝 2:1 等轴测三维体块引擎(IsoScene) & 4/8向角色转身行走派生器(DirectionalRig)
│       ├── lighting.py             # HD-2D 逐部件切线法线贴图、自发光遮罩提取与 360° 赛璐璐点光源渲染器
│       ├── autorig.py              # 爆炸概念图边缘泛洪去底、连通域拆件、统一锁色像素化与自动关节绑骨器
│       ├── aseprite_io.py          # 原生 .ase/.aseprite v1.3 二进制多图层/关联Cel/标签/色板/Slice双向读写器
│       ├── linter.py               # 代码级像素静态检查器（孤立噪点、轮廓漏口、曲线阶梯锯齿、体积/基准线异常）
│       ├── inspector.py            # 多模态全息自检看板（字符色板图例+坐标标尺+深浅双底预览+剪影+洋葱皮+Diff）
│       └── exporter.py             # GIF / 真半透明 APNG / 无损动态 WebP / 多行精灵表 / Aseprite JSON 导出
├── references/                     # 按需加载的专项技法手册
│   ├── craft_and_shading.md
│   ├── edit_and_pixelate.md
│   ├── animation_and_rigging.md
│   ├── tileset_and_ui.md
│   ├── world_iso_and_scene.md
│   ├── hd2d_and_autorig.md
│   ├── aseprite_and_mcp.md
│   └── cli_and_api.md
├── examples/                       # 10 个独立可运行的端到端实战脚本
│   ├── 01_knight_multi_anim.py
│   ├── 02_edit_and_recolor.py
│   ├── 03_pixelate_concept.py
│   ├── 04_tileset_and_9slice.py
│   ├── 05_autotile_island.py
│   ├── 06_scene_mockup_value_check.py
│   ├── 07_isometric_and_4dir_rpg.py
│   ├── 08_hd2d_normal_and_lighting.py
│   ├── 09_sketch_to_rig_boss.py
│   └── 10_aseprite_and_mcp.py
└── tests/
    └── test_pixelforge.py          # 全模块自动化单元测试
```

---

## 常用 CLI 命令速览

```bash
# 1. 运行内置演示与全套自动化测试
python3 scripts/pforge.py demo -o output/demo
python3 tests/test_pixelforge.py -v

# 2. 对任意现有 PNG / GIF / 精灵表生成全息视觉自检看板与 Linter 诊断
python3 scripts/pforge.py inspect sprite.gif -o work/

# 3. 逆向反编译已有动图或精灵表为可编辑 Python 工程
python3 scripts/pforge.py decompile walk_sheet.png --cols 6 --rows 1 -o work/walk/

# 4. 大图局部手术切片与回写（自动生成 Before / After / Diff 三联对比图）
python3 scripts/pforge.py region-extract boss.png --box 16,8,24,20 -o work/patch/
python3 scripts/pforge.py region-apply boss.png --patch work/patch/boss_x16_y8_w24_h20.json -o work/patched/

# 5. 高分原画或 AI 概念图转干净像素底稿
python3 scripts/pforge.py pixelate concept.png --size 48x48 --palette endesga32 --outline "#181425" -o work/px/

# 6. 无缝地图块 3x3 检验 & 九宫格 UI 面板生成
python3 scripts/pforge.py tile water.png -o work/tile/
python3 scripts/pforge.py nine-slice frame.png --margins 5,5,5,5 --size 160x56 -o work/dialog.png
```

## License

[MIT](LICENSE)
