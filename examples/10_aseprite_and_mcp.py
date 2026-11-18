#!/usr/bin/env python3
"""Example 10: Native Multi-Layer `.aseprite` Binary Project Export + Live MCP Stdio Round-Trip
1. Exports a 7-layer, 2-tag (`idle`, `attack`), variable-duration, pivot-sliced `.aseprite`
   binary source file (`azure_knight_layered.aseprite`) ready to open directly in Aseprite!
2. Spawns `pforge_mcp.py` over real JSON-RPC 2.0 Stdio and calls `pixelforge_aseprite_inspect`
   to decode the binary `.aseprite` file and render its Multi-Layer Timeline Matrix Sheet!
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from pforge import (
    Rig,
    vfx_dust_puff,
    vfx_slash_arc,
    write_aseprite,
)


def main(output_dir: str = "output/examples/10_aseprite_and_mcp") -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rig = Rig(canvas_size=(40, 40), palette="endesga32", outline_mode="selout")
    rig.add_part("cape", [".RRRR.", "RRRRrr", "RRRrrr", "RRrrrr", ".rrrr."], offset=(11, 21), pivot_local=(3, 0), z_index=5, outline_group=0)
    rig.add_part("torso", [".BBBBBBBB.", "B11BBBB22B", "B11YYYY22B", ".bbbbbbbb.", ".LL....LL.", ".ll....ll."], offset=(14, 22), pivot_local=(5, 3), z_index=10, outline_group=0)
    rig.add_part("plume", ["..RRR.", ".RRRRr", "RRrr.."], offset=(13, 11), pivot_local=(4, 2), z_index=18, outline_group=0)
    rig.add_part(
        "helmet",
        {
            "idle": ["..111111..", ".1WW11122.", ".11111122.", ".2KKKKKK2.", ".2KCKKCK2.", "..222222.."],
            "fierce": ["..111111..", ".1WW11122.", ".11111122.", ".2KKKKKK2.", ".2YYKKYY2.", "..222222.."],
        },
        offset=(14, 14),
        pivot_local=(5, 5),
        z_index=20,
        outline_group=0,
    )
    rig.add_part("shield", [".YYYY.", "Y1112Y", "Y1BB2Y", "Y1bb2Y", ".YooY.", "..oo.."], offset=(11, 22), pivot_local=(3, 2), z_index=25, outline_group=1)
    rig.add_part("sword", ["..W..", ".W1..", ".W1..", ".W1..", ".W1..", ".12..", ".12..", "YYYYY", "..L..", "..l.."], offset=(24, 14), pivot_local=(2, 8), z_index=30, outline_group=1)

    # Timeline: 3 frames of 'idle' (F0..F2) + 5 frames of 'attack' (F3..F7) = 8 frames total
    poses = [
        {},
        {"helmet": {"dy": 1}, "plume": {"dy": 1, "angle": -6}, "shield": {"dy": 1}, "sword": {"dy": 1, "angle": 5}},
        {"plume": {"angle": 3}},
        # Attack clip starts at F3
        {"helmet": {"variant": "fierce", "dx": -2, "dy": 1}, "torso": {"dx": -2, "scale_x": 1.06, "scale_y": 0.94}, "plume": {"dx": -3, "angle": -15}, "cape": {"dx": -2, "angle": 14}, "shield": {"dx": -3, "dy": 1}, "sword": {"angle": -68, "dx": -4, "dy": -2}},
        {"helmet": {"variant": "fierce", "dx": -2, "dy": 1}, "torso": {"dx": -2, "scale_x": 1.08, "scale_y": 0.92}, "plume": {"dx": -3, "angle": -18}, "cape": {"dx": -2, "angle": 16}, "shield": {"dx": -3, "dy": 1}, "sword": {"angle": -76, "dx": -5, "dy": -2}},
        {"helmet": {"variant": "fierce", "dx": 3}, "torso": {"dx": 3}, "plume": {"dx": 1, "angle": 14}, "cape": {"dx": 1, "angle": -16}, "shield": {"dx": 1}, "sword": {"angle": 82, "dx": 4, "dy": 2}},
        {"helmet": {"variant": "fierce", "dx": 3}, "torso": {"dx": 3}, "plume": {"dx": 2, "angle": 8}, "cape": {"dx": 2, "angle": -10}, "shield": {"dx": 1}, "sword": {"angle": 88, "dx": 4, "dy": 3}},
        {"helmet": {"dx": 1}, "torso": {"dx": 1}, "sword": {"angle": 20, "dx": 1, "dy": 1}},
    ]
    durations = [240, 200, 220, 140, 190, 45, 65, 150]

    part_layers = rig.render_named_layers_sequence(poses)

    # Dedicated Dust VFX bottom layer + Slash VFX top layer!
    dust_seq = vfx_dust_puff((40, 40), origin=(15, 28), direction="left")
    dust_layer = [None, None, None, None, dust_seq[0], dust_seq[1], dust_seq[2], dust_seq[3]]

    slash_seq = vfx_slash_arc((40, 40), center=(23, 21), radius=12, start_deg=-80, end_deg=75, thickness=4)
    slash_layer = [None, None, None, None, slash_seq[0], slash_seq[1], slash_seq[2], slash_seq[3]]

    all_layers = [("dust_vfx", dust_layer), *part_layers, ("slash_vfx", slash_layer)]
    tags = [
        {"name": "idle", "from": 0, "to": 2, "direction": "forward", "color": "#41A6F6"},
        {"name": "attack", "from": 3, "to": 7, "direction": "forward", "color": "#E43B44"},
    ]

    ase_file = out / "azure_knight_layered.aseprite"
    write_aseprite(
        ase_file,
        canvas_size=(40, 40),
        layers=all_layers,
        durations_ms=durations,
        palette="endesga32",
        frame_tags=tags,
        pivots=rig.get_named_canvas_pivots(),
        use_linked_cels=True,
    )
    print(f"Wrote 8-layer native .aseprite binary project -> {ase_file} ({ase_file.stat().st_size} bytes)")

    # 2. Verify via live MCP Stdio Server subprocess (`pforge_mcp.py`)!
    mcp_script = ROOT / "scripts" / "pforge_mcp.py"
    proc = subprocess.Popen(
        [sys.executable, str(mcp_script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdin and proc.stdout

    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "demo", "version": "1.0"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "pixelforge_aseprite_inspect",
                "arguments": {
                    "path": str(ase_file),
                    "unpack_layers": True,
                    "output_dir": str(out / "mcp_decoded"),
                },
            },
        },
    ]
    payload_in = "\n".join(json.dumps(r) for r in requests) + "\n"
    stdout_data, _ = proc.communicate(input=payload_in, timeout=15)
    responses = [json.loads(line) for line in stdout_data.strip().splitlines() if line.strip()]
    call_res = json.loads(responses[-1]["result"]["content"][0]["text"])
    print(
        f"MCP Server decoded {len(call_res['layers'])} layers & {len(call_res['tags'])} tags -> "
        f"{call_res['layer_breakdown_sheet']}"
    )


if __name__ == "__main__":
    main()
