# 多部件骨骼绑定（Rig）、RotSprite 旋转、节奏曲线与特效指南

## 1. 核心分工原则

> **刚体运动与弹性形变交给 `Rig` + `rotsprite`；结构拓扑变化交给 ASCII 部件多状态字典（Variants）。**

- **什么时候用 `Rig` 旋转/位移**：箱盖绕左后铰链掀起、手臂挥剑旋转、头冠随弹跳滞后晃动、身体蓄力下压。
- **什么时候用 `variants` 状态切换**：眨眼（`open` / `half` / `closed`）、披风飘动波形、嘴巴从闭合切换为露出獠牙、手掌从握拳切换为张开。

## 2. 紧凑局部部件绑定范式（无需画全屏空白点！）

传统写法每帧都要写满 `48x48` 个字符；在 `PixelForge` 中，每个部件只需写出自身最小包围盒的内部色块（**不画外黑边**），通过 `offset=(ox, oy)` 放到画布指定位置，最后由引擎按 `outline_group` 合并自动包上干净的 1px 外描边或 `selout` 光源描边！

```python
from pforge import Rig, SpriteActor, build_actor_assets, vfx_slash_arc, composite_vfx

rig = Rig(canvas_size=(48, 48), palette="endesga32", outline_mode="selout")

# outline_group=0：躯干与头部合并后统一描边，衔接处无缝融合
rig.add_part("torso", TORSO_GRID, offset=(18, 22), pivot_local=(6, 10), z_index=10, outline_group=0)
rig.add_part("head", {"idle": HEAD_IDLE, "fierce": HEAD_FIERCE}, offset=(17, 10), pivot_local=(7, 11), z_index=20, outline_group=0)

# outline_group=1：前景持剑手臂独立成组描边，叠在躯干前方时保留清晰轮廓分隔线！
rig.add_part("sword_arm", SWORD_GRID, offset=(24, 14), pivot_local=(2, 12), z_index=30, outline_group=1)

f_anticipation = rig.render_pose({
    "torso": {"scale_x": 1.08, "scale_y": 0.92, "dy": 1},
    "head": {"variant": "fierce", "dy": 1},
    "sword_arm": {"angle": -48, "dx": -2, "dy": -1},  # RotSprite 无破碎旋转！
})
```

> **坐标系提示**：`angle` 正值为顺时针旋转，负值为逆时针旋转。调用 `rig.get_canvas_pivots()` 传给 `build_pixel_asset(..., pivots=...)` 可在 `_inspect.png` 上直接画出黄色十字旋转轴心，方便核对铰链位置！

## 3. 动作打击感帧时长配方（Variable `durations_ms`）

绝对避免在攻击、跳跃、受击动画中使用呆板的均分帧长！经典游戏帧时长参考配方：

| 动作类型 | 推荐帧数 | 逐帧 `durations_ms` 配方 | 动力学解析 |
| :--- | :---: | :--- | :--- |
| **待机呼吸（Idle）** | 4 帧 | `[280, 180, 280, 180]` | 最高点与最低点略作停留（Ease-in-out），切忌匀速上下抖动 |
| **轻快弹跳（Bounce）** | 6 帧 | `[200, 100, 75, 130, 75, 120]` | 待机 → 蓄力挤压 → 快速起跳 → 滞空顶点悬停 → 加速下落 → 落地缓冲 |
| **重击挥砍 / 宝箱扑咬** | 6 帧 | `[180, 150, 210, 40, 55, 160]` | 预备 → 后仰蓄力 → **极限蓄力悬停(210ms)** → **瞬间爆发(40ms+刀光)** → **命中顿帧(55ms)** → 收招恢复 |
| **受击硬直（Hit / Hurt）** | 4 帧 | `[45, 65, 110, 140]` | 首帧 `flash_mix=0.9` 闪白并横向震退 `dx=-3`，随后回弹恢复 |

## 4. 次级动作（Secondary Motion）与预制特效叠加

1. **滞后跟随（Follow-through / Overlap）**：主角身体起跳的第 1 帧，帽子/皇冠/披风末端略微向下压；身体落地的第 1 帧，帽子/耳朵晚 1 帧再落回原位，立刻赋予像素角色鲜活弹性。
2. **内置 VFX 快速合成**：
   - `vfx_slash_arc(canvas_size, center, radius, start_deg, end_deg)`：生成 4 帧双色高光弯月刀光。
   - `vfx_dust_puff(canvas_size, origin=(cx, baseline_y), direction="both"|"left"|"right")`：生成 4 帧赛璐璐烟尘团。
   - `vfx_hit_spark(canvas_size, center, radius)`：生成 4 帧十字受击星芒。
   - `vfx_twinkle_stars(canvas_size, centers, frames_count)`：生成无缝循环闪烁星点。
   - 用 `composite_vfx(base_frames, vfx_frames, start_frame=3, under=False)` 一键精准对齐爆发帧！
