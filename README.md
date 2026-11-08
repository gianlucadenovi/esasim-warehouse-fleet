# Warehouse Fleet

From one robot to fifty: a goods-to-person warehouse simulated live in 3D, and a fleet-size sweep that finds how many robots it needs, on CPU, NVIDIA GPU or Tenstorrent.

An [EsaSim](https://esacode.com/) project of the workspace Gianluca De Novi's workspace (Robotics & manipulation).

## Blueprints

- [1 · Live warehouse](blueprints/1-live-warehouse.json) · 6 blocks · version 7
- [2 · How many robots? (fleet-size sweep)](blueprints/2-how-many-robots-fleet-size-sweep.json) · 3 blocks · version 2
- [3 · Same code, any accelerator (CPU vs GPU vs Tenstorrent)](blueprints/3-same-code-any-accelerator-cpu-vs-gpu-vs-tenstorrent.json) · 4 blocks · version 2
- [4 · On Tenstorrent](blueprints/4-on-tenstorrent.json) · 5 blocks · version 1
- [5 · Which layout? (same hall, same orders)](blueprints/5-which-layout-same-hall-same-orders.json) · 5 blocks · version 2

## Workspace blocks it uses

- [Warehouse models](blocks/ws-warehouse-models) · version 1
- [Fleet sweep view](blocks/ws-fleet-sweep-view) · version 1

Keys pasted in blocks (secret settings) are not saved here. Datasets, results and the team stay in EsaSim.
