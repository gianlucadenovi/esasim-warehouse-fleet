# Fleet-size sweep

How many robots does the warehouse need? Hundreds of fleet-size × order-rate scenarios simulated at once, as one batch on the CPU, an NVIDIA GPU or Tenstorrent cards.

Simulates every combination of Fleet sizes, Order rates and Seeds in the warehouse of the Warehouse fleet block, for the same simulated hours (after a warm-up), all at once: the robots of all scenarios are one batch of tensors, so a GPU or Tenstorrent cards run hundreds of scenarios in the time a CPU runs a few. Fleet sizes and order rates are lists (5,10,20) or ranges (5-50/5 = from 5 to 50 by 5). For each fleet size and order rate, averaged over the seeds: orders per hour delivered, share of the demand served, average and 95th-percentile order time, robots busy, time spent waiting, orders left waiting, and robot cost per order (Robot cost per hour). Live telemetry (channel sweep) carries the results as they form, for the Fleet sweep view; the results are also in fleet_sweep.csv (one row each), throughput_by_fleet.csv (one column per order rate, for a Chart) and sweep_summary.json (the cheapest fleet that keeps up with each order rate, and the speed of the machine).

An [EsaSim](https://esacode.com/) blueprint block: it runs on a machine, in Python (`backend.py`, `def run(ctx)`).

| | |
|---|---|
| Block | `ws-fleet-size-sweep` · version 1 |
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
| `fleets` Fleet sizes | text | `"5-50/5"` | Robots: a list (10,20,30) or a range (5-50/5) |
| `rates` Order rates (orders per hour) | text | `"600,900,1200,1500"` |  |
| `seeds` Seeds per combination | number | `3` | Each with other random orders; the results are averaged |
| `hours` Simulated hours | number | `2` |  |
| `warmup_min` Warm-up (simulated minutes, not counted) | number | `10` |  |
| `robot_cost_h` Robot cost per hour ($) | number | `2.5` | Lease, energy and upkeep of one robot for an hour of work |
| `accelerator` Accelerator | select | `"auto"` | auto: Tenstorrent cards, else an NVIDIA GPU, else the CPU of the machine that runs it |
| `stations` Pick stations | number | `6` |  |
| `rack_pairs` Rack pairs | number | `9` |  |
| `pick_s` Seconds to pick an item | number | `6` |  |
| `station_s` Seconds at the station | number | `8` |  |
| `seed` Random seed | number | `1` |  |

## Use it in EsaSim

In a workspace, open **Projects > Blocks > New block**, choose this kind of block, copy the ports and settings above and paste the code; or ask an AI assistant connected to EsaSim (MCP) to create it from this folder.
