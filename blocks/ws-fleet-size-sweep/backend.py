# ── EsaSim block ──────────────────────────────────────────────────────
# Fleet-size sweep (ws-fleet-size-sweep) · version 1 · machine block, Python: def run(ctx)
# How many robots does the warehouse need? Hundreds of fleet-size × order-rate scenarios simulated at once, as one batch on the CPU, an NVIDIA GPU or Tenstorrent cards.
# Workspace: Gianluca De Novi's workspace · Author: Gianluca De Novi
# Saved: 2026-11-08
#
# Inputs   ctx.inputs["id"] is a list of files: .path .name .size .read_text() .read_json()
#   (none)
# Outputs  ctx.output("id", "name.ext") is the path to write; ctx.write_json / ctx.write_text
#   results     Table (csv)               Results · fleet_sweep.csv: one row per fleet size and order rate
#   chart       Table (csv)               For a chart · throughput_by_fleet.csv: orders per hour by fleet size, one column per order rate
#   summary     Metrics (json)            Summary · Best fleet per order rate, scenarios, time and speed on this machine
#   telemetry   Live telemetry            ctx.telemetry("channel", data) while it runs
# Settings ctx.params["key"]
#   fleets      text      Fleet sizes = "5-50/5"
#   rates       text      Order rates (orders per hour) = "600,900,1200,1500"
#   seeds       number    Seeds per combination = 3
#   hours       number    Simulated hours = 2
#   warmup_min  number    Warm-up (simulated minutes, not counted) = 10
#   robot_cost_h number    Robot cost per hour ($) = 2.5
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

"""Fleet-size sweep: how many robots does the warehouse need? Every combination of fleet size, order rate and seed
is simulated for the same hours, all at once as one batch of scenarios on this machine's CPU, NVIDIA GPU or
Tenstorrent cards (Accelerator). Gives orders per hour, order time, robot use and cost per order for each."""
import json
import time

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


def pick_device(want, log=print):
    """(device, label, kind, xla module or None) for the Accelerator setting. auto: Tenstorrent cards when this
    machine has them (PyTorch/XLA through TT-Forge), else an NVIDIA GPU (CUDA), else the CPU. A device asked for by
    name is used, or the block stops and says why: a run never silently moves to another accelerator."""
    import torch
    w = str(want or "auto").strip().lower()

    def tenstorrent():
        import torch_xla.core.xla_model as xm
        try:
            import torch_xla.runtime as xr
            xr.set_device_type("TT")
        except Exception:
            pass
        dev = xm.xla_device()
        hw = ""
        try:
            hw = str(xm.xla_device_hw(dev))
        except Exception:
            pass
        if hw.upper() in ("CPU", ""):
            raise RuntimeError("PyTorch/XLA found no Tenstorrent card (device %s)" % (hw or "unknown"))
        return dev, "Tenstorrent (PyTorch/XLA, %s)" % hw, "tenstorrent", xm

    def nvidia():
        if not torch.cuda.is_available():
            why = ("this PyTorch was built without CUDA (%s)" % torch.__version__) if not torch.version.cuda else "no NVIDIA GPU or driver usable from the worker"
            raise RuntimeError(why)
        return torch.device("cuda"), "NVIDIA " + torch.cuda.get_device_name(0), "nvidia", None

    if w.startswith("tenstorrent") or w == "tt":
        try:
            return tenstorrent()
        except Exception as e:
            raise RuntimeError("Tenstorrent asked, but %s. On the Linux machine with the cards, install TT-Forge's PyTorch "
                               "support (tt-xla) for the worker's Python, check that tt-smi sees the cards, then run again." % e)
    if w.startswith("nvidia") or w in ("cuda", "gpu"):
        try:
            return nvidia()
        except Exception as e:
            raise RuntimeError("NVIDIA GPU asked, but %s. Check that nvidia-smi works on the machine, or set Accelerator to auto or CPU." % e)
    if w == "auto":
        try:
            import importlib.util
            if importlib.util.find_spec("torch_xla") is not None:
                return tenstorrent()
        except Exception as e:
            log("No Tenstorrent card used (%s)." % e)
        try:
            return nvidia()
        except Exception:
            pass
    return torch.device("cpu"), "CPU (%d threads)" % torch.get_num_threads(), "cpu", None


