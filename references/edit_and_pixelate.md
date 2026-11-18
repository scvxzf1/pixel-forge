# 已有像素画逆向修改、局部切片精修与 AI 图转像素指南

## 1. 面对外部图片时的决策树

拿到用户给的任意图片时，先判断它的本质类型：

1. **已经是原生像素画，或是 `4x`/`8x` 整数倍无损放大的预览图（PNG / GIF / APNG / WebP）**：
   - 直接运行 `pforge.py inspect <file>` 或 `pforge.py decompile <file>`。
   - 引擎内置 GCD 游程检测器 `detect_integer_upscale_factor()`，会自动把 `8x` 放大的 `256x256` 像素图无损还原成 `32x32` 原生网格，绝不会错误生成巨型网格！
2. **多帧横向或网格排列的精灵表（Sprite Sheet）**：
   - 指定单帧尺寸 `--frame-size 32x32` 或行列数 `--cols 6 --rows 2` 调用 `decompile`。
3. **高分辨率插画、3D 渲染图，或 AI 生成的“伪像素画”（网格歪斜、颜色高达几百种、边缘半透明发糊）**：
   - **严禁直接 `decompile`！** 必须先走 `pixelate` 管线降采样、锁色去噪，再进入精修闭环。

---

## 2. 大图局部手术式精修（Region Patch 工作流）

当画布达到 `48x48`、`64x64` 甚至 `128x128` 时，全图重写 ASCII 极易导致未修改区域错位。**务必使用 Region Patch 三步法**：

### Step 1：全图观测定位坐标框
```bash
python3 <SKILL_DIR>/scripts/pforge.py inspect character.png -o work/
```
用看图工具查看 `work/character_inspect.png`，读出待修改区域（例如头部表情）的 0 起始坐标范围 `X: 16..35, Y: 6..23`，即 `box = 16,6,20,18`。

### Step 2：切片提取（带全局坐标标尺）
```bash
python3 <SKILL_DIR>/scripts/pforge.py region-extract character.png --box 16,6,20,18 -o work/patch/
```
产出三个关键文件：
- `character_x16_y6_w20_h18.txt`：仅 `20x18` 大小的轻量纯文本字符网格，直接用 `edit_file` 或 `write_file` 修改！
- `character_x16_y6_w20_h18.json`：记录源路径、偏移量 `(16, 6)` 与完整字符调色板映射。
- `character_x16_y6_w20_h18_inspect.png`：**标尺直接显示全局坐标 `16..35` 和 `6..23`**，无需人工换算加减！

### Step 3：回写并查看三联 Diff 看板
修改 `.txt` 文件后（如需要使用新颜色，可同步在 `.json` 的 `"palette"` 中补充新字符映射），执行回写：
```bash
python3 <SKILL_DIR>/scripts/pforge.py region-apply character.png \
  --patch work/patch/character_x16_y6_w20_h18.json \
  --mode replace \
  -o work/patched/
```
- `--mode replace`：用补丁完整替换该矩形框（含透明像素擦除旧内容，适合重画五官/改造型）。
- `--mode alpha_over`：仅非透明字符覆盖到底图上（适合给角色戴帽子、贴伤疤、加特效徽章）。
- **必须打开 `work/patched/*_diff.png`**：检查 `DIFF` 面板中的绿色（新增）、红色（擦除）、琥珀色（改色）像素是否精准无误！

---

## 3. AI 概念草图 / 高分图转真像素（Pixelate & Clean）

```bash
# 针对高分原画/图标：锐化对比度区域池化 + 锁定经典色板 + 自动外描边
python3 <SKILL_DIR>/scripts/pforge.py pixelate concept.png \
  --size 48x48 --palette endesga32 --mode contrast_box --outline "#181425" -o work/px/

# 针对 AI 生成的“伪像素图”：中心块众数投票消除网格错位与边缘杂色
python3 <SKILL_DIR>/scripts/pforge.py pixelate ai_draft.png \
  --size 64x64 --palette resurrect64 --mode dominant_block -o work/px/
```

**为什么 Pixelate 之后必须由视觉 LLM 二次精修？**
自动降采样能完美解决大比例与构图，但五官（如眼睛高光粘连）、武器刃口（断成虚线）需要你在自动生成的 `edit_*.py` 或通过 `region-extract` 做 1~2 轮手工点睛清理，从而兼具“概念图的构图张力”与“手绘像素的极致干净”。
