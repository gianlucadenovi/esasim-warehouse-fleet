# Warehouse layouts

Which layout works best in the same building? Several warehouse layouts with the same robots, the very same orders and incidents, simulated and compared: throughput, order time, metres driven, waiting

Compares warehouse layouts in the same building. Each line of Layouts is one layout in the hall of the Warehouse fleet block (its width from Rack pairs, its depth from Rack blocks × Rack length): blocks=9 cuts the racks into more, shorter blocks with more cross-aisles (shorter trips, less storage), blocks=3 into fewer, longer ones; stations=4 or 12 changes the pack-out stations; stations_at=both splits them between the south and north walls; slotting=random puts popular products anywhere instead of near the stations. Every layout gets the same robots, the very same orders (arrival times and lines) and the same incidents (when, what kind and how long; where depends on the layout), for Simulated hours after a warm-up, once per seed, with routes planned on the machine's accelerator. Results per layout: orders and lines per hour, share of the demand served, average and 95th-percentile order time, metres driven per item, robots busy, waiting, charging, time stopped by faults, incidents, orders left waiting, pick faces and metres of racks (storage). layouts.csv for a Table, layouts_chart.csv for a Chart (bars by layout), a plan of each layout coloured blue to red where robots waited (for an Images view), and layouts_summary.json. Near the robots' limit (Orders per hour) the layouts differ most; well below it they all keep up and differ in order time and driving. To watch one of them, put its line in the Layout setting of Warehouse fleet.

An [EsaSim](https://esacode.com/) blueprint block: it runs on a machine, in Python (`backend.py`, `def run(ctx)`).

| | |
|---|---|
| Block | `ws-warehouse-layouts` · version 1 |
| Workspace | Gianluca De Novi's workspace |
| Author | Gianluca De Novi |
| Runs on | Any machine, NVIDIA GPU, Tenstorrent |

## Outputs

| Port | Type | Description |
|---|---|---|
| `results` Results | Table (csv) | layouts.csv: one row per layout (throughput, order time, metres per item, waiting, storage…) |
| `chart` For a chart | Table (csv) | layouts_chart.csv: orders per hour, order time, metres per item and waiting by layout |
| `plans` Plans | Files (png, json) | A plan of each layout from above, coloured where robots waited (PNG), and its layout (JSON) |
| `summary` Summary | Metrics (json) | The best layout for throughput, order time and driving, and each layout against the first |

## Settings

| Key | Type | Default | Description |
|---|---|---|---|
| `layouts` Layouts | textarea | `"Today: blocks=5 stations=8\n3 long blocks: blocks=3\n9 short blocks: blocks=9\nStations at both ends: stations_at=both\nRandom slotting: slotting=random\n4 stations: stations=4"` | One per line, Name: key=value … with blocks (rack blocks from front to back: more blocks, more cross-aisles), stations (pack-out stations), stations_at (south or both), slotting (abc: popular products near the stations, or random). The first is the reference |
| `robots` Robots | number | `40` |  |
| `order_rate` Orders per hour | number | `500` | Near what the robots can do, the layouts differ most |
| `seeds` Seeds per layout | number | `3` | Each seed is another day of orders and incidents, the same for every layout |
| `hours` Simulated hours | number | `2` |  |
| `warmup_min` Warm-up (simulated minutes, not counted) | number | `10` |  |
| `accelerator` Accelerator | select | `"auto"` | auto: Tenstorrent cards, else an NVIDIA GPU, else the CPU of the machine that runs it |
| `rack_pairs` Rack pairs (sets the hall's width) | number | `20` |  |
| `rack_blocks` Rack blocks of the reference hall | number | `5` |  |
| `rack_len` Rack length of the reference hall (m) | number | `8` | With Rack blocks, sets the hall's depth; every layout fits in that same hall |
| `stations` Pack-out stations (unless a layout says) | number | `8` |  |
| `pick_s` Seconds to pick an item | number | `10` |  |
| `station_s` Seconds to unload at the station | number | `15` |  |
| `robot_speed` Robot speed (m/s) | number | `1.2` |  |
| `battery_h` Hours on a charge | number | `8` |  |
| `charge_min` Minutes to charge from empty | number | `60` |  |
| `charge_below` Go to charge below (%) | number | `25` |  |
| `incidents_h` Incidents per hour | number | `2` |  |
| `fault_share` Robot faults (% of incidents) | number | `40` |  |
| `response_min` Minutes until someone comes | number | `3` |  |
| `clear_min` Minutes to clean up a spill | number | `4` |  |
| `repair_min` Minutes to repair a robot | number | `8` |  |
| `seed` Random seed | number | `1` |  |

## Use it in EsaSim

In a workspace, open **Projects > Blocks > New block**, choose this kind of block, copy the ports and settings above and paste the code; or ask an AI assistant connected to EsaSim (MCP) to create it from this folder.
