/*
 * Maquette 3D d'un Site — module infrastructure (Student 1).
 *
 * Lit le JSON de la vue site_maquette_json (voir docs/CONTRAT_JSON.md) et dessine :
 * zones, canalisations souterraines, pompes, compteurs (Student 2), fuites (Student 3).
 * Dépendances : Three.js r128 + OrbitControls (chargés par le template).
 */
(function () {
  "use strict";

  const root = document.getElementById("maquette-root");
  if (!root) return;

  const STATUS = {
    en_service: { label: "En service", tone: "ok" },
    a_surveiller: { label: "À surveiller", tone: "warn" },
    en_panne: { label: "En panne", tone: "crit" },
    hors_service: { label: "Hors service", tone: "none" }
  };
  const MW_TYPE = { preventive: "Préventive", corrective: "Corrective" };
  const TONE_RANK = { none: -1, ok: 0, warn: 1, crit: 2 };
  const riskTone = r => r == null ? "none" : r < 0.3 ? "ok" : r < 0.6 ? "warn" : "crit";
  const fmtDate = d => d ? new Date(d + "T00:00:00").toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" }) : "Aucune";
  const fmtMonth = d => new Date(d + "T00:00:00").toLocaleDateString("fr-FR", { month: "short" });
  const pct = r => r == null ? "non calculé" : Math.round(r * 100) + " %";
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const WRENCH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.2L3 17.8V21h3.2l6.3-6.3a4 4 0 0 0 5.2-5.4l-2.6 2.6-2.4-.4-.4-2.4z"/></svg>';
  const csrf = () => (document.querySelector("input[name=csrfmiddlewaretoken]") || {}).value || "";
  const fill = (tpl, id) => tpl.replace("__id__", id);

  fetch(root.dataset.url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
    .then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(start)
    .catch(err => {
      document.getElementById("stage").innerHTML = '<p class="err">Impossible de charger les données du site (' + esc(err.message) + "). Rechargez la page.</p>";
    });

  function monthEnds(fromIso, toIso) {
    const out = [];
    const to = new Date(toIso + "T00:00:00");
    let d = new Date(fromIso + "T00:00:00");
    d = new Date(d.getFullYear(), d.getMonth() + 1, 0);
    while (d < to) {
      out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
      d = new Date(d.getFullYear(), d.getMonth() + 2, 0);
    }
    return out;
  }

  function start(DATA) {
    const stage = document.getElementById("stage");
    const labelsEl = document.getElementById("labels");
    document.getElementById("json-src").textContent = JSON.stringify(DATA, null, 2);
    if (typeof THREE === "undefined" || !THREE.OrbitControls) {
      stage.innerHTML = '<p class="err">La bibliothèque 3D n\'a pas pu être chargée (connexion internet nécessaire pour le CDN).</p>';
      return;
    }
    if (!DATA.zones.length) {
      stage.innerHTML = '<p class="err">Ce site n\'a encore aucune zone. Ajoutez une zone depuis la fiche du site.</p>';
      return;
    }

    // ---------- Timeline built from the dates present in the data ----------
    const TODAY = DATA.today;
    const allDates = [];
    DATA.meters.forEach(m => m.readings.forEach(r => allDates.push(r[0])));
    DATA.works.forEach(w => { allDates.push(w.scheduled_at); if (w.completed_at) allDates.push(w.completed_at); });
    DATA.incidents.forEach(i => allDates.push(i.opened_at));
    DATA.equipment.forEach(e => e.history.forEach(h => allDates.push(h[0])));
    const earliest = allDates.filter(Boolean).sort()[0] || TODAY;
    const TIMELINE = monthEnds(earliest, TODAY).slice(-11).concat([TODAY]);

    // ---------- UI state ----------
    const ui = { colorMode: "status", type: "all", highRisk: false, focusZone: null, sel: null, flowOn: !reduceMotion, xray: true, edit: false, t: TIMELINE.length - 1 };
    let scn = null;
    const date = () => scn ? TODAY : TIMELINE[ui.t];
    const scnIncident = DATA.incidents.find(i => i.suspected_pipe) || null;

    // ---------- Domain helpers (mirror model methods) ----------
    const zoneById = id => DATA.zones.find(z => z.id === id);
    const eqByRef = ref => DATA.equipment.find(e => e.reference === ref);
    const meterBySerial = s => DATA.meters.find(m => m.serial_number === s);
    const techName = id => (DATA.technicians.find(t => t.id === id) || {}).name || "Non assigné";

    function eqState(eq) {
      const d = date();
      let h = eq.history[0];
      for (const x of eq.history) if (x[0] <= d) h = x;
      let status = h[1];
      if (scn && scnIncident && eq.reference === scnIncident.suspected_pipe && (scn.step === 2 || (scn.step === 3 && !scn.arrived))) status = "a_surveiller";
      return { status, risk: h[2] };
    }
    function toneOf(eq) { const s = eqState(eq); return ui.colorMode === "status" ? (STATUS[s.status] || STATUS.en_service).tone : riskTone(s.risk); }
    function readingsOf(m) { const d = date(); return m.readings.filter(x => x[0] <= d); }
    function monthly(m) { // calculate_volume(): difference between consecutive cumulative indexes
      const r = readingsOf(m), out = [];
      for (let i = 1; i < r.length; i++) out.push({ d: r[i][0], m3: Math.round((r[i][1] - r[i - 1][1]) * 10) / 10 });
      return out;
    }
    function isSpike(series, i) {
      if (i < 3) return false;
      const avg = (series[i - 1].m3 + series[i - 2].m3 + series[i - 3].m3) / 3;
      return series[i].m3 > 1.4 * avg;
    }
    function lastCons(zoneId) {
      const ms = DATA.meters.filter(x => x.zone === zoneId);
      if (!ms.length) return null;
      return ms.reduce((sum, m) => { const s = monthly(m); return sum + (s.length ? s[s.length - 1].m3 : 0); }, 0);
    }
    function worksFor(ref) { return DATA.works.filter(w => (w.pipe === ref || w.pump === ref) && w.scheduled_at <= date()); }
    function openWork(ref) { const d = date(); return worksFor(ref).find(w => !w.completed_at || w.completed_at > d); }
    function activeIncidents() {
      const d = date();
      return DATA.incidents.filter(i => {
        if (scn) return i === scnIncident && (scn.step === 2 || (scn.step === 3 && !scn.arrived));
        return i.opened_at && i.opened_at <= d && (!i.resolved_at || i.resolved_at > d);
      });
    }
    function eqVisible(eq) {
      if (ui.type !== "all" && eq.type !== ui.type) return false;
      if (ui.highRisk && !(eqState(eq).risk >= 0.6)) return false;
      return true;
    }
    function zoneWorst(zoneId) {
      let w = "ok";
      DATA.equipment.filter(e => e.zone === zoneId && e.role !== "main").forEach(e => { const t = toneOf(e); if (TONE_RANK[t] > TONE_RANK[w]) w = t; });
      if (activeIncidents().some(i => (eqByRef(i.suspected_pipe) || eqByRef(i.suspected_pump) || {}).zone === zoneId)) w = "crit";
      return w;
    }
    const inFocus = eq => !ui.focusZone || eq.zone === ui.focusZone || eq.role === "main";

    // ---------- Header ----------
    document.getElementById("site-facts").innerHTML = [["Type", DATA.site.site_type], ["Gouvernorat", DATA.site.governorate], ["Zones", DATA.zones.length], ["Équipements", DATA.equipment.length], ["Compteurs", DATA.meters.length]]
      .map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("");

    // ---------- Three.js setup ----------
    const css = n => getComputedStyle(root).getPropertyValue(n).trim();
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    stage.prepend(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 600);
    const ZW = 8, ZD = 7, PY = -0.7;
    const spanX = Math.max(38, DATA.zones.length * (ZW + 3) + 8);
    const GW = spanX, GD = 26, ENTRY_Z = 10.5;
    const HOME = { pos: new THREE.Vector3(GW * 0.5, 22, 28), target: new THREE.Vector3(0, 0, 0) };
    camera.position.copy(HOME.pos);
    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI * 0.47;
    controls.minDistance = 8; controls.maxDistance = 120;

    scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 0.55));
    const sun = new THREE.DirectionalLight(0xffffff, 0.8);
    sun.position.set(14, 26, 12);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -GW / 2 - 4, right: GW / 2 + 4, top: 24, bottom: -24 });
    scene.add(sun);

    const std = (o = {}) => new THREE.MeshStandardMaterial(Object.assign({ roughness: 0.8 }, o));
    const M = {
      ground: std({ roughness: 1, transparent: true }), wall: std({ roughness: 0.7 }), roof: std({ roughness: 0.6 }),
      glass: std({ roughness: 0.2, metalness: 0.3 }), grass: std({ roughness: 1 }), tree: std(),
      entry: std({ roughness: 0.4, metalness: 0.2 }), water: new THREE.MeshBasicMaterial(), tech: std({ roughness: 0.5 }),
      incident: new THREE.MeshBasicMaterial({ transparent: true }), ring: new THREE.MeshBasicMaterial({ transparent: true, side: THREE.DoubleSide })
    };
    const zoneMats = {}, eqMats = {}, meterMats = {};
    function applyTheme() {
      scene.background = new THREE.Color(css("--scene"));
      M.ground.color.set(css("--ground")); M.wall.color.set(css("--wall")); M.roof.color.set(css("--roof"));
      M.glass.color.set(css("--glass")); M.grass.color.set(css("--grass")); M.tree.color.set(css("--tree"));
      M.entry.color.set(css("--accent")); M.water.color.set(css("--water")); M.tech.color.set(css("--tech"));
      M.incident.color.set(css("--crit")); M.ring.color.set(css("--crit"));
    }

    // ---------- Ground + entry ----------
    const ground = new THREE.Mesh(new THREE.BoxGeometry(GW, 0.3, GD), M.ground);
    ground.position.y = -0.15; ground.receiveShadow = true; scene.add(ground);
    const entry = new THREE.Group();
    const box = new THREE.Mesh(new THREE.BoxGeometry(1.6, 1, 1.2), M.entry); box.position.y = 0.5; box.castShadow = true;
    const dial = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.3, 0.08, 20), M.wall); dial.rotation.x = Math.PI / 2; dial.position.set(0, 0.6, 0.62);
    entry.add(box, dial); entry.position.set(0, 0, ENTRY_Z); scene.add(entry);

    // ---------- Zones ----------
    const zoneGroups = {}, zonePads = [], pickables = [], decor = new Set();
    const zoneX = i => (i - (DATA.zones.length - 1) / 2) * (ZW + 3);
    DATA.zones.forEach((z, i) => {
      if (z.pos_x == null || z.pos_y == null) { z.pos_x = zoneX(i); z.pos_y = -4; z._auto = true; }
      const g = new THREE.Group();
      g.position.set(z.pos_x, 0, z.pos_y);
      const zm = zoneMats[z.id] = std({ roughness: 0.9, transparent: true });
      const pad = new THREE.Mesh(new THREE.BoxGeometry(ZW, 0.2, ZD), zm);
      pad.position.y = 0.1; pad.receiveShadow = true;
      pad.userData = { kind: "zone", id: z.id };
      g.add(pad); zonePads.push(pad); pickables.push(pad);
      if (z.kind === "garden") buildGarden(g); else buildBuilding(g, z);
      scene.add(g);
      zoneGroups[z.id] = g;
    });
    function addDecor(g, mesh) { g.add(mesh); decor.add(mesh); return mesh; }
    function buildBuilding(g, z) {
      const floors = Math.max(1, z.floors || 1);
      const w = ZW - 1.6, d = 4.4, h = floors * 1.6 + 0.2, cz = -0.9;
      const walls = addDecor(g, new THREE.Mesh(new THREE.BoxGeometry(w, h, d), M.wall));
      walls.position.set(0, 0.2 + h / 2, cz); walls.castShadow = true; walls.receiveShadow = true;
      const winGeo = new THREE.BoxGeometry(0.7, 0.6, 0.06);
      for (let f = 0; f < floors; f++) for (let k = -2; k <= 2; k++) {
        if (f === 0 && k === 0) continue;
        addDecor(g, new THREE.Mesh(winGeo, M.glass)).position.set(k * 1.25, 0.2 + 0.95 + f * 1.6, cz + d / 2 + 0.02);
      }
      addDecor(g, new THREE.Mesh(new THREE.BoxGeometry(0.9, 1.3, 0.06), M.roof)).position.set(0, 0.85, cz + d / 2 + 0.02);
      if (z.roof === "gable") {
        const s = new THREE.Shape(); s.moveTo(-w / 2 - 0.25, 0); s.lineTo(w / 2 + 0.25, 0); s.lineTo(0, 1.3); s.lineTo(-w / 2 - 0.25, 0);
        const roof = addDecor(g, new THREE.Mesh(new THREE.ExtrudeGeometry(s, { depth: d + 0.5, bevelEnabled: false }), M.roof));
        roof.position.set(0, 0.2 + h, cz - (d + 0.5) / 2); roof.castShadow = true;
      } else {
        const slab = addDecor(g, new THREE.Mesh(new THREE.BoxGeometry(w + 0.3, 0.18, d + 0.3), M.roof));
        slab.position.set(0, 0.2 + h + 0.09, cz); slab.castShadow = true;
        const tank = addDecor(g, new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 0.9, 18), M.wall));
        tank.position.set(w / 2 - 0.9, 0.2 + h + 0.63, cz - 0.8); tank.castShadow = true;
      }
    }
    function buildGarden(g) {
      addDecor(g, new THREE.Mesh(new THREE.BoxGeometry(ZW - 0.8, 0.06, ZD - 2.4), M.grass)).position.set(0, 0.23, -0.9);
      [[-3, -2.8], [-1.2, -3], [0.8, -2.6], [2.8, -2.9], [-2.4, -0.6], [-0.2, -1], [2, -0.4]].forEach(([x, zz], k) => {
        const hgt = 1.1 + (k % 3) * 0.35;
        const t = addDecor(g, new THREE.Mesh(new THREE.ConeGeometry(0.5, hgt, 8), M.tree));
        t.position.set(x, 0.26 + hgt / 2, zz); t.castShadow = true;
      });
      for (let k = -3; k <= 3; k++) addDecor(g, new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.35, 0.35), M.tree)).position.set(k * 1.05, 0.38, 1.0);
    }

    // ---------- Pumps ----------
    const eqMeshes = {}, pumpObj = new Map(), pumpsPerZone = {};
    const eqMat = ref => eqMats[ref] || (eqMats[ref] = std({ roughness: 0.35, metalness: 0.25, transparent: true }));
    DATA.equipment.filter(e => e.type === "pump").forEach(eq => {
      const g = zoneGroups[eq.zone]; if (!g) return;
      const n = pumpsPerZone[eq.zone] = (pumpsPerZone[eq.zone] || 0) + 1;
      const p = new THREE.Group(), mat = eqMat(eq.reference);
      const base = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.25, 0.9), mat); base.position.y = 0.13;
      const body = new THREE.Mesh(new THREE.CylinderGeometry(0.38, 0.38, 1, 18), mat); body.rotation.z = Math.PI / 2; body.position.y = 0.68;
      const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.28, 0.6, 18), mat); motor.position.y = 1.2;
      [base, body, motor].forEach(m => { m.castShadow = true; m.userData = { kind: "eq", id: eq.reference }; p.add(m); pickables.push(m); });
      p.position.set(2.2 - (n - 1) * 1.6, 0.2, ZD / 2 - 1.2);
      g.add(p);
      eqMeshes[eq.reference] = [base, body, motor];
      pumpObj.set(eq.reference, p);
    });

    // ---------- Meters (Student 2) ----------
    const meterObjs = {}, metersPerZone = {};
    DATA.meters.forEach(m => {
      const g = zoneGroups[m.zone]; if (!g) return;
      const n = metersPerZone[m.zone] = (metersPerZone[m.zone] || 0) + 1;
      const mat = meterMats[m.serial_number] = std({ roughness: 0.4, metalness: 0.2, transparent: true });
      const grp = new THREE.Group();
      const post = new THREE.Mesh(new THREE.BoxGeometry(0.55, 0.7, 0.45), mat); post.position.y = 0.35;
      const face = new THREE.Mesh(new THREE.CylinderGeometry(0.17, 0.17, 0.05, 18), M.wall); face.rotation.x = Math.PI / 2; face.position.set(0, 0.45, 0.24);
      [post, face].forEach(o => { o.castShadow = true; o.userData = { kind: "meter", id: m.serial_number }; grp.add(o); pickables.push(o); });
      grp.position.set(-1.1 - (n - 1) * 0.9, 0.2, ZD / 2 - 0.7);
      g.add(grp);
      meterObjs[m.serial_number] = grp;
    });

    // ---------- Pipes ----------
    let pipeObjs = [];
    function roundedCurve(raw, rc) {
      const pts = raw.filter((p, i) => i === 0 || p.distanceTo(raw[i - 1]) > 1e-3);
      const path = new THREE.CurvePath();
      let cur = pts[0].clone();
      for (let i = 1; i < pts.length - 1; i++) {
        const p = pts[i], da = pts[i - 1].clone().sub(p), db = pts[i + 1].clone().sub(p);
        const r = Math.min(rc, da.length() / 2, db.length() / 2);
        const p1 = p.clone().addScaledVector(da.normalize(), r), p2 = p.clone().addScaledVector(db.normalize(), r);
        if (cur.distanceTo(p1) > 1e-3) path.add(new THREE.LineCurve3(cur.clone(), p1));
        path.add(new THREE.QuadraticBezierCurve3(p1, p.clone(), p2));
        cur = p2;
      }
      const last = pts[pts.length - 1];
      if (cur.distanceTo(last) > 1e-3) path.add(new THREE.LineCurve3(cur, last.clone()));
      return path;
    }
    function routeFor(eq) {
      const J = Math.min(ENTRY_Z - 2.2, Math.max(...DATA.zones.map(z => z.pos_y + ZD / 2 - 0.4)) + 2);
      if (eq.role === "main") return [new THREE.Vector3(0, 0.4, ENTRY_Z), new THREE.Vector3(0, PY, ENTRY_Z), new THREE.Vector3(0, PY, J)];
      const z = zoneById(eq.zone);
      const branches = DATA.equipment.filter(e => e.type === "pipe" && e.role !== "main" && e.zone === eq.zone);
      const off = (branches.indexOf(eq) - (branches.length - 1) / 2) * 0.9;
      const zx = z.pos_x + off, zf = z.pos_y + ZD / 2 - 0.4;
      return [new THREE.Vector3(0, PY, J), new THREE.Vector3(zx, PY, J), new THREE.Vector3(zx, PY, zf), new THREE.Vector3(zx, 0.45, zf)];
    }
    function buildPipes() {
      pipeObjs.forEach(o => { scene.remove(o.mesh); o.mesh.geometry.dispose(); const i = pickables.indexOf(o.mesh); if (i >= 0) pickables.splice(i, 1); });
      pipeObjs = [];
      DATA.equipment.filter(e => e.type === "pipe" && zoneById(e.zone)).forEach(eq => {
        const curve = roundedCurve(routeFor(eq), 0.7);
        const r = 0.09 + (eq.diameter_mm || 40) / 300;
        const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(40, Math.round(curve.getLength() * 6)), r, 12, false), eqMat(eq.reference));
        mesh.castShadow = true;
        mesh.userData = { kind: "eq", id: eq.reference };
        scene.add(mesh); pickables.push(mesh);
        eqMeshes[eq.reference] = [mesh];
        pipeObjs.push({ eq, mesh, curve, r });
      });
      buildFlow();
      placeIncidents();
      eqMeshSet = new Set(Object.values(eqMeshes).flat());
    }

    // ---------- Water flow (InstancedMesh) ----------
    const MAX_P = 600;
    const flowMesh = new THREE.InstancedMesh(new THREE.SphereGeometry(0.11, 8, 6), M.water, MAX_P);
    flowMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    scene.add(flowMesh);
    let particles = [];
    function buildFlow() {
      particles = [];
      pipeObjs.forEach(o => {
        const len = o.curve.getLength(), n = Math.max(3, Math.round(len / 1.6));
        for (let k = 0; k < n && particles.length < MAX_P; k++) particles.push({ o, u0: k / n, len });
      });
    }
    function flowSpeed(o) {
      // No meter data yet (Student 2): constant gentle flow. Otherwise speed follows last month's m³.
      const c = o.eq.role === "main"
        ? DATA.zones.reduce((s, z) => s + (lastCons(z.id) || 0), 0) || (DATA.meters.length ? 0 : null)
        : lastCons(o.eq.zone);
      if (c == null) return 0.8;
      return c <= 0 ? 0 : 0.4 + c / 70;
    }
    const _m = new THREE.Matrix4(), _p = new THREE.Vector3(), _zero = new THREE.Matrix4().makeScale(0, 0, 0);
    function updateFlow(t) {
      const speeds = new Map(pipeObjs.map(o => [o, flowSpeed(o)]));
      for (let i = 0; i < MAX_P; i++) {
        const pa = particles[i];
        if (!pa || !ui.flowOn || !eqVisible(pa.o.eq) || speeds.get(pa.o) === 0 || !inFocus(pa.o.eq)) { flowMesh.setMatrixAt(i, _zero); continue; }
        _p.copy(pa.o.curve.getPointAt((pa.u0 + t * speeds.get(pa.o) / pa.len) % 1));
        _m.makeTranslation(_p.x, _p.y + pa.o.r + 0.06, _p.z);
        flowMesh.setMatrixAt(i, _m);
      }
      flowMesh.instanceMatrix.needsUpdate = true;
    }

    // ---------- Incidents (Student 3) ----------
    const incObjs = {};
    DATA.incidents.forEach(inc => {
      const g = new THREE.Group();
      const s = new THREE.Mesh(new THREE.SphereGeometry(0.42, 18, 12), M.incident);
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.6, 0.85, 32), M.ring); ring.rotation.x = -Math.PI / 2;
      const beacon = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 1.6, 8), M.incident);
      [s, ring, beacon].forEach(o => { o.userData = { kind: "incident", id: inc.reference }; pickables.push(o); });
      g.add(s, ring, beacon); scene.add(g);
      incObjs[inc.reference] = { g, s, ring, beacon, pos: new THREE.Vector3() };
    });
    function placeIncidents() {
      DATA.incidents.forEach(inc => {
        const io = incObjs[inc.reference];
        const o = pipeObjs.find(p => p.eq.reference === inc.suspected_pipe);
        if (o) io.pos.copy(o.curve.getPointAt(Math.min(1, Math.max(0, inc.position_on_pipe || 0.5))));
        else if (inc.suspected_pump && pumpObj.get(inc.suspected_pump)) pumpObj.get(inc.suspected_pump).getWorldPosition(io.pos);
        else return;
        io.s.position.copy(io.pos);
        io.ring.position.set(io.pos.x, 0.04, io.pos.z);
        io.beacon.position.set(io.pos.x, 0.8 + PY / 2, io.pos.z);
      });
    }

    // ---------- Technician avatar (scenario) ----------
    const tech = new THREE.Group();
    const tb = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.32, 1.1, 14), M.tech); tb.position.y = 0.55;
    const th = new THREE.Mesh(new THREE.SphereGeometry(0.24, 14, 10), M.tech); th.position.y = 1.35;
    [tb, th].forEach(o => { o.castShadow = true; tech.add(o); });
    tech.visible = false; scene.add(tech);

    let eqMeshSet = new Set();
    buildPipes();

    // ---------- Labels ----------
    const labels = [];
    function addLabel(cls, html, getPos, isShown, ref) {
      const el = document.createElement("div");
      el.className = "lbl " + cls; el.innerHTML = html;
      labelsEl.appendChild(el);
      labels.push({ el, getPos, isShown, ref });
    }
    const wp = new THREE.Vector3();
    DATA.zones.forEach(z => addLabel("zone", `${esc(z.code)} · ${esc(z.name)}`, () => zoneGroups[z.id].localToWorld(wp.set(0, z.kind === "garden" ? 2.4 : (z.floors || 1) * 1.6 + 2.2, -0.9)), () => true, "zone:" + z.id));
    addLabel("", "Arrivée SONEDE", () => wp.set(0, 1.8, ENTRY_Z), () => true);
    DATA.equipment.forEach(eq => {
      if (!zoneById(eq.zone)) return;
      const getPos = () => {
        if (eq.type === "pump") return pumpObj.get(eq.reference).localToWorld(wp.set(0, 2, 0));
        const o = pipeObjs.find(p => p.eq === eq);
        wp.copy(o.curve.getPointAt(eq.role === "main" ? 0.55 : 0.4));
        return wp.set(wp.x, 0.55, wp.z);
      };
      addLabel("eq", esc(eq.reference), getPos, () => eqVisible(eq), "eq:" + eq.reference);
      addLabel("wrench", WRENCH, () => { const p = getPos(); return p.set(p.x, p.y + 0.75, p.z); }, () => eqVisible(eq) && !!openWork(eq.reference), "eq:" + eq.reference);
    });
    DATA.meters.forEach(m => { if (meterObjs[m.serial_number]) addLabel("meter", esc(m.serial_number), () => meterObjs[m.serial_number].localToWorld(wp.set(0, 1.25, 0)), () => true, "meter:" + m.serial_number); });
    DATA.incidents.forEach(inc => addLabel("inc", "Fuite suspectée", () => wp.copy(incObjs[inc.reference].pos).setY(1.9), () => activeIncidents().includes(inc), "incident:" + inc.reference));
    addLabel("tech", "Technicien", () => tech.localToWorld(wp.set(0, 2.1, 0)), () => tech.visible);

    function labelInFocus(ref) {
      const [k, id] = ref.split(":");
      if (k === "zone") return +id === ui.focusZone;
      if (k === "eq") return inFocus(eqByRef(id));
      if (k === "meter") return meterBySerial(id).zone === ui.focusZone;
      if (k === "incident") { const i = DATA.incidents.find(x => x.reference === id); const e = eqByRef(i.suspected_pipe) || eqByRef(i.suspected_pump); return !e || e.zone === ui.focusZone; }
      return true;
    }
    const tmp = new THREE.Vector3();
    function placeLabels() {
      const w = stage.clientWidth, h = stage.clientHeight;
      const selKey = ui.sel ? ui.sel.kind + ":" + ui.sel.id : null;
      for (const L of labels) {
        if (!L.isShown()) { L.el.hidden = true; continue; }
        tmp.copy(L.getPos()).project(camera);
        const vis = tmp.z < 1 && Math.abs(tmp.x) < 1.05 && Math.abs(tmp.y) < 1.05;
        L.el.hidden = !vis;
        if (!vis) continue;
        L.el.style.left = ((tmp.x + 1) / 2 * w) + "px";
        L.el.style.top = ((1 - tmp.y) / 2 * h) + "px";
        L.el.classList.toggle("sel", !!L.ref && L.ref === selKey);
        L.el.classList.toggle("dim", !!(ui.focusZone && L.ref && !labelInFocus(L.ref)));
      }
    }

    // ---------- Paint ----------
    const mix = (a, b, t) => new THREE.Color(a).lerp(new THREE.Color(b), t);
    function paint() {
      const accent = new THREE.Color(css("--accent")), black = new THREE.Color(0);
      DATA.equipment.forEach(eq => {
        const mat = eqMat(eq.reference);
        mat.color.set(css("--" + toneOf(eq)));
        const selected = ui.sel && ui.sel.kind === "eq" && ui.sel.id === eq.reference;
        mat.emissive.copy(selected ? accent : black); mat.emissiveIntensity = selected ? 0.5 : 0;
        mat.opacity = inFocus(eq) ? 1 : 0.18; mat.depthWrite = mat.opacity === 1;
        (eqMeshes[eq.reference] || []).forEach(m => { m.visible = eqVisible(eq); });
      });
      DATA.zones.forEach(z => {
        const zm = zoneMats[z.id], worst = zoneWorst(z.id);
        zm.color.copy(worst === "ok" || worst === "none" ? new THREE.Color(css("--zone")) : mix(css("--zone"), css("--" + worst), 0.42));
        const selected = ui.sel && ui.sel.kind === "zone" && ui.sel.id === z.id;
        zm.emissive.copy(selected ? accent : black); zm.emissiveIntensity = selected ? 0.25 : 0;
        const dim = !!(ui.focusZone && ui.focusZone !== z.id);
        zm.opacity = dim ? 0.3 : 1;
        zoneGroups[z.id].traverse(o => { if (decor.has(o)) o.visible = !dim; });
      });
      DATA.meters.forEach(m => {
        const mat = meterMats[m.serial_number]; if (!mat) return;
        mat.color.set(css("--accent"));
        const selected = ui.sel && ui.sel.kind === "meter" && ui.sel.id === m.serial_number;
        mat.emissive.copy(selected ? new THREE.Color(css("--water")) : black); mat.emissiveIntensity = selected ? 0.6 : 0;
        mat.opacity = (!ui.focusZone || m.zone === ui.focusZone) ? 1 : 0.2;
      });
      DATA.incidents.forEach(inc => { incObjs[inc.reference].g.visible = activeIncidents().includes(inc); });
      M.ground.opacity = ui.xray ? 0.55 : 1; M.ground.depthWrite = !ui.xray;
      renderLegend(); renderList();
    }

    // ---------- Side panels ----------
    function renderLegend() {
      document.getElementById("legend-title").textContent = ui.colorMode === "status" ? "Statut" : "Risque de panne à 30 jours";
      const tones = ui.colorMode === "status"
        ? Object.values(STATUS).map(s => `<li><span class="dot ${s.tone}"></span>${s.label}</li>`).join("")
        : `<li><span class="dot ok"></span>Faible · moins de 30 %</li><li><span class="dot warn"></span>Moyen · 30 à 60 %</li><li><span class="dot crit"></span>Élevé · plus de 60 %</li><li><span class="dot none"></span>Non calculé</li>`;
      document.getElementById("legend").innerHTML = tones +
        (DATA.meters.length ? `<li><span class="sq"></span>Compteur d'eau</li>` : "") +
        `<li><span class="dot water"></span>Flux d'eau${DATA.meters.length ? ", vitesse selon la consommation du mois" : ""}</li>` +
        (DATA.incidents.length ? `<li><span class="dot crit"></span>Point rouge pulsant · fuite suspectée</li>` : "") +
        `<li><span style="color:var(--warn);display:inline-flex">${WRENCH}</span>Intervention en cours</li>`;
    }
    function renderList() {
      const selRef = ui.sel && ui.sel.kind === "eq" ? ui.sel.id : null;
      document.getElementById("eq-list").innerHTML = DATA.equipment.map(eq => {
        const s = eqState(eq), z = zoneById(eq.zone);
        return `<li${eqVisible(eq) ? "" : " hidden"}><button type="button" data-id="${esc(eq.reference)}" aria-current="${eq.reference === selRef}">
          <span class="dot ${toneOf(eq)}"></span>
          <span><span class="ref">${esc(eq.reference)}</span> <span class="sub">${eq.type === "pipe" ? "Canalisation" : "Pompe"} · ${esc(z ? z.name : "")}${openWork(eq.reference) ? " · en intervention" : ""}</span></span>
          <span class="val">${ui.colorMode === "risk" ? pct(s.risk) : (STATUS[s.status] || {}).label || s.status}</span></button></li>`;
      }).join("");
    }
    document.getElementById("eq-list").addEventListener("click", e => { const b = e.target.closest("button[data-id]"); if (b) select({ kind: "eq", id: b.dataset.id }, true); });

    const detail = document.getElementById("detail");
    const head = (kind, title) => `<div class="panel-head"><span class="kind">${kind}</span><button type="button" data-act="close">Fermer</button></div><h2>${esc(title)}</h2>`;
    function sparkline(series) {
      if (!series.length) return '<p class="note">Aucun relevé à cette date.</p>';
      const W = 300, H = 92, pad = 16, max = Math.max(1, ...series.map(s => s.m3)) * 1.1, bw = (W - pad) / series.length;
      const bars = series.map((s, i) => {
        const h = Math.max(0, (s.m3 / max) * (H - 26));
        return `<rect x="${pad + i * bw + 2}" y="${H - 14 - h}" width="${Math.max(1, bw - 4)}" height="${h}" rx="2" style="fill:var(${isSpike(series, i) ? "--crit" : "--accent"})"><title>${fmtMonth(s.d)} : ${s.m3} m³</title></rect>
          <text x="${pad + i * bw + bw / 2}" y="${H - 3}" text-anchor="middle">${fmtMonth(s.d).slice(0, 3)}</text>`;
      }).join("");
      return `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="Consommation mensuelle en m³"><line x1="${pad}" y1="${H - 14}" x2="${W}" y2="${H - 14}" style="stroke:var(--line)"/><text x="0" y="10">m³</text>${bars}</svg>`;
    }
    function renderDetail() {
      detail.classList.toggle("open", !!ui.sel);
      if (!ui.sel) { detail.innerHTML = `<h2>Inspecteur</h2><p class="card-empty">Cliquez sur une zone, une canalisation, une pompe${DATA.meters.length ? ", un compteur" : ""}${DATA.incidents.length ? " ou le point rouge d'une fuite" : ""}.</p>`; return; }
      const { kind, id } = ui.sel;
      if (kind === "eq") detailEq(eqByRef(id));
      else if (kind === "zone") detailZone(zoneById(id));
      else if (kind === "meter") detailMeter(meterBySerial(id));
      else if (kind === "incident") detailIncident(DATA.incidents.find(i => i.reference === id));
    }
    function detailEq(eq) {
      const z = zoneById(eq.zone), s = eqState(eq), st = STATUS[s.status] || STATUS.en_service, rt = riskTone(s.risk);
      const spec = eq.type === "pipe"
        ? [["Matière", eq.material], ["Longueur", eq.length_m + " m"], ["Diamètre", eq.diameter_mm + " mm"]]
        : [["Puissance", eq.power_kw + " kW"], ["Débit nominal", eq.rated_flow_m3_h + " m³/h"], ["Rendement", eq.efficiency_pct == null ? "—" : eq.efficiency_pct + " %"]];
      const rows = [["Classe", eq.type === "pipe" ? "WaterPipe" : "WaterPump"], ["Zone", `${z.code} · ${z.name}`], ["Installation", fmtDate(eq.installation_date)], ...spec, ["Remplacement estimé", eq.replacement_cost_tnd + " TND"]];
      const works = worksFor(eq.reference).slice().sort((a, b) => b.scheduled_at.localeCompare(a.scheduled_at)), d = date();
      const detailUrl = fill(eq.type === "pipe" ? DATA.urls.pipe_detail : DATA.urls.pump_detail, eq.id);
      detail.innerHTML = head(eq.type === "pipe" ? "Canalisation" : "Pompe", eq.reference) + `
        <span class="status ${st.tone}"><span class="dot ${st.tone}"></span>${st.label}</span>
        <dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
        <dl class="kv"><dt>Risque de panne (30 j)</dt><dd>${pct(s.risk)}</dd></dl>
        ${s.risk == null ? "" : `<div class="risk-bar"><span style="width:${s.risk * 100}%;background:var(--${rt})"></span></div>`}
        <p class="note">predict_failure_30d() · modèle ${esc(eq.model_version || "—")}</p>
        <h3>Interventions (${works.length})</h3>
        ${works.length ? `<ul class="works">${works.map(w => {
          const open = !w.completed_at || w.completed_at > d;
          return `<li><a class="ref" href="${fill(DATA.urls.work_detail, w.id)}">${esc(w.reference)}</a><span class="note">${open ? "En cours" : "Terminée"}</span>
            <span class="sub">${MW_TYPE[w.maintenance_type] || w.maintenance_type} · ${fmtDate(w.scheduled_at)} · ${esc(techName(w.technician))}${w.cost_tnd ? " · " + w.cost_tnd + " TND" : ""}</span>
            ${w.work_summary ? `<span class="sub">${esc(w.work_summary)}</span>` : ""}</li>`;
        }).join("")}</ul>` : '<p class="note">Aucune intervention à cette date.</p>'}
        <a class="btn btn-primary btn-sm" href="${DATA.urls.work_create}?${eq.type}=${eq.id}">Planifier une maintenance</a>
        <a class="btn btn-outline-secondary btn-sm" href="${detailUrl}">Ouvrir la fiche</a>`;
    }
    function detailZone(z) {
      const eqs = DATA.equipment.filter(e => e.zone === z.id), ms = DATA.meters.filter(x => x.zone === z.id), worst = zoneWorst(z.id);
      const label = { ok: "Aucun problème", warn: "À surveiller", crit: "Problème actif", none: "—" }[worst];
      const cons = lastCons(z.id);
      detail.innerHTML = head("Zone", `${z.code} · ${z.name}`) + `
        <span class="status ${worst}"><span class="dot ${worst}"></span>${label}</span>
        <dl class="kv"><dt>Classe</dt><dd>WaterZone</dd><dt>Usage</dt><dd>${esc(z.usage || "—")}</dd><dt>Pression de service</dt><dd>${z.service_pressure_bar == null ? "—" : z.service_pressure_bar + " bar"}</dd>
        <dt>Équipements</dt><dd>${eqs.length}</dd><dt>Compteurs</dt><dd>${ms.length ? ms.map(m => esc(m.serial_number)).join(", ") : "Aucun"}</dd>
        ${cons == null ? "" : `<dt>Conso. dernier mois</dt><dd>${cons} m³</dd>`}
        <dt>Position</dt><dd>${z._auto ? "automatique" : `pos_x ${z.pos_x} · pos_y ${z.pos_y}`}</dd></dl>
        ${DATA.meters.length || ms.length ? `<p class="note">validate_meter_coverage() : ${ms.length ? "la zone a au moins un compteur." : "aucun compteur, la zone est invalide."}</p>` : ""}
        ${ui.focusZone === z.id ? '<button type="button" data-act="unfocus">Voir tout le site</button>' : '<button type="button" class="primary" data-act="focus">Isoler cette zone</button>'}
        ${DATA.can_edit ? `<a class="btn btn-outline-secondary btn-sm" href="${fill(DATA.urls.zone_edit, z.id)}">Modifier la zone</a>` : ""}`;
    }
    function detailMeter(m) {
      const z = zoneById(m.zone), series = monthly(m), r = readingsOf(m), last = r[r.length - 1];
      const spikeIdx = series.findIndex((_, i) => isSpike(series, i));
      detail.innerHTML = head("Compteur · Student 2", m.serial_number) + `
        <dl class="kv"><dt>Classe</dt><dd>WaterMeter</dd><dt>Zone</dt><dd>${esc(z.code)} · ${esc(z.name)}</dd><dt>Catégorie</dt><dd>${esc(m.customer_category || "—")}</dd>
        <dt>Dernier index</dt><dd>${last ? last[1].toLocaleString("fr-FR") + " m³" : "—"}</dd><dt>Relevé du</dt><dd>${last ? fmtDate(last[0]) : "—"}</dd>
        ${m.forecast_m3 == null ? "" : `<dt>Prévision ${m.horizon_days || 30} j</dt><dd>${m.forecast_m3} m³</dd>`}</dl>
        <h3>Consommation mensuelle</h3>${sparkline(series)}
        ${spikeIdx >= 0 ? `<p class="note">Barre rouge : consommation supérieure à 140 % de la moyenne des 3 mois précédents. Un signal à vérifier, pas une preuve de fuite.</p>` : ""}
        ${scn && scn.step === 4 ? `<p class="msg">Les relevés qui suivent la réparation mesurent l'eau économisée. Cet écart mesuré alimente l'objectif d'économie (Student 4) ; une économie annuelle resterait une estimation.</p>` : ""}`;
    }
    function detailIncident(inc) {
      const active = activeIncidents().includes(inc);
      detail.innerHTML = head("Incident · Student 3", inc.reference) + `
        <span class="status ${active ? "crit" : "ok"}"><span class="dot ${active ? "crit" : "ok"}"></span>${active ? "En investigation" : "Résolu"}</span>
        <dl class="kv"><dt>Classe</dt><dd>LeakIncident</dd><dt>Compteur</dt><dd>${esc(inc.meter || "—")}</dd>
        <dt>Cible suspectée</dt><dd>${esc(inc.suspected_pipe || inc.suspected_pump || "—")}</dd><dt>Technicien</dt><dd>${esc(techName(inc.technician))}</dd><dt>Ouvert le</dt><dd>${fmtDate(inc.opened_at)}</dd></dl>
        ${inc.rule ? `<p class="note">Règle : ${esc(inc.rule)}</p>` : ""}
        ${inc.description ? `<p>${esc(inc.description)}</p>` : ""}
        <p class="note">Un incident est un signal à vérifier. Il ne prouve pas la fuite.</p>
        ${inc.suspected_pipe || inc.suspected_pump ? `<button type="button" class="primary" data-act="goto" data-id="${esc(inc.suspected_pipe || inc.suspected_pump)}">Voir l'équipement suspecté</button>` : ""}`;
    }
    detail.addEventListener("click", e => {
      const b = e.target.closest("[data-act]"); if (!b) return;
      const act = b.dataset.act;
      if (act === "close") select(null);
      if (act === "focus") setFocus(ui.sel.id);
      if (act === "unfocus") setFocus(null);
      if (act === "goto") select({ kind: "eq", id: b.dataset.id }, true);
    });

    // ---------- Selection, focus, camera ----------
    let tween = null;
    function flyTo(target, dist) {
      const dir = camera.position.clone().sub(controls.target).normalize();
      const endPos = target.clone().addScaledVector(dir, dist || camera.position.distanceTo(controls.target));
      if (reduceMotion) { controls.target.copy(target); camera.position.copy(endPos); return; }
      tween = { t0: performance.now(), dur: 800, fromT: controls.target.clone(), toT: target.clone(), fromP: camera.position.clone(), toP: endPos };
    }
    function objPos(sel) {
      const p = new THREE.Vector3();
      if (sel.kind === "zone") return zoneGroups[sel.id].getWorldPosition(p);
      if (sel.kind === "meter") return meterObjs[sel.id].getWorldPosition(p);
      if (sel.kind === "incident") return p.copy(incObjs[sel.id].pos).setY(0);
      const eq = eqByRef(sel.id);
      if (eq.type === "pump") return pumpObj.get(eq.reference).getWorldPosition(p);
      return p.copy(pipeObjs.find(o => o.eq === eq).curve.getPointAt(0.5)).setY(0);
    }
    function select(sel, fly) {
      ui.sel = sel;
      paint(); renderDetail();
      if (sel && fly) flyTo(objPos(sel), sel.kind === "zone" ? 22 : 18);
    }
    function setFocus(zid) {
      ui.focusZone = zid;
      if (zid) flyTo(zoneGroups[zid].getWorldPosition(new THREE.Vector3()), 20);
      else flyTo(HOME.target.clone(), HOME.pos.distanceTo(HOME.target));
      paint(); renderDetail();
    }

    // ---------- Picking + edit-mode drag ----------
    const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(), plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const shown = o => { for (let x = o; x; x = x.parent) if (!x.visible) return false; return true; };
    function setNdc(e) { const r = renderer.domElement.getBoundingClientRect(); ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1); ray.setFromCamera(ndc, camera); }
    function hitAt(e, list) { setNdc(e); return ray.intersectObjects(list || pickables, false).find(h => shown(h.object) && !(h.object.material && h.object.material.opacity < 0.5)); }
    let down = null, drag = null, rebuildQueued = false;
    const dom = renderer.domElement;
    dom.addEventListener("pointerdown", e => {
      down = [e.clientX, e.clientY];
      if (!ui.edit) return;
      const h = hitAt(e, zonePads);
      if (!h) return;
      const z = zoneById(h.object.userData.id), p = new THREE.Vector3();
      ray.ray.intersectPlane(plane, p);
      drag = { z, off: new THREE.Vector2(p.x - z.pos_x, p.z - z.pos_y) };
      controls.enabled = false; dom.setPointerCapture(e.pointerId);
    });
    dom.addEventListener("pointermove", e => {
      if (drag) {
        setNdc(e);
        const p = new THREE.Vector3();
        if (ray.ray.intersectPlane(plane, p)) {
          const snap = v => Math.round(v * 2) / 2;
          drag.z.pos_x = Math.max(-GW / 2 + ZW / 2, Math.min(GW / 2 - ZW / 2, snap(p.x - drag.off.x)));
          drag.z.pos_y = Math.max(-GD / 2 + ZD / 2, Math.min(ENTRY_Z - 3.5 - ZD / 2, snap(p.z - drag.off.y)));
          drag.z._auto = false;
          zoneGroups[drag.z.id].position.set(drag.z.pos_x, 0, drag.z.pos_y);
          if (!rebuildQueued) { rebuildQueued = true; requestAnimationFrame(() => { rebuildQueued = false; buildPipes(); paint(); }); }
        }
        return;
      }
      dom.style.cursor = ui.edit ? (hitAt(e, zonePads) ? "move" : "grab") : (hitAt(e) ? "pointer" : "grab");
    });
    dom.addEventListener("pointerup", e => {
      if (drag) {
        const z = drag.z; drag = null; controls.enabled = true;
        saveZonePosition(z);
        if (ui.sel && ui.sel.kind === "zone") renderDetail();
        return;
      }
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
      const h = hitAt(e);
      if (!h) { select(null); return; }
      select({ kind: h.object.userData.kind, id: h.object.userData.id }, false);
    });
    function saveZonePosition(z) {
      const hint = document.getElementById("hint");
      fetch(fill(DATA.urls.zone_position, z.id), {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ pos_x: z.pos_x, pos_y: z.pos_y })
      }).then(r => {
        hint.innerHTML = r.ok ? `<span>Position de ${esc(z.code)} enregistrée.</span>` : `<span>Position non enregistrée (erreur ${r.status}).</span>`;
      }).catch(() => { hint.innerHTML = "<span>Position non enregistrée : serveur injoignable.</span>"; });
    }

    // ---------- Controls ----------
    const $ = id => document.getElementById(id);
    const pressed = (el, v) => el.setAttribute("aria-pressed", v);
    $("mode-status").onclick = () => { ui.colorMode = "status"; pressed($("mode-status"), true); pressed($("mode-risk"), false); paint(); renderDetail(); };
    $("mode-risk").onclick = () => { ui.colorMode = "risk"; pressed($("mode-status"), false); pressed($("mode-risk"), true); paint(); renderDetail(); };
    const refilter = () => { if (ui.sel && ui.sel.kind === "eq" && !eqVisible(eqByRef(ui.sel.id))) select(null); else paint(); };
    document.querySelectorAll("[data-type]").forEach(b => b.onclick = () => { ui.type = b.dataset.type; document.querySelectorAll("[data-type]").forEach(x => pressed(x, x === b)); refilter(); });
    $("f-risk").onchange = e => { ui.highRisk = e.target.checked; refilter(); };
    $("btn-xray").onclick = () => { ui.xray = !ui.xray; pressed($("btn-xray"), ui.xray); paint(); };
    $("btn-flow").onclick = () => { ui.flowOn = !ui.flowOn; pressed($("btn-flow"), ui.flowOn); };
    pressed($("btn-flow"), ui.flowOn);
    const editBtn = $("btn-edit");
    if (!DATA.can_edit) { editBtn.disabled = true; editBtn.title = "Droit « modifier une zone » nécessaire"; }
    editBtn.onclick = () => {
      ui.edit = !ui.edit; pressed(editBtn, ui.edit); stage.classList.toggle("editing", ui.edit);
      $("hint").innerHTML = ui.edit ? "<span>Mode édition : glissez une zone. Sa position est enregistrée au relâchement.</span>" : "<span>Glisser pour tourner · molette pour zoomer · cliquer une zone, un équipement ou un compteur</span>";
    };
    $("btn-reset").onclick = () => { ui.focusZone = null; tween = null; camera.position.copy(HOME.pos); controls.target.copy(HOME.target); paint(); renderDetail(); };
    const tl = $("tl"), tlOut = $("tl-out");
    tl.max = TIMELINE.length - 1; tl.value = ui.t;
    $("timeline").hidden = TIMELINE.length < 2;
    function syncTimeline() { tlOut.textContent = ui.t === TIMELINE.length - 1 ? "Aujourd'hui" : fmtDate(TIMELINE[ui.t]); tl.disabled = !!scn; }
    tl.oninput = () => { ui.t = +tl.value; syncTimeline(); paint(); renderDetail(); };

    // ---------- Scenario (uses the first incident with a suspected pipe) ----------
    const scnBtn = $("btn-scn");
    if (!scnIncident) { scnBtn.disabled = true; scnBtn.title = "Disponible quand le module de Student 3 signale une fuite sur une canalisation"; }
    const scnMeter = scnIncident && scnIncident.meter && meterBySerial(scnIncident.meter) ? scnIncident.meter : null;
    function steps() {
      const i = scnIncident;
      return [
        { t: "Enregistrer", p: scnMeter ? `Les relevés du compteur ${scnMeter} sont importés. La barre rouge signale une consommation anormale (detect_anomaly).` : "Les relevés de consommation sont importés (module de Student 2)." },
        { t: "Enquêter", p: `La règle d'alerte ouvre l'incident ${i.reference}. La canalisation ${i.suspected_pipe} est suspectée et passe « À surveiller ».` },
        { t: "Réparer", p: `Un technicien se rend sur place. L'intervention vise ${i.suspected_pipe} et elle seule. À la clôture, l'incident est résolu.` },
        { t: "Mesurer", p: "Les relevés suivants mesurent l'eau économisée. Cet écart alimente l'objectif d'économie et l'audit (Student 4)." }
      ];
    }
    function renderScenario() {
      const el = $("scenario");
      if (!scn) { el.hidden = true; return; }
      el.hidden = false;
      const all = steps(), s = all[scn.step - 1];
      el.innerHTML = `<div class="steps">${all.map((_, i) => `<i class="${i < scn.step ? "on" : ""}"></i>`).join("")}</div>
        <h3>Étape ${scn.step} sur 4 · ${s.t}</h3><p>${s.p}</p>
        <div class="scn-actions"><button type="button" data-s="quit">Quitter</button><button type="button" data-s="prev" ${scn.step === 1 ? "disabled" : ""}>Précédent</button>
        <button type="button" class="primary" data-s="next">${scn.step === 4 ? "Terminer" : "Suivant"}</button></div>`;
    }
    $("scenario").addEventListener("click", e => {
      const b = e.target.closest("[data-s]"); if (!b) return;
      if (b.dataset.s === "quit" || (b.dataset.s === "next" && scn.step === 4)) return stopScenario();
      goStep(scn.step + (b.dataset.s === "next" ? 1 : -1));
    });
    function goStep(n) {
      scn.step = n; scn.arrived = n === 4; tech.visible = n === 3; scn.techT0 = performance.now();
      ui.focusZone = null; ui.type = "all"; ui.highRisk = false; $("f-risk").checked = false;
      document.querySelectorAll("[data-type]").forEach(x => pressed(x, x.dataset.type === "all"));
      if ((n === 1 || n === 4) && scnMeter) select({ kind: "meter", id: scnMeter }, true);
      else if (n === 2) select({ kind: "incident", id: scnIncident.reference }, true);
      else select({ kind: "eq", id: scnIncident.suspected_pipe }, true);
      renderScenario(); syncTimeline();
    }
    function startScenario() { scn = { step: 1 }; ui.t = TIMELINE.length - 1; tl.value = ui.t; goStep(1); }
    function stopScenario() { scn = null; tech.visible = false; renderScenario(); syncTimeline(); select(null); setFocus(null); }
    scnBtn.onclick = () => scn ? stopScenario() : startScenario();
    function updateTech(now) {
      if (!scn || scn.step !== 3) return;
      const target = incObjs[scnIncident.reference].pos;
      const a = new THREE.Vector3(1.4, 0, ENTRY_Z), b = new THREE.Vector3(target.x + 1, 0, ENTRY_Z - 2), c = new THREE.Vector3(target.x + 1, 0, target.z);
      const k = Math.min(1, (now - scn.techT0) / (reduceMotion ? 1 : 3500));
      tech.position.copy(k < 0.5 ? a.clone().lerp(b, k * 2) : b.clone().lerp(c, (k - 0.5) * 2));
      if (k >= 1 && !scn.arrived) { scn.arrived = true; paint(); renderDetail(); }
    }

    // ---------- Resize + loop ----------
    function resize() {
      const w = stage.clientWidth, h = stage.clientHeight;
      renderer.setSize(w, h, false);
      camera.aspect = w / h; camera.fov = w < 560 ? 54 : 40; camera.updateProjectionMatrix();
    }
    new ResizeObserver(resize).observe(stage);
    applyTheme(); resize(); paint(); renderDetail(); syncTimeline();

    const clock = new THREE.Clock();
    (function loop() {
      const t = clock.getElapsedTime();
      if (tween) {
        const k = Math.min(1, (performance.now() - tween.t0) / tween.dur), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        controls.target.lerpVectors(tween.fromT, tween.toT, e); camera.position.lerpVectors(tween.fromP, tween.toP, e);
        if (k >= 1) tween = null;
      }
      const pulse = reduceMotion ? 1 : 1 + 0.35 * Math.sin(t * 4);
      Object.values(incObjs).forEach(o => o.ring.scale.setScalar(pulse));
      M.ring.opacity = reduceMotion ? 0.8 : 0.45 + 0.4 * (Math.sin(t * 4) + 1) / 2;
      updateTech(performance.now());
      updateFlow(t);
      controls.update();
      renderer.render(scene, camera);
      placeLabels();
      requestAnimationFrame(loop);
    })();
  }
})();
