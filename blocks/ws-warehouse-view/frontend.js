// ── EsaSim block ──────────────────────────────────────────────────────
// Warehouse view (ws-warehouse-view) · version 1 · view, JavaScript: function render(ctx)
// The Warehouse fleet in 3D, live: textured racks, the robots with their light strips, totes and routes, a heat map of waiting, KPIs, and controls that change the run.
// Workspace: Gianluca De Novi's workspace · Author: Gianluca De Novi
// Saved: 2026-11-08
//
// Inputs   ctx.input("id") gives { files, stream }; ctx.rows("id"), ctx.json("id"), ctx.text("id")
//   live        Stream                    Live · several · The Warehouse fleet block's telemetry
//   models      Files (glb, json, txt)    Models · optional · From Warehouse models (without them, simple shapes)
// Settings ctx.params.key
//   quality     select    Quality = "high" of high | balanced | fast
//   routes      bool      Show the routes = true
//   heat        bool      Show the heat map = false
//   camera      select    Camera = "orbit" of orbit | cinematic
//   delay       number    Behind real time (seconds) = 2.5
// EsaSim rewrites these lines from the block's definition each time it is saved: change the definition, not them.
// ── end of EsaSim block header ────────────────────────────────────────

/* Warehouse fleet view: the warehouse of the Warehouse fleet block in 3D, live.
 *
 * Inputs: the fleet block's live telemetry (channels layout, fleet, kpi, heat, event) and the Warehouse models
 * (GLB files: racks, robot, desks, pallets). The robots move smoothly between the simulation's steps, show what
 * they do with their light strip (cyan: to a pick face, amber: picking, green: carrying a tote to a station,
 * violet: at the station, red: waiting), and draw the route they plan. The bar at the bottom changes the run while it
 * goes on (order rate, robots, speed, block an aisle); when the run has ended, the whole run plays back. */
