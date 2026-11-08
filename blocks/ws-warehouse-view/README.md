# Warehouse view

The Warehouse fleet in 3D, live: textured racks, the robots with their light strips, totes and routes, a heat map of waiting, KPIs, and controls that change the run.

Connect Live to the Warehouse fleet block's telemetry and Models to Warehouse models. While the run goes on, the robots move smoothly a couple of seconds behind the simulation (Behind real time); their light strip tells what they do: cyan to a pick face, amber picking (the rack lights the place), green carrying a tote to a station, violet at the station, red waiting for the way to clear. Routes draws the path each robot plans; Heat map colours where robots wait. The bar at the bottom sends commands to the run: order rate, robots, speed, pause, Block an aisle (then click an aisle; click it again to open it) and Open all. Click a robot to follow it, Cinematic for a slow orbit. When the run has ended, the whole run plays back with a timeline. Quality fast skips shadows and glow for slower computers.

An [EsaSim](https://esacode.com/) blueprint block: a view that draws in the browser, in JavaScript (`frontend.js`, `function render(ctx)`).

| | |
|---|---|
| Block | `ws-warehouse-view` · version 1 |
| Workspace | Gianluca De Novi's workspace |
| Author | Gianluca De Novi |

## Inputs

| Port | Type | Description |
|---|---|---|
| `live` Live | Stream | The Warehouse fleet block's telemetry Several connections. |
| `models` Models | Files (glb, json, txt) | From Warehouse models (without them, simple shapes) Optional. |

## Settings

| Key | Type | Default | Description |
|---|---|---|---|
| `quality` Quality | select | `"high"` |  |
| `routes` Show the routes | bool | `true` |  |
| `heat` Show the heat map | bool | `false` |  |
| `camera` Camera | select | `"orbit"` |  |
| `delay` Behind real time (seconds) | number | `2.5` | Live data comes in batches: a small delay keeps the motion smooth |

## Use it in EsaSim

In a workspace, open **Projects > Blocks > New block**, choose this kind of block, copy the ports and settings above and paste the code; or ask an AI assistant connected to EsaSim (MCP) to create it from this folder.
