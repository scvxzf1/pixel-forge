# 原生 `.aseprite` 二进制分层工程读写与 MCP Server 接入指南

## 1. 原生 `.aseprite` 二进制分层读写（`aseprite_io.py`）

无需本机安装 Aseprite 软件，`PixelForge` 通过纯 Python 标准库（`struct` + `zlib`）完整实现了符合 Aseprite v1.3 二进制规范（Magic `0xA5E0`）的双向读写：
- **默认自动直出**：`build_pixel_asset` 与 `build_actor_assets` 默认包含 `"aseprite"` 格式，自动写出 `<name>.aseprite` / `<actor>_master.aseprite`（内嵌 `0x2019` 命名 RGBA 色板、sRGB 色彩配置、逐帧毫秒时长与动作标签 `0x2018`）。
- **多图层骨骼工程直出（人类画师无缝接力）**：调用 `Rig.render_named_layers_sequence(poses)` + `write_aseprite(...)`，可将每个角色部件（披风、躯干、头盔、盾牌、武器、烟尘、刀光）分别写入独立图层（`0x2004`），并将关节轴心写入 Aseprite Slice/Pivot（`0x2022`），同时开启 `use_linked_cels=True` 自动将静止帧压缩为关联 Cel（`cel_type=1`）！

```python
from pforge import Rig, write_aseprite, read_aseprite, generate_aseprite_layer_sheet

part_layers = rig.render_named_layers_sequence(poses)
all_layers = [("dust_vfx", dust_frames), *part_layers, ("slash_vfx", slash_frames)]

write_aseprite(
    "output/hero_layered.aseprite",
    canvas_size=(40, 40),
    layers=all_layers,
    durations_ms=[240, 200, 140, 45, 65, 150],
    palette="endesga32",
    frame_tags=[
        {"name": "idle", "from": 0, "to": 1, "direction": "forward"},
        {"name": "attack", "from": 2, "to": 5, "direction": "forward"},
    ],
    pivots=rig.get_named_canvas_pivots(),
    use_linked_cels=True,
)
```

- **读取与图层时间轴拆解自检**：
  - `inspect`、`decompile`、`recolor`、`normalmap` 等全部命令均支持直接传入 `.ase` / `.aseprite` 文件！
  - 运行 `python3 <SKILL_DIR>/scripts/pforge.py aseprite-inspect hero_layered.aseprite --unpack-layers -o work/`，自动解码二进制结构并渲染 **`*_layers_inspect.png` 多图层时间轴矩阵看板**。

---

## 2. 零外部依赖 MCP Server（`scripts/pforge_mcp.py`）

`pforge_mcp.py` 遵循标准 MCP JSON-RPC 2.0 Stdio 协议（兼容 `2024-11-05` / `2025-03-26` 及 `Content-Length` 帧头回退），**无需安装 `mcp` 第三方包**，直接由 `python3` 启动。

### 一键生成配置并挂载
```bash
# 打印当前环境绝对路径配置（或加 --write 直接写入目标文件）
python3 <SKILL_DIR>/scripts/pforge.py print-mcp-config
```

挂载位置：
- **Antigravity 全局**：`~/.gemini/config/mcp_config.json`（项目级为 `.agents/mcp_config.json`）
- **Claude Code**：项目根目录 `.mcp.json` 或 `claude mcp add pixelforge -- python3 /abs/path/to/pforge_mcp.py`

### 暴露的 12 个原生零脚本 MCP 工具（含 `InitializeResult.instructions` 自动工作流注入）
每个工具的返回值均内置 **`agent_checklist`**（明确列出必看自检看板 `must_view_images`、自动补齐说明 `auto_healed` 与 `(x, y)` 逐像素修复处方 `actionable_fixes`）：

1. `pixelforge_palette_guide`：输出任意内置色板或参考图的单字符语义速查表与色相明暗色阶链（`暗部 -> 中间调 -> 高光`），杜绝盲猜字符。
2. `pixelforge_build`：直接传入 ASCII 网格（支持 `|...|` 对齐竖线、`# 行尾注释`、`pad_ragged=True` 自动补齐行宽、`outline_mode='selout'`），一键产出 PNG / GIF / APNG / WebP / `.aseprite` 与全息自检看板。
3. `pixelforge_build_rig`：**零 Python 脚本多部件骨骼角色构建器**！传入紧凑无描边局部 `parts`（`at='center'` + `attach_to='torso', side='top'|'right', hinge='grip'` 零算术吸附、`canvas_size='auto'` 自动留挥剑边距）与一行 `clips` 预设（`'idle_breathe'` / `'float_bob'` / `'slime_bounce'` / `'melee_attack'` / `'hurt_flash'`），自动直出多图层二进制 `.aseprite`、图层时间轴拆解图与全格式动图（可选 `hd2d=True` 同步生成法线贴图与 360° 火把受光动图）。
4. `pixelforge_inspect`：对任意 PNG / GIF / 精灵表 / `.aseprite` 生成全息自检看板与 Linter 坐标诊断。
5. `pixelforge_decompile`：逆向拆解任意图像或 `.aseprite` 为可编辑 ASCII 网格与色阶表。
6. `pixelforge_region_patch`：大图局部 `[x,y,w,h]` 切片提取（`extract`）与回写 Diff 验证（`apply`）。
7. `pixelforge_recolor`：批量替换调色板字符或色值并生成 Diff 验证图。
8. `pixelforge_pixelate`：高分原画或 AI 草图锁色去噪转像素画。
9. `pixelforge_autotile`：合成 47 块 Blob 或 16 块 Wang 自动拼接地形与测试地图。
10. `pixelforge_hd2d_normal`：生成切线法线贴图、自发光遮罩与 360° 火把环绕动图。
11. `pixelforge_scene_check`：对任意实机场景图运行 4 联纯灰度眯眼图 + 三阶明度归纳 + 前景可读性诊断。
12. `pixelforge_aseprite_inspect`：解析 `.aseprite` 二进制图层树、标签与切片，渲染多图层时间轴拆解矩阵图并可解包单层 PNG。
