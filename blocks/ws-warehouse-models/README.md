# Warehouse models

Realistic 3D models for the warehouse demo: textured racks, pallets, desks and the MiR100 mobile robot, as GLB files.

Downloads once, from GitHub (raw.githubusercontent.com), the warehouse models of AWS RoboMaker's Small Warehouse World (racks with boxes, pallets of goods, a pallet jack, pack desks, a bin; MIT No Attribution licence) and the body of the MiR100 robot from DFKI's mir_robot (BSD-3-Clause). Converts them to GLB (metres, Y-up, textures inside) and keeps them in the worker's data folder (cache/warehouse-kit), so later runs take a second. Gives the GLB files, kit.json (sizes) and LICENSES-warehouse-models.txt. Connect Models to the Warehouse view, and to the Warehouse fleet block so the run starts once the models are ready.

An [EsaSim](https://esacode.com/) blueprint block: it runs on a machine, in Python (`backend.py`, `def run(ctx)`).

| | |
|---|---|
| Block | `ws-warehouse-models` · version 1 |
| Workspace | Gianluca De Novi's workspace |
| Author | Gianluca De Novi |
| Runs on | Any machine |

## Outputs

| Port | Type | Description |
|---|---|---|
| `models` Models | Files (glb, json, txt) | rack_d/e/f, goods_a/c/d, pallet_jack, desk, bin and amr (the robot) as GLB, kit.json, licences |

## Use it in EsaSim

In a workspace, open **Projects > Blocks > New block**, choose this kind of block, copy the ports and settings above and paste the code; or ask an AI assistant connected to EsaSim (MCP) to create it from this folder.
