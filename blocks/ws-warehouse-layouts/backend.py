# ── EsaSim block ──────────────────────────────────────────────────────
# Warehouse layouts (ws-warehouse-layouts) · version 1 · machine block, Python: def run(ctx)
# Which layout works best in the same building? Several warehouse layouts with the same robots, the very same orders and incidents, simulated and compared: throughput, order time, metres driven, waiting
# Workspace: Gianluca De Novi's workspace · Author: Gianluca De Novi
# Saved: 2026-11-08
#
# Inputs   ctx.inputs["id"] is a list of files: .path .name .size .read_text() .read_json()
#   (none)
# Outputs  ctx.output("id", "name.ext") is the path to write; ctx.write_json / ctx.write_text
#   results     Table (csv)               Results · layouts.csv: one row per layout (throughput, order time, metres per item, waiting, storage…)
#   chart       Table (csv)               For a chart · layouts_chart.csv: orders per hour, order time, metres per item and waiting by layout
#   plans       Files (png, json)         Plans · A plan of each layout from above, coloured where robots waited (PNG), and its layout (JSON)
#   summary     Metrics (json)            Summary · The best layout for throughput, order time and driving, and each layout against the first
#   telemetry   Live telemetry            ctx.telemetry("channel", data) while it runs
# Settings ctx.params["key"]
#   layouts     textarea  Layouts = "Today: blocks=5 stations=8\n3 long blocks: blocks=3\n9 short blocks: blocks=9\nStations …
#   robots      number    Robots = 40
#   order_rate  number    Orders per hour = 500
#   seeds       number    Seeds per layout = 3
#   hours       number    Simulated hours = 2
#   warmup_min  number    Warm-up (simulated minutes, not counted) = 10
#   accelerator select    Accelerator = "auto" of auto | CPU | NVIDIA GPU | Tenstorrent
#   rack_pairs  number    Rack pairs (sets the hall's width) = 20
#   rack_blocks number    Rack blocks of the reference hall = 5
#   rack_len    number    Rack length of the reference hall (m) = 8
#   stations    number    Pack-out stations (unless a layout says) = 8
#   pick_s      number    Seconds to pick an item = 10
#   station_s   number    Seconds to unload at the station = 15
#   robot_speed number    Robot speed (m/s) = 1.2
#   battery_h   number    Hours on a charge = 8
#   charge_min  number    Minutes to charge from empty = 60
#   charge_below number    Go to charge below (%) = 25
#   incidents_h number    Incidents per hour = 2
#   fault_share number    Robot faults (% of incidents) = 40
#   response_min number    Minutes until someone comes = 3
#   clear_min   number    Minutes to clean up a spill = 4
#   repair_min  number    Minutes to repair a robot = 8
#   seed        number    Random seed = 1
# Runs on  Any machine, NVIDIA GPU, Tenstorrent. Return a dict to fill the "result" output.
# Packages torch[cuda], scipy, pillow (installed by the worker with pip when missing)
# EsaSim rewrites these lines from the block's definition each time it is saved: change the definition, not them.
# ── end of EsaSim block header ────────────────────────────────────────

"""Warehouse layouts: which layout works best in the same building? Every layout gets the same hall, the same robots,
the very same orders and the same incidents, for the same simulated hours, on this machine's CPU, NVIDIA GPU or
Tenstorrent cards (Accelerator). Gives throughput, order time, metres driven per item, waiting, storage and a plan
of each layout with the places where robots waited."""
import json
import time

# ---- Warehouse fleet engine (shared by Warehouse fleet, Fleet-size sweep and Warehouse layouts) -----------------
#
# A picking warehouse on a 1 m grid, worked by mobile robots and pickers (the collaborative way: the robot brings a
# tote to the pick faces, a picker puts the items in, the robot takes them to a pack-out station). Rack rows run
# north-south with one-way aisles between them, cross-aisles between rack blocks and two-lane highways at both ends;
# pack-out stations at the south wall (or at both ends), each with an in-lane (the queue) and an out-lane; docks with
# chargers along the walls. The layout is a setting: how many rack blocks (more cross-aisles: shorter trips, less
# storage), how many stations and where, and where the popular products sit (slotting).
# An order has 1 to 3 lines: the robot drives to each pick face, waits while the item goes into its tote, then
# drives to the least busy station, where the tote is emptied. Batteries run down as robots drive and work; a robot
# low on charge finishes its order, goes to its dock and charges; idle robots charge at their dock between orders.
# Times and speeds default to those of real warehouse robots (MiR100: 1.5 m/s at most, about 10 h per charge, 2-3 h
# to charge; Locus Origin: about 8 h, 50 min to charge; 8-12 s per pick).
# Incidents: a spill or a dropped item closes an aisle cell, a robot stops with a fault where it is; each waits for a
# person (response time) who then clears it (clearing or repair time); routes are planned again around it.
#
# The engine runs B scenarios side by side (B = 1 for the live demo, hundreds for a sweep), each with up to N robots,
# as tensors: every step is the same dense operations on all robots of all scenarios, on a CPU, an NVIDIA GPU (CUDA)
# or Tenstorrent cards. Routes come from the distance of every cell to every target, planned with what the machine
# does best: breadth-first search in compiled code on a CPU (SciPy), wavefront relaxation on an NVIDIA GPU, tile
# matmuls on the Tensix cores of Tenstorrent cards (TT-NN); and again whenever an aisle is blocked.
# Orders (arrival times and lines) come from their own random stream, so two layouts given the same seed get the very
# same orders, and so do the incidents (when, what kind, how long); only where they happen depends on the layout.

E, N_, W_, S_ = 0, 1, 2, 3
DX = (1, 0, -1, 0)
DY = (0, 1, 0, -1)
MODE_IDLE, MODE_TO_PICK, MODE_PICKING, MODE_TO_STATION, MODE_AT_STATION, MODE_TO_CHARGE, MODE_CHARGING, MODE_OFF = range(8)
MODE_FAULT = 8        # shown for a robot stopped by a fault (it keeps its task and goes on once repaired)
CELL_M = 1.0          # one grid cell, in metres
LAYOUT_KEYS = ("blocks", "stations", "stations_at", "slotting", "bay")


