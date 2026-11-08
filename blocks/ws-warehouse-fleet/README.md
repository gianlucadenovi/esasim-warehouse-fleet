# Warehouse fleet

A goods-to-person warehouse with up to 50 mobile robots, simulated live on the CPU, an NVIDIA GPU or Tenstorrent cards; the view changes orders, robots and aisles while it runs.

Runs a warehouse live for Minutes: orders arrive (Order rate), idle robots take them, drive along one-way aisles to the pick face, wait while the item goes into their tote, carry it to the least busy pick station, and go back to their dock. Routes come from distance fields of every target, computed on the machine's accelerator, and again whenever an aisle is blocked. Accelerator: CPU and NVIDIA GPU run everything with PyTorch; Tenstorrent plans the routes on the cards with TT-NN (Tensix tile matmuls), and runs the robots' steps on the cards too when PyTorch/XLA for Tenstorrent (tt-xla) is installed, else on the CPU beside them. The Linux machine with the cards needs TT-NN in the worker's Python (pip install ttnn, the version of the cards' firmware). auto uses Tenstorrent cards when the machine has them, else an NVIDIA GPU, else the CPU; naming one makes the block stop if it is not there. Live telemetry: layout, fleet (every robot at every step, compact), kpi, heat and event, for the Warehouse view, which sends back the controls: order rate, robots, speed, pause, block an aisle. Results: kpis.json, timeline.csv and events.json, warehouse.json.

An [EsaSim](https://esacode.com/) blueprint block: it runs on a machine, in Python (`backend.py`, `def run(ctx)`).

| | |
|---|---|
| Block | `ws-warehouse-fleet` · version 2 |
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
| `kpis` KPIs | Metrics (json) | The run's totals: orders, orders per hour, order time, robots busy |
| `timeline` Timeline | Table (csv, json) | timeline.csv (every 30 simulated seconds) and events.json (what changed) |
| `layout` Layout | Files (json) | warehouse.json (esasim.warehouse/1) |

## Settings

| Key | Type | Default | Description |
|---|---|---|---|
| `robots` Robots at the start | number | `24` |  |
| `order_rate` Orders per hour at the start | number | `900` |  |
| `speed` Simulation speed | select | `"2"` | Times real time; the view can change it |
| `minutes` Minutes it runs | number | `20` | Real minutes; Stop in the view, or the run's Stop, ends it before |
| `accelerator` Accelerator | select | `"auto"` | auto: Tenstorrent cards, else an NVIDIA GPU, else the CPU of the machine that runs it |
| `stations` Pick stations | number | `6` |  |
| `rack_pairs` Rack pairs | number | `9` | Double rows of racks, with one-way aisles between them |
| `pick_s` Seconds to pick an item | number | `6` |  |
| `station_s` Seconds at the station | number | `8` |  |
| `seed` Random seed | number | `1` |  |

## Use it in EsaSim

In a workspace, open **Projects > Blocks > New block**, choose this kind of block, copy the ports and settings above and paste the code; or ask an AI assistant connected to EsaSim (MCP) to create it from this folder.
