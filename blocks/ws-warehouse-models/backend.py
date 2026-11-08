# ── EsaSim block ──────────────────────────────────────────────────────
# Warehouse models (ws-warehouse-models) · version 1 · machine block, Python: def run(ctx)
# Realistic 3D models for the warehouse demo: textured racks, pallets, desks and the MiR100 mobile robot, as GLB files.
# Workspace: Gianluca De Novi's workspace · Author: Gianluca De Novi
# Saved: 2026-11-08
#
# Inputs   ctx.inputs["id"] is a list of files: .path .name .size .read_text() .read_json()
#   (none)
# Outputs  ctx.output("id", "name.ext") is the path to write; ctx.write_json / ctx.write_text
#   models      Files (glb, json, txt)    Models · rack_d/e/f, goods_a/c/d, pallet_jack, desk, bin and amr (the robot) as GLB, kit.json, licences
#   telemetry   Live telemetry            ctx.telemetry("channel", data) while it runs
# Settings ctx.params["key"]
#   (none)
# Runs on  Any machine. Return a dict to fill the "result" output.
# Packages numpy, trimesh, pycollada, pillow, scipy (installed by the worker with pip when missing)
# EsaSim rewrites these lines from the block's definition each time it is saved: change the definition, not them.
# ── end of EsaSim block header ────────────────────────────────────────

"""Warehouse models: the 3D models of the Warehouse Fleet demo, as GLB files for the warehouse view.

Racks, pallets of goods, a pallet jack, pack desks and a bin from AWS RoboMaker's Small Warehouse World (MIT No
Attribution licence, Amazon.com, Inc.), and the body of the MiR100 mobile robot from DFKI's mir_robot (BSD-3-Clause).
The sources are downloaded once into the worker's data folder (cache/warehouse-kit), converted (centimetres to
metres, Z-up to Y-up, textures embedded) and kept there; later runs only copy the GLB files out, with the licences."""
import json
import os
import shutil

AWS_REPO = "https://raw.githubusercontent.com/aws-robotics/aws-robomaker-small-warehouse-world/ee0af733315e78432408c3cd98d378ecee5f767c/models/"
MIR_REPO = "https://raw.githubusercontent.com/DFKI-NI/mir_robot/ea7749ea2a9af0ff89a8a38759c70bf0b8bb0288/mir_description/meshes/visual/"
KIT_VERSION = 6

# name in the kit: AWS model
AWS_MODELS = {
    "rack_d": "ShelfD", "rack_e": "ShelfE", "rack_f": "ShelfF", "pallet_jack": "PalletJackB",
    "goods_a": "ClutteringA", "goods_c": "ClutteringC", "goods_d": "ClutteringD", "desk": "DeskC", "bin": "TrashCanC",
}

AWS_LICENSE_URL = "https://raw.githubusercontent.com/aws-robotics/aws-robomaker-small-warehouse-world/ee0af733315e78432408c3cd98d378ecee5f767c/LICENSE"
MIR_LICENSE_URL = "https://raw.githubusercontent.com/DFKI-NI/mir_robot/ea7749ea2a9af0ff89a8a38759c70bf0b8bb0288/LICENSE"


def cache_folder():
    here = os.path.abspath(os.getcwd())                    # <data>/jobs/<job>/<task>
    jobs = os.path.dirname(os.path.dirname(here))
    base = os.path.dirname(jobs) if os.path.basename(jobs) == "jobs" else os.path.dirname(here)
    return os.path.join(base, "cache", "warehouse-kit")


def fetch(url, path, log):
    import urllib.request
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    log("Downloading " + url)
    with urllib.request.urlopen(url, timeout=90) as r:
        data = r.read()
    with open(path + ".part", "wb") as f:
        f.write(data)
    os.replace(path + ".part", path)
    return path


def aws_textures(dae_path):
    """Texture files a DAE names (../materials/textures/x.png)."""
    import re
    txt = open(dae_path, "r", encoding="utf-8", errors="replace").read()
    return sorted(set(re.findall(r"<init_from>\.\./materials/textures/([^<]+)</init_from>", txt)))