function render(ctx) {
  var THREE = ctx.THREE, A = THREE.addons, P = ctx.params, el = ctx.el;
  var quality = P.quality || 'high';
  el.innerHTML = '';
  el.style.overflow = 'hidden'; el.style.background = '#0c1016';

  // ------------------------------------------------------------------ look
  var css = document.createElement('style');
  css.textContent = [
    '.wf{position:absolute;inset:0;font:13px/1.35 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#e8edf5;pointer-events:none;user-select:none}',
    '.wf *{box-sizing:border-box}',
    '.wf [hidden]{display:none!important}',
    '.wf .glass{background:rgba(14,19,27,.72);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);border:1px solid rgba(255,255,255,.08);border-radius:10px;pointer-events:auto}',
    '.wf .top{position:absolute;left:12px;right:12px;top:12px;display:flex;gap:10px;align-items:stretch;flex-wrap:wrap}',
    '.wf .title{padding:9px 12px;min-width:210px}',
    '.wf .title b{display:block;font-size:14px;letter-spacing:.2px}',
    '.wf .badge{display:inline-flex;align-items:center;gap:6px;margin-top:5px;padding:2px 8px;border-radius:99px;font-size:11.5px;font-weight:600;background:rgba(255,255,255,.08)}',
    '.wf .badge i{width:7px;height:7px;border-radius:50%;background:#94a3b8;box-shadow:0 0 8px currentColor}',
    '.wf .badge.nvidia{color:#86efac}.wf .badge.nvidia i{background:#76b900}',
    '.wf .badge.tenstorrent{color:#c4b5fd}.wf .badge.tenstorrent i{background:#8b5cf6}',
    '.wf .badge.cpu{color:#cbd5e1}',
    '.wf .sub{font-size:11.5px;opacity:.65;margin-top:4px}',
    '.wf .kpis{display:flex;gap:8px;flex-wrap:wrap}',
    '.wf .kpi{padding:8px 12px;min-width:112px}',
    '.wf .kpi span{display:block;font-size:11px;opacity:.62;text-transform:uppercase;letter-spacing:.5px}',
    '.wf .kpi b{display:block;font-size:22px;font-weight:650;font-variant-numeric:tabular-nums;margin-top:1px}',
    '.wf .kpi small{font-size:11.5px;opacity:.6;font-variant-numeric:tabular-nums}',
    '.wf .kpi canvas{display:block;margin-top:3px}',
    '.wf .events{position:absolute;right:12px;top:96px;width:300px;display:flex;flex-direction:column;gap:6px}',
    '.wf .ev{padding:7px 10px;font-size:12px;transition:opacity .6s;pointer-events:none}',
    '.wf .ev em{font-style:normal;opacity:.55;margin-right:6px;font-variant-numeric:tabular-nums}',
    '.wf .bottom{position:absolute;left:12px;right:12px;bottom:12px;display:flex;flex-direction:column;align-items:flex-start;gap:8px;pointer-events:none}',
    '.wf .bar{align-self:stretch;display:flex;gap:8px 10px;align-items:center;flex-wrap:wrap;padding:8px 10px}',
    '.wf .ctl{display:flex;align-items:center;gap:8px}',
    '.wf .ctl label{font-size:11.5px;opacity:.7;white-space:nowrap}',
    '.wf .ctl output{min-width:44px;font-variant-numeric:tabular-nums;font-weight:600}',
    '.wf input[type=range]{width:120px;accent-color:#38bdf8}',
    '.wf button{font:inherit;font-size:12px;color:#e8edf5;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);border-radius:7px;padding:5px 9px;cursor:pointer}',
    '.wf button:hover{background:rgba(255,255,255,.16)}',
    '.wf button.on{background:#0ea5e9;border-color:#38bdf8;color:#fff}',
    '.wf button.warn.on{background:#dc2626;border-color:#f87171}',
    '.wf button:disabled,.wf input:disabled{opacity:.4;cursor:default}',
    '.wf .sep{width:1px;align-self:stretch;background:rgba(255,255,255,.1)}',
    '.wf .grow{flex:1}',
    '.wf .hint{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);padding:14px 18px;text-align:center;max-width:420px}',
    '.wf .tip{position:absolute;padding:6px 9px;font-size:12px;pointer-events:none;white-space:nowrap;transform:translate(12px,12px)}',
    '.wf .legend{display:flex;gap:12px;font-size:11.5px;padding:6px 10px;flex-wrap:wrap}',
    '.wf .legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:4px;vertical-align:-1px}',
    '@media (max-width:820px){.wf .events{display:none}.wf .kpi{min-width:92px}.wf .kpi b{font-size:18px}.wf input[type=range]{width:90px}.wf .legend{display:none}}'
  ].join('\n');
  el.appendChild(css);

  var MODE_COLORS = [0xcbd5e1, 0x22d3ee, 0xfbbf24, 0x34d399, 0xa78bfa, 0x000000];
  var WAIT_COLOR = 0xef4444;
  var MODE_NAMES = ['Idle, going to its dock', 'Going to a pick face', 'Picking', 'Carrying a tote to a station', 'At the station', 'Parked away'];

  // ------------------------------------------------------------------ renderer, scene, camera
  var renderer = new THREE.WebGLRenderer({ antialias: quality !== 'fast', powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, quality === 'high' ? 2 : quality === 'balanced' ? 1.5 : 1));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.92;
  renderer.shadowMap.enabled = quality !== 'fast';
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.style.display = 'block';
  el.appendChild(renderer.domElement);

  var scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0c1016);
  scene.fog = new THREE.Fog(0x0c1016, 70, 150);
  var camera = new THREE.PerspectiveCamera(40, 1, 0.1, 400);
  camera.position.set(18, 26, 34);
  var controls = new A.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.47; controls.minDistance = 2.5; controls.maxDistance = 120;
  controls.target.set(0, 0, 0);

  var pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new A.RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.42;
  var hemi = new THREE.HemisphereLight(0xe6eeff, 0x3a3328, 0.5);
  scene.add(hemi);
  var sun = new THREE.DirectionalLight(0xfff4e6, 2.1);
  sun.castShadow = renderer.shadowMap.enabled;
  var sm = quality === 'high' ? 4096 : 2048;
  sun.shadow.mapSize.set(sm, sm);
  sun.shadow.bias = -0.0003; sun.shadow.normalBias = 0.03; sun.shadow.radius = 3;
  scene.add(sun, sun.target);

  var composer = null, bloom = null;
  if (quality !== 'fast') {
    composer = new A.EffectComposer(renderer);
    composer.addPass(new A.RenderPass(scene, camera));
    // no screen-space ambient occlusion: it darkens the lit strips and the routes on the floor
    bloom = new A.UnrealBloomPass(new THREE.Vector2(256, 256), 0.75, 0.35, 1.25);
    composer.addPass(bloom);
    composer.addPass(new A.OutputPass());
  }

  // ------------------------------------------------------------------ helpers
  function std(color, rough, metal, extra) { return new THREE.MeshStandardMaterial(Object.assign({ color: color, roughness: rough, metalness: metal || 0 }, extra || {})); }
  function shadowy(o, cast, receive) { o.traverse(function (m) { if (m.isMesh) { m.castShadow = cast !== false; m.receiveShadow = receive !== false; } }); return o; }
  function smooth(u) { return u * u * (3 - 2 * u); }
  function easeIn(u) { return u * u * (2 - u); }
  function easeOut(u) { return 1 - easeIn(1 - u); }
  function fmt(n, d) { return n == null || isNaN(n) ? '–' : Number(n).toLocaleString(undefined, { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 }); }
  function mmss(s) { s = Math.max(0, Math.round(s)); var m = Math.floor(s / 60); return m + ':' + ('0' + (s % 60)).slice(-2); }
  function esc(v) { return String(v == null ? '' : v).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  // ------------------------------------------------------------------ models (GLB from Warehouse models, procedural when missing)
  var MODELS = {}, modelsWanted = 0, modelsDone = 0;
  function loadModels() {
    var fs = ctx.input('models').files.filter(function (f) { return /\.glb$/i.test(f.name); });
    fs.forEach(function (f) {
      var key = f.name.replace(/\.glb$/i, '');
      if (MODELS[key] !== undefined) return;
      MODELS[key] = null; modelsWanted++;
      ctx.files.buffer(f).then(function (buf) {
        return new Promise(function (res, rej) {
          var L = new A.GLTFLoader();
          // embedded pictures through <img> (the frame may not fetch blob: URLs)
          L.register(function (parser) { parser.textureLoader = new THREE.TextureLoader(); return { name: 'esasim_images' }; });
          L.parse(buf, '', function (g) { res(g.scene); }, rej);
        });
      }).then(function (obj) {
        obj.traverse(function (m) {
          if (m.isMesh && m.material) {
            var ms = Array.isArray(m.material) ? m.material : [m.material];
            ms.forEach(function (mt) { if (mt.map) { mt.map.anisotropy = 8; mt.map.colorSpace = THREE.SRGBColorSpace; } });
          }
        });
        MODELS[key] = obj; modelsDone++; rebuild();
      }).catch(function (e) { modelsDone++; ctx.status('Could not open ' + f.name + ': ' + e.message); });
    });
  }

  // Instances of a model: one InstancedMesh per part, so fifty racks cost a handful of draw calls.
  function instanced(model, mats) {
    var g = new THREE.Group();
    if (!model || !mats.length) return g;
    model.updateMatrixWorld(true);
    model.traverse(function (m) {
      if (!m.isMesh) return;
      var im = new THREE.InstancedMesh(m.geometry, m.material, mats.length);
      var tmp = new THREE.Matrix4();
      mats.forEach(function (M, i) { tmp.multiplyMatrices(M, m.matrixWorld); im.setMatrixAt(i, tmp); });
      im.castShadow = true; im.receiveShadow = true;
      im.instanceMatrix.needsUpdate = true;
      im.computeBoundingSphere && im.computeBoundingSphere();
      g.add(im);
    });
    return g;
  }
  function placed(model, x, y, z, yaw, s) {
    var o = model.clone(true);
    o.position.set(x, y || 0, z); o.rotation.y = yaw || 0; if (s) o.scale.setScalar(s);
    return shadowy(o);
  }

  // ------------------------------------------------------------------ layout and world
  var LAY = null, layoutSig = '', W = 0, H = 0;
  var world = new THREE.Group(); scene.add(world);
  var dyn = new THREE.Group(); scene.add(dyn);
  function cx(x) { return x + 0.5 - W / 2; }
  function cz(y) { return -(y + 0.5 - H / 2); }
  function kindAt(x, y) { return x < 0 || y < 0 || x >= W || y >= H ? '.' : LAY.kinds[y * W + x]; }

  // floor markings, painted on a canvas: lanes, arrows, stations, docks, rack outlines
  function floorTexture() {
    var M = 8, ppm = quality === 'fast' ? 32 : 56;
    var cw = (W + 2 * M) * ppm, ch = (H + 2 * M) * ppm;
    var max = 4096; if (cw > max || ch > max) { ppm = Math.floor(ppm * Math.min(max / cw, max / ch)); cw = (W + 2 * M) * ppm; ch = (H + 2 * M) * ppm; }
    var c = document.createElement('canvas'); c.width = cw; c.height = ch;
    var g = c.getContext('2d');
    // polished concrete
    g.fillStyle = '#5d6269'; g.fillRect(0, 0, cw, ch);
    var s = 7;
    function rnd() { s = (s * 16807) % 2147483647; return s / 2147483647; }
    for (var i = 0; i < cw * ch / 900; i++) { var v = 80 + rnd() * 40 | 0; g.fillStyle = 'rgba(' + v + ',' + v + ',' + (v + 4) + ',' + (0.05 + rnd() * 0.07) + ')'; var r = 2 + rnd() * 26; g.beginPath(); g.arc(rnd() * cw, rnd() * ch, r, 0, 6.283); g.fill(); }
    g.strokeStyle = 'rgba(40,44,50,.35)'; g.lineWidth = Math.max(1, ppm / 28);
    for (var sx = 0; sx <= W + 2 * M; sx += 6) { g.beginPath(); g.moveTo(sx * ppm, 0); g.lineTo(sx * ppm, ch); g.stroke(); }
    for (var sy = 0; sy <= H + 2 * M; sy += 6) { g.beginPath(); g.moveTo(0, sy * ppm); g.lineTo(cw, sy * ppm); g.stroke(); }
    function px(x) { return (x + M) * ppm; }
    function py(y) { return (H - y + M) * ppm; }        // grid y up -> canvas y down
    function cell(x, y, fill) { g.fillStyle = fill; g.fillRect(px(x), py(y + 1), ppm, ppm); }
    // driving area a little darker and smoother
    for (var y = 0; y < H; y++) for (var x = 0; x < W; x++) {
      var k = kindAt(x, y);
      if ('hcaqsx'.indexOf(k) >= 0) cell(x, y, k === 'h' ? 'rgba(58,64,72,.55)' : 'rgba(70,76,84,.4)');
      if (k === 'q' || k === 's' || k === 'x') cell(x, y, 'rgba(56,189,248,.10)');
      if (k === 'd') cell(x, y, 'rgba(52,211,153,.16)');
    }
    // safety lines round the racks
    g.strokeStyle = '#e8c547'; g.lineWidth = Math.max(2, ppm * 0.06);
    LAY.racks.forEach(function (r) { g.strokeRect(px(r[0]) + ppm * 0.03, py(r[1] + r[2]) + ppm * 0.03, ppm * 0.94, r[2] * ppm - ppm * 0.06); });
    // highway edges and centre line
    g.lineWidth = Math.max(2, ppm * 0.05);
    [[4, 5], [LAY.store[1], LAY.store[1] + 1]].forEach(function (pair) {
      var y0 = pair[0], x0 = 1, x1 = W - 1;
      g.strokeStyle = '#e8c547';
      g.beginPath(); g.moveTo(px(x0), py(y0)); g.lineTo(px(x1), py(y0)); g.stroke();
      g.beginPath(); g.moveTo(px(x0), py(y0 + 2)); g.lineTo(px(x1), py(y0 + 2)); g.stroke();
      g.strokeStyle = 'rgba(255,255,255,.75)'; g.setLineDash([ppm * 0.6, ppm * 0.5]);
      g.beginPath(); g.moveTo(px(x0), py(y0 + 1)); g.lineTo(px(x1), py(y0 + 1)); g.stroke();
      g.setLineDash([]);
    });
    // one-way arrows
    var DX = [1, 0, -1, 0], DY = [0, 1, 0, -1];
    g.fillStyle = 'rgba(255,255,255,.55)';
    for (y = 0; y < H; y++) for (x = 0; x < W; x++) {
      k = kindAt(x, y); var m = parseInt(LAY.moves[y * W + x], 16);
      if (!(k === 'h' || k === 'a' || k === 'c')) continue;
      var dirs = []; for (var d = 0; d < 4; d++) if (m & (1 << d)) { var nk = kindAt(x + DX[d], y + DY[d]); if (nk === k || (k === 'a' && nk === 'c') || (k === 'c' && nk === 'a')) dirs.push(d); }
      if (dirs.length !== 1) continue;
      if (k === 'h' && (x % 3)) continue;
      if (k === 'a' && (y % 2)) continue;
      d = dirs[0];
      var ax = px(x) + ppm / 2, ay = py(y + 1) + ppm / 2, ang = -Math.atan2(DY[d], DX[d]);
      g.save(); g.translate(ax, ay); g.rotate(ang);
      g.beginPath(); g.moveTo(ppm * 0.22, 0); g.lineTo(-ppm * 0.12, -ppm * 0.16); g.lineTo(-ppm * 0.04, 0); g.lineTo(-ppm * 0.12, ppm * 0.16); g.closePath(); g.fill();
      g.restore();
    }
    // stations: hatched operator zone and number
    LAY.stations.forEach(function (st, i) {
      var x0 = st[0] - 0.5, w = 3;
      g.save(); g.beginPath(); g.rect(px(x0), py(0.6), w * ppm, 0.6 * ppm); g.clip();
      g.fillStyle = '#1f2328'; g.fillRect(px(x0), py(0.6), w * ppm, 0.6 * ppm);
      g.strokeStyle = '#f5c518'; g.lineWidth = ppm * 0.12;
      for (var hx = -2; hx < w + 2; hx += 0.35) { g.beginPath(); g.moveTo(px(x0 + hx), py(0)); g.lineTo(px(x0 + hx + 0.6), py(0.6)); g.stroke(); }
      g.restore();
      g.strokeStyle = 'rgba(56,189,248,.9)'; g.lineWidth = ppm * 0.05;
      g.strokeRect(px(st[0]) + ppm * 0.06, py(st[1] + 1) + ppm * 0.06, ppm * 0.88, ppm * 0.88);
      g.fillStyle = 'rgba(255,255,255,.85)'; g.font = '700 ' + Math.round(ppm * 0.55) + 'px system-ui,sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
      g.fillText(String(i + 1), px(st[0] + 1) + ppm * 0.5, py(1) + ppm * 0.5 + ppm * 0.02);
    });
    // docks: charging pads
    LAY.docks.forEach(function (dk) {
      var x = dk[0], y = dk[1];
      g.strokeStyle = 'rgba(52,211,153,.8)'; g.lineWidth = ppm * 0.04;
      g.strokeRect(px(x) + ppm * 0.12, py(y + 1) + ppm * 0.12, ppm * 0.76, ppm * 0.76);
      g.fillStyle = 'rgba(52,211,153,.75)'; g.beginPath();
      var bx = px(x) + ppm * 0.5, by = py(y + 1) + ppm * 0.5, u = ppm * 0.12;
      g.moveTo(bx + u * 0.3, by - u * 1.4); g.lineTo(bx - u * 0.8, by + u * 0.2); g.lineTo(bx, by + u * 0.2); g.lineTo(bx - u * 0.3, by + u * 1.4); g.lineTo(bx + u * 0.8, by - u * 0.2); g.lineTo(bx, by - u * 0.2); g.closePath(); g.fill();
    });
    var tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    return { tex: tex, w: W + 2 * M, h: H + 2 * M };
  }

  var rebuildTimer = 0;
  function rebuild() { clearTimeout(rebuildTimer); rebuildTimer = setTimeout(buildWorld, 30); }
  var stationLights = [], blockedGroup = new THREE.Group(); scene.add(blockedGroup);
  function buildWorld() {
    if (!LAY) return;
    world.children.slice().forEach(function (c) { world.remove(c); });
    stationLights = [];
    var ft = floorTexture();
    var floor = new THREE.Mesh(new THREE.PlaneGeometry(ft.w, ft.h), new THREE.MeshPhysicalMaterial({ map: ft.tex, roughness: 0.42, metalness: 0, clearcoat: 0.35, clearcoatRoughness: 0.35 }));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true;
    world.add(floor);
    // the hall: back and left walls, a low rail in front
    var wallMat = std(0x2b323c, 0.85, 0.15), panel = std(0x37404c, 0.7, 0.25);
    var hallW = W + 16, hallD = H + 16, wallH = 7.5;
    var back = new THREE.Mesh(new THREE.BoxGeometry(hallW, wallH, 0.3), wallMat); back.position.set(0, wallH / 2, -(H / 2 + 5)); world.add(shadowy(back, false));
    var left = new THREE.Mesh(new THREE.BoxGeometry(0.3, wallH, hallD), wallMat); left.position.set(-(W / 2 + 7), wallH / 2, 0); world.add(shadowy(left, false));
    for (var i = -hallW / 2 + 2; i < hallW / 2; i += 4) { var rib = new THREE.Mesh(new THREE.BoxGeometry(0.25, wallH, 0.25), panel); rib.position.set(i, wallH / 2, -(H / 2 + 4.8)); world.add(shadowy(rib)); }
    for (i = -hallD / 2 + 2; i < hallD / 2; i += 4) { var rib2 = new THREE.Mesh(new THREE.BoxGeometry(0.25, wallH, 0.25), panel); rib2.position.set(-(W / 2 + 6.8), wallH / 2, i); world.add(shadowy(rib2)); }
    var stripe = new THREE.Mesh(new THREE.BoxGeometry(hallW, 0.5, 0.05), std(0xe8c547, 0.6)); stripe.position.set(0, 0.25, -(H / 2 + 4.82)); world.add(stripe);
    // racks
    var rackMats = [[], []];
    LAY.racks.forEach(function (r, i) {
      var M = new THREE.Matrix4().compose(new THREE.Vector3(cx(r[0]), 0, cz(r[1] + r[2] / 2 - 0.5)),
        new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2 + (r[3] === 2 ? Math.PI : 0)), new THREE.Vector3(r[2] / 4 * 0.995, 1, 1));
      rackMats[(i * 7 + (i >> 2)) % 3 === 0 ? 1 : 0].push(M);
    });
    if (MODELS.rack_d) { world.add(instanced(MODELS.rack_d, rackMats[0])); world.add(instanced(MODELS.rack_e || MODELS.rack_d, rackMats[1])); }
    else world.add(fallbackRacks());
    // pallet racking along the back wall
    if (MODELS.rack_f) {
      var span = 18.05, n = Math.ceil((W + 4) / span), mats = [];
      for (i = 0; i < n; i++) mats.push(new THREE.Matrix4().compose(new THREE.Vector3(-((n - 1) * span) / 2 + i * span, 0, -(H / 2 + 3.4)),
        new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2), new THREE.Vector3(1, 1, 1)));
      world.add(instanced(MODELS.rack_f, mats));
    }
    // receiving area on the left: pallets of goods and a pallet jack
    var gx = -(W / 2 + 3.6);
    [['goods_a', gx, -H / 2 + 6, 0], ['goods_c', gx, -H / 2 + 9, 0.1], ['goods_d', gx + 0.4, -H / 2 + 12.5, Math.PI / 2], ['goods_a', gx, 2, Math.PI],
      ['goods_c', gx, 5.5, -0.05], ['pallet_jack', gx + 2.0, 8, -Math.PI / 2], ['goods_d', gx + 0.4, H / 2 - 1, 0], ['bin', gx + 0.5, -H / 2 + 2.2, 0.3]].forEach(function (p) {
      if (MODELS[p[0]]) world.add(placed(MODELS[p[0]], p[1], 0, p[2], p[3]));
    });
    // stations: a pack desk facing the robot, a light tower, a bin
    LAY.stations.forEach(function (st, i) {
      var X = cx(st[0]) + 0.5, Z = cz(0) + 0.15;
      if (MODELS.desk) world.add(placed(MODELS.desk, X, 0, Z + 0.2, Math.PI / 2));
      else { var dsk = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.9, 0.8), std(0x6b7280, 0.6)); dsk.position.set(X, 0.45, Z + 0.2); world.add(shadowy(dsk)); }
      var tower = new THREE.Group();
      var pole = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 1.6, 10), std(0x9ca3af, 0.4, 0.8)); pole.position.y = 0.8; tower.add(pole);
      var lamps = [0xef4444, 0xfbbf24, 0x22c55e].map(function (c, k) {
        var m = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.12, 16), new THREE.MeshStandardMaterial({ color: c, emissive: c, emissiveIntensity: 0.15, roughness: 0.3, transparent: true, opacity: 0.92 }));
        m.position.y = 1.65 + k * 0.13; tower.add(m); return m;
      });
      tower.position.set(X + 1.05, 0, Z + 0.35); world.add(shadowy(tower));
      stationLights.push({ cell: st[1] * W + st[0], lamps: lamps });
    });
    // chargers at the docks
    var chg = new THREE.BoxGeometry(0.5, 0.34, 0.1), chgMat = std(0x1f2937, 0.5, 0.3), led = new THREE.MeshStandardMaterial({ color: 0x34d399, emissive: 0x34d399, emissiveIntensity: 3.5 });
    var ledG = new THREE.BoxGeometry(0.2, 0.04, 0.02);
    LAY.docks.forEach(function (dk) {
      var out = dk[2], back = (out + 2) % 4, DX = [1, 0, -1, 0], DY = [0, 1, 0, -1];
      var X = cx(dk[0]) + DX[back] * 0.47, Z = cz(dk[1]) - DY[back] * 0.47;
      var b = new THREE.Mesh(chg, chgMat); b.position.set(X, 0.17, Z); b.rotation.y = back % 2 === 0 ? Math.PI / 2 : 0; world.add(shadowy(b));
      var l = new THREE.Mesh(ledG, led); l.position.set(X - DX[back] * 0.055, 0.28, Z + DY[back] * 0.055); l.rotation.y = b.rotation.y; world.add(l);
    });
    fitLight();
    buildBlocked();
    if (MODELS.amr) robots.forEach(function (R) { if (R.g.userData.real) return; R.g.remove(R.body); R.body = shadowy(robotBody()); R.g.add(R.body); R.g.userData.real = true; });
    fields = {};
    if (!camSet) homeCamera();
  }
  function fallbackRacks() {
    var g = new THREE.Group(), frame = std(0xe0b52c, 0.5, 0.4), shelf = std(0x8b6b45, 0.8), box = std(0xc9a46a, 0.85);
    LAY.racks.forEach(function (r) {
      var X = cx(r[0]), Z = cz(r[1] + r[2] / 2 - 0.5), L = r[2] * 0.98;
      [0.2, 0.95, 1.7, 2.45].forEach(function (h) { var s = new THREE.Mesh(new THREE.BoxGeometry(0.86, 0.05, L), shelf); s.position.set(X, h, Z); g.add(s); if (h < 2) { var b = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.4, L * 0.8), box); b.position.set(X, h + 0.23, Z); g.add(b); } });
      [-1, 1].forEach(function (sz) { [-1, 1].forEach(function (sx) { var p = new THREE.Mesh(new THREE.BoxGeometry(0.06, 2.6, 0.06), frame); p.position.set(X + sx * 0.42, 1.3, Z + sz * L / 2); g.add(p); }); });
    });
    return shadowy(g);
  }
  function fitLight() {
    var R = Math.max(W, H) * 0.75 + 6;
    sun.position.set(R * 0.55, R * 1.25, R * 0.75); sun.target.position.set(0, 0, 0);
    var s = sun.shadow.camera; s.left = -R; s.right = R; s.top = R; s.bottom = -R; s.near = 1; s.far = R * 4; s.updateProjectionMatrix();
  }

  // pallets and cones where an aisle is blocked
  var blockedSig = '';
  function buildBlocked() {
    var list = (LAY && LAY.blocked) || [], sig = JSON.stringify(list) + (MODELS.pallet_jack ? 'm' : '');
    if (sig === blockedSig) return; blockedSig = sig;
    blockedGroup.children.slice().forEach(function (c) { blockedGroup.remove(c); });
    var cone = new THREE.ConeGeometry(0.11, 0.42, 20), coneMat = std(0xf97316, 0.55), band = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.4 });
    var cross = new THREE.MeshBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0.45, depthWrite: false });
    list.forEach(function (c) {
      var X = cx(c[0]), Z = cz(c[1]);
      var q = new THREE.Mesh(new THREE.PlaneGeometry(0.96, 0.96), cross); q.rotation.x = -Math.PI / 2; q.position.set(X, 0.012, Z); blockedGroup.add(q);
      if (MODELS.pallet_jack) blockedGroup.add(placed(MODELS.pallet_jack, X, 0, Z, Math.PI / 2 + 0.25, 0.85));
      else { var p = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.9, 0.8), std(0xc9a46a, 0.8)); p.position.set(X, 0.45, Z); blockedGroup.add(shadowy(p)); }
      [[-0.32, 0.36], [0.32, -0.36]].forEach(function (o) {
        var g = new THREE.Group(), k = new THREE.Mesh(cone, coneMat); k.position.y = 0.21; g.add(k);
        var b = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.09, 0.07, 20), band); b.position.y = 0.24; g.add(b);
        var base = new THREE.Mesh(new THREE.BoxGeometry(0.26, 0.03, 0.26), coneMat); base.position.y = 0.015; g.add(base);
        g.position.set(X + o[0], 0, Z + o[1]); blockedGroup.add(shadowy(g));
      });
    });
    fields = {};
  }

  // ------------------------------------------------------------------ robots
  var robots = [];
  var ledGeo = null, toteGeo = null;
  function robotBody() {
    if (MODELS.amr) return MODELS.amr.clone(true);
    var g = new THREE.Group();
    var body = new THREE.Mesh(new THREE.BoxGeometry(0.89, 0.24, 0.58), std(0xdfe3e8, 0.4)); body.position.y = 0.17; g.add(body);
    var skirt = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.08, 0.59), std(0x16181c, 0.6)); skirt.position.y = 0.06; g.add(skirt);
    return g;
  }
  function makeRobot(i) {
    var g = new THREE.Group();
    var body = shadowy(robotBody());
    g.add(body);
    g.userData.real = !!MODELS.amr;
    if (!ledGeo) {
      // light strip round the body (a thin frame), the tote and its boxes
      var shape = new THREE.Shape(); var w = 0.462, d = 0.302, r = 0.06;
      shape.moveTo(-w + r, -d); shape.lineTo(w - r, -d); shape.quadraticCurveTo(w, -d, w, -d + r); shape.lineTo(w, d - r); shape.quadraticCurveTo(w, d, w - r, d); shape.lineTo(-w + r, d); shape.quadraticCurveTo(-w, d, -w, d - r); shape.lineTo(-w, -d + r); shape.quadraticCurveTo(-w, -d, -w + r, -d);
      var hole = new THREE.Path(); var wi = w - 0.02, di = d - 0.02;
      hole.moveTo(-wi + r, -di); hole.lineTo(wi - r, -di); hole.quadraticCurveTo(wi, -di, wi, -di + r); hole.lineTo(wi, di - r); hole.quadraticCurveTo(wi, di, wi - r, di); hole.lineTo(-wi + r, di); hole.quadraticCurveTo(-wi, di, -wi, di - r); hole.lineTo(-wi, -di + r); hole.quadraticCurveTo(-wi, -di, -wi + r, -di);
      shape.holes.push(hole);
      ledGeo = new THREE.ExtrudeGeometry(shape, { depth: 0.022, bevelEnabled: false, curveSegments: 6 });
      ledGeo.rotateX(-Math.PI / 2);
      toteGeo = makeTote();
    }
    var ledMat = new THREE.MeshStandardMaterial({ color: 0x0b0f14, emissive: 0x22d3ee, emissiveIntensity: 5, roughness: 0.4 });
    var led = new THREE.Mesh(ledGeo, ledMat); led.position.y = 0.205; g.add(led);
    var tote = toteGeo.clone(true); tote.position.y = 0.335; tote.visible = false; g.add(tote);
    // a soft dark contact shadow under the robot (looks right even without shadow maps)
    var blob = new THREE.Mesh(new THREE.PlaneGeometry(1.15, 0.85), blobMat()); blob.rotation.x = -Math.PI / 2; blob.position.y = 0.006; blob.renderOrder = 1; g.add(blob);
    g.visible = false;
    dyn.add(g);
    return { g: g, body: body, led: led, ledMat: ledMat, tote: tote, last: null, mode: -1, changed: 0, yaw: 0, id: i };
  }
  var blobTex = null;
  function blobMat() {
    if (!blobTex) {
      var c = document.createElement('canvas'); c.width = c.height = 64; var x = c.getContext('2d');
      var gr = x.createRadialGradient(32, 32, 4, 32, 32, 32); gr.addColorStop(0, 'rgba(0,0,0,.55)'); gr.addColorStop(1, 'rgba(0,0,0,0)');
      x.fillStyle = gr; x.fillRect(0, 0, 64, 64); blobTex = new THREE.CanvasTexture(c);
    }
    return new THREE.MeshBasicMaterial({ map: blobTex, transparent: true, depthWrite: false });
  }
  function makeTote() {
    var g = new THREE.Group();
    var blue = std(0x1d4ed8, 0.45, 0, { emissive: 0x0b1f5c, emissiveIntensity: 0.2 });
    var wall = 0.02, w = 0.6, d = 0.4, h = 0.22;
    [[w, h, wall, 0, d / 2 - wall / 2], [w, h, wall, 0, -d / 2 + wall / 2], [wall, h, d, w / 2 - wall / 2, 0], [wall, h, d, -w / 2 + wall / 2, 0], [w, wall, d, 0, -h / 2 + wall / 2]].forEach(function (p) {
      var m = new THREE.Mesh(new THREE.BoxGeometry(p[0], p[1], p[2]), blue); m.position.set(p[3], h / 2 + (p[1] === wall ? -h / 2 + wall / 2 : 0), p[4]); g.add(m);
    });
    var rim = new THREE.Mesh(new THREE.BoxGeometry(w + 0.03, 0.025, d + 0.03), std(0x1e40af, 0.4)); rim.position.y = h; g.add(rim);
    var card = std(0xc8a165, 0.85), card2 = std(0xb98f55, 0.85);
    var b1 = new THREE.Mesh(new THREE.BoxGeometry(0.24, 0.16, 0.18), card); b1.position.set(-0.13, 0.1, -0.06); b1.rotation.y = 0.12; g.add(b1);
    var b2 = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.12, 0.2), card2); b2.position.set(0.14, 0.08, 0.05); b2.rotation.y = -0.2; g.add(b2);
    return shadowy(g);
  }

  // ------------------------------------------------------------------ routes (from the layout's one-way roads)
  var fields = {};
  function field(t) {
    if (fields[t]) return fields[t];
    var C = W * H, Dist = new Int32Array(C).fill(1 << 29), DX = [1, 0, -1, 0], DY = [0, 1, 0, -1];
    var blocked = {}; (LAY.blocked || []).forEach(function (b) { blocked[b[1] * W + b[0]] = 1; });
    Dist[t] = 0; var q = [t], h = 0;
    while (h < q.length) {
      var c = q[h++], x = c % W, y = (c / W) | 0;
      for (var d = 0; d < 4; d++) { // cells p with a move p -> c
        var px = x - DX[d], py = y - DY[d]; if (px < 0 || py < 0 || px >= W || py >= H) continue;
        var p = py * W + px; if (Dist[p] <= Dist[c] + 1 || blocked[c]) continue;
        if (parseInt(LAY.moves[p], 16) & (1 << d)) { Dist[p] = Dist[c] + 1; q.push(p); }
      }
    }
    return (fields[t] = Dist);
  }
  function route(from, to, maxLen) {
    var D = field(to), out = [from], c = from, DX = [1, 0, -1, 0], DY = [0, 1, 0, -1], n = 0;
    while (c !== to && n++ < (maxLen || 120)) {
      var x = c % W, y = (c / W) | 0, m = parseInt(LAY.moves[c], 16), best = -1, bd = D[c];
      for (var d = 0; d < 4; d++) if (m & (1 << d)) { var nc = (y + DY[d]) * W + x + DX[d]; if (D[nc] < bd) { bd = D[nc]; best = nc; } }
      if (best < 0) break; out.push(best); c = best;
    }
    return out;
  }
  var routeMesh = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, depthWrite: false }));
  routeMesh.renderOrder = 2; routeMesh.frustumCulled = false; scene.add(routeMesh);
  var ringGeo = new THREE.RingGeometry(0.24, 0.32, 32); ringGeo.rotateX(-Math.PI / 2);
  var rings = [];
  function buildRoutes(fr, show) {
    var pos = [], col = [], idx = [], tmp = new THREE.Color(), off = fr.off, wv = 0.035;
    rings.forEach(function (r) { r.visible = false; });
    if (!show) { routeMesh.geometry.dispose(); routeMesh.geometry = new THREE.BufferGeometry(); return; }
    var n = 0;
    for (var r = 0; r < fr.n; r++) {
      var cell = fr.v[3 * r], s = fr.v[3 * r + 1], tc = fr.v[3 * r + 2], mode = s >> 2;
      if (cell >= off || tc >= off || cell === tc || (mode !== 1 && mode !== 3)) continue;
      var path = route(cell, tc, 160); if (path.length < 2) continue;
      tmp.setHex(MODE_COLORS[mode]);
      for (var i = 0; i < path.length - 1; i++) {
        var a = path[i], b = path[i + 1];
        var ax = cx(a % W), az = cz((a / W) | 0), bx = cx(b % W), bz = cz((b / W) | 0);
        var dx = bx - ax, dz = bz - az, L = Math.hypot(dx, dz) || 1, nx = -dz / L * wv, nz = dx / L * wv;
        var y = 0.014 + r * 0.0002, al0 = 0.75 * (1 - i / path.length) + 0.12, al1 = 0.75 * (1 - (i + 1) / path.length) + 0.12;
        var base = pos.length / 3;
        pos.push(ax + nx, y, az + nz, ax - nx, y, az - nz, bx + nx, y, bz + nz, bx - nx, y, bz - nz);
        col.push(tmp.r, tmp.g, tmp.b, al0, tmp.r, tmp.g, tmp.b, al0, tmp.r, tmp.g, tmp.b, al1, tmp.r, tmp.g, tmp.b, al1);
        idx.push(base, base + 2, base + 1, base + 1, base + 2, base + 3);
      }
      var ring = rings[n] || (rings[n] = (function () { var m = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.9, depthWrite: false })); m.renderOrder = 3; scene.add(m); return m; })());
      ring.material.color.setHex(MODE_COLORS[mode]); ring.position.set(cx(tc % W), 0.016, cz((tc / W) | 0)); ring.visible = true; n++;
    }
    var geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 4));
    geo.setIndex(idx);
    routeMesh.geometry.dispose(); routeMesh.geometry = geo;
  }

  // ------------------------------------------------------------------ heat map of waiting
  var heatTex = null, heatMesh = null, heatData = null;
  function setHeat(item) {
    if (!LAY || !item || item.w !== W) return;
    var raw = atob(item.v), n = raw.length;
    if (!heatData || heatData.length !== W * H * 4) {
      heatData = new Uint8Array(W * H * 4);
      heatTex = new THREE.DataTexture(heatData, W, H, THREE.RGBAFormat);
      heatTex.magFilter = THREE.LinearFilter; heatTex.minFilter = THREE.LinearFilter; heatTex.flipY = false;
      if (heatMesh) scene.remove(heatMesh);
      heatMesh = new THREE.Mesh(new THREE.PlaneGeometry(W, H), new THREE.MeshBasicMaterial({ map: heatTex, transparent: true, depthWrite: false }));
      heatMesh.rotation.x = -Math.PI / 2; heatMesh.position.y = 0.011; heatMesh.renderOrder = 1; scene.add(heatMesh);
    }
    for (var c = 0; c < W * H && c < n; c++) {
      var v = raw.charCodeAt(c) / 255, x = c % W, y = (c / W) | 0, o = ((H - 1 - y) * W + x) * 4;
      v = Math.sqrt(v);
      heatData[o] = 255; heatData[o + 1] = Math.round(220 * (1 - v) + 40 * v); heatData[o + 2] = Math.round(60 * (1 - v));
      heatData[o + 3] = v < 0.04 ? 0 : Math.round(40 + 170 * v);
    }
    heatTex.needsUpdate = true;
    heatMesh.visible = UI.heat;
  }

  // ------------------------------------------------------------------ data from the run
  var frames = [], kpis = [], layouts = [], heats = [], events = [];
  var lastT = {}, liveKpi = null;
  function decode(b64) { var s = atob(b64), u = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return new Uint16Array(u.buffer); }
  function ingest() {
    var stream = ctx.input('live').stream || [];
    var fresh = false;
    for (var i = 0; i < stream.length; i++) {
      var it = stream[i], ch = it.channel, d = it.data;
      if (!d || typeof d !== 'object') continue;
      var key = ch + '|' + (it.node || '');
      if (lastT[key] != null && it.t <= lastT[key]) continue;
      lastT[key] = it.t; fresh = true;
      if (ch === 'fleet' && Array.isArray(d.f)) {
        for (var k = 0; k < d.f.length; k++) {
          var t = d.t + k * d.dt;
          if (frames.length && t <= frames[frames.length - 1].t + 1e-6) continue;
          frames.push({ t: t, v: decode(d.f[k]), n: d.n, off: d.off });
        }
        dt = d.dt || dt;
      } else if (ch === 'kpi') { kpis.push(d); liveKpi = d; }
      else if (ch === 'layout' && d.format === 'esasim.warehouse/1') layouts.push(d);
      else if (ch === 'heat') heats.push(d);
      else if (ch === 'event') events.push(d);
    }
    if (layouts.length) {
      var Lnow = layouts[layouts.length - 1];
      var sig = Lnow.w + 'x' + Lnow.h + Lnow.kinds;
      if (sig !== layoutSig) { layoutSig = sig; LAY = Lnow; W = LAY.w; H = LAY.h; fields = {}; rebuild(); }
    }
    if (fresh) showHint();
    return fresh;
  }
  var dt = 0.6;
  function atTime(list, t) { // the last item of a list (sorted by .t) at or before t
    var lo = 0, hi = list.length - 1, best = -1;
    while (lo <= hi) { var mid = (lo + hi) >> 1; if (list[mid].t <= t + 1e-6) { best = mid; lo = mid + 1; } else hi = mid - 1; }
    return best < 0 ? null : list[best];
  }
  function frameIndex(t) {
    var lo = 0, hi = frames.length - 1, best = 0;
    while (lo <= hi) { var mid = (lo + hi) >> 1; if (frames[mid].t <= t) { best = mid; lo = mid + 1; } else hi = mid - 1; }
    return best;
  }

  // ------------------------------------------------------------------ the clock: live (a little behind the run) or replay
  var clockT = null, replay = { playing: true, speed: 4 };
  function isLive() { var r = ctx.run || {}; return !!r.active; }
  function advanceClock(dw) {
    if (!frames.length) return;
    var first = frames[0].t, last = frames[frames.length - 1].t;
    if (isLive()) {
      var k = liveKpi || {}, spd = k.paused ? 0 : (+k.speed || 1);
      var lagTarget = Math.max(1.2, +P.delay || 2.5) * Math.max(spd, 0.5);
      if (clockT === null || clockT < first) clockT = Math.max(first, last - lagTarget);
      var lag = last - clockT;
      if (lag > lagTarget * 6 + 10) clockT = last - lagTarget;
      var rate = lag > lagTarget * 1.8 ? 1.7 : lag > lagTarget * 1.2 ? 1.15 : lag < lagTarget * 0.4 ? 0.55 : lag < lagTarget * 0.8 ? 0.88 : 1;
      clockT = Math.min(last, clockT + dw * spd * rate);
    } else {
      if (clockT === null) clockT = first;
      if (replay.playing) { clockT += dw * replay.speed; if (clockT > last) clockT = first; }
      clockT = Math.max(first, Math.min(last, clockT));
    }
  }

  // ------------------------------------------------------------------ pose of the robots at the clock
  var lastFrameIdx = -1;
  var tmpV = new THREE.Vector3();
  function yawOf(h) { return h * Math.PI / 2; }
  function cellPos(c) { return [cx(c % W), cz((c / W) | 0)]; }
  function poseRobots(now) {
    if (!LAY || !frames.length || clockT === null) return;
    var i = frameIndex(clockT), f0 = frames[i], f1 = frames[Math.min(i + 1, frames.length - 1)];
    var fp = frames[Math.max(0, i - 1)], f2 = frames[Math.min(i + 2, frames.length - 1)];
    var u = f1 === f0 ? 0 : Math.max(0, Math.min(1, (clockT - f0.t) / (f1.t - f0.t)));
    var n = f0.n, off = f0.off;
    while (robots.length < n) robots.push(makeRobot(robots.length));
    var busyCells = {};
    for (var r = 0; r < robots.length; r++) {
      var R = robots[r];
      if (r >= n) { R.g.visible = false; continue; }
      var c0 = f0.v[3 * r], c1 = f1.v[3 * r], s0 = f0.v[3 * r + 1], s1 = f1.v[3 * r + 1];
      if (c0 >= off && c1 >= off) { R.g.visible = false; R.mode = -1; continue; }
      var a = c0 >= off ? c1 : c0, b = c1 >= off ? c0 : c1;
      var pa = cellPos(a), pb = cellPos(b), e = u;
      if (a !== b) {
        var movedBefore = fp.v[3 * r] !== c0 && fp !== f0, movesAfter = f2.v[3 * r] !== c1 && f2 !== f1;
        e = movedBefore && movesAfter ? u : movedBefore ? easeOut(u) : movesAfter ? easeIn(u) : smooth(u);
      }
      R.g.visible = true;
      R.g.position.set(pa[0] + (pb[0] - pa[0]) * e, 0, pa[1] + (pb[1] - pa[1]) * e);
      var h0 = s0 & 3, h1 = s1 & 3, y0 = yawOf(h0), y1 = yawOf(h1), dy = y1 - y0;
      if (dy > Math.PI) dy -= 2 * Math.PI; if (dy < -Math.PI) dy += 2 * Math.PI;
      R.g.rotation.y = h0 === h1 ? y0 : y0 + dy * smooth(u);
      var mode = s0 >> 2;
      if (c0 >= off && c1 < off) { var sc = 0.2 + 0.8 * u; R.g.scale.setScalar(sc); } else if (c1 >= off) R.g.scale.setScalar(1 - 0.8 * u); else R.g.scale.setScalar(1);
      // waiting: wanted to move, did not move or turn
      var stillBefore = fp.v[3 * r] === c0 && (fp.v[3 * r + 1] & 3) === h0;
      var waiting = (mode === 1 || mode === 3) && c0 === c1 && h0 === h1 && stillBefore && c0 !== f0.v[3 * r + 2];
      if (mode !== R.mode) { R.changed = now; R.prevMode = R.mode; R.mode = mode; }
      var col = waiting ? WAIT_COLOR : MODE_COLORS[mode];
      R.ledMat.emissive.setHex(col);
      var pulse = waiting ? 4 + 2 * Math.sin(now * 0.012) : mode === 2 ? 4.5 + 1.5 * Math.sin(now * 0.008) : mode === 0 ? 1.4 : 5;
      R.ledMat.emissiveIntensity = pulse;
      var carry = mode === 3 || mode === 4;
      R.tote.visible = carry;
      if (carry) { var k = Math.min(1, (now - R.changed) / 420), sk = R.prevMode === 2 && mode === 3 ? 1 + 0.12 * Math.sin(k * Math.PI) : 1; R.tote.scale.setScalar(R.prevMode === 2 && mode === 3 ? Math.max(0.05, k) * sk : 1); }
      R.cell = c0; R.target = f0.v[3 * r + 2]; R.waiting = waiting;
      if (mode === 4) busyCells[c0] = 1;
      if (mode === 2) pickLight(r, c0, now);
    }
    pickLightsDone();
    stationLights.forEach(function (s) {
      var busy = !!busyCells[s.cell];
      s.lamps[2].material.emissiveIntensity = busy ? 5 : 0.15;
      s.lamps[1].material.emissiveIntensity = !busy && queueAt(s.cell, f0) ? 4 : 0.15;
    });
    if (i !== lastFrameIdx) { lastFrameIdx = i; buildRoutes(f0, UI.routes); }
  }
  function queueAt(cell, fr) { // robots waiting in this station's lane
    var x = cell % W, n = 0;
    for (var r = 0; r < fr.n; r++) { var c = fr.v[3 * r]; if (c < fr.off && c % W === x && ((c / W) | 0) <= 3 && ((c / W) | 0) >= 2) n++; }
    return n;
  }
  // put-to-light: a light on the rack beside a robot that picks
  var pickPool = [], pickUsed = 0;
  var pickGeo = new THREE.BoxGeometry(0.05, 0.08, 0.6);
  function pickLight(r, cell, now) {
    var m = pickPool[pickUsed] || (pickPool[pickUsed] = (function () { var o = new THREE.Mesh(pickGeo, new THREE.MeshStandardMaterial({ color: 0x111, emissive: 0x4ade80, emissiveIntensity: 3 })); scene.add(o); return o; })());
    pickUsed++;
    var x = cell % W, y = (cell / W) | 0, side = kindAt(x + 1, y) === 'r' && (kindAt(x - 1, y) !== 'r' || ((x * 7 + y * 3 + r) & 1)) ? 1 : -1;
    m.position.set(cx(x) + side * 0.5, 0.75 + ((y * 5 + r) % 3) * 0.75, cz(y)); m.visible = true;
    m.material.emissiveIntensity = 4.5 + Math.sin(now * 0.01) * 1.5;
  }
  function pickLightsDone() { for (var i = pickUsed; i < pickPool.length; i++) pickPool[i].visible = false; pickUsed = 0; }

  // ------------------------------------------------------------------ overlay: KPIs, events, controls
  var UI = { routes: P.routes !== false, heat: !!P.heat, blockMode: false, cam: P.camera === 'cinematic' ? 'cinematic' : 'orbit', follow: -1 };
  var hud = document.createElement('div'); hud.className = 'wf'; el.appendChild(hud);
  hud.innerHTML =
    '<div class="top">' +
    '  <div class="glass title"><b>Warehouse fleet</b><span class="badge cpu" data-k="badge"><i></i><span>waiting for the run</span></span><div class="sub" data-k="sub"></div></div>' +
    '  <div class="kpis">' +
    '    <div class="glass kpi"><span>Orders / hour</span><b data-k="orders">–</b><canvas width="120" height="26" data-k="spark"></canvas></div>' +
    '    <div class="glass kpi"><span>Avg order time</span><b data-k="avg">–</b><small data-k="done"></small></div>' +
    '    <div class="glass kpi"><span>Robots busy</span><b data-k="util">–</b><small data-k="fleet"></small></div>' +
    '    <div class="glass kpi"><span>Orders waiting</span><b data-k="backlog">–</b><small data-k="rate"></small></div>' +
    '    <div class="glass kpi"><span>Simulated</span><b data-k="clock">–</b><small data-k="steps"></small></div>' +
    '  </div>' +
    '</div>' +
    '<div class="events" data-k="events"></div>' +
    '<div class="bottom">' +
    '<div class="glass legend"><span><i style="background:#22d3ee"></i>to a pick face</span><span><i style="background:#fbbf24"></i>picking</span><span><i style="background:#34d399"></i>tote to a station</span><span><i style="background:#a78bfa"></i>at the station</span><span><i style="background:#ef4444"></i>waiting</span></div>' +
    '<div class="glass bar">' +
    '  <div class="ctl" data-run><label>Order rate</label><input type="range" min="0" max="3000" step="50" data-k="rateIn"><output data-k="rateOut"></output></div>' +
    '  <div class="ctl" data-run><label>Robots</label><input type="range" min="1" max="50" step="1" data-k="robotsIn"><output data-k="robotsOut"></output></div>' +
    '  <div class="ctl" data-k="speeds"><label>Speed</label><button data-sp="1">1×</button><button data-sp="2">2×</button><button data-sp="4">4×</button><button data-sp="8">8×</button></div>' +
    '  <button data-k="pause" data-run>Pause</button>' +
    '  <div class="sep" data-run></div>' +
    '  <button class="warn" data-run data-k="block" title="Then click an aisle: a pallet left there closes it; click it again to open it">Block an aisle</button>' +
    '  <button data-k="clear" data-run>Open all</button>' +
    '  <div class="sep"></div>' +
    '  <button data-k="routes">Routes</button><button data-k="heat">Heat map</button><button data-k="cam">Cinematic</button>' +
    '  <div class="grow"></div>' +
    '  <div class="ctl" data-k="replay" hidden><button data-k="play">⏸</button><input type="range" min="0" max="1000" value="0" data-k="scrub" style="width:200px"><output data-k="replayT"></output></div>' +
    '</div></div>' +
    '<div class="glass hint" data-k="hint" hidden></div>' +
    '<div class="glass tip" data-k="tip" hidden></div>';
  var $ = function (k) { return hud.querySelector('[data-k="' + k + '"]'); };
  function setOn(k, on) { $(k).classList.toggle('on', !!on); }
  setOn('routes', UI.routes); setOn('heat', UI.heat); setOn('cam', UI.cam === 'cinematic');

  function send(data) {
    if (!isLive()) { toast('The run has ended: run the blueprint to change it live.'); return; }
    ctx.send('control', data).catch(function (e) { toast('Not sent: ' + e.message); });
  }
  var rateIn = $('rateIn'), robotsIn = $('robotsIn');
  rateIn.addEventListener('input', function () { $('rateOut').textContent = rateIn.value; rateIn.dataset.touched = performance.now(); });
  rateIn.addEventListener('change', function () { send({ rate: +rateIn.value }); });
  robotsIn.addEventListener('input', function () { $('robotsOut').textContent = robotsIn.value; robotsIn.dataset.touched = performance.now(); });
  robotsIn.addEventListener('change', function () { send({ robots: +robotsIn.value }); });
  hud.querySelectorAll('[data-sp]').forEach(function (b) {
    b.addEventListener('click', function () { if (isLive()) send({ speed: +b.dataset.sp }); else { replay.speed = +b.dataset.sp; markSpeeds(); } });
  });
  $('pause').addEventListener('click', function () { send({ pause: !(liveKpi && liveKpi.paused) }); });
  $('block').addEventListener('click', function () { UI.blockMode = !UI.blockMode; setOn('block', UI.blockMode); renderer.domElement.style.cursor = UI.blockMode ? 'crosshair' : ''; if (!UI.blockMode) hover.visible = false; });
  $('clear').addEventListener('click', function () { send({ clear: true }); });
  $('routes').addEventListener('click', function () { UI.routes = !UI.routes; setOn('routes', UI.routes); lastFrameIdx = -1; });
  $('heat').addEventListener('click', function () { UI.heat = !UI.heat; setOn('heat', UI.heat); if (heatMesh) heatMesh.visible = UI.heat; });
  $('cam').addEventListener('click', function () { UI.cam = UI.cam === 'cinematic' ? 'orbit' : 'cinematic'; UI.follow = -1; setOn('cam', UI.cam === 'cinematic'); keep(); });
  $('play').addEventListener('click', function () { replay.playing = !replay.playing; $('play').textContent = replay.playing ? '⏸' : '▶'; });
  $('scrub').addEventListener('input', function () {
    if (!frames.length) return; var a = frames[0].t, b = frames[frames.length - 1].t;
    clockT = a + (b - a) * (+$('scrub').value / 1000); replay.playing = false; $('play').textContent = '▶';
  });
  function markSpeeds() {
    var cur = isLive() ? (liveKpi ? +liveKpi.speed : 0) : replay.speed;
    hud.querySelectorAll('[data-sp]').forEach(function (b) { b.classList.toggle('on', +b.dataset.sp === cur); });
  }
  var toasts = [];
  function toast(text) { toasts.push({ text: text, at: performance.now() }); drawEvents(); }
  var shownEvents = '';
  function drawEvents() {
    var now = performance.now(), list = events.filter(function (e) { return clockT === null || e.t <= clockT + 0.01; }).slice(-4);
    var html = list.map(function (e) { return '<div class="glass ev"><em>' + mmss(e.t) + '</em>' + esc(e.text) + '</div>'; }).join('') +
      toasts.filter(function (t) { return now - t.at < 5000; }).map(function (t) { return '<div class="glass ev" style="border-color:rgba(248,113,113,.5)">' + esc(t.text) + '</div>'; }).join('');
    if (html !== shownEvents) { shownEvents = html; $('events').innerHTML = html; }
  }
  var hintEl = $('hint');
  function showHint() {
    var msg = '';
    if (!frames.length && !LAY) msg = isLive() ? 'The warehouse is starting…' : '<b>Warehouse fleet</b><br>Run the blueprint: the robots appear here, and the bar below changes the order rate, the fleet and the aisles while it runs.';
    hintEl.hidden = !msg; if (msg) hintEl.innerHTML = msg;
  }
  var sparkC = $('spark').getContext('2d');
  var hudAt = 0;
  function drawHud(now) {
    if (now - hudAt < 200) return; hudAt = now;
    var live = isLive();
    var k = live ? liveKpi : atTime(kpis, clockT === null ? -1 : clockT);
    if (k) {
      $('orders').textContent = fmt(k.orders_h);
      $('avg').textContent = k.avg_order_s ? mmss(k.avg_order_s) : '–';
      $('done').textContent = fmt(k.done) + ' orders done';
      $('util').textContent = Math.round(100 * (k.utilization || 0)) + '%';
      $('fleet').textContent = k.on_floor + ' robots · ' + k.waiting + ' waiting';
      $('backlog').textContent = fmt(k.backlog);
      $('rate').textContent = fmt(k.order_rate) + ' new per hour';
      var b = $('badge'); b.className = 'badge ' + (k.kind || 'cpu'); b.querySelector('span').textContent = 'Simulated on ' + k.backend;
      $('sub').textContent = (k.replan_ms ? 'Routes planned in ' + fmt(k.replan_ms, 1) + ' ms' : '') + (k.blocked ? ' · ' + k.blocked + ' aisle' + (k.blocked > 1 ? 's' : '') + ' blocked' : '');
      $('steps').textContent = live ? (k.paused ? 'paused' : fmt(k.speed) + '× real time') : 'replay';
      if (live) {
        if (!rateIn.dataset.touched || now - rateIn.dataset.touched > 4000) { rateIn.value = k.order_rate; $('rateOut').textContent = fmt(k.order_rate); }
        if (!robotsIn.dataset.touched || now - robotsIn.dataset.touched > 4000) { robotsIn.value = k.robots; $('robotsOut').textContent = k.robots; }
        $('pause').textContent = k.paused ? 'Resume' : 'Pause';
      }
      // sparkline of orders per hour
      var pts = kpis.filter(function (q) { return q.t <= (clockT || 0) + 0.01; }).slice(-120);
      sparkC.clearRect(0, 0, 120, 26);
      if (pts.length > 1) {
        var mx = Math.max.apply(null, pts.map(function (q) { return q.orders_h; }).concat([10]));
        sparkC.strokeStyle = '#38bdf8'; sparkC.lineWidth = 1.5; sparkC.beginPath();
        pts.forEach(function (q, j) { var x = j / (pts.length - 1) * 118 + 1, y = 24 - q.orders_h / mx * 22; if (j) sparkC.lineTo(x, y); else sparkC.moveTo(x, y); });
        sparkC.stroke();
      }
    }
    if (LAY && robotsIn.max != LAY.robots_max) robotsIn.max = LAY.robots_max || 50;
    $('clock').textContent = clockT === null ? '–' : mmss(clockT);
    hud.querySelectorAll('[data-run]').forEach(function (b) { b.hidden = !live; });
    $('replay').hidden = live || !frames.length;
    if (!live && frames.length) {
      var a = frames[0].t, z = frames[frames.length - 1].t;
      $('scrub').value = Math.round(1000 * ((clockT || a) - a) / Math.max(1e-6, z - a));
      $('replayT').textContent = mmss((clockT || a) - a) + ' / ' + mmss(z - a);
    }
    markSpeeds();
    drawEvents();
    showHint();
  }

  // ------------------------------------------------------------------ pointer: hover, block an aisle, follow a robot
  var ray = new THREE.Raycaster(), mouse = new THREE.Vector2(), ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
  var hover = new THREE.Mesh(new THREE.PlaneGeometry(0.98, 0.98), new THREE.MeshBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0.45, depthWrite: false }));
  hover.rotation.x = -Math.PI / 2; hover.position.y = 0.02; hover.visible = false; hover.renderOrder = 4; scene.add(hover);
  var tip = $('tip'), down = null;
  function cellUnder(ev) {
    var rc = renderer.domElement.getBoundingClientRect();
    mouse.set(((ev.clientX - rc.left) / rc.width) * 2 - 1, -((ev.clientY - rc.top) / rc.height) * 2 + 1);
    ray.setFromCamera(mouse, camera);
    var p = ray.ray.intersectPlane(ground, tmpV); if (!p || !LAY) return null;
    var x = Math.floor(p.x + W / 2), y = Math.floor(-p.z + H / 2);
    return x >= 0 && y >= 0 && x < W && y < H ? { x: x, y: y, p: p.clone() } : null;
  }
  function robotUnder(ev) {
    var c = cellUnder(ev); if (!c) return -1;
    var best = -1, bd = 0.6;
    robots.forEach(function (R, i) { if (!R.g.visible) return; var d = Math.hypot(R.g.position.x - c.p.x, R.g.position.z - c.p.z); if (d < bd) { bd = d; best = i; } });
    return best;
  }
  renderer.domElement.addEventListener('pointerdown', function (ev) { down = { x: ev.clientX, y: ev.clientY }; });
  renderer.domElement.addEventListener('pointermove', function (ev) {
    var rc = el.getBoundingClientRect();
    if (UI.blockMode) {
      var c = cellUnder(ev);
      if (c) { var k = kindAt(c.x, c.y), ok = k === 'a' || k === 'c'; hover.visible = true; hover.position.x = cx(c.x); hover.position.z = cz(c.y); hover.material.color.setHex(ok ? 0xef4444 : 0x64748b); }
      else hover.visible = false;
      tip.hidden = true; return;
    }
    var r = robotUnder(ev);
    if (r >= 0 && robots[r].mode >= 0) {
      tip.hidden = false; tip.style.left = (ev.clientX - rc.left) + 'px'; tip.style.top = (ev.clientY - rc.top) + 'px';
      tip.textContent = 'Robot ' + (r + 1) + ' · ' + (robots[r].waiting ? 'Waiting for the way to clear' : MODE_NAMES[robots[r].mode]) + ' · click to follow';
    } else tip.hidden = true;
  });
  renderer.domElement.addEventListener('pointerup', function (ev) {
    if (!down || Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 5) return;
    if (UI.blockMode) {
      var c = cellUnder(ev); if (!c) return;
      var k = kindAt(c.x, c.y);
      if (k !== 'a' && k !== 'c') { toast('Only aisles can be blocked.'); return; }
      var isB = (LAY.blocked || []).some(function (b) { return b[0] === c.x && b[1] === c.y; });
      send(isB ? { unblock: [c.x, c.y] } : { block: [c.x, c.y] });
      return;
    }
    var r = robotUnder(ev);
    UI.follow = r; if (r >= 0) { UI.cam = 'follow'; setOn('cam', false); toast('Following robot ' + (r + 1) + ': drag or press Esc to stop.'); }
  });
  window.addEventListener('keydown', function (e) { if (e.key === 'Escape') { UI.follow = -1; UI.cam = 'orbit'; UI.blockMode = false; setOn('block', false); hover.visible = false; renderer.domElement.style.cursor = ''; } });
  controls.addEventListener('start', function () { if (UI.cam !== 'orbit') { UI.cam = 'orbit'; UI.follow = -1; setOn('cam', false); } });
  controls.addEventListener('end', keep);

  // ------------------------------------------------------------------ camera
  var camSet = false;
  function homeCamera() {
    if (!W) return;
    var d = Math.max(W, H);
    camera.position.set(d * 0.42, d * 0.78, d * 0.95); controls.target.set(0, 0, d * 0.04);
    camera.updateProjectionMatrix(); camSet = true;
  }
  var orbitA = null;
  function moveCamera(dw, now) {
    if (UI.cam === 'cinematic' && W) {
      var c = controls.target, off = camera.position.clone().sub(c);
      var r = Math.hypot(off.x, off.z), h = off.y;
      if (orbitA === null) orbitA = Math.atan2(off.z, off.x);
      orbitA += dw * 0.045;
      var want = Math.max(W, H) * 0.95, wantH = Math.max(W, H) * 0.55 + Math.sin(now * 0.00017) * 3;
      r += (want - r) * 0.01; h += (wantH - h) * 0.01;
      c.lerp(tmpV.set(0, 0, 0), 0.01);
      camera.position.set(c.x + Math.cos(orbitA) * r, h, c.z + Math.sin(orbitA) * r);
    } else orbitA = null;
    if (UI.cam === 'follow' && UI.follow >= 0 && robots[UI.follow] && robots[UI.follow].g.visible) {
      var p = robots[UI.follow].g.position, delta = p.clone().sub(controls.target);
      var step = delta.multiplyScalar(0.08);
      controls.target.add(step); camera.position.add(step);
      var dist = camera.position.distanceTo(controls.target);
      if (dist > 9) camera.position.lerp(controls.target, 0.02);
    }
    controls.update();
  }
  function keep() {
    if (!ctx.saveState) return;
    ctx.saveState({ cam: { p: camera.position.toArray(), t: controls.target.toArray() }, ui: { routes: UI.routes, heat: UI.heat, cam: UI.cam === 'cinematic' ? 'cinematic' : 'orbit' } });
  }
  var was = ctx.state || {};
  if (was.cam && Array.isArray(was.cam.p)) { camera.position.fromArray(was.cam.p); controls.target.fromArray(was.cam.t); camSet = true; }
  if (was.ui) { UI.routes = was.ui.routes !== false; UI.heat = !!was.ui.heat; UI.cam = was.ui.cam || UI.cam; setOn('routes', UI.routes); setOn('heat', UI.heat); setOn('cam', UI.cam === 'cinematic'); }

  // ------------------------------------------------------------------ loop
  function resize() {
    var w = Math.max(10, el.clientWidth), h = Math.max(10, el.clientHeight);
    renderer.setSize(w, h, false); renderer.domElement.style.width = w + 'px'; renderer.domElement.style.height = h + 'px';
    if (composer) composer.setSize(w, h);
    if (bloom) bloom.resolution.set(w, h);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  var prev = performance.now(), heatShown = null;
  function tick() {
    if (!renderer.domElement.isConnected) { renderer.dispose(); return; }
    requestAnimationFrame(tick);
    var now = performance.now(), dw = Math.min(0.1, (now - prev) / 1000); prev = now;
    advanceClock(dw);
    poseRobots(now);
    var hItem = clockT === null ? null : atTime(heats, clockT);
    if (hItem && hItem !== heatShown) { heatShown = hItem; setHeat(hItem); }
    var Lt = clockT === null ? null : atTime(layouts.filter(function (l) { return l.t != null; }), clockT);
    if (Lt && LAY && JSON.stringify(Lt.blocked) !== JSON.stringify(LAY.blocked)) { LAY = Object.assign({}, LAY, { blocked: Lt.blocked }); buildBlocked(); lastFrameIdx = -1; }
    moveCamera(dw, now);
    drawHud(now);
    if (composer) composer.render(); else renderer.render(scene, camera);
  }
  ctx.on('update', function () { ingest(); loadModels(); });
  var runId = (ctx.run || {}).id;
  ctx.on('run', function (r) {
    if (r && r.id !== runId) { // another run: start again from its data
      runId = r.id; frames = []; kpis = []; layouts = []; heats = []; events = []; lastT = {}; liveKpi = null; layoutSig = ''; lastFrameIdx = -1; heatShown = null;
      ingest();
    }
    clockT = null; drawHud(performance.now() + 1000);
  });
  ctx.on('resize', resize);
  resize();
  loadModels();
  ingest();
  showHint();
  tick();
}
