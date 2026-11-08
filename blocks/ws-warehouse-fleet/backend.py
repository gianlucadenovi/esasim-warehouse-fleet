# ── EsaSim block ──────────────────────────────────────────────────────
# Warehouse fleet (ws-warehouse-fleet) · version 3 · machine block, Python: def run(ctx)
# A goods-to-person warehouse with up to 50 mobile robots, simulated live on the CPU, an NVIDIA GPU or Tenstorrent cards; the 3D view shows it and changes orders, robots and aisles while it runs.
# Workspace: Gianluca De Novi's workspace · Author: Gianluca De Novi
# Saved: 2026-11-08
#
# Inputs   ctx.inputs["id"] is a list of files: .path .name .size .read_text() .read_json()
#   kit         Files (glb, json, txt)    Warehouse models · optional · From Warehouse models: the run starts once the view has its models
# Outputs  ctx.output("id", "name.ext") is the path to write; ctx.write_json / ctx.write_text
#   kpis        Metrics (json)            KPIs · The run's totals: orders, orders per hour, order time, robots busy
#   timeline    Table (csv, json)         Timeline · timeline.csv (every 30 simulated seconds) and events.json (what changed)
#   layout      Files (json)              Layout · warehouse.json (esasim.warehouse/1)
#   telemetry   Live telemetry            ctx.telemetry("channel", data) while it runs
# Settings ctx.params["key"]
#   robots      number    Robots at the start = 24
#   order_rate  number    Orders per hour at the start = 900
#   speed       select    Simulation speed = "2" of 1 | 2 | 4 | 8
#   minutes     number    Minutes it runs = 20
#   accelerator select    Accelerator = "auto" of auto | CPU | NVIDIA GPU | Tenstorrent
#   stations    number    Pick stations = 6
#   rack_pairs  number    Rack pairs = 9
#   pick_s      number    Seconds to pick an item = 6
#   station_s   number    Seconds at the station = 8
#   seed        number    Random seed = 1
# Runs on  Any machine, NVIDIA GPU, Tenstorrent. Return a dict to fill the "result" output.
# Packages torch[cuda] (installed by the worker with pip when missing)
# EsaSim rewrites these lines from the block's definition each time it is saved: change the definition, not them.
# ── end of EsaSim block header ────────────────────────────────────────

"""Warehouse fleet: a goods-to-person warehouse run live. Robots take orders, drive to the pick faces, then to the
pick stations, while the 3D view shows them and the people watching change the order rate, the number of robots
and block aisles. The simulation runs on this machine's CPU, NVIDIA GPU or Tenstorrent cards (Accelerator)."""
import base64
import json
import struct
import time
from collections import deque

# ---- Warehouse fleet engine (shared by Warehouse fleet and Fleet-size sweep) -------------------------------------
#
# A goods-to-person warehouse on a 1 m grid. Rack rows run north-south with one-way aisles between them (alternating
# north and south), cross-aisles and two-lane highways at both ends; pick stations at the south wall, each with an
# in-lane (the queue) and an out-lane; docks along the walls where idle robots wait.
# An order is one pick: an idle robot drives to the pick face (popular locations near the front, ABC), waits while
# the item goes into its tote, drives to the least busy station, waits for the operator, then takes the next order
# or goes back to its dock.
#
# The engine runs B scenarios side by side (B = 1 for the live demo, hundreds for a sweep), each with up to N robots,
# as tensors: every step is the same dense operations on all robots of all scenarios, so it runs unchanged on a CPU,
# an NVIDIA GPU (CUDA) or Tenstorrent cards (PyTorch/XLA); routes come from distance fields of every target,
# computed by wavefront relaxation on the device (and again when an aisle is blocked).

E, N_, W_, S_ = 0, 1, 2, 3
DX = (1, 0, -1, 0)
DY = (0, 1, 0, -1)
MODE_IDLE, MODE_TO_PICK, MODE_PICKING, MODE_TO_STATION, MODE_AT_STATION, MODE_OFF = 0, 1, 2, 3, 4, 5
TICK_S = 0.6          # one step: a robot moves one cell (1.67 m/s) or turns


