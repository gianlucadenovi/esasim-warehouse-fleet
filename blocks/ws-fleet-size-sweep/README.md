# Fleet-size sweep

How many robots does the warehouse need? Hundreds of fleet-size × order-rate scenarios with real robot speeds, pick times and batteries, simulated at once as one batch on the CPU, an NVIDIA GPU or Ten

Simulates every combination of Fleet sizes, Order rates and Seeds in the warehouse of the Warehouse fleet block (same hall, robots, times and batteries), for the same simulated hours (after a warm-up), all at once: the robots of all scenarios are one batch of tensors. Fleet sizes and order rates are lists (10,20,30) or ranges (10-60/10 = from 10 to 60 by 10). Accelerator: CPU plans routes with SciPy and steps with PyTorch; NVIDIA GPU runs everything on the GPU; Tenstorrent plans the routes on the cards with TT-NN (Tensix tile matmuls) and runs the scenarios' steps on the cards too when PyTorch/XLA for Tenstorrent (tt-xla) is installed, else on the CPU beside them; the machine with the cards needs TT-NN in the worker's Python (pip install ttnn). auto uses Tenstorrent cards when the machine has them, else an NVIDIA GPU, else the CPU. For each fleet size and order rate, averaged over the seeds: orders and lines per hour delivered, share of the demand served, average and 95th-percentile order time, robots busy, time spent waiting, time spent charging, orders left waiting, and robot cost per order (Robot cost per hour). Live telemetry (channel sweep) carries the results as they form, for the Fleet sweep view; the results are also in fleet_sweep.csv, throughput_by_fleet.csv (for a Chart) and sweep_summary.json (the cheapest fleet that keeps up with each order rate, and the speed of the machine).

An [EsaSim](https://esacode.com/) blueprint block: it runs on a machine, in Python (`backend.py`, `def run(ctx)`).

| | |
|---|---|
| Block | `ws-fleet-size-sweep` · version 3 |
| Workspace | Gianluca De Novi's workspace |
| Author | Gianluca De Novi |
| Runs on | Any machine, NVIDIA GPU, Tenstorrent |

## Outputs

| Port | Type | Description |
|---|---|---|
| `results` Results | Table (csv) | fleet_sweep.csv: one row per fleet size and order rate |
| `chart` For a chart | Table (csv) | throughput_by_fleet.csv: orders per hour by fleet size, one column per order rate |
| `summary` Summary | Metrics (json) | Best fleet per order rate, scenarios, time and speed on this machine |

## Settings

| Key | Type | Default | Description |
|---|---|---|---|
| `fleets` Fleet sizes | text | `"10-60/10"` | Robots: a list (10,20,30) or a range (10-60/10) |
| `rates` Order rates (orders per hour) | text | `"300,500,700,900"` | Each order has 1 to 3 lines (items) |
| `seeds` Seeds per combination | number | `3` | Each with other random orders; the results are averaged |
| `hours` Simulated hours | number | `2` |  |
| `warmup_min` Warm-up (simulated minutes, not counted) | number | `10` |  |
| `robot_cost_h` Robot cost per hour ($) | number | `2.5` | Lease, energy and upkeep of one robot for an hour of work |
| `accelerator` Accelerator | select | `"auto"` | auto: Tenstorrent cards, else an NVIDIA GPU, else the CPU of the machine that runs it |
| `rack_pairs` Rack pairs | number | `20` |  |
| `rack_blocks` Rack blocks | number | `5` |  |
| `rack_len` Rack length (m) | number | `8` |  |
| `stations` Pack-out stations | number | `8` |  |
| `pick_s` Seconds to pick an item | number | `10` |  |
| `station_s` Seconds to unload at the station | number | `15` |  |
| `robot_speed` Robot speed (m/s) | number | `1.2` |  |
| `battery_h` Hours on a charge | number | `8` |  |
| `charge_min` Minutes to charge from empty | number | `60` |  |
| `charge_below` Go to charge below (%) | number | `25` |  |
| `seed` Random seed | number | `1` |  |

## Use it in EsaSim

In a workspace, open **Projects > Blocks > New block**, choose this kind of block, copy the ports and settings above and paste the code; or ask an AI assistant connected to EsaSim (MCP) to create it from this folder.