def convert_aws(src, kit_name, model, out, log):
    import numpy as np
    import trimesh
    full = "aws_robomaker_warehouse_%s_01" % model
    folder = os.path.join(src, full)
    dae = fetch(AWS_REPO + "%s/meshes/%s_visual.DAE" % (full, full), os.path.join(folder, "meshes", full + "_visual.DAE"), log)
    for t in aws_textures(dae):
        fetch(AWS_REPO + "%s/materials/textures/%s" % (full, t), os.path.join(folder, "materials", "textures", t), log)

    class Files(trimesh.resolvers.Resolver):
        def __init__(self, d):
            self.d = d

        def get(self, name):
            p = os.path.normpath(os.path.join(self.d, name))
            if not p.startswith(os.path.normpath(folder)):
                raise ValueError("outside the model folder: " + name)
            return open(p, "rb").read()

        def write(self, *a):
            pass

        def keys(self):
            return []

        def namespaced(self, ns):
            return Files(os.path.join(self.d, ns))

    scene = trimesh.load(open(dae, "rb"), file_type="dae", force="scene", resolver=Files(os.path.dirname(dae)))
    t = np.eye(4)
    t[:3, :3] *= 0.01                                                         # centimetres -> metres
    scene.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]) @ t)   # Z-up -> Y-up
    for g in scene.geometry.values():                                         # matte, not plastic
        m = getattr(g.visual, "material", None)
        if m is not None and hasattr(m, "roughnessFactor"):
            m.roughnessFactor = 0.75
            m.metallicFactor = 0.05 if "Shelf" not in model else 0.35
    scene.export(out)
    b = scene.bounds
    return {"file": os.path.basename(out), "size_m": [round(float(x), 3) for x in (b[1] - b[0])], "min": [round(float(x), 3) for x in b[0]],
            "triangles": int(sum(len(g.faces) for g in scene.geometry.values()))}


def read_stl(data):
    import numpy as np
    if data[:5].lower() == b"solid" and b"facet" in data[:400]:
        nums = [float(x) for line in data.decode("ascii", "replace").splitlines() if line.strip().startswith("vertex") for x in line.split()[1:4]]
        return np.array(nums, np.float32).reshape(-1, 3, 3)
    n = int(np.frombuffer(data[80:84], "<u4")[0])
    rec = np.frombuffer(data[84:84 + n * 50], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
    return rec["v"].copy()


def decimate(tris, cell):
    """Vertex clustering: vertices closer than `cell` merge, triangles that collapse go. Returns (vertices, faces)."""
    import numpy as np
    v = tris.reshape(-1, 3).astype(np.float64)
    keys = np.floor(v / cell).astype(np.int64)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    sums = np.zeros((len(uniq), 3))
    np.add.at(sums, inv, v)
    cnt = np.bincount(inv, minlength=len(uniq))[:, None]
    verts = sums / cnt
    f = inv.reshape(-1, 3)
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])]
    if len(f):
        _, idx = np.unique(np.sort(f, axis=1), axis=0, return_index=True)
        f = f[np.sort(idx)]
    used = np.unique(f)
    remap = -np.ones(len(verts), np.int64)
    remap[used] = np.arange(len(used))
    return verts[used], remap[f]