class Layout:
    """The warehouse: grid cells, allowed moves (one-way traffic), racks, pick faces, stations and docks."""

    def __init__(self, pairs=9, blocks=3, rack_len=4, stations=6):
        self.pairs, self.blocks, self.rack_len = pairs, blocks, rack_len
        W = 3 * pairs + 5                                   # x: margin, dock column, aisles and rack pairs, dock column, margin
        y_store = 6                                         # rack rows start here
        y_top = y_store + blocks * (rack_len + 1) - 1        # first top highway row
        H = y_top + 3                                        # top highways (2) + dock row
        self.W, self.H, self.C = W, H, W * H
        self.y_store, self.y_top = y_store, y_top
        moves = [[set() for _ in range(W)] for _ in range(H)]
        kind = [["wall"] * W for _ in range(H)]

        def allow(x, y, d):
            moves[y][x].add(d)

        aisles = [2 + 3 * k for k in range(pairs + 1)]
        self.aisles = aisles
        # highways: two one-way loops. South: y=4 eastbound, y=5 westbound; north: y_top westbound, y_top+1 eastbound;
        # each joined only at its two ends (lane changes elsewhere make small loops that jam).
        for x in range(1, W - 1):
            for y, d in ((4, E), (5, W_), (y_top, W_), (y_top + 1, E)):
                kind[y][x] = "highway"
                if (d == E and x < W - 2) or (d == W_ and x > 1):
                    allow(x, y, d)
        allow(1, 5, S_); allow(W - 2, 4, N_)
        allow(1, y_top, N_); allow(W - 2, y_top + 1, S_)
        # storage: cross-aisles between rack blocks, one-way aisles between rack pairs
        cross = [y_store + b * (rack_len + 1) + rack_len for b in range(blocks - 1)]
        self.cross = cross
        for i, y in enumerate(cross):
            d = E if i % 2 == 0 else W_
            for x in range(2, W - 2):
                kind[y][x] = "cross"
                if (d == E and x < W - 3) or (d == W_ and x > 2):
                    allow(x, y, d)
        racks = []
        for k, x in enumerate(aisles):
            d = N_ if k % 2 == 0 else S_
            for y in range(y_store, y_top):
                if kind[y][x] != "cross":
                    kind[y][x] = "aisle"
                allow(x, y, d)
            if d == N_:
                allow(x, 5, N_)                             # enter from the south highway
            else:
                allow(x, y_top, S_)                          # enter from the north highway
        for k in range(pairs):
            for b in range(blocks):
                y0 = y_store + b * (rack_len + 1)
                for side, x in enumerate((3 + 3 * k, 4 + 3 * k)):
                    racks.append({"x": x, "y": y0, "len": rack_len, "face": W_ if side == 0 else E, "id": len(racks)})
                    for y in range(y0, y0 + rack_len):
                        kind[y][x] = "rack"
        # pick faces: aisle cells beside a rack
        picks = []
        for x in aisles:
            for y in range(y_store, y_top):
                if kind[y][x] == "aisle":
                    near = [r for r in racks if r["y"] <= y < r["y"] + rack_len and abs(r["x"] - x) == 1]
                    if near:
                        picks.append((x, y, [r["id"] for r in near]))
        # stations: in-lane south from y=4 to the station (y=1), out-lane north back to y=4
        stations = max(1, min(int(stations), (W - 4) // 3))                # each needs an in-lane and an out-lane
        st_x = [round(2 + (W - 6) * (i + 0.5) / stations) for i in range(stations)]
        stations_ = []
        for x in st_x:
            for y in (3, 2):
                kind[y][x] = "queue"; allow(x, y, S_)
            allow(x, 4, S_)
            kind[1][x] = "station"; allow(x, 1, E)
            kind[1][x + 1] = "exit"; allow(x + 1, 1, N_)
            for y in (2, 3):
                kind[y][x + 1] = "exit"; allow(x + 1, y, N_)
            stations_.append((x, 1))
        # docks: north wall (from the north highway), west and east walls (from the outer aisles)
        docks = []
        for x in range(2, W - 2):
            if x % 3 == 2:                                  # keep the aisle mouths free
                continue
            docks.append((x, H - 1, S_))
        for y in range(y_store, y_top):
            if kind[y][2] in ("aisle", "cross"):
                docks.append((1, y, E))
            if kind[y][aisles[-1]] in ("aisle", "cross"):
                docks.append((W - 2, y, W_))
        used = set(x for x, _ in stations_) | set(x + 1 for x, _ in stations_)
        for x in range(2, W - 2):                           # south wall, between the stations
            if x not in used and x - 1 not in used and x + 1 not in used:
                docks.append((x, 3, N_))
        for (x, y, out) in docks:
            kind[y][x] = "dock"
            allow(x, y, out)
            bx, by = x + DX[out], y + DY[out]
            allow(bx, by, (out + 2) % 4)                    # in from the lane beside it
        self.kind, self.moves = kind, moves
        self.racks, self.picks, self.stations, self.docks = racks, picks, stations_, docks
        # targets: picks, then stations, then docks
        self.targets = [(x, y) for x, y, _ in picks] + list(stations_) + [(x, y) for x, y, _ in docks]
        self.n_picks, self.n_stations, self.n_docks = len(picks), len(stations_), len(docks)
        self.blocked = set()

    def idx(self, x, y):
        return y * self.W + x

    def neighbours(self, blocked=None):
        """next[c][d]: the cell a robot reaches from c going d, or C (nowhere) when not allowed."""
        blocked = self.blocked if blocked is None else blocked
        nxt = []
        for y in range(self.H):
            for x in range(self.W):
                row = []
                for d in range(4):
                    nx, ny = x + DX[d], y + DY[d]
                    ok = d in self.moves[y][x] and 0 <= nx < self.W and 0 <= ny < self.H and (nx, ny) not in blocked
                    row.append(self.idx(nx, ny) if ok else self.C)
                nxt.append(row)
        return nxt

    def popularity(self):
        """ABC: pick faces near the front (stations) are asked for more often."""
        import math
        w = []
        for x, y, _ in self.picks:
            depth = (y - self.y_store) / max(1, self.y_top - self.y_store)
            w.append(math.exp(-2.2 * depth) * (1.0 + 0.6 * math.cos(x * 1.7) ** 2))
        s = sum(w)
        return [v / s for v in w]

    def check(self):
        """Every target reaches every other (strongly connected roads)."""
        nxt = self.neighbours(set())
        from collections import deque
        start = self.idx(*self.targets[0])
        seen = {start}; q = deque([start])
        while q:
            c = q.popleft()
            for n in nxt[c]:
                if n < self.C and n not in seen:
                    seen.add(n); q.append(n)
        rev = {}
        for c, row in enumerate(nxt):
            for n in row:
                if n < self.C:
                    rev.setdefault(n, []).append(c)
        back = {start}; q = deque([start])
        while q:
            c = q.popleft()
            for n in rev.get(c, []):
                if n not in back:
                    back.add(n); q.append(n)
        bad = [t for t in self.targets if self.idx(*t) not in seen or self.idx(*t) not in back]
        return bad

    def describe(self):
        """The layout for the 3D view (esasim.warehouse/1)."""
        dirs = []
        for y in range(self.H):
            for x in range(self.W):
                m = 0
                for d in self.moves[y][x]:
                    m |= 1 << d
                dirs.append("0123456789abcdef"[m])
        code = {"wall": ".", "highway": "h", "cross": "c", "aisle": "a", "rack": "r", "queue": "q", "station": "s", "exit": "x", "dock": "d"}
        return {"format": "esasim.warehouse/1", "cell_m": 1.0, "tick_s": TICK_S, "w": self.W, "h": self.H,
                "kinds": "".join(code[self.kind[y][x]] for y in range(self.H) for x in range(self.W)),
                "moves": "".join(dirs),
                "racks": [[r["x"], r["y"], r["len"], r["face"]] for r in self.racks],
                "stations": [list(s) for s in self.stations], "docks": [list(d) for d in self.docks],
                "aisles": self.aisles, "cross": self.cross, "store": [self.y_store, self.y_top],
                "targets": len(self.targets), "picks": self.n_picks,
                "blocked": sorted([list(b) for b in self.blocked])}


class TTPlanner:
    """Route planning on Tenstorrent cards with TT-NN, the cards' own library: the distance fields of every target
    as tile matmuls and element-wise operations on the Tensix cores. A robot's next cell east is read through a
    shift matrix (D @ P), north and south through the transposed grid; a move that is not allowed adds a large
    number; then D = min(D, neighbour + 1) until nothing changes. bfloat16 holds whole numbers exactly up to 256,
    more than the longest route in the hall. `ops` is TT-NN on the cards, or the same arithmetic in PyTorch to check
    it."""
    INF = 1000.0

    def __init__(self, ops):
        self.ops = ops

    def distances(self, layout, tgt_cells):
        """[T, C + 1] float32 on the CPU: steps from every cell to every target (1e6 = cannot get there)."""
        import torch
        o, INF = self.ops, self.INF
        W, H, C, T = layout.W, layout.H, layout.C, len(tgt_cells)
        Wp, Hp = -(-W // 32) * 32, -(-H // 32) * 32                 # whole 32 x 32 tiles
        D0 = torch.full((T, Hp, Wp), INF)
        for i, c in enumerate(tgt_cells):
            D0[i, c // W, c % W] = 0.0
        nxt = layout.neighbours()
        masks = []
        for d in range(4):                                             # 0 where the move is allowed, INF where not
            m = torch.full((Hp, Wp), INF)
            for c, row in enumerate(nxt):
                if row[d] < C:
                    m[c // W, c % W] = 0.0
            masks.append(o.up(m.expand(T, Hp, Wp).contiguous()))
        px = [torch.zeros(Wp, Wp), torch.zeros(Wp, Wp)]                # east: out[x] = D[x + 1]; west: out[x] = D[x - 1]
        py = [torch.zeros(Hp, Hp), torch.zeros(Hp, Hp)]                # north: out[y] = D[y + 1]; south: out[y] = D[y - 1]
        for x in range(Wp - 1):
            px[0][x + 1, x] = 1.0
            px[1][x, x + 1] = 1.0
        for y in range(Hp - 1):
            py[0][y + 1, y] = 1.0
            py[1][y, y + 1] = 1.0
        PE, PW, PN, PS = o.up(px[0]), o.up(px[1]), o.up(py[0]), o.up(py[1])
        D = o.up(D0)
        prev, it = None, 0
        while it < 4 * C:
            for _ in range(8):
                Dt = o.transpose(D)
                cand = o.minimum(o.minimum(o.add(o.matmul(D, PE), masks[0]), o.add(o.matmul(D, PW), masks[2])),
                                 o.minimum(o.add(o.transpose(o.matmul(Dt, PN)), masks[1]), o.add(o.transpose(o.matmul(Dt, PS)), masks[3])))
                D = o.minimum(D, o.add_scalar(cand, 1.0))
                it += 1
            host = o.down(D)
            if prev is not None and torch.equal(host, prev):
                break
            prev = host
        out = host[:, :H, :W].reshape(T, C).float()
        out = torch.where(out >= INF / 2, torch.full_like(out, 1e6), out)
        self.iterations = it
        return torch.cat([out, torch.full((T, 1), 1e6)], 1)


class TTNNOps:
    """TT-NN on a Tenstorrent card: tensors in bfloat16 tiles in the card's memory."""

    def __init__(self, ttnn, device):
        self.tt, self.dev = ttnn, device

    def up(self, t):
        import torch
        return self.tt.from_torch(t.to(torch.bfloat16), dtype=self.tt.bfloat16, layout=self.tt.TILE_LAYOUT, device=self.dev)

    def down(self, x):
        return self.tt.to_torch(x).float()

    def matmul(self, a, b):
        return self.tt.matmul(a, b)

    def add(self, a, b):
        return self.tt.add(a, b)

    def add_scalar(self, a, s):
        return self.tt.add(a, s)

    def minimum(self, a, b):
        return self.tt.minimum(a, b)

    def transpose(self, a):
        return self.tt.transpose(a, -2, -1)


class TorchBF16Ops:
    """The same operations in PyTorch, rounded to bfloat16 like the card: to check the Tenstorrent planner."""

    def up(self, t):
        import torch
        return t.to(torch.bfloat16)

    def down(self, x):
        return x.float()

    def matmul(self, a, b):
        return (a.float() @ b.float()).to(a.dtype)

    def add(self, a, b):
        return a + b

    def add_scalar(self, a, s):
        return a + s

    def minimum(self, a, b):
        import torch
        return torch.minimum(a, b)

    def transpose(self, a):
        return a.transpose(-2, -1).contiguous()


class Backend:
    """Where the simulation runs. device: the PyTorch device of the robots' step (CPU, CUDA or PyTorch/XLA on
    Tenstorrent); tt: the TT-NN route planner when the machine has Tenstorrent cards."""

    def __init__(self, device, label, kind, xm=None, tt=None, tt_device=None, ttnn=None):
        self.device, self.label, self.kind, self.xm, self.tt = device, label, kind, xm, tt
        self._tt_device, self._ttnn = tt_device, ttnn

    def close(self):
        if self._tt_device is not None:
            try:
                self._ttnn.close_device(self._tt_device)
            except Exception:
                pass
            self._tt_device = None


def tenstorrent_backend(log=print):
    """Tenstorrent cards: routes planned with TT-NN on the cards; the robots' step on the cards too when PyTorch/XLA
    for Tenstorrent (TT-Forge's tt-xla) is installed, else on the CPU beside them. Raises when there is no card."""
    import torch
    try:
        import ttnn
    except ImportError as e:
        ttnn = None
        why = "TT-NN is not installed (%s)" % e
    tt = dev_tt = None
    arch = ""
    if ttnn is not None:
        n = int(ttnn.GetNumAvailableDevices())
        if n < 1:
            why = "TT-NN finds no Tenstorrent card"
        else:
            dev_tt = ttnn.open_device(device_id=0)
            try:
                arch = str(dev_tt.arch()).split(".")[-1].replace("_", " ").title()
            except Exception:
                arch = ""
            tt = TTPlanner(TTNNOps(ttnn, dev_tt))
    xm = None
    try:
        import torch_xla.core.xla_model as xm_mod
        import torch_xla.runtime as xr
        xr.set_device_type("TT")
        dev = xm_mod.xla_device()
        if str(xm_mod.xla_device_hw(dev)).upper() not in ("CPU", ""):
            xm = xm_mod
    except ImportError:
        pass
    except Exception as e:
        log("PyTorch/XLA for Tenstorrent not used (%s)." % e)
    if tt is None and xm is None:
        raise RuntimeError(why)
    name = "Tenstorrent" + (" " + arch if arch else "")
    if xm is not None:
        return Backend(dev, name + " (TT-NN routes, steps with PyTorch/XLA)", "tenstorrent", xm, tt, dev_tt, ttnn)
    return Backend(torch.device("cpu"), name + " (TT-NN routes, steps on the CPU)", "tenstorrent", None, tt, dev_tt, ttnn)


def pick_device(want, log=print):
    """The Backend for the Accelerator setting. auto: Tenstorrent cards when this machine has them, else an NVIDIA
    GPU (CUDA), else the CPU. A device asked for by name is used, or the block stops and says why: a run never
    silently moves to another accelerator. (Imports of the Tenstorrent libraries sit in try blocks, so machines
    without the cards do not try to install them.)"""
    import torch
    w = str(want or "auto").strip().lower()

    def nvidia():
        if not torch.cuda.is_available():
            why = ("this PyTorch was built without CUDA (%s)" % torch.__version__) if not torch.version.cuda else "no NVIDIA GPU or driver usable from the worker"
            raise RuntimeError(why)
        name = torch.cuda.get_device_name(0)
        return Backend(torch.device("cuda"), name if name.upper().startswith("NVIDIA") else "NVIDIA " + name, "nvidia")

    if w.startswith("tenstorrent") or w == "tt":
        try:
            return tenstorrent_backend(log)
        except Exception as e:
            raise RuntimeError("Tenstorrent asked, but %s. On the Linux machine with the cards, install TT-NN for the worker's "
                               "Python (pip install ttnn, matching the cards' firmware), check that tt-smi sees the cards, then run again." % e)
    if w.startswith("nvidia") or w in ("cuda", "gpu"):
        try:
            return nvidia()
        except Exception as e:
            raise RuntimeError("NVIDIA GPU asked, but %s. Check that nvidia-smi works on the machine, or set Accelerator to auto or CPU." % e)
    if w == "auto":
        try:
            return tenstorrent_backend(log)
        except Exception as e:
            if "not installed" not in str(e):
                log("No Tenstorrent card used: %s." % e)
        try:
            return nvidia()
        except Exception:
            pass
    return Backend(torch.device("cpu"), "CPU (%d threads)" % torch.get_num_threads(), "cpu")


class Fleet:
    """B warehouses side by side, each with up to N robots (fleet[b] of them working), as tensors on `device`."""

    def __init__(self, layout, B, N, backend, seed=1, pick_s=6.0, station_s=8.0, queue=1024):
        import torch
        self.L, self.B, self.N, self.dev, self.xm, self.tt = layout, B, N, backend.device, backend.xm, backend.tt
        device = self.dev
        self.T = len(layout.targets)
        self.C = layout.C
        self.pick_ticks = max(1, round(pick_s / TICK_S))
        self.station_ticks = max(1, round(station_s / TICK_S))
        self.Q = queue
        torch.manual_seed(seed)
        dev = device
        self.lower = torch.tril(torch.ones(N, N, dtype=torch.bool), diagonal=-1).to(dev)     # [i, j]: j has priority over i
        tgt_cells = [layout.idx(x, y) for x, y in layout.targets]
        self.tgt_cell = torch.tensor(tgt_cells + [self.C], dtype=torch.long, device=dev)
        pop = torch.tensor(layout.popularity(), dtype=torch.float32)
        self.pop_cdf = torch.cumsum(pop, 0).to(dev)
        self.pop_cdf[-1] = 1.0001
        self.flowing = torch.tensor([layout.kind[c // layout.W][c % layout.W] == "highway" for c in range(self.C)] + [False], device=dev)
        # cells only a robot going there may enter: a dock (its owner) and a station's queue (robots for that station)
        owner = [-1] * (self.C + 1)
        for i, (x, y) in enumerate(layout.targets):
            if i >= layout.n_picks:
                owner[layout.idx(x, y)] = i
        for i, (x, y) in enumerate(layout.stations):
            for qy in (2, 3):
                owner[layout.idx(x, qy)] = layout.n_picks + i
        self.owner = torch.tensor(owner, dtype=torch.long, device=dev)
        self.station_ids = torch.arange(layout.n_picks, layout.n_picks + layout.n_stations, device=dev)
        self.dock_ids = torch.arange(layout.n_picks + layout.n_stations, self.T, device=dev)
        self.timing = {}
        self.replan()
        # state
        z = lambda dt=torch.long: torch.zeros(B, N, dtype=dt, device=dev)
        self.pos = torch.full((B, N), self.C, dtype=torch.long, device=dev); self.head = z(); self.mode = z(); self.tgt = z(); self.timer = z(); self.wait = z()
        self.order_t = z(torch.float32)
        self.home = z()
        self.active = z(torch.bool)
        self.q_t = torch.zeros(B, queue, dtype=torch.float32, device=dev)
        self.q_head = torch.zeros(B, dtype=torch.long, device=dev)
        self.q_tail = torch.zeros(B, dtype=torch.long, device=dev)
        self.rate = torch.zeros(B, dtype=torch.float32, device=dev)            # orders per hour
        self.t = 0.0
        self.steps = 0
        # statistics
        self.done = torch.zeros(B, dtype=torch.float32, device=dev)
        self.done_time = torch.zeros(B, dtype=torch.float32, device=dev)
        self.done_hist = torch.zeros(B, 64, dtype=torch.float32, device=dev)  # order times, 15 s bins
        self.busy_ticks = torch.zeros(B, dtype=torch.float32, device=dev)
        self.robot_ticks = torch.zeros(B, dtype=torch.float32, device=dev)
        self.wait_ticks = torch.zeros(B, dtype=torch.float32, device=dev)
        self.dropped = torch.zeros(B, dtype=torch.float32, device=dev)
        self.heat = torch.zeros(B, self.C + 1, dtype=torch.float32, device=dev) if B == 1 else None
        self.set_fleet([0] * B)

    # -- routes --------------------------------------------------------------------------------------------------
    def replan(self):
        """Distance (in steps) from every cell to every target along the allowed moves, by wavefront relaxation on
        the device: D[t, c] = min over moves c -> n of 1 + D[t, n]. Run again when the roads change."""
        import time
        import torch
        t0 = time.perf_counter()
        L, C, T, dev = self.L, self.C, self.T, self.dev
        nxt = torch.tensor(L.neighbours(), dtype=torch.long, device=dev)                  # [C, 4]
        self.nxt = torch.cat([nxt, torch.full((1, 4), C, dtype=torch.long, device=dev)])  # row C: nowhere
        INF = 1e6
        if self.tt is not None:                                                           # on the Tenstorrent cards
            D = self.tt.distances(L, self.tgt_cell[:T].cpu().tolist()).to(dev)
            self.D = D
            self.reach = (D[:, :C] < INF / 2)
            ms = (time.perf_counter() - t0) * 1000
            self.timing["replan_ms"] = ms
            self.timing["replan_iterations"] = self.tt.iterations
            return ms
        D = torch.full((T, C + 1), INF, dtype=torch.float32, device=dev)
        D[torch.arange(T, device=dev), self.tgt_cell[:T]] = 0.0
        flat = self.nxt[:C].reshape(-1)                                                    # [C*4]
        it, changed = 0, True
        while changed and it < 4 * C:
            for _ in range(16):
                cand = D[:, flat].reshape(T, C, 4).amin(2) + 1.0
                newD = torch.cat([torch.minimum(D[:, :C], cand), D[:, C:]], 1)
                if self.xm is not None:
                    self.xm.mark_step()
                it += 1
                last, D = D, newD
            changed = bool((last != D).any().item())
        self.D = D
        self.reach = (D[:, :C] < INF / 2)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        ms = (time.perf_counter() - t0) * 1000
        self.timing["replan_ms"] = ms
        self.timing["replan_iterations"] = it
        return ms

    # -- fleet size and orders -----------------------------------------------------------------------------------
    def set_fleet(self, sizes):
        """Robots 0..sizes[b]-1 work in scenario b. New robots start at their docks; robots taken away finish their
        order first, then leave."""
        import torch
        dev = self.dev
        n_d = self.L.n_docks
        size = torch.tensor(sizes, dtype=torch.long, device=dev).clamp(0, min(self.N, n_d))
        ids = torch.arange(self.N, device=dev)[None, :].expand(self.B, -1)
        want = ids < size[:, None]
        # docks spread round the walls: robot i -> dock (i * step) mod n_docks
        import math
        step = next(s for s in (7, 5, 11, 13, 3, 1) if math.gcd(s, n_d) == 1)
        home_t = self.dock_ids[(ids * step) % n_d]
        new = want & ~self.active
        self.home = torch.where(new, home_t, self.home)
        self.pos = torch.where(new, self.tgt_cell[home_t], self.pos)
        dock_out = torch.tensor([d[2] for d in self.L.docks], dtype=torch.long, device=dev)
        self.head = torch.where(new, (dock_out[(ids * step) % n_d] + 2) % 4, self.head)
        self.mode = torch.where(new, torch.full_like(self.mode, MODE_IDLE), self.mode)
        self.tgt = torch.where(new, home_t, self.tgt)
        self.timer = torch.where(new, torch.zeros_like(self.timer), self.timer)
        self.wait = torch.where(new, torch.zeros_like(self.wait), self.wait)
        self.leaving = self.active & ~want
        self.active = self.active | want
        self.size = size

    def set_rate(self, rates):
        import torch
        self.rate = torch.as_tensor(rates, dtype=torch.float32, device=self.dev).reshape(self.B).clone()

    def set_blocked(self, cells):
        """Close cells (a pallet left in an aisle): routes are planned again; orders for pick faces there wait."""
        self.L.blocked = set(tuple(c) for c in cells)
        return self.replan()

    # -- one step ------------------------------------------------------------------------------------------------
    def step(self):
        import torch
        B, N, C, dev = self.B, self.N, self.C, self.dev
        t = self.t
        act = self.active
        # orders arrive (Poisson, as 4 Bernoulli draws per step)
        p = (self.rate * TICK_S / 3600.0 / 4.0).clamp(max=1.0)
        arrivals = (torch.rand(B, 4, device=dev) < p[:, None]).long()
        qpos = torch.arange(self.Q, device=dev)[None, :]
        for k in range(4):
            slot = (self.q_tail % self.Q)[:, None] == qpos
            write = slot & (arrivals[:, k:k + 1] > 0)
            self.q_t = torch.where(write, torch.full_like(self.q_t, t), self.q_t)
            self.q_tail = self.q_tail + arrivals[:, k]
        overflow = (self.q_tail - self.q_head - self.Q).clamp(min=0)
        self.dropped = self.dropped + overflow.float()
        self.q_head = self.q_head + overflow
        pending = self.q_tail - self.q_head
        # robots that finished their order and are no longer wanted leave
        gone = self.leaving & (self.mode == MODE_IDLE) & (self.pos == self.tgt_cell[self.home])
        self.active = self.active & ~gone
        self.leaving = self.leaving & ~gone
        act = self.active
        self.pos = torch.where(gone, torch.full_like(self.pos, C), self.pos)
        # idle robots take the oldest orders (lowest robot number first)
        idle = act & ~self.leaving & (self.mode == MODE_IDLE)
        rank = torch.cumsum(idle.long(), 1) - 1
        take = idle & (rank < pending[:, None])
        u = torch.rand(B, N, device=dev)
        pick = (u[:, :, None] >= self.pop_cdf[None, None, :]).long().sum(2).clamp(max=self.L.n_picks - 1)
        reach = self.reach[pick, self.pos.clamp(max=C - 1)] & self.reach[self.station_ids[0], self.tgt_cell[pick]]
        take = take & reach
        q_idx = (self.q_head[:, None] + rank) % self.Q
        self.order_t = torch.where(take, torch.gather(self.q_t, 1, q_idx), self.order_t)
        self.tgt = torch.where(take, pick, self.tgt)
        self.mode = torch.where(take, torch.full_like(self.mode, MODE_TO_PICK), self.mode)
        self.q_head = self.q_head + take.long().sum(1)
        # arrivals at targets
        at = act & (self.pos == self.tgt_cell[self.tgt])
        start_pick = at & (self.mode == MODE_TO_PICK)
        self.mode = torch.where(start_pick, torch.full_like(self.mode, MODE_PICKING), self.mode)
        self.timer = torch.where(start_pick, torch.full_like(self.timer, self.pick_ticks), self.timer)
        start_st = at & (self.mode == MODE_TO_STATION)
        self.mode = torch.where(start_st, torch.full_like(self.mode, MODE_AT_STATION), self.mode)
        self.timer = torch.where(start_st, torch.full_like(self.timer, self.station_ticks), self.timer)
        dwell = act & ((self.mode == MODE_PICKING) | (self.mode == MODE_AT_STATION))
        self.timer = torch.where(dwell, self.timer - 1, self.timer)
        # picked: off to the least busy station (robots already heading there, then distance)
        picked = dwell & (self.mode == MODE_PICKING) & (self.timer <= 0)
        heading = ((self.mode == MODE_TO_STATION) | (self.mode == MODE_AT_STATION)) & act
        load = (heading[:, :, None] & (self.tgt[:, :, None] == self.station_ids[None, None, :])).float().sum(1)   # [B, S]
        dist = self.D[self.station_ids][:, self.pos.clamp(max=C)].permute(1, 2, 0)                             # [B, N, S]
        score = dist + 6.0 * load[:, None, :]
        st = self.station_ids[score.argmin(2)]
        self.tgt = torch.where(picked, st, self.tgt)
        self.mode = torch.where(picked, torch.full_like(self.mode, MODE_TO_STATION), self.mode)
        # delivered: the order is done
        served = dwell & (self.mode == MODE_AT_STATION) & (self.timer <= 0)
        took = torch.where(served, t - self.order_t, torch.zeros_like(self.order_t))
        self.done = self.done + served.float().sum(1)
        self.done_time = self.done_time + took.sum(1)
        bins = (took / 15.0).long().clamp(0, 63)
        self.done_hist = self.done_hist + (served[:, :, None] & (bins[:, :, None] == torch.arange(64, device=dev)[None, None, :])).float().sum(1)
        self.mode = torch.where(served, torch.full_like(self.mode, MODE_IDLE), self.mode)
        self.tgt = torch.where(served | (self.mode == MODE_IDLE), self.home, self.tgt)
        # movement: the best next cell towards the target, turning first when needed
        moving = act & ((self.mode == MODE_TO_PICK) | (self.mode == MODE_TO_STATION) | (self.mode == MODE_IDLE)) & (self.pos != self.tgt_cell[self.tgt])
        nb = self.nxt[self.pos.clamp(max=C)]                                       # [B, N, 4]
        cost = self.D.reshape(-1)[(self.tgt[:, :, None] * (C + 1) + nb)]           # [B, N, 4]
        dirs = torch.arange(4, device=dev)[None, None, :]
        cost = cost + 0.01 * (dirs != self.head[:, :, None]).float()               # go straight when it is as short
        own = self.owner[nb]
        cost = torch.where((own >= 0) & (own != self.tgt[:, :, None]), torch.full_like(cost, 1e6), cost)   # not my dock, not my queue
        # on a highway, a robot does not stop for a full lane or queue: it drives on (round the loop) and comes back
        flow = self.flowing[self.pos.clamp(max=C)][:, :, None]
        taken = (nb[:, :, :, None] == self.pos[:, None, None, :]).any(3)            # [B, N, 4]: that cell has a robot
        cost = torch.where(flow & taken, cost + 40.0, cost)
        stuck = (self.wait > 10)[:, :, None]
        best = cost.argmin(2, keepdim=True)
        cost = torch.where(stuck & (dirs == best), cost + 50.0, cost)              # stuck a while: try another way
        want = cost.argmin(2)
        ok = torch.gather(cost, 2, want[:, :, None])[:, :, 0] < 1e5
        moving = moving & ok
        turn = moving & (want != self.head)
        self.head = torch.where(turn, want, self.head)
        go = moving & ~turn
        dest = torch.gather(nb, 2, self.head[:, :, None])[:, :, 0]
        occupied = (dest[:, :, None] == self.pos[:, None, :]).any(2)
        rival = ((dest[:, :, None] == dest[:, None, :]) & go[:, None, :] & self.lower[None]).any(2)
        move = go & ~occupied & ~rival
        blocked_now = go & ~move
        self.pos = torch.where(move, dest, self.pos)
        self.wait = torch.where(move | ~moving, torch.zeros_like(self.wait), self.wait + 1)   # turning or blocked: still waiting
        # statistics
        working = act & (self.mode != MODE_IDLE)
        self.busy_ticks = self.busy_ticks + working.float().sum(1)
        self.robot_ticks = self.robot_ticks + act.float().sum(1)
        self.wait_ticks = self.wait_ticks + blocked_now.float().sum(1)
        if self.heat is not None:
            self.heat = self.heat * 0.995
            self.heat = self.heat.index_add(1, self.pos[0], blocked_now.float())
        if self.xm is not None:
            self.xm.mark_step()
        self.t = t + TICK_S
        self.steps += 1

    # -- reading out ---------------------------------------------------------------------------------------------
    def snapshot(self, b=0):
        """Robots of scenario b: [cell, heading, mode, target cell] each (cell C = not on the floor)."""
        import torch
        m = torch.where(self.active[b], self.mode[b], torch.full_like(self.mode[b], MODE_OFF))
        pos = torch.where(self.active[b], self.pos[b], torch.full_like(self.pos[b], self.C))
        tc = self.tgt_cell[self.tgt[b]]
        return torch.stack([pos, self.head[b], m, tc], 1).cpu().tolist()

    def stats(self):
        import torch
        busy = (self.busy_ticks / self.robot_ticks.clamp(min=1)).cpu()
        hours = max(self.t, 1e-6) / 3600.0
        done = self.done.cpu()
        return {"done": done.tolist(), "per_hour": (done / hours).tolist(),
                "avg_order_s": (self.done_time.cpu() / done.clamp(min=1)).tolist(),
                "utilization": busy.tolist(), "backlog": (self.q_tail - self.q_head).cpu().tolist(),
                "wait_share": (self.wait_ticks / self.robot_ticks.clamp(min=1)).cpu().tolist(),
                "hist": self.done_hist.cpu().tolist()}


def pack16(values):
    return base64.b64encode(struct.pack("<%dH" % len(values), *values)).decode()


class Live:
    def __init__(self, ctx):
        self.ctx = ctx
        p = ctx.params
        self.layout = Layout(pairs=int(p.get("rack_pairs", 9)), blocks=int(p.get("rack_blocks", 3)), stations=int(p.get("stations", 6)))
        bad = self.layout.check()
        if bad:
            raise RuntimeError("This layout leaves %d places out of reach; change Rack pairs or Stations." % len(bad))
        self.max_robots = min(int(p.get("max_robots", 50)), self.layout.n_docks)
        self.hw = pick_device(p.get("accelerator", "auto"), ctx.log)
        self.backend, self.kind = self.hw.label, self.hw.kind
        ctx.log("Simulation on %s." % self.backend)
        self.fleet = Fleet(self.layout, 1, self.max_robots, self.hw, seed=int(p.get("seed", 1)),
                           pick_s=float(p.get("pick_s", 6)), station_s=float(p.get("station_s", 8)))
        self.robots = max(1, min(self.max_robots, int(p.get("robots", 24))))
        self.rate = max(0.0, float(p.get("order_rate", 900)))
        self.speed = max(0.25, min(16.0, float(str(p.get("speed", "2")).rstrip("x×"))))
        self.fleet.set_fleet([self.robots])
        self.fleet.set_rate([self.rate])
        self.paused = False
        self.frames = []
        self.history = deque()          # (sim t, done, done_time)
        self.timeline = []
        self.events = []
        self.last_tl = -1e9
        self.steps_wall = deque(maxlen=50)

    # -- telemetry -----------------------------------------------------------------------------------------------
    def send_layout(self):
        d = self.layout.describe()
        d.update({"t": round(self.fleet.t, 2), "robots_max": self.max_robots, "backend": self.backend, "kind": self.kind,
                  "pick_s": self.fleet.pick_ticks * TICK_S, "station_s": self.fleet.station_ticks * TICK_S})
        self.ctx.telemetry("layout", d)

    def event(self, text, **extra):
        e = dict({"t": round(self.fleet.t, 1), "text": text}, **extra)
        self.events.append(e)
        self.ctx.telemetry("event", e)
        self.ctx.log("[%.0f s] %s" % (self.fleet.t, text))

    def frame(self):
        C = self.layout.C
        vals = []
        for cell, head, mode, tcell in self.fleet.snapshot():
            vals += [min(cell, C), head + 4 * mode, min(tcell, C)]
        self.frames.append(vals)

    def flush_frames(self):
        if not self.frames:
            return
        n = len(self.frames)
        t0 = self.fleet.t - (n - 1) * TICK_S
        self.ctx.telemetry("fleet", {"t": round(t0, 2), "dt": TICK_S, "n": self.max_robots, "off": self.layout.C,
                                     "f": [pack16(v) for v in self.frames]})
        self.frames = []

    def kpis(self):
        F = self.fleet
        st = F.stats()
        done, total_time = st["done"][0], float(F.done_time[0])
        self.history.append((F.t, done, total_time))
        while len(self.history) > 2 and self.history[1][0] < F.t - 600:      # the last 10 minutes
            self.history.popleft()
        t0, d0, tt0 = self.history[0]
        span = max(F.t - t0, 1e-6)
        per_h = (done - d0) * 3600.0 / span if span > 30 else st["per_hour"][0]
        avg = (total_time - tt0) / (done - d0) if done > d0 else st["avg_order_s"][0]
        snap = F.snapshot()
        modes = [m for _, _, m, _ in snap]
        moving = sum(1 for m in modes if m in (MODE_TO_PICK, MODE_TO_STATION))
        working = sum(1 for m in modes if m in (MODE_TO_PICK, MODE_PICKING, MODE_TO_STATION, MODE_AT_STATION))
        on_floor = sum(1 for m in modes if m != MODE_OFF)
        waiting = int((F.wait[0] > 0).sum())
        sps = 0.0
        if len(self.steps_wall) > 1:
            (w0, s0), (w1, s1) = self.steps_wall[0], self.steps_wall[-1]
            sps = (s1 - s0) / max(w1 - w0, 1e-6)
        k = {"t": round(F.t, 1), "orders_h": round(per_h, 1), "avg_order_s": round(avg, 1), "done": int(done),
             "backlog": int(st["backlog"][0]), "utilization": round(working / max(1, on_floor), 3),
             "robots": self.robots, "on_floor": on_floor, "moving": moving, "waiting": waiting,
             "order_rate": self.rate, "speed": self.speed, "paused": self.paused,
             "backend": self.backend, "kind": self.kind, "steps_s": round(sps, 1),
             "replan_ms": round(F.timing.get("replan_ms", 0), 2), "blocked": len(self.layout.blocked)}
        self.ctx.telemetry("kpi", k)
        if F.t - self.last_tl >= 30:
            self.last_tl = F.t
            self.timeline.append(k)
        return k

    def send_heat(self):
        h = self.fleet.heat[0, :self.layout.C].cpu()
        top = float(h.max())
        vals = [0] * self.layout.C if top <= 0 else [int(min(255, 255 * v / max(top, 4.0))) for v in h.tolist()]
        self.ctx.telemetry("heat", {"t": round(self.fleet.t, 1), "w": self.layout.W, "h": self.layout.H,
                                    "v": base64.b64encode(bytes(vals)).decode()})

    # -- controls from the view ----------------------------------------------------------------------------------
    def control(self, d):
        if not isinstance(d, dict):
            return False
        if "control" in d:                  # from the 3D view's controls or a Controls view: {control: NAME, value}
            name, v = str(d.get("control") or "").strip().lower().replace(" ", "_"), d.get("value")
            if name in ("order_rate", "rate"):
                d = {"rate": v}
            elif name in ("robots", "speed", "stop"):
                d = {name: v}
            elif name in ("paused", "pause"):
                d = {"pause": bool(v)}
            elif name in ("block_aisle", "block") and isinstance(v, (list, tuple)) and len(v) >= 2:
                cell = (int(v[0]), int(v[1]))
                d = {"unblock": list(cell)} if cell in self.layout.blocked else {"block": list(cell)}
            elif name in ("open_all_aisles", "open_all", "clear"):
                d = {"clear": True}
            else:
                self.event("Unknown control %s" % d.get("control"), kind="refused")
                return True
        F = self.fleet
        if "rate" in d:
            self.rate = max(0.0, min(6000.0, float(d["rate"])))
            F.set_rate([self.rate])
            self.event("Order rate %d orders per hour" % self.rate, kind="rate", value=self.rate)
        if "robots" in d:
            n = max(1, min(self.max_robots, int(d["robots"])))
            if n != self.robots:
                more = n > self.robots
                self.robots = n
                F.set_fleet([n])
                self.event(("%d robots: new robots leave their docks" if more else "%d robots: the others finish their order and park") % n, kind="robots", value=n)
        if "speed" in d:
            self.speed = max(0.25, min(16.0, float(d["speed"])))
            self.event("Simulation speed %gx" % self.speed, kind="speed", value=self.speed)
        if "pause" in d:
            self.paused = bool(d["pause"])
            self.event("Paused" if self.paused else "Running again", kind="pause")
        if "block" in d or "unblock" in d or d.get("clear"):
            cells = set(self.layout.blocked)
            if d.get("clear"):
                cells = set()
            if "unblock" in d:
                cells.discard(tuple(int(v) for v in d["unblock"]))
            if "block" in d:
                x, y = (int(v) for v in d["block"])
                if not (0 <= x < self.layout.W and 0 <= y < self.layout.H) or self.layout.kind[y][x] not in ("aisle", "cross"):
                    self.event("Only aisles can be blocked", kind="refused")
                    return True
                cells.add((x, y))
                old = self.layout.blocked
                self.layout.blocked = cells
                bad = [t for t in self.layout.targets[self.layout.n_picks:] if t not in cells and not self._reach_ok(t)]
                self.layout.blocked = old
                if bad:
                    self.event("Blocking there would cut off stations or docks", kind="refused")
                    return True
            ms = F.set_blocked(sorted(cells))
            lost = self._unreachable_picks()
            moved = F.retarget()
            what = ("Aisle blocked at %s" % (list(d["block"]),)) if "block" in d else ("Aisle open again" if not d.get("clear") else "All aisles open")
            self.event("%s: %d routes planned again in %.1f ms on %s%s%s" % (
                what, F.T, ms, self.backend, (", %d pick faces out of reach" % lost) if lost else "",
                (", %d robot%s sent elsewhere" % (moved, "" if moved == 1 else "s")) if moved else ""), kind="replan", ms=round(ms, 2), cells=[list(c) for c in sorted(cells)])
            self.send_layout()
        if d.get("stop"):
            self.event("Stopped from the view", kind="stop")
            return "stop"
        return True

    def _reach_ok(self, target):
        nxt = self.layout.neighbours()
        start = self.layout.idx(*self.layout.stations[0])
        goal = self.layout.idx(*target)
        seen, todo = {start}, [start]
        while todo:
            c = todo.pop()
            for n in nxt[c]:
                if n < self.layout.C and n not in seen:
                    seen.add(n); todo.append(n)
        if goal not in seen:
            return False
        seen, todo = {goal}, [goal]
        while todo:
            c = todo.pop()
            for n in nxt[c]:
                if n < self.layout.C and n not in seen:
                    seen.add(n); todo.append(n)
        return start in seen

    def _unreachable_picks(self):
        F = self.fleet
        st = F.tgt_cell[F.station_ids[0]]
        return int((~F.reach[:self.layout.n_picks, st]).sum())

    # -- the loop ------------------------------------------------------------------------------------------------
    def run(self, minutes):
        ctx, F = self.ctx, self.fleet
        self.send_layout()
        self.event("%d robots, %d orders per hour, on %s" % (self.robots, self.rate, self.backend), kind="start")
        self.frame()
        start = time.time()
        end = start + minutes * 60
        clock = time.time()
        owed = 0.0
        last_flush = last_kpi = last_heat = last_layout = 0.0
        last_progress = 0
        while time.time() < end:
            now = time.time()
            for m in ctx.messages("control"):
                if self.control(m.get("data")) == "stop":
                    end = 0
            if not self.paused:
                owed += (now - clock) * self.speed / TICK_S
            clock = now
            n = 0
            while owed >= 1 and n < 64:
                F.step()
                self.frame()
                owed -= 1
                n += 1
            if owed > 64:
                owed = 0                    # too far behind (a slow machine): skip rather than run away
            self.steps_wall.append((now, F.steps))
            if now - last_flush >= 0.5:
                self.flush_frames(); last_flush = now
            if now - last_kpi >= 1.0:
                k = self.kpis(); last_kpi = now
                pct = int(100 * (now - start) / max(1, minutes * 60))
                if pct != last_progress:
                    ctx.progress(pct, "%d orders, %.0f/h" % (k["done"], k["orders_h"])); last_progress = pct
            if now - last_heat >= 4.0:
                self.send_heat(); last_heat = now
            if now - last_layout >= 60.0:
                self.send_layout(); last_layout = now
            time.sleep(0.04)
        self.flush_frames()
        return self.kpis()


def retarget(self):
    """Robots going to a pick face that can no longer be reached pick another order location."""
    import torch
    C = self.C
    bad = self.active & (self.mode == MODE_TO_PICK) & ~self.reach[self.tgt, self.pos.clamp(max=C - 1)]
    n = int(bad.sum())
    if n:
        ok = self.reach[:self.L.n_picks][:, self.tgt_cell[self.station_ids[0]]]
        for _ in range(8):
            u = torch.rand(self.B, self.N, device=self.dev)
            pick = (u[:, :, None] >= self.pop_cdf[None, None, :]).long().sum(2).clamp(max=self.L.n_picks - 1)
            good = ok[pick] & self.reach[pick, self.pos.clamp(max=C - 1)]
            self.tgt = torch.where(bad & good, pick, self.tgt)
            bad = bad & ~good
    return n


Fleet.retarget = retarget


def run(ctx):
    live = Live(ctx)
    minutes = max(0.5, min(180.0, float(ctx.params.get("minutes", 20))))
    try:
        k = live.run(minutes)
    finally:
        live.hw.close()
    ctx.write_json("layout", "warehouse.json", live.layout.describe())
    cols = ["t", "orders_h", "avg_order_s", "utilization", "backlog", "robots", "on_floor", "waiting", "order_rate", "speed"]
    lines = [",".join(cols)] + [",".join(str(r.get(c, "")) for c in cols) for r in live.timeline + [k]]
    ctx.write_text("timeline", "timeline.csv", "\n".join(lines) + "\n")
    ctx.write_json("timeline", "events.json", live.events)
    summary = {"orders_done": k["done"], "orders_per_hour": k["orders_h"], "avg_order_s": k["avg_order_s"],
               "utilization": k["utilization"], "backlog": k["backlog"], "robots": live.robots,
               "simulated_minutes": round(live.fleet.t / 60, 1), "backend": live.backend,
               "steps": live.fleet.steps, "replan_ms": k["replan_ms"]}
    ctx.write_json("kpis", "kpis.json", summary)
    ctx.log("Done: %d orders in %.0f simulated minutes, %.0f per hour." % (k["done"], live.fleet.t / 60, k["orders_h"]))
    return summary