def fmt_time(s):
    s = int(round(max(0.0, s)))
    return "%d:%02d" % (s // 60, s % 60) if s < 3600 else "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)


class Layout:
    """The warehouse: grid cells, allowed moves (one-way traffic), racks, pick faces, stations and docks.
    pairs: double rack rows across the hall (3 m each); blocks: rack blocks from front to back, with a cross-aisle
    between two blocks; depth: metres from the first to the last rack row (default: blocks of rack_len); stations:
    pack-out stations, at the south wall or split between both ends (stations_at); slotting: abc (popular products
    near the stations) or random."""

    def __init__(self, pairs=20, blocks=5, rack_len=8, stations=8, bay=2, depth=None, stations_at="south",
                 slotting="abc", name=""):
        blocks = max(1, int(blocks))
        both = str(stations_at).strip().lower().startswith("both")
        self.stations_at = "both" if both else "south"
        self.slotting = "random" if str(slotting).strip().lower().startswith("rand") else "abc"
        self.name = str(name or "")
        depth = int(depth) if depth is not None else blocks * (int(rack_len) + 1) - 1
        rows = depth - (blocks - 1)                          # rack rows; the others are cross-aisles
        if rows < 2 * blocks:
            raise ValueError("%d rack blocks do not fit in %d m from front to back" % (blocks, depth))
        lens = [rows // blocks + (1 if b < rows % blocks else 0) for b in range(blocks)]
        bay = max(1, int(bay))
        self.pairs, self.blocks, self.bay, self.depth, self.rack_len = pairs, blocks, bay, depth, max(lens)
        W = 3 * pairs + 5                                   # x: margin, dock column, aisles and rack pairs, dock column, margin
        y_store = 6                                         # rack rows start here
        y_top = y_store + depth                             # first top highway row
        H = y_top + (6 if both else 3)                      # top highways (2) + dock row, or + queues and stations
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
        # storage: rack blocks, cross-aisles between them, one-way aisles between rack pairs
        starts, y = [], y_store
        for ln in lens:
            starts.append(y)
            y += ln + 1
        cross = [s + ln for s, ln in zip(starts[:-1], lens[:-1])]
        self.cross, self.block_rows = cross, [[s, ln] for s, ln in zip(starts, lens)]
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
        offset = {}
        for k in range(pairs):
            for y0, ln in zip(starts, lens):
                for side, x in enumerate((3 + 3 * k, 4 + 3 * k)):
                    racks.append({"x": x, "y": y0, "len": ln, "face": W_ if side == 0 else E, "id": len(racks)})
                    for y in range(y0, y0 + ln):
                        kind[y][x] = "rack"
                        offset[y] = y - y0
        # pick faces: aisle cells beside a rack, one per bay (a shelf section of `bay` metres)
        picks = []
        for x in aisles:
            for y in range(y_store, y_top):
                if kind[y][x] == "aisle" and y in offset and offset[y] % bay == bay // 2:
                    near = [r for r in racks if r["y"] <= y < r["y"] + r["len"] and abs(r["x"] - x) == 1]
                    if near:
                        picks.append((x, y, [r["id"] for r in near]))
        # stations, south: in-lane south from the highway (y=4) to the station (y=1), out-lane north back to it;
        # north (stations_at=both): the same, mirrored, beyond the north highway
        per_wall = (W - 4) // 3
        n = max(1, int(stations))
        n_south = min(per_wall, (n + 1) // 2 if both else n)
        n_north = min(per_wall, n - n_south) if both else 0
        stations_, queues, sides, docks = [], [], [], []

        def spread(m):
            return [round(2 + (W - 6) * (i + 0.5) / m) for i in range(m)] if m else []

        for x in spread(n_south):
            for y in (3, 2):
                kind[y][x] = "queue"; allow(x, y, S_)
            allow(x, 4, S_)
            kind[1][x] = "station"; allow(x, 1, E)
            kind[1][x + 1] = "exit"; allow(x + 1, 1, N_)
            for y in (2, 3):
                kind[y][x + 1] = "exit"; allow(x + 1, y, N_)
            stations_.append((x, 1)); queues.append([(x, 2), (x, 3)]); sides.append("S")
        ys = y_top + 4
        for x in spread(n_north):
            for y in (y_top + 2, y_top + 3):
                kind[y][x] = "queue"; allow(x, y, N_)
            allow(x, y_top + 1, N_)
            kind[ys][x] = "station"; allow(x, ys, E)
            kind[ys][x + 1] = "exit"; allow(x + 1, ys, S_)
            for y in (y_top + 2, y_top + 3):
                kind[y][x + 1] = "exit"; allow(x + 1, y, S_)
            stations_.append((x, ys)); queues.append([(x, y_top + 2), (x, y_top + 3)]); sides.append("N")
        # docks: north wall (or between the north stations), west and east walls (from the outer aisles), south wall
        # between the stations
        def between(xs):
            used = set(xs) | set(x + 1 for x in xs)
            return [x for x in range(2, W - 2) if x not in used and x - 1 not in used and x + 1 not in used]

        south_x = [x for (x, _), s in zip(stations_, sides) if s == "S"]
        north_x = [x for (x, _), s in zip(stations_, sides) if s == "N"]
        if both:
            for x in between(north_x):
                docks.append((x, y_top + 2, S_))
        else:
            for x in range(2, W - 2):
                if x % 3 == 2:                              # keep the aisle mouths free
                    continue
                docks.append((x, H - 1, S_))
        for y in range(y_store, y_top):
            if kind[y][2] in ("aisle", "cross"):
                docks.append((1, y, E))
            if kind[y][aisles[-1]] in ("aisle", "cross"):
                docks.append((W - 2, y, W_))
        for x in between(south_x):
            docks.append((x, 3, N_))
        for (x, y, out) in docks:
            kind[y][x] = "dock"
            allow(x, y, out)
            bx, by = x + DX[out], y + DY[out]
            allow(bx, by, (out + 2) % 4)                    # in from the lane beside it
        self.kind, self.moves = kind, moves
        self.racks, self.picks, self.stations, self.docks = racks, picks, stations_, docks
        self.queues, self.station_sides = queues, sides
        # targets: picks, then stations, then docks
        self.targets = [(x, y) for x, y, _ in picks] + list(stations_) + [(x, y) for x, y, _ in docks]
        self.n_picks, self.n_stations, self.n_docks = len(picks), len(stations_), len(docks)
        self.rack_m = sum(r["len"] for r in racks)
        self.blocked = set()

    # -- layouts from a line of text -----------------------------------------------------------------------------
    @staticmethod
    def parse(spec):
        """'Name: blocks=3 stations=8 stations_at=both slotting=random' -> (name, {key: value})."""
        import re
        s = str(spec or "").strip()
        name = ""
        if ":" in s:
            name, s = s.split(":", 1)
        opts = {}
        for part in re.split(r"[\s,;]+", s.strip()):
            if not part:
                continue
            if "=" not in part:
                raise ValueError("'%s' is not key=value (keys: %s)" % (part, ", ".join(LAYOUT_KEYS)))
            k, v = part.split("=", 1)
            k = k.strip().lower()
            if k not in LAYOUT_KEYS:
                raise ValueError("unknown layout setting '%s' (keys: %s)" % (k, ", ".join(LAYOUT_KEYS)))
            opts[k] = v.strip()
        return name.strip(), opts

    @classmethod
    def variant(cls, spec, pairs=20, blocks=5, rack_len=8, stations=8, bay=2):
        """A layout in the same hall as Layout(pairs, blocks, rack_len, stations): same width and depth of the
        building, with the settings of `spec` changed."""
        base = cls(pairs=pairs, blocks=blocks, rack_len=rack_len, stations=stations, bay=bay)
        name, o = cls.parse(spec)
        at = o.get("stations_at", "south")
        top = 6 if str(at).lower().startswith("both") else 3
        depth = base.H - 6 - top
        L = cls(pairs=pairs, blocks=int(o.get("blocks", blocks)), stations=int(o.get("stations", stations)),
                bay=int(o.get("bay", bay)), depth=depth, stations_at=at, slotting=o.get("slotting", "abc"),
                name=name or spec)
        return L

    def summary(self):
        return {"name": self.name, "blocks": self.blocks, "rack_len": self.rack_len, "cross_aisles": len(self.cross),
                "stations": self.n_stations, "stations_at": self.stations_at, "slotting": self.slotting,
                "pick_faces": self.n_picks, "rack_m": self.rack_m, "docks": self.n_docks,
                "width_m": self.W, "depth_m": self.H, "area_m2": self.W * self.H}

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
        """Where orders go. abc: pick faces near the stations are asked for more often; random: all alike."""
        import math
        w = []
        span = max(1, self.y_top - 1 - self.y_store)
        for x, y, _ in self.picks:
            if self.slotting == "random":
                w.append(1.0)
                continue
            d = (y - self.y_store) / span
            if self.stations_at == "both":
                d = 2 * min(d, 1 - d)
            w.append(math.exp(-2.2 * d) * (1.0 + 0.6 * math.cos(x * 1.7) ** 2))
        s = sum(w)
        return [v / s for v in w]

    def check(self, blocked=None, targets=None):
        """Targets (default: all) that cannot reach a station or be reached from it, with `blocked` cells closed
        (default: none). Empty when the roads hold together."""
        from collections import deque
        blocked = set() if blocked is None else set(blocked)
        nxt = self.neighbours(blocked)
        start = self.idx(*self.stations[0])
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
        targets = self.targets if targets is None else targets
        return [t for t in targets if tuple(t) not in blocked and (self.idx(*t) not in seen or self.idx(*t) not in back)]

    def cuts_off(self, cells):
        """True when closing `cells` (with what is closed already) would cut a station or a dock off."""
        return bool(self.check(set(self.blocked) | set(cells), self.targets[self.n_picks:]))

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
        d = {"format": "esasim.warehouse/1", "cell_m": CELL_M, "w": self.W, "h": self.H,
             "kinds": "".join(code[self.kind[y][x]] for y in range(self.H) for x in range(self.W)),
             "moves": "".join(dirs),
             "racks": [[r["x"], r["y"], r["len"], r["face"]] for r in self.racks],
             "stations": [list(s) for s in self.stations], "station_sides": self.station_sides,
             "queues": [[list(c) for c in q] for q in self.queues], "docks": [list(d) for d in self.docks],
             "aisles": self.aisles, "cross": self.cross, "store": [self.y_store, self.y_top],
             "targets": len(self.targets), "picks": self.n_picks,
             "blocked": sorted([list(b) for b in self.blocked])}
        d["layout"] = self.summary()
        return d

    def plan(self, path, title="", lines=(), heat=None, scale=8):
        """A picture of the layout from above (PNG): racks, aisles, stations, docks, and where robots waited (heat,
        one value per cell)."""
        from PIL import Image, ImageDraw, ImageFont
        W, H, s, top = self.W, self.H, scale, 30 + 16 * len(lines)
        img = Image.new("RGB", (W * s + 20, H * s + top + 10), (15, 19, 26))
        dr = ImageDraw.Draw(img)
        col = {"wall": (15, 19, 26), "highway": (58, 64, 74), "cross": (52, 58, 68), "aisle": (46, 52, 62),
               "rack": (200, 160, 60), "queue": (40, 90, 120), "station": (56, 189, 248), "exit": (40, 70, 90),
               "dock": (52, 160, 120)}
        hv = None
        if heat is not None:
            top_v = max(max(heat), 1e-9)
            hv = [v / top_v for v in heat]
        for y in range(H):
            for x in range(W):
                k = self.kind[y][x]
                c = col[k]
                if hv is not None and k not in ("rack", "wall") and hv[y * W + x] > 0.04:
                    c = heat_rgb(hv[y * W + x] ** 0.5)
                X, Y = 10 + x * s, top + (H - 1 - y) * s
                dr.rectangle([X, Y, X + s - 1, Y + s - 1], fill=c)
        try:
            font = ImageFont.load_default(size=14)
        except TypeError:
            font = ImageFont.load_default()
        dr.text((10, 6), title or self.name, fill=(235, 238, 242), font=font)
        for i, ln in enumerate(lines):
            dr.text((10, 24 + 16 * i), ln, fill=(170, 178, 190), font=font)
        img.save(path)
        return path


def heat_rgb(v):
    """Blue (little) -> yellow -> orange -> red (a lot), v in 0..1."""
    stops = [(0.0, (37, 99, 235)), (0.4, (250, 204, 21)), (0.7, (249, 115, 22)), (1.0, (220, 38, 38))]
    v = min(1.0, max(0.0, v))
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if v <= b:
            u = (v - a) / (b - a)
            return tuple(int(ca[i] + (cb[i] - ca[i]) * u) for i in range(3))
    return stops[-1][1]


class TTPlanner:
    """Route planning on Tenstorrent cards with TT-NN, the cards' own library: the distance fields of every target
    as tile matmuls and element-wise operations on the Tensix cores. A robot's next cell east is read through a
    shift matrix (D @ P), north and south through the transposed grid; a move that is not allowed adds a large
    number; then D = min(D, neighbour + 1) until nothing changes. In float32: routes in a large hall are longer than
    the 256 steps bfloat16 counts exactly. `ops` is TT-NN on the cards, or the same arithmetic in PyTorch to check
    it."""
    INF = 100000.0

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
    """TT-NN on a Tenstorrent card: tensors in float32 tiles in the card's memory."""

    def __init__(self, ttnn, device):
        self.tt, self.dev = ttnn, device

    def up(self, t):
        import torch
        return self.tt.from_torch(t.to(torch.float32), dtype=self.tt.float32, layout=self.tt.TILE_LAYOUT, device=self.dev)

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


class TorchOps:
    """The same operations in PyTorch on the CPU, to check the Tenstorrent planner."""

    def up(self, t):
        import torch
        return t.to(torch.float32)

    def down(self, x):
        return x.float()

    def matmul(self, a, b):
        return a @ b

    def add(self, a, b):
        return a + b

    def add_scalar(self, a, s):
        return a + s

    def minimum(self, a, b):
        import torch
        return torch.minimum(a, b)

    def transpose(self, a):
        return a.transpose(-2, -1).contiguous()


def cpu_distances(layout, tgt_cells):
    """[T, C + 1] float32: steps from every cell to every target, by breadth-first search in compiled code (SciPy's
    csgraph) over the reversed one-way roads. None when SciPy is missing."""
    try:
        import numpy as np
        from scipy.sparse import csr_matrix
        from scipy.sparse.csgraph import shortest_path
    except ImportError:
        return None
    import torch
    C = layout.C
    src, dst = [], []
    for c, row in enumerate(layout.neighbours()):
        for n in row:
            if n < C:
                src.append(n); dst.append(c)                        # reversed: from the next cell back to this one
    g = csr_matrix((np.ones(len(src)), (src, dst)), shape=(C, C))
    d = shortest_path(g, method="D", directed=True, unweighted=True, indices=list(tgt_cells))
    d[~np.isfinite(d)] = 1e6
    D = torch.from_numpy(d.astype(np.float32))
    return torch.cat([D, torch.full((len(tgt_cells), 1), 1e6)], 1)


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
    """B warehouses side by side, each with up to N robots (fleet[b] of them working), as tensors on the backend's
    device. Times in seconds, speed in metres per second, battery as a share of a full charge."""

    def __init__(self, layout, B, N, backend, seed=1, pick_s=10.0, station_s=15.0, speed=1.2, lines=(0.5, 0.3, 0.2),
                 battery_h=8.0, charge_min=60.0, low=0.25, full=0.95, queue=1024):
        import torch
        self.L, self.B, self.N, self.dev, self.xm, self.tt = layout, B, N, backend.device, backend.xm, backend.tt
        self.kind = backend.kind
        dev = self.dev
        self.T = len(layout.targets)
        self.C = layout.C
        self.speed = max(0.2, float(speed))
        self.tick = CELL_M / self.speed                                    # one step: a robot moves one cell, or turns
        self.pick_ticks = max(1, round(pick_s / self.tick))
        self.station_ticks = max(1, round(station_s / self.tick))
        self.drain_move = self.tick / (max(0.5, battery_h) * 3600.0)       # share of a charge used per step on the move
        self.drain_still = self.drain_move * 0.35                          # waiting, picking, at the station
        self.charge_step = self.tick / (max(5.0, charge_min) * 60.0)       # share of a charge gained per step on the dock
        self.low, self.full = float(low), float(full)
        self.Q = queue
        torch.manual_seed(seed)
        self.g_orders = torch.Generator().manual_seed(int(seed) * 1000003 + 17)   # orders: the same for every layout
        self.lower = torch.tril(torch.ones(N, N, dtype=torch.bool), diagonal=-1).to(dev)     # [i, j]: j has priority over i
        tgt_cells = [layout.idx(x, y) for x, y in layout.targets]
        self.tgt_cell = torch.tensor(tgt_cells + [self.C], dtype=torch.long, device=dev)
        pop = torch.tensor(layout.popularity(), dtype=torch.float32)
        self.pop_cdf = torch.cumsum(pop, 0).to(dev)
        self.pop_cdf[-1] = 1.0001
        lp = torch.tensor(list(lines), dtype=torch.float32)
        self.lines_cdf = (torch.cumsum(lp / lp.sum(), 0)).to(dev)
        self.lines_cdf[-1] = 1.0001
        self.flowing = torch.tensor([layout.kind[c // layout.W][c % layout.W] == "highway" for c in range(self.C)] + [False], device=dev)
        # cells only a robot going there may enter: a dock (its owner) and a station's queue (robots for that station)
        owner = [-1] * (self.C + 1)
        for i, (x, y) in enumerate(layout.targets):
            if i >= layout.n_picks:
                owner[layout.idx(x, y)] = i
        for i, q in enumerate(layout.queues):
            for (qx, qy) in q:
                owner[layout.idx(qx, qy)] = layout.n_picks + i
        self.owner = torch.tensor(owner, dtype=torch.long, device=dev)
        self.station_ids = torch.arange(layout.n_picks, layout.n_picks + layout.n_stations, device=dev)
        self.dock_ids = torch.arange(layout.n_picks + layout.n_stations, self.T, device=dev)
        self.timing = {}
        self.user_blocked = set(layout.blocked)
        self.replan()
        # state
        z = lambda dt=torch.long: torch.zeros(B, N, dtype=dt, device=dev)
        self.pos = torch.full((B, N), self.C, dtype=torch.long, device=dev)
        self.head, self.mode, self.tgt, self.timer, self.wait = z(), z(), z(), z(), z()
        self.lines_left, self.items = z(), z()
        self.battery = torch.full((B, N), 0.9, dtype=torch.float32, device=dev)
        self.order_t = z(torch.float32)
        self.home = z()
        self.active = z(torch.bool)
        self.leaving = z(torch.bool)
        self.fault = z(torch.bool)
        self.q_t = torch.zeros(B, queue, dtype=torch.float32, device=dev)
        self.q_lines = torch.ones(B, queue, dtype=torch.long, device=dev)
        self.q_head = torch.zeros(B, dtype=torch.long, device=dev)
        self.q_tail = torch.zeros(B, dtype=torch.long, device=dev)
        self.rate = torch.zeros(B, dtype=torch.float32, device=dev)            # orders per hour
        self.t = 0.0
        self.steps = 0
        # statistics
        f = lambda: torch.zeros(B, dtype=torch.float32, device=dev)
        self.done, self.lines_done, self.done_time, self.moved = f(), f(), f(), f()
        self.done_hist = torch.zeros(B, 64, dtype=torch.float32, device=dev)  # order times, 15 s bins
        self.busy_ticks, self.robot_ticks, self.wait_ticks, self.charge_ticks, self.fault_ticks, self.dropped = f(), f(), f(), f(), f(), f()
        self.heat = torch.zeros(B, self.C + 1, dtype=torch.float32, device=dev) if B == 1 else None
        self.heat_total = torch.zeros(self.C + 1, dtype=torch.float32, device=dev)    # where robots of scenario 0 waited
        self.events = []
        self.set_incidents(0)
        self.set_fleet([0] * B)

    # -- routes --------------------------------------------------------------------------------------------------
    def replan(self):
        """Steps from every cell to every target along the allowed moves, planned on this machine's accelerator.
        Run again when the roads change."""
        import time
        import torch
        t0 = time.perf_counter()
        L, C, T, dev = self.L, self.C, self.T, self.dev
        nxt = torch.tensor(L.neighbours(), dtype=torch.long, device=dev)                  # [C, 4]
        self.nxt = torch.cat([nxt, torch.full((1, 4), C, dtype=torch.long, device=dev)])  # row C: nowhere
        INF = 1e6
        D, how, it = None, "", 0
        if self.tt is not None:                                                           # Tensix cores, TT-NN
            D, how, it = self.tt.distances(L, self.tgt_cell[:T].cpu().tolist()), "TT-NN tile matmuls", self.tt.iterations
        elif dev.type == "cpu":                                                           # CPU: compiled BFS
            D = cpu_distances(L, self.tgt_cell[:T].cpu().tolist())
            how = "breadth-first search (SciPy)" if D is not None else ""
        if D is None:                                                                     # GPU: wavefront relaxation
            D = torch.full((T, C + 1), INF, dtype=torch.float32, device=dev)
            D[torch.arange(T, device=dev), self.tgt_cell[:T]] = 0.0
            flat = self.nxt[:C].reshape(-1)                                                # [C*4]
            changed = True
            while changed and it < 4 * C:
                for _ in range(16):
                    cand = D[:, flat].reshape(T, C, 4).amin(2) + 1.0
                    newD = torch.cat([torch.minimum(D[:, :C], cand), D[:, C:]], 1)
                    if self.xm is not None:
                        self.xm.mark_step()
                    it += 1
                    last, D = D, newD
                changed = bool((last != D).any().item())
            how = "wavefront relaxation"
        self.D = D.to(dev)
        self.reach = (self.D[:, :C] < INF / 2)
        if dev.type == "cuda":
            torch.cuda.synchronize()
        ms = (time.perf_counter() - t0) * 1000
        self.timing.update({"replan_ms": ms, "replan_iterations": it, "replan_how": how})
        return ms

    # -- fleet size and orders -----------------------------------------------------------------------------------
    def set_fleet(self, sizes):
        """Robots 0..sizes[b]-1 work in scenario b. New robots start at their docks; robots taken away finish their
        order first, then park at their dock and leave."""
        import math
        import torch
        dev = self.dev
        n_d = self.L.n_docks
        size = torch.tensor(sizes, dtype=torch.long, device=dev).clamp(0, min(self.N, n_d))
        ids = torch.arange(self.N, device=dev)[None, :].expand(self.B, -1)
        want = ids < size[:, None]
        step = next(s for s in (7, 5, 11, 13, 3, 1) if math.gcd(s, n_d) == 1)          # docks spread round the walls
        home_t = self.dock_ids[(ids * step) % n_d]
        new = want & ~self.active
        self.home = torch.where(new, home_t, self.home)
        self.pos = torch.where(new, self.tgt_cell[home_t], self.pos)
        dock_out = torch.tensor([d[2] for d in self.L.docks], dtype=torch.long, device=dev)
        self.head = torch.where(new, (dock_out[(ids * step) % n_d] + 2) % 4, self.head)
        self.mode = torch.where(new, torch.full_like(self.mode, MODE_IDLE), self.mode)
        self.tgt = torch.where(new, home_t, self.tgt)
        for name in ("timer", "wait", "lines_left", "items"):
            setattr(self, name, torch.where(new, torch.zeros_like(getattr(self, name)), getattr(self, name)))
        # robots arrive with the charge they have (as at the start of a shift): some go to charge first
        g = torch.Generator().manual_seed(int(self.g_orders.initial_seed()) + 7)
        fresh = (0.2 + 0.75 * torch.rand(self.B, self.N, generator=g)).to(dev)
        self.battery = torch.where(new, fresh, self.battery)
        self.leaving = self.active & ~want
        self.active = self.active | want
        self.size = size

    def set_rate(self, rates):
        import torch
        self.rate = torch.as_tensor(rates, dtype=torch.float32, device=self.dev).reshape(self.B).clone()

    def set_blocked(self, cells):
        """Close cells by hand (a pallet left in an aisle), on top of incidents: routes are planned again; orders for
        pick faces there wait."""
        self.user_blocked = set(tuple(c) for c in cells)
        return self._apply_blocked()

    def _apply_blocked(self):
        self.L.blocked = set(self.user_blocked) | set(tuple(i["cell"]) for i in self.incidents if i["closes"])
        ms = self.replan()
        self.retarget()
        return ms

    # -- incidents -----------------------------------------------------------------------------------------------
    def set_incidents(self, per_h=0.0, fault_share=0.4, response_min=3.0, clear_min=4.0, repair_min=8.0, seed=1):
        """Incidents at random (Poisson, per_h an hour): a spill or a dropped item closes an aisle cell, or (a
        fault_share of them) a working robot stops where it is. Each waits for a person (response_min on average)
        who then cleans up (clear_min) or repairs the robot (repair_min); times vary (gamma, shape 2). When, what and
        how long come from their own random stream (the same for every layout); where depends on the layout."""
        import random
        self.inc_rate = max(0.0, float(per_h))
        self.inc_fault_share = min(1.0, max(0.0, float(fault_share)))
        self.inc_resp, self.inc_clear, self.inc_repair = max(0.0, float(response_min)), max(0.1, float(clear_min)), max(0.1, float(repair_min))
        self.inc_rng = random.Random(int(seed) * 7919 + 3)
        self.cell_rng = random.Random(int(seed) * 104729 + 5)
        self.incidents = getattr(self, "incidents", [])
        self.inc_count = getattr(self, "inc_count", 0)
        self.inc_next = self.t + self.inc_rng.expovariate(self.inc_rate / 3600.0) if self.inc_rate > 0 else float("inf")

    def _gamma(self, mean):
        return self.inc_rng.gammavariate(2.0, mean / 2.0) * 60.0 if mean > 0 else 0.0

    def _event(self, text, **extra):
        e = dict({"t": round(self.t, 1), "text": text}, **extra)
        self.events.append(e)
        return e

    def drain_events(self):
        ev, self.events = self.events, []
        return ev

    def _incidents_step(self):
        t = self.t
        for inc in [i for i in self.incidents if t >= i["until"]]:            # cleared
            self.incidents.remove(inc)
            if inc["kind"] == "fault":
                self.fault[:, inc["robot"]] = False
                what = "Robot %d back at work after %s (technician %s, repair %s)" % (inc["robot"] + 1, fmt_time(t - inc["since"]), fmt_time(inc["help_at"] - inc["since"]), fmt_time(inc["until"] - inc["help_at"]))
            else:
                what = "Aisle at %s clear again after %s (response %s, cleaning %s)" % (list(inc["cell"]), fmt_time(t - inc["since"]), fmt_time(inc["help_at"] - inc["since"]), fmt_time(inc["until"] - inc["help_at"]))
            ms = self._apply_blocked() if inc["closes"] else 0.0
            self._event(what + (", routes planned again in %.0f ms" % ms if inc["closes"] else ""), kind="cleared", incident=inc["id"], minutes=round((t - inc["since"]) / 60, 2))
        while t >= self.inc_next:
            r = self.inc_rng
            fault = r.random() < self.inc_fault_share
            resp = self._gamma(self.inc_resp)
            work = self._gamma(self.inc_repair if fault else self.inc_clear)
            robot_u = r.random()
            self.inc_next += r.expovariate(self.inc_rate / 3600.0)
            if fault:
                self._start_fault(robot_u, resp, work)
            else:
                self._start_spill(resp, work)

    def _start_spill(self, resp, work):
        L, rng = self.L, self.cell_rng
        busy = set(self.pos[0].cpu().tolist()) if self.B == 1 else set()
        cand = [(x, y) for y in range(L.H) for x in range(L.W) if L.kind[y][x] in ("aisle", "cross") and (x, y) not in L.blocked]
        for _ in range(40):
            c = cand[rng.randrange(len(cand))]
            if L.idx(*c) in busy or L.cuts_off([c]):
                continue
            self.inc_count += 1
            inc = {"id": self.inc_count, "kind": "spill", "cell": c, "closes": True, "since": self.t,
                   "help_at": self.t + resp, "until": self.t + resp + work, "robot": -1}
            self.incidents.append(inc)
            ms = self._apply_blocked()
            self._event("Spill in the aisle at %s: closed, routes planned again in %.0f ms; someone is on the way" % (list(c), ms),
                        kind="incident", incident=inc["id"], cell=list(c))
            return inc
        return None

    def _start_fault(self, robot_u, resp, work):
        """A working robot stops where it is (in scenario 0 the next one that is driving, from a number drawn at
        random; the same robot number in the other scenarios)."""
        import torch
        moving = ((self.mode[0] == MODE_TO_PICK) | (self.mode[0] == MODE_TO_STATION)) & self.active[0] & ~self.fault[0]
        ids = torch.nonzero(moving).flatten().cpu().tolist()
        if not ids:
            return None
        start = int(robot_u * self.N)
        rid = min(ids, key=lambda i: (i - start) % self.N)
        cell = int(self.pos[0, rid])
        c = (cell % self.L.W, cell // self.L.W)
        closes = self.B == 1 and self.L.kind[c[1]][c[0]] in ("aisle", "cross", "highway") and not self.L.cuts_off([c])
        self.inc_count += 1
        inc = {"id": self.inc_count, "kind": "fault", "cell": c, "closes": closes, "since": self.t,
               "help_at": self.t + resp, "until": self.t + resp + work, "robot": rid}
        self.incidents.append(inc)
        self.fault[:, rid] = self.active[:, rid]
        ms = self._apply_blocked() if closes else 0.0
        self._event("Robot %d stopped with a fault at %s; a technician is on the way%s" % (rid + 1, list(c), (", routes planned around it in %.0f ms" % ms) if closes else ""),
                    kind="incident", incident=inc["id"], cell=list(c), robot=rid + 1)
        return inc

    def incidents_now(self):
        return [{"id": i["id"], "kind": i["kind"], "cell": list(i["cell"]), "since": round(i["since"], 1),
                 "help_at": round(i["help_at"], 1), "until": round(i["until"], 1), "robot": i["robot"] + 1 if i["robot"] >= 0 else None}
                for i in self.incidents]

    def _sample(self, u, cdf, top):
        return (u[:, :, None] >= cdf[None, None, :]).long().sum(2).clamp(max=top)

    def _new_pick(self, B, N, C):
        """A pick face for every robot, by popularity, among the faces reachable from where it is."""
        import torch
        pick = self._sample(torch.rand(B, N, device=self.dev), self.pop_cdf, self.L.n_picks - 1)
        ok = self.reach[pick, self.pos.clamp(max=C - 1)] & self.reach[self.station_ids[0], self.tgt_cell[pick]]
        return pick, ok

    # -- one step ------------------------------------------------------------------------------------------------
    def step(self):
        import torch
        B, N, C, dev = self.B, self.N, self.C, self.dev
        t, tick = self.t, self.tick
        full = lambda m: torch.full_like(self.mode, m)
        if self.incidents or t >= self.inc_next:
            self._incidents_step()
        frozen = self.fault
        # orders arrive (Poisson, as 4 Bernoulli draws per step) with 1-3 lines each, from the orders' own stream
        u = torch.rand(B, 8, generator=self.g_orders).to(dev)
        p = (self.rate * tick / 3600.0 / 4.0).clamp(max=1.0)
        arrivals = (u[:, :4] < p[:, None]).long()
        nl = self._sample(u[:, 4:], self.lines_cdf, self.lines_cdf.numel() - 1) + 1      # [B, 4]
        qpos = torch.arange(self.Q, device=dev)[None, :]
        for k in range(4):
            slot = (self.q_tail % self.Q)[:, None] == qpos
            write = slot & (arrivals[:, k:k + 1] > 0)
            self.q_t = torch.where(write, torch.full_like(self.q_t, t), self.q_t)
            self.q_lines = torch.where(write, nl[:, k:k + 1].expand(-1, self.Q), self.q_lines)
            self.q_tail = self.q_tail + arrivals[:, k]
        overflow = (self.q_tail - self.q_head - self.Q).clamp(min=0)
        self.dropped = self.dropped + overflow.float()
        self.q_head = self.q_head + overflow
        pending = self.q_tail - self.q_head
        # robots no longer wanted leave once parked at their dock
        at_home = self.pos == self.tgt_cell[self.home]
        gone = self.leaving & at_home & ((self.mode == MODE_IDLE) | (self.mode == MODE_CHARGING)) & ~frozen
        self.active = self.active & ~gone
        self.leaving = self.leaving & ~gone
        act = self.active
        self.pos = torch.where(gone, torch.full_like(self.pos, C), self.pos)
        # idle robots with enough charge take the oldest orders (lowest robot number first)
        idle = act & ~self.leaving & ~frozen & (self.mode == MODE_IDLE) & (self.battery >= self.low)
        rank = torch.cumsum(idle.long(), 1) - 1
        take = idle & (rank < pending[:, None])
        pick, ok = self._new_pick(B, N, C)
        take = take & ok
        q_idx = (self.q_head[:, None] + rank) % self.Q
        self.order_t = torch.where(take, torch.gather(self.q_t, 1, q_idx), self.order_t)
        self.tgt = torch.where(take, pick, self.tgt)
        self.mode = torch.where(take, full(MODE_TO_PICK), self.mode)
        self.lines_left = torch.where(take, torch.gather(self.q_lines, 1, q_idx), self.lines_left)
        self.items = torch.where(take, torch.zeros_like(self.items), self.items)
        self.q_head = self.q_head + take.long().sum(1)
        # arrivals at targets
        at = act & ~frozen & (self.pos == self.tgt_cell[self.tgt])
        start_pick = at & (self.mode == MODE_TO_PICK)
        self.mode = torch.where(start_pick, full(MODE_PICKING), self.mode)
        self.timer = torch.where(start_pick, torch.full_like(self.timer, self.pick_ticks), self.timer)
        start_st = at & (self.mode == MODE_TO_STATION)
        self.mode = torch.where(start_st, full(MODE_AT_STATION), self.mode)
        self.timer = torch.where(start_st, torch.full_like(self.timer, self.station_ticks), self.timer)
        start_ch = at & (self.mode == MODE_TO_CHARGE)
        self.mode = torch.where(start_ch, full(MODE_CHARGING), self.mode)
        dwell = act & ~frozen & ((self.mode == MODE_PICKING) | (self.mode == MODE_AT_STATION))
        self.timer = torch.where(dwell, self.timer - 1, self.timer)
        # an item picked: the next line of the order, or off to the least busy station
        picked = dwell & (self.mode == MODE_PICKING) & (self.timer <= 0)
        self.items = torch.where(picked, self.items + 1, self.items)
        self.lines_left = torch.where(picked, self.lines_left - 1, self.lines_left)
        self.lines_done = self.lines_done + picked.float().sum(1)
        more = picked & (self.lines_left > 0)
        pick2, ok2 = self._new_pick(B, N, C)
        more = more & ok2
        self.tgt = torch.where(more, pick2, self.tgt)
        self.mode = torch.where(more, full(MODE_TO_PICK), self.mode)
        to_st = picked & ~more
        heading = ((self.mode == MODE_TO_STATION) | (self.mode == MODE_AT_STATION)) & act
        load = (heading[:, :, None] & (self.tgt[:, :, None] == self.station_ids[None, None, :])).float().sum(1)   # [B, S]
        dist = self.D[self.station_ids][:, self.pos.clamp(max=C)].permute(1, 2, 0)                             # [B, N, S]
        st = self.station_ids[(dist + 6.0 * load[:, None, :]).argmin(2)]
        self.tgt = torch.where(to_st, st, self.tgt)
        self.mode = torch.where(to_st, full(MODE_TO_STATION), self.mode)
        # tote emptied at the station: the order is done
        served = dwell & (self.mode == MODE_AT_STATION) & (self.timer <= 0)
        took = torch.where(served, t - self.order_t, torch.zeros_like(self.order_t))
        self.done = self.done + served.float().sum(1)
        self.done_time = self.done_time + took.sum(1)
        bins = (took / 15.0).long().clamp(0, 63)
        self.done_hist = self.done_hist + (served[:, :, None] & (bins[:, :, None] == torch.arange(64, device=dev)[None, None, :])).float().sum(1)
        self.items = torch.where(served, torch.zeros_like(self.items), self.items)
        # after an order: low on charge -> to the dock to charge, else idle (waiting for an order, back at the dock)
        low = served & (self.battery < self.low)
        self.mode = torch.where(low, full(MODE_TO_CHARGE), torch.where(served, full(MODE_IDLE), self.mode))
        idle_low = act & ~frozen & (self.mode == MODE_IDLE) & (self.battery < self.low)
        self.mode = torch.where(idle_low, full(MODE_TO_CHARGE), self.mode)
        homeward = (self.mode == MODE_IDLE) | (self.mode == MODE_TO_CHARGE) | (self.mode == MODE_CHARGING)
        self.tgt = torch.where(homeward, self.home, self.tgt)
        # charging on the dock: full -> waiting for orders again; idle robots on their dock charge too
        on_dock = act & ~frozen & (self.pos == self.tgt_cell[self.home])
        charging = on_dock & ((self.mode == MODE_CHARGING) | (self.mode == MODE_IDLE))
        self.battery = torch.where(charging, (self.battery + self.charge_step).clamp(max=1.0), self.battery)
        done_charging = act & (self.mode == MODE_CHARGING) & (self.battery >= self.full)
        self.mode = torch.where(done_charging, full(MODE_IDLE), self.mode)
        # movement: the best next cell towards the target, turning first when needed
        moving = act & ~frozen & ((self.mode == MODE_TO_PICK) | (self.mode == MODE_TO_STATION) | (self.mode == MODE_IDLE) | (self.mode == MODE_TO_CHARGE)) & (self.pos != self.tgt_cell[self.tgt])
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
        cost = torch.where(stuck & (dirs == best) & taken, cost + 50.0, cost)      # stuck behind a robot: try another way
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
        # the battery runs down: more on the move than standing
        use = torch.where(move | turn, torch.full_like(self.battery, self.drain_move), torch.full_like(self.battery, self.drain_still))
        self.battery = torch.where(act & ~charging, (self.battery - use).clamp(min=0.0), self.battery)
        # statistics
        working = act & (self.mode >= MODE_TO_PICK) & (self.mode <= MODE_AT_STATION)
        self.busy_ticks = self.busy_ticks + working.float().sum(1)
        self.robot_ticks = self.robot_ticks + act.float().sum(1)
        self.wait_ticks = self.wait_ticks + blocked_now.float().sum(1)
        self.charge_ticks = self.charge_ticks + (act & ((self.mode == MODE_CHARGING) | (self.mode == MODE_TO_CHARGE))).float().sum(1)
        self.fault_ticks = self.fault_ticks + (act & frozen).float().sum(1)
        self.moved = self.moved + move.float().sum(1)
        self.heat_total = self.heat_total.index_add(0, self.pos[0], blocked_now[0].float())
        if self.heat is not None:
            self.heat = self.heat * 0.995
            self.heat = self.heat.index_add(1, self.pos[0], blocked_now.float())
        if self.xm is not None:
            self.xm.mark_step()
        self.t = t + tick
        self.steps += 1

    def retarget(self):
        """Robots going to a pick face that can no longer be reached take another place for that line."""
        import torch
        C = self.C
        bad = self.active & (self.mode == MODE_TO_PICK) & ~self.reach[self.tgt, self.pos.clamp(max=C - 1)]
        n = int(bad.sum())
        for _ in range(8):
            if not bool(bad.any()):
                break
            pick, ok = self._new_pick(self.B, self.N, C)
            self.tgt = torch.where(bad & ok, pick, self.tgt)
            bad = bad & ~ok
        return n

    # -- reading out ---------------------------------------------------------------------------------------------
    def snapshot(self, b=0):
        """Robots of scenario b: [cell, heading, mode, target cell, battery %, items in the tote] each
        (cell C = not on the floor; mode MODE_FAULT while stopped by a fault)."""
        import torch
        m = torch.where(self.fault[b], torch.full_like(self.mode[b], MODE_FAULT), self.mode[b])
        m = torch.where(self.active[b], m, torch.full_like(self.mode[b], MODE_OFF))
        pos = torch.where(self.active[b], self.pos[b], torch.full_like(self.pos[b], self.C))
        tc = self.tgt_cell[self.tgt[b]]
        bat = (self.battery[b] * 100).round().long()
        return torch.stack([pos, self.head[b], m, tc, bat, self.items[b]], 1).cpu().tolist()

    def stats(self):
        import torch
        busy = (self.busy_ticks / self.robot_ticks.clamp(min=1)).cpu()
        hours = max(self.t, 1e-6) / 3600.0
        done = self.done.cpu()
        lines = self.lines_done.cpu()
        return {"done": done.tolist(), "per_hour": (done / hours).tolist(), "lines": lines.tolist(),
                "avg_order_s": (self.done_time.cpu() / done.clamp(min=1)).tolist(),
                "utilization": busy.tolist(), "backlog": (self.q_tail - self.q_head).cpu().tolist(),
                "wait_share": (self.wait_ticks / self.robot_ticks.clamp(min=1)).cpu().tolist(),
                "charge_share": (self.charge_ticks / self.robot_ticks.clamp(min=1)).cpu().tolist(),
                "fault_share": (self.fault_ticks / self.robot_ticks.clamp(min=1)).cpu().tolist(),
                "m_per_line": (self.moved.cpu() * CELL_M / lines.clamp(min=1)).tolist(),
                "incidents": self.inc_count, "hist": self.done_hist.cpu().tolist()}


DEFAULT_LAYOUTS = """Today: blocks=5 stations=8
3 long blocks: blocks=3
9 short blocks: blocks=9
Stations at both ends: stations_at=both
Random slotting: slotting=random
4 stations: stations=4"""


def run(ctx):
    p = ctx.params
    hw = pick_device(p.get("accelerator", "auto"), ctx.log)
    try:
        return compare(ctx, p, hw)
    finally:
        hw.close()


def compare(ctx, p, hw):
    import torch
    base = dict(pairs=int(p.get("rack_pairs", 20)), blocks=int(p.get("rack_blocks", 5)), rack_len=int(p.get("rack_len", 8)),
                stations=int(p.get("stations", 8)))
    specs = [ln.strip() for ln in str(p.get("layouts") or DEFAULT_LAYOUTS).splitlines() if ln.strip() and not ln.strip().startswith("#")]
    layouts = []
    for i, spec in enumerate(specs[:12]):
        try:
            L = Layout.variant(spec, **base)
        except ValueError as e:
            raise RuntimeError("Layout %d (%s): %s" % (i + 1, spec, e))
        if not L.name:
            L.name = "Layout %d" % (i + 1)
        bad = L.check()
        if bad:
            raise RuntimeError("Layout %s leaves %d places out of reach." % (L.name, len(bad)))
        layouts.append(L)
    robots = max(1, int(p.get("robots", 40)))
    rate = max(1.0, float(p.get("order_rate", 500)))
    seeds = max(1, min(20, int(p.get("seeds", 3))))
    hours = max(0.1, min(24.0, float(p.get("hours", 2))))
    warm_min = max(0.0, float(p.get("warmup_min", 10)))
    seed = int(p.get("seed", 1))
    inc = dict(per_h=float(p.get("incidents_h", 2)), fault_share=float(p.get("fault_share", 40)) / 100.0,
               response_min=float(p.get("response_min", 3)), clear_min=float(p.get("clear_min", 4)), repair_min=float(p.get("repair_min", 8)))
    fleet_kw = dict(pick_s=float(p.get("pick_s", 10)), station_s=float(p.get("station_s", 15)), speed=float(p.get("robot_speed", 1.2)),
                    battery_h=float(p.get("battery_h", 8)), charge_min=float(p.get("charge_min", 60)), low=float(p.get("charge_below", 25)) / 100.0)
    backend, kind = hw.label, hw.kind
    hall = layouts[0]
    ctx.log("%d layouts in the same %d x %d m hall, %d robots, %d orders per hour, %d seeds x %.1f simulated hours each, on %s." % (
        len(layouts), hall.W, hall.H, robots, rate, seeds, hours, backend))
    ctx.telemetry("compare", {"phase": "start", "layouts": [L.summary() for L in layouts], "robots": robots, "order_rate": rate,
                              "seeds": seeds, "hours": hours, "backend": backend, "kind": kind})
    rows, t_all = [], time.time()
    for li, L in enumerate(layouts):
        n = min(robots, L.n_docks)
        # one simulation per seed (seed s of every layout gets the very same orders and incidents), each with its own
        # routes, so a closed aisle or a stopped robot is driven round as in the live block
        runs, t0, last, heat = [], time.time(), 0.0, None
        for k in range(seeds):
            L.blocked = set()
            F = Fleet(L, 1, n, hw, seed=seed + k, **fleet_kw)
            F.set_fleet([n])
            F.set_rate([rate])
            F.set_incidents(seed=seed + k, **inc)
            warm = int(warm_min * 60 / F.tick)
            steps = int(hours * 3600 / F.tick)
            total = warm + steps
            base_s = None
            for i in range(total):
                F.step()
                if i + 1 == warm:
                    base_s = snap(F)
                now = time.time()
                if now - last >= 1.0 or i + 1 == total:
                    last = now
                    done_share = (li + (k + (i + 1) / total) / seeds) / len(layouts)
                    ctx.progress(int(100 * done_share), "%s: seed %d of %d, %d%%" % (L.name, k + 1, seeds, int(100 * (i + 1) / total)))
            F.drain_events()
            runs.append((F, base_s))
            h = F.heat_total[:L.C].cpu()
            heat = h if heat is None else heat + h
        L.blocked = set()
        row = summarise(runs, L, steps * F.tick, rate, n)
        row["wall_s"] = round(time.time() - t0, 1)
        rows.append(row)
        heat = heat.tolist()
        lines = ["%s orders/h  ·  %s s per order  ·  %s m per item  ·  waiting %s%%" % (row["orders_h"], row["avg_order_s"], row["m_per_line"], row["waiting_pct"]),
                 "%d blocks (%d m racks), %d cross-aisles, %d stations (%s), %s slotting, %d pick faces" % (
                     L.blocks, L.rack_len, len(L.cross), L.n_stations, L.stations_at, L.slotting, L.n_picks)]
        L.plan(ctx.output("plans", "%02d_%s.png" % (li + 1, slug(L.name))), title="%d · %s" % (li + 1, L.name), lines=lines, heat=heat)
        ctx.write_json("plans", "%02d_%s.json" % (li + 1, slug(L.name)), L.describe())
        ctx.telemetry("compare", {"phase": "layout", "index": li + 1, "of": len(layouts), "row": row})
        ctx.log("%s: %s orders/h, %s s per order, %s m per item, waiting %s%%." % (L.name, row["orders_h"], row["avg_order_s"], row["m_per_line"], row["waiting_pct"]))
    cols = ["layout", "orders_h", "served_pct", "lines_h", "avg_order_s", "p95_order_s", "m_per_line", "utilization", "waiting_pct",
            "charging_pct", "fault_pct", "incidents", "backlog", "pick_faces", "rack_m", "blocks", "cross_aisles", "stations", "stations_at", "slotting", "robots"]
    ctx.write_text("results", "layouts.csv", "\n".join([",".join(cols)] + [",".join(csv_cell(r[c]) for c in cols) for r in rows]) + "\n")
    chart = ["layout,orders_h,avg_order_s,m_per_line,waiting_pct"] + ["%s,%s,%s,%s,%s" % (csv_cell(r["layout"]), r["orders_h"], r["avg_order_s"], r["m_per_line"], r["waiting_pct"]) for r in rows]
    ctx.write_text("chart", "layouts_chart.csv", "\n".join(chart) + "\n")
    ref = rows[0]
    best_tp = max(rows, key=lambda r: (r["orders_h"], -r["avg_order_s"]))
    best_time = min(rows, key=lambda r: r["avg_order_s"])
    best_travel = min(rows, key=lambda r: r["m_per_line"])
    summary = {"layouts": len(rows), "robots": robots, "order_rate": rate, "seeds": seeds, "simulated_hours_each": hours,
               "hall_m": [hall.W, hall.H], "backend": backend, "kind": kind, "wall_seconds": round(time.time() - t_all, 1),
               "best_throughput": best_tp["layout"], "fastest_orders": best_time["layout"], "least_travel": best_travel["layout"],
               "against_first": [{"layout": r["layout"], "orders_h_pct": pct(r["orders_h"], ref["orders_h"]),
                                  "avg_order_s_pct": pct(r["avg_order_s"], ref["avg_order_s"]), "m_per_line_pct": pct(r["m_per_line"], ref["m_per_line"]),
                                  "pick_faces_pct": pct(r["pick_faces"], ref["pick_faces"])} for r in rows]}
    keep_up = all(r["served_pct"] >= 98 for r in rows)
    summary["all_keep_up"] = keep_up
    if keep_up:
        ctx.log("Every layout keeps up with %d orders per hour; they differ in how long orders take and how far robots drive. "
                "Fastest orders: %s. Least driving: %s." % (rate, summary["fastest_orders"], summary["least_travel"]))
    else:
        ctx.log("Most orders per hour: %s. Fastest orders: %s. Least driving: %s." % (summary["best_throughput"], summary["fastest_orders"], summary["least_travel"]))
    ctx.write_json("summary", "layouts_summary.json", summary)
    ctx.telemetry("compare", {"phase": "done", "rows": rows, "summary": summary})
    return summary


def pct(a, b):
    return round(100.0 * (a - b) / b, 1) if b else None


def slug(s):
    import re
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "layout"


def csv_cell(v):
    s = str(v)
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


def snap(F):
    return {"done": F.done.clone(), "lines": F.lines_done.clone(), "time": F.done_time.clone(), "hist": F.done_hist.clone(),
            "busy": F.busy_ticks.clone(), "robot": F.robot_ticks.clone(), "wait": F.wait_ticks.clone(), "charge": F.charge_ticks.clone(),
            "fault": F.fault_ticks.clone(), "moved": F.moved.clone()}


def summarise(runs, L, seconds, rate, robots):
    """One layout, over its seeds (after the warm-up)."""
    import torch
    cur = None
    for F, base in runs:
        c = snap(F)
        if base is not None:
            c = {k: c[k] - base[k] for k in c}
        cur = c if cur is None else {k: cur[k] + c[k] for k in c}
    hours = max(seconds, 1.0) / 3600.0
    S = len(runs)
    s = lambda k: float(cur[k].sum())
    done, lines = s("done"), s("lines")
    rt = max(s("robot"), 1.0)
    h = cur["hist"].sum(0)
    cum = torch.cumsum(h, 0)
    p95 = float((cum < 0.95 * cum[-1]).sum()) * 15 + 7.5 if float(cum[-1]) > 0 else 0.0
    per_h = done / S / hours
    return {"layout": L.name, "orders_h": round(per_h, 1), "served_pct": min(100.0, round(100.0 * per_h / rate, 1)),
            "lines_h": round(lines / S / hours, 1), "avg_order_s": round(s("time") / max(done, 1e-6), 1), "p95_order_s": round(p95, 0),
            "m_per_line": round(s("moved") * CELL_M / max(lines, 1.0), 1), "utilization": round(s("busy") / rt, 3),
            "waiting_pct": round(100 * s("wait") / rt, 1), "charging_pct": round(100 * s("charge") / rt, 1),
            "fault_pct": round(100 * s("fault") / rt, 2), "incidents": round(sum(F.inc_count for F, _ in runs) / S, 1),
            "backlog": round(sum(float((F.q_tail - F.q_head).float().mean()) for F, _ in runs) / S, 1), "pick_faces": L.n_picks, "rack_m": L.rack_m,
            "blocks": L.blocks, "cross_aisles": len(L.cross), "stations": L.n_stations, "stations_at": L.stations_at,
            "slotting": L.slotting, "robots": robots}
