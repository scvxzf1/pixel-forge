# HD-2D 像素法线动态光影与“生图拆件 → 自动绑骨（Sketch-to-Rig）”指南

## 1. HD-2D 像素法线贴图、自发光遮罩与 360° 火把动态打光（`lighting.py`）

现代 HD-2D 游戏（如《死亡细胞》《八方旅人》）通过 **Albedo（漫反射色）+ Normal Map（切线空间法线，OpenGL `+X右/+Y上/+Z外` 标准）+ Emission（自发光层）** 在引擎中实现实时火把、魔法飞弹动态照明。

### 分部件立体浮雕法线（强烈推荐）
不要只对合并后的整图算一个大球面！调用 `Rig.render_part_layers()` 为不同几何特征的部件指定专属浮雕截面：
- `"dome"`：球面/枕面饱满体积（适合头盔、胸甲、圆盾、史莱姆、药水瓶）。
- `"ridge"`：双斜面脊线刀锋（适合剑刃、长枪、水晶棱柱——火把掠过中脊时产生凌厉的冷暖切面跳变！）。
- `"bevel"`：平顶倒角（适合石砖、UI 边框、木箱）。

```python
from pforge import Rig, export_hd2d_bundle

albedo = rig.render_pose({})
part_layers = rig.render_part_layers({}, part_profiles={"sword": "ridge", "shield": "dome"})

export_hd2d_bundle(
    name="hd2d_knight",
    albedo=albedo,
    part_layers=part_layers,
    emissive_colors=["#2CE8F5"],  # 提取发光目镜与宝石，暗部依旧自发光！
    output_dir="output/hd2d",
)
```

- **CLI 单图直出**：
  ```bash
  python3 <SKILL_DIR>/scripts/pforge.py normalmap hero.png --emit "#2CE8F5,#FEE761" -o work/hd2d/
  ```
- **强制查看 `*_hd2d_inspect.png`**：核对顶排法线贴图（受光顶缘偏绿、右侧偏洋红、左侧偏青蓝、剑脊中线分明）与底排 `NW / NE / SE / SW` 四角火把实机受光是否自然。

---

## 2. 生图概念稿 / 拆件设定图 → 自动绑骨管线（`autorig.py`）

面对造型复杂的 Boss、机械或带翼生物，先利用生图大模型（或用户手绘草图）解决宏观创意，再交由 `autorig` 转化为干净的可动像素骨骼工程：

### Step 1：给生图模型的最佳拆件提示词（Exploded Parts Sheet Prompt）
若调用生图工具（如 `image-generator`），要求其生成：
> *"2D game character exploded parts sheet on solid flat white background (#FFFFFF), wide empty spacing between parts, no overlapping parts: [1] central torso armor in middle, [2] helmet/head above torso, [3] left wing on upper-left, [4] right wing on upper-right, [5] greatsword vertically on lower-right. Clean cel-shaded shapes, crisp dark outlines."*

### Step 2：一键去底、连通域拆件、统一比例锁色与关节吸附
```bash
python3 <SKILL_DIR>/scripts/pforge.py autorig boss_concept_sheet.png \
  --canvas 56x56 --part-scale 46 --palette endesga32 -o work/boss_rig/
```
引擎自动执行 5 步流水线：
1. **边缘漫水去底（`remove_solid_background`）**：仅从画布四边向内泛洪剥离纯色背景，**绝不会误删角色头盔内部封闭的纯白眼球或银白剑芯**！
2. **8 邻域连通域分割与碎片吸附（`segment_parts_from_sheet`）**：滤除噪点，按空间拓扑自动识别 `torso`、`head`、`wing_l`、`wing_r`、`shield_l`、`weapon_r`。
3. **全局单一缩放比 + 共享调色板像素化**：确保剑与躯干像素颗粒大小 `1:1` 严格一致。
4. **解剖学插槽拼装与铰链推断**：自动把爆炸图各部件吸附到躯干对应插槽，并将双翼轴心定在内侧肩关节、头轴心定在颈底、武器轴心定在剑柄护手。
5. **生成可编辑工程 `rig_<name>.py` 与 `*_autorig_pipeline.png`**。

### Step 3：多模态复检与逐像素精修
**必须打开 `*_autorig_pipeline.png` 与 `*_autorig_inspect.png`**：检查部件归类框、黄色十字旋转铰链点是否准确，随后在生成的 `rig_<name>.py` 中微调 `offset`、`pivot_local` 并清理降采样产生的单像素杂色簇，即可进一步串联 `SpriteActor` 或 `export_hd2d_bundle`。
