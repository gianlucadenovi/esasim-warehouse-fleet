# Warehouse fleet

A picking warehouse of 3,400 m² with up to 60 mobile robots, real robot speeds, pick times and batteries, simulated live on the CPU, an NVIDIA GPU or Tenstorrent cards; the 3D view shows it and change

Runs a picking warehouse live for Minutes. The hall (65 x 53 m with the defaults, about 3,400 m²) has 20 pairs of rack rows in 5 blocks, one-way aisles, cross-aisles, highways at both ends, 8 pack-out stations on the south wall and docks with chargers along the walls. Orders arrive (Order rate) with 1 to 3 lines; an idle robot with enough charge takes one, drives to each pick face (popular places near the front), waits while the picker puts the item in its tote (Seconds to pick an item), takes the tote to the least busy station and waits while it is unloaded (Seconds to unload), then goes back to its dock. Batteries run down on the move and less standing; a robot below Go to charge below finishes its order and charges at its dock (Minutes to charge from empty); idle robots charge too. The defaults follow real robots: MiR100 drives at up to 1.5 m/s, about 10 h on a charge, 2-3 h to charge; Locus Origin about 8 h, about 50 min to charge; collaborative picking 8-12 s per item. Routes come from distance fields of every target, computed on the machine's accelerator (CPU: SciPy breadth-first search; NVIDIA: wavefront on the GPU; Tenstorrent: TT-NN tile matmuls on the cards), and again whenever an aisle is blocked. Tenstorrent runs the robots' steps on the cards too when PyTorch/XLA for Tenstorrent (tt-xla) is installed, else on the CPU beside them; the Linux machine with the cards needs TT-NN in the worker's Python (pip install ttnn, the version of the cards' firmware). auto uses Tenstorrent cards when the machine has them, else an NVIDIA GPU, else the CPU; naming one makes the block stop if it is not there. Connect its telemetry to a 3D view: it draws the warehouse (layout), the robots with their battery and the items in their tote (fleet), the KPIs (kpi), where robots wait (heat) and what changed (event). Commands on the control channel, as the 3D view's Controls or a Controls view send them ({"control": NAME, "value": …}): order_rate, robots, speed, paused, block_aisle ([x, y]: blocks that aisle cell, or opens it again) and Open all aisles. Results: kpis.json, timeline.csv and events.json, warehouse.json.

An [EsaSim](https://esacode.com/) blueprint block: it runs on a machine, in Python (`backend.py`, `def run(ctx)`).

| | |
|---|---|
| Block | `ws-warehouse-fleet` · version 4 |
| Workspace | Gianluca De Novi's workspace |
| Author | Gianluca De Novi |
| Runs on | Any machine, NVIDIA GPU, Tenstorrent |

## Inputs

| Port | Type | Description |
|---|---|---|
| `kit` Warehouse models | Files (glb, json, txt) | From Warehouse models: the run starts once the view has its models Optional. |

## Outputs

| Port | Type | Description |
|---|---|---|
| `kpis` KPIs | Metrics (json) | The run's totals: orders, lines, orders per hour, order time, robots busy |
| `timeline` Timeline | Table (csv, json) | timeline.csv (every 30 simulated seconds) and events.json (what changed) |
| `layout` Layout | Files (json) | warehouse.json (esasim.warehouse/1) |

## Settings

| Key | Type | Default | Description |
|---|---|---|---|
| `robots` Robots at the start | number | `40` |  |
| `order_rate` Orders per hour at the start | number | `400` | Each order has 1 to 3 lines (items); about 40 robots serve 400 orders per hour in this hall |
| `speed` Simulation speed | select | `"2"` | Times real time; the view can change it |
| `minutes` Minutes it runs | number | `20` | Real minutes; the run's Stop ends it before |
| `accelerator` Accelerator | select | `"auto"` | auto: Tenstorrent cards, else an NVIDIA GPU, else the CPU of the machine that runs it |
| `rack_pairs` Rack pairs | number | `20` | Double rows of racks across the hall, with one-way aisles between them (3 m each) |
| `rack_blocks` Rack blocks | number | `5` | Blocks of racks from front to back, with cross-aisles between them |
| `rack_len` Rack length (m) | number | `8` |  |
| `stations` Pack-out stations | number | `8` |  |
| `pick_s` Seconds to pick an item | number | `10` | Collaborative picking takes about 8-12 s per item |
| `station_s` Seconds to unload at the station | number | `15` |  |
| `robot_speed` Robot speed (m/s) | number | `1.2` | Warehouse AMRs drive at 1 to 1.5 m/s at most; 1.2 allows for slowing at turns |
| `battery_h` Hours on a charge | number | `8` | Working, on the move; standing uses about a third |
| `charge_min` Minutes to charge from empty | number | `60` |  |
| `charge_below` Go to charge below (%) | number | `25` |  |
| `seed` Random seed | number | `1` |  |

## Use it in EsaSim

In a workspace, open **Projects > Blocks > New block**, choose this kind of block, copy the ports and settings above and paste the code; or ask an AI assistant connected to EsaSim (MCP) to create it from this folder.
