# 无缝地图块（Tileset）与九宫格 UI（9-Slice）设计指南

## 1. 无缝平铺地图块（Seamless Tile）设计法则

在绘制 `16x16` 或 `32x32` 地表砖块（草地、石板路、水面、熔岩）时，最常见的两个缺陷是：
1. **边缘断层（Edge Seam）**：左边界 `x=0` 的砖缝或暗纹没有延续到右边界 `x=w-1`，平铺后出现刺眼的十字切线。
2. **网格重复感（Grid Plaid Effect）**：单块中心放了一颗过于显眼的高亮石头或花朵，3x3 平铺后像排队的棋盘。

### 标准制作与检验流程
1. **绘制基础纹理**：使用柔和的低对比主色与次暗色簇铺底，避免把高对比特征放在正中央或紧贴单侧边缘。
2. **跨边界连续绘制技巧**：
   - 可以用 `shift_grid(grid, dx=w//2, dy=h//2, wrap=True)` 将接缝临时移到画布正中央修顺，再移回原位！
   - 动态水流/云层动画可直接对基础无缝砖执行循环包裹位移：`[shift_grid(water, dx=i*2, dy=0, wrap=True) for i in range(8)]`。
3. **强制运行 3x3 无缝检验**：
   ```bash
   python3 <SKILL_DIR>/scripts/pforge.py tile grass_tile.png -o output/tiles/
   ```
   **读取生成的 `*_tile3x3_inspect.png`**：
   - 面板 1 查看单块 `(X, Y)` 精确坐标；
   - 面板 2 查看无网格 `3x3` 真实平铺效果，检查是否有明显的十字格纹或重复斑点；
   - 面板 3 查看算法标出的红色接缝异常点（对应 `left_right_mismatch_rows_y` 与 `top_bottom_mismatch_cols_x`）。

---

## 2. 九宫格可伸缩 UI 面板（9-Slice UI）

制作 RPG 对话框、血槽外框、按钮面板时，只需精心绘制一个 `16x16` 或 `24x24` 的母版框，设定四角保留边距 `margins=(left, top, right, bottom)`：

- **四角区域**（如 `4x4` 金属包角铆钉）在缩放时 `1:1` 原样保留，绝不变形。
- **上下左右四条边**建议设计成长度为 `2px`、`4px` 或 `8px` 的周期性循环纹理，使用默认 `mode="tile"` 整数平铺延伸，比 `stretch` 拉伸更精致锐利。
- 导出母版时传入 `build_pixel_asset(..., nine_slice_margins=(4, 4, 4, 4))`，引擎会自动在 `*_atlas.json` 中写入标准 Aseprite `meta.slices` 九宫格切分数据，可直接导入 Godot / Unity / Phaser 使用；也可用 `render_9slice()` 直接渲染出任意目标尺寸（如 `180x64`）的成品 UI 底板。