class Fleet:
    """B warehouses side by side, each with up to N robots (fleet[b] of them working), as tensors on `device`."""

    def __init__(self, layout, B, N, device, xm=None, seed=1, pick_s=6.0, station_s=8.0, queue=1024):
        import torch
        self.L, self.B, self.N, self.dev, self.xm = layout, B, N, device, xm
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


def numbers(text, default):
    """"5,10,20" or "5-50/5" (from 5 to 50 by 5), or both."""
    import re
    out = []
    for part in re.split(r"[,;\s]+", str(text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)(?:/(\d+(?:\.\d+)?))?", part)
        if m:
            a, b, st = float(m.group(1)), float(m.group(2)), float(m.group(3) or 5)
            v = a
            while v <= b + 1e-9 and len(out) < 200:
                out.append(v)
                v += max(st, 1e-3)
        else:
            out.append(float(part))
    return out or default


def run(ctx):
    import torch
    p = ctx.params
    layout = Layout(pairs=int(p.get("rack_pairs", 9)), blocks=int(p.get("rack_blocks", 3)), stations=int(p.get("stations", 6)))
    fleets = sorted(set(int(v) for v in numbers(p.get("fleets"), [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]) if v >= 1))
    fleets = [f for f in fleets if f <= layout.n_docks] or [min(layout.n_docks, 10)]
    rates = sorted(set(float(v) for v in numbers(p.get("rates"), [600, 900, 1200, 1500]) if v > 0))
    seeds = max(1, min(20, int(p.get("seeds", 3))))
    hours = max(0.1, min(24.0, float(p.get("hours", 2))))
    warm_min = max(0.0, float(p.get("warmup_min", 10)))
    cost_h = float(p.get("robot_cost_h", 2.5))
    device, backend, kind, xm = pick_device(p.get("accelerator", "auto"), ctx.log)
    combos = [(f, r, s) for r in rates for f in fleets for s in range(seeds)]
    B, N = len(combos), max(fleets)
    ctx.log("%d scenarios (%d fleet sizes x %d order rates x %d seeds), %.1f simulated hours each, on %s." % (B, len(fleets), len(rates), seeds, hours, backend))
    ctx.telemetry("sweep", {"phase": "start", "scenarios": B, "fleets": fleets, "rates": rates, "seeds": seeds, "hours": hours,
                            "backend": backend, "kind": kind, "warmup_min": warm_min, "robot_cost_h": cost_h})
    torch.manual_seed(int(p.get("seed", 1)))
    F = Fleet(layout, B, N, device, xm, seed=int(p.get("seed", 1)), pick_s=float(p.get("pick_s", 6)), station_s=float(p.get("station_s", 8)))
    F.set_fleet([c[0] for c in combos])
    F.set_rate([c[1] for c in combos])
    warm = int(warm_min * 60 / TICK_S)
    steps = int(hours * 3600 / TICK_S)
    total = warm + steps
    t0 = time.time()
    base = None
    last = 0.0
    for i in range(total):
        F.step()
        if i + 1 == warm:
            base = snapshot(F)
        now = time.time()
        if now - last >= 1.0 or i + 1 == total:
            last = now
            if device.type == "cuda":
                torch.cuda.synchronize()
            el = now - t0
            rate = (i + 1) * B / max(el, 1e-6)
            pct = int(100 * (i + 1) / total)
            ctx.progress(pct, "%d of %d steps, %s scenario-steps/s" % (i + 1, total, format(int(rate), ",")))
            part = summarise(F, base, combos, fleets, rates, cost_h, i + 1 - warm) if i + 1 > warm + 60 else None
            ctx.telemetry("sweep", {"phase": "running", "step": i + 1, "steps": total, "sim_h": round((i + 1 - warm) * TICK_S / 3600, 3),
                                    "elapsed_s": round(el, 1), "scenario_steps_s": round(rate), "robot_steps_s": round(rate * sum(fleets) / len(fleets)),
                                    "backend": backend, "kind": kind, "rows": part})
    if device.type == "cuda":
        torch.cuda.synchronize()
    wall = time.time() - t0
    rows = summarise(F, base, combos, fleets, rates, cost_h, steps)
    cols = ["fleet", "order_rate", "orders_h", "served_pct", "avg_order_s", "p95_order_s", "utilization", "waiting_pct", "backlog", "cost_per_order"]
    ctx.write_text("results", "fleet_sweep.csv", "\n".join([",".join(cols)] + [",".join(str(r[c]) for c in cols) for r in rows]) + "\n")
    wide = ["fleet," + ",".join("orders_h@%d" % r for r in rates)]
    for f in fleets:
        wide.append(str(f) + "," + ",".join(str(next(x["orders_h"] for x in rows if x["fleet"] == f and x["order_rate"] == r)) for r in rates))
    ctx.write_text("chart", "throughput_by_fleet.csv", "\n".join(wide) + "\n")
    best = {}
    for r in rates:
        ok = [x for x in rows if x["order_rate"] == r and x["served_pct"] >= 98]
        pick = min(ok, key=lambda x: x["cost_per_order"]) if ok else max((x for x in rows if x["order_rate"] == r), key=lambda x: x["orders_h"])
        best[str(int(r))] = {"fleet": pick["fleet"], "orders_h": pick["orders_h"], "cost_per_order": pick["cost_per_order"], "meets_demand": bool(ok)}
    total_steps = total * B
    summary = {"scenarios": B, "simulated_hours_each": hours, "wall_seconds": round(wall, 1), "backend": backend, "kind": kind,
               "scenario_steps_per_s": round(total_steps / wall), "robot_steps_per_s": round(total_steps / wall * sum(fleets) / len(fleets)),
               "simulated_robot_hours": round(sum(c[0] for c in combos) * hours, 1), "best_fleet": best}
    ctx.write_json("summary", "sweep_summary.json", summary)
    ctx.telemetry("sweep", {"phase": "done", "rows": rows, "summary": summary, "backend": backend, "kind": kind})
    ctx.log("%d scenarios in %.1f s on %s: %s scenario-steps/s." % (B, wall, backend, format(summary["scenario_steps_per_s"], ",")))
    for r, b in best.items():
        ctx.log("At %s orders/h: %d robots (%s orders/h, %.2f per order)%s." % (r, b["fleet"], b["orders_h"], b["cost_per_order"], "" if b["meets_demand"] else ", demand not met by any fleet tried"))
    return summary


def snapshot(F):
    return {"done": F.done.clone(), "time": F.done_time.clone(), "hist": F.done_hist.clone(), "busy": F.busy_ticks.clone(),
            "robot": F.robot_ticks.clone(), "wait": F.wait_ticks.clone()}


def summarise(F, base, combos, fleets, rates, cost_h, steps):
    """Per fleet size and order rate, averaged over the seeds."""
    import torch
    cur = snapshot(F)
    if base is not None:
        cur = {k: cur[k] - base[k] for k in cur}
    hours = max(steps, 1) * TICK_S / 3600.0
    done = cur["done"].cpu().tolist()
    ttime = cur["time"].cpu().tolist()
    hist = cur["hist"].cpu()
    busy = (cur["busy"] / cur["robot"].clamp(min=1)).cpu().tolist()
    wait = (cur["wait"] / cur["robot"].clamp(min=1)).cpu().tolist()
    backlog = (F.q_tail - F.q_head).cpu().tolist()
    groups = {}
    for i, (f, r, s) in enumerate(combos):
        groups.setdefault((f, r), []).append(i)
    rows = []
    for r in rates:
        for f in fleets:
            ix = groups[(f, r)]
            d = sum(done[i] for i in ix) / len(ix)
            per_h = d / hours
            h = hist[ix].sum(0)
            cum = torch.cumsum(h, 0)
            p95 = float((cum < 0.95 * cum[-1]).sum()) * 15 + 7.5 if float(cum[-1]) > 0 else 0.0
            rows.append({"fleet": f, "order_rate": int(r), "orders_h": round(per_h, 1),
                         "served_pct": min(100.0, round(100.0 * per_h / r, 1)) if r else 0.0,
                         "avg_order_s": round(sum(ttime[i] for i in ix) / max(1e-6, sum(done[i] for i in ix)), 1),
                         "p95_order_s": round(p95, 0),
                         "utilization": round(sum(busy[i] for i in ix) / len(ix), 3),
                         "waiting_pct": round(100 * sum(wait[i] for i in ix) / len(ix), 1),
                         "backlog": round(sum(backlog[i] for i in ix) / len(ix), 1),
                         "cost_per_order": round(f * cost_h / per_h, 3) if per_h > 0 else None})
    return rows
