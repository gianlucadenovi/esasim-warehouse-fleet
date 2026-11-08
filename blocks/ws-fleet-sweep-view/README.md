# Fleet sweep view

How many robots? The fleet-size sweep drawn as it runs: orders per hour and cost per order against the fleet, with the cheapest fleet that keeps up.

Connect Data to the Fleet-size sweep block's telemetry. While the sweep runs the curves form; at the end: orders per hour delivered against the number of robots (one line per order rate, the demand dashed), robot cost per order, and for each order rate the cheapest fleet that serves at least 98% of the orders, or the most the layout can deliver. The header shows the machine and its speed (robot-steps per second), to compare CPUs, NVIDIA GPUs and Tenstorrent cards.

An [EsaSim](https://esacode.com/) blueprint block: a view that draws in the browser, in JavaScript (`frontend.js`, `function render(ctx)`).

| | |
|---|---|
| Block | `ws-fleet-sweep-view` · version 1 |
| Workspace | Gianluca De Novi's workspace |
| Author | Gianluca De Novi |

## Inputs

| Port | Type | Description |
|---|---|---|
| `data` Data | Stream | The Fleet-size sweep block's telemetry Several connections. |

## Use it in EsaSim

In a workspace, open **Projects > Blocks > New block**, choose this kind of block, copy the ports and settings above and paste the code; or ask an AI assistant connected to EsaSim (MCP) to create it from this folder.