def convert_amr(src, out, log):
    """The MiR100 body: decimated, standing on the floor, centred, facing +X, in three materials (light shell, dark
    lower band and bumpers, grey top deck), with sharp edges kept sharp."""
    import numpy as np
    import trimesh
    path = fetch(MIR_REPO + "mir_100_base.stl", os.path.join(src, "mir", "mir_100_base.stl"), log)
    tris = read_stl(open(path, "rb").read())
    v, f = decimate(tris, 0.006)
    v = v[:, [0, 2, 1]] * np.array([1, 1, -1])           # Z-up (x forward, y left) -> Y-up (x forward, z right)
    lo, hi = v.min(0), v.max(0)
    v = v - np.array([(lo[0] + hi[0]) / 2, lo[1] - 0.012, (lo[2] + hi[2]) / 2])
    mesh = trimesh.Trimesh(v, f, process=True)
    h = mesh.bounds[1][1]
    cz = mesh.triangles_center[:, 1]
    ny = mesh.face_normals[:, 1]
    part = np.where((ny > 0.8) & (cz > h - 0.03), 2, np.where(cz < h * 0.42, 1, 0))
    colours = [([0.6, 0.62, 0.64, 1], 0.35, 0.0, "shell"), ([0.018, 0.02, 0.022, 1], 0.55, 0.0, "base"), ([0.16, 0.17, 0.18, 1], 0.75, 0.0, "deck")]
    scene = trimesh.Scene()
    for i, (rgba, rough, metal, name) in enumerate(colours):
        sub = mesh.submesh([np.nonzero(part == i)[0]], append=True)
        if not len(sub.faces):
            continue
        sub = trimesh.graph.smooth_shade(sub, angle=np.radians(35))
        sub.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=name, baseColorFactor=rgba, roughnessFactor=rough, metallicFactor=metal))
        scene.add_geometry(sub, node_name="amr_" + name, geom_name="amr_" + name)
    scene.export(out)
    b = scene.bounds
    return {"file": os.path.basename(out), "size_m": [round(float(x), 3) for x in (b[1] - b[0])], "min": [round(float(x), 3) for x in b[0]],
            "triangles": int(len(mesh.faces)), "original": int(len(tris))}


def build_kit(cache, log=print):
    kit = os.path.join(cache, "v%d" % KIT_VERSION)
    manifest = os.path.join(kit, "kit.json")
    if os.path.exists(manifest):
        return kit, json.load(open(manifest))
    src = os.path.join(cache, "sources")
    tmp = kit + ".part"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    models = {}
    for name, model in AWS_MODELS.items():
        models[name] = convert_aws(os.path.join(src, "aws"), name, model, os.path.join(tmp, name + ".glb"), log)
        log("%s: %s m, %d triangles" % (name, models[name]["size_m"], models[name]["triangles"]))
    models["amr"] = convert_amr(src, os.path.join(tmp, "amr.glb"), log)
    log("amr: %s m, %d triangles (from %d)" % (models["amr"]["size_m"], models["amr"]["triangles"], models["amr"]["original"]))
    aws_lic = open(fetch(AWS_LICENSE_URL, os.path.join(src, "aws", "LICENSE"), log), encoding="utf-8").read()
    mir_lic = open(fetch(MIR_LICENSE_URL, os.path.join(src, "mir", "LICENSE"), log), encoding="utf-8").read()
    with open(os.path.join(tmp, "LICENSES-warehouse-models.txt"), "w", encoding="utf-8") as fh:
        fh.write("Racks, pallets, pallet jack, desk and bin: AWS RoboMaker Small Warehouse World\n"
                 "https://github.com/aws-robotics/aws-robomaker-small-warehouse-world (converted to GLB)\n\n" + aws_lic.strip() +
                 "\n\n----------------------------------------------------------------------\n\n"
                 "Mobile robot body (MiR100): mir_robot by DFKI GmbH\n"
                 "https://github.com/DFKI-NI/mir_robot (mesh simplified and coloured, converted to GLB)\n\n" + mir_lic.strip() + "\n")
    info = {"kind": "esasim.warehouse-kit/1", "version": KIT_VERSION, "models": models}
    with open(os.path.join(tmp, "kit.json"), "w") as fh:
        json.dump(info, fh, indent=1)
    shutil.rmtree(kit, ignore_errors=True)
    os.replace(tmp, kit)
    return kit, info


def run(ctx):
    try:
        kit, info = build_kit(cache_folder(), ctx.log)
    except Exception as e:
        raise RuntimeError("Could not make the warehouse models (%s). The machine downloads them once from GitHub "
                           "(raw.githubusercontent.com): check that it reaches it." % e)
    total = 0
    for name in sorted(os.listdir(kit)):
        shutil.copyfile(os.path.join(kit, name), ctx.output("models", name))
        total += os.path.getsize(os.path.join(kit, name))
    ctx.log("Warehouse models: %d files, %.1f MB." % (len(os.listdir(kit)), total / 1e6))
    return {"models": len(info["models"]), "megabytes": round(total / 1e6, 1)}
