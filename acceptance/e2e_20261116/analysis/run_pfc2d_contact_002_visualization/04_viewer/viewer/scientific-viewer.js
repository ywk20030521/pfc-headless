(function () {
  "use strict";

  const DATA = window.PFC_VIEWER_DATA = window.PFC_VIEWER_DATA || {
    catalog: null,
    static: null,
    caseMeta: Object.create(null),
    caseCharts: Object.create(null),
    globalCharts: null,
    pendingChunks: Object.create(null),
    pendingHistories: Object.create(null),
    registerCatalog(value) { this.catalog = value; },
    registerStatic(value) { this.static = value; },
    registerCaseMeta(caseId, value) { this.caseMeta[caseId] = value; },
    registerCharts(caseId, value) { this.caseCharts[caseId] = value; },
    registerGlobalCharts(value) { this.globalCharts = value; },
    registerChunk(caseId, chunkIndex, value) {
      const byCase = this.pendingChunks[caseId] || (this.pendingChunks[caseId] = Object.create(null));
      byCase[chunkIndex] = value;
    },
    registerHistory(caseId, bucket, value) {
      const byCase = this.pendingHistories[caseId] || (this.pendingHistories[caseId] = Object.create(null));
      byCase[bucket] = value;
    }
  };

  const byId = (id) => document.getElementById(id);
  const body = document.body;
  const errorBox = byId("errorBox");
  const loading = byId("loading");
  const visualSemantics = window.PFC_VISUAL_SEMANTICS || {};
  const semanticColors = visualSemantics.colors || {};
  const COLORS = Object.freeze({
    primary: semanticColors.primary || "#3C5488",
    fracture: semanticColors.fracture || "#E64B35",
    slate: semanticColors.slate || "#8491B4",
    tan: semanticColors.tan || "#B09C85",
    accent: semanticColors.accent || "#F39B7F",
    low: semanticColors.particle_low || "#B8CCE4",
    high: semanticColors.particle_high || "#3C5488",
    missing: semanticColors.missing || "#A8ADB7",
    ink: "#171717",
    muted: "#6F7074",
    grid: "#E6E7E4"
  });

  function showError(code, error) {
    const details = error && error.stack ? error.stack : String(error);
    body.dataset.error = "1";
    body.dataset.errorCode = code;
    window.__PFC_VIEWER_ERROR__ = { code, message: details };
    errorBox.hidden = false;
    errorBox.textContent = code + "\n\n" + details;
    loading.hidden = true;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
    }[ch]));
  }

  function finiteNumber(value) {
    if (value == null || value === "") return null;
    if (typeof value !== "number" && typeof value !== "string") return null;
    if (typeof value === "string" && value.trim() === "") return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function formatNumber(value, digits = 3) {
    const number = finiteNumber(value);
    if (number === null) return "—";
    const abs = Math.abs(number);
    if (abs !== 0 && (abs < 1e-3 || abs >= 1e5)) {
      const rendered = number.toExponential(Math.max(1, Math.min(8, digits)));
      const parts = rendered.split("e");
      const superscript = String(Number(parts[1])).replace(/-/g, "⁻").replace(/[0-9]/g, (digit) => (
        "⁰¹²³⁴⁵⁶⁷⁸⁹"[Number(digit)]
      ));
      return parts[0].replace(/\.?0+$/, "") + " × 10" + superscript;
    }
    return number.toLocaleString("en-US", {
      maximumFractionDigits: digits,
      minimumFractionDigits: 0
    });
  }

  function formatMetric(value, unit, digits = 4) {
    return finiteNumber(value) === null
      ? "未采集"
      : formatNumber(value, digits) + (unit ? " " + unit : "");
  }

  function formatAxisValue(value, formatting) {
    const settings = formatting || {};
    const digits = settings.scientific
      ? Math.max(1, Number(settings.significant_digits || 4) - 1)
      : Number(settings.decimals != null ? settings.decimals : settings.significant_digits || 4);
    return formatNumber(value, digits);
  }

  function formatTooltipValue(value, formatting) {
    const settings = formatting || {};
    return formatNumber(value, Number(settings.tooltip_digits || 8));
  }

  function axisUnit(unit) {
    if (!unit || unit === "1") return "";
    return " (" + unit + ")";
  }

  function decodeU32(base64) {
    if (!base64) return new Uint32Array(0);
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    const view = new DataView(bytes.buffer);
    const out = new Uint32Array(bytes.length / 4);
    for (let index = 0; index < out.length; index += 1) out[index] = view.getUint32(index * 4, true);
    return out;
  }

  function decodeF32(base64) {
    if (!base64) return new Float32Array(0);
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    const view = new DataView(bytes.buffer);
    const out = new Float32Array(bytes.length / 4);
    for (let index = 0; index < out.length; index += 1) out[index] = view.getFloat32(index * 4, true);
    return out;
  }

  function decodeHistoryRows(base64) {
    const flat = decodeF32(base64);
    const stride = 8;
    const rows = [];
    for (let offset = 0; offset + stride <= flat.length; offset += stride) {
      rows.push({
        sourceFrameIndex: flat[offset],
        viewerFrameIndex: flat[offset + 1],
        x: flat[offset + 2],
        y: flat[offset + 3],
        z: flat[offset + 4],
        displacement: flat[offset + 5],
        speed: flat[offset + 6],
        acceleration: flat[offset + 7]
      });
    }
    return rows;
  }

  function nearestIndex(values, target) {
    if (!Array.isArray(values) || values.length === 0) return -1;
    const numberTarget = finiteNumber(target);
    if (numberTarget === null) return -1;
    let bestIndex = -1;
    let bestDistance = Infinity;
    for (let index = 0; index < values.length; index += 1) {
      const number = finiteNumber(values[index]);
      if (number === null) continue;
      const distance = Math.abs(number - numberTarget);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestIndex = index;
      }
    }
    return bestIndex;
  }

  function createStore(initial) {
    let state = Object.freeze({ ...initial });
    const listeners = new Set();
    return {
      get() { return state; },
      subscribe(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
      set(patch, reason) {
        const next = Object.freeze({ ...state, ...patch });
        const previous = state;
        state = next;
        listeners.forEach((listener) => listener(next, previous, reason || "update"));
        return next;
      }
    };
  }

  const store = createStore({
    currentCase: null,
    currentFrame: 0,
    currentCycle: null,
    currentTime: null,
    selectedBallIds: [],
    selectedMetric: "displacement",
    selectedRange: null,
    colorMetric: "displacement"
  });

  const runtime = {
    caseToken: 0,
    frameToken: 0,
    current: null,
    caseRuntimes: new Map(),
    globalChartsLoaded: false,
    charts: [],
    currentCharts: Object.create(null),
    historyChart: null,
    currentHistories: Object.create(null),
    selectedHistories: new Map(),
    loadedScripts: new Set(),
    trajectories: [],
    playing: false,
    playAccumulator: 0,
    ready: false
  };
  runtime.lastHistogramUpdate = 0;

  const lowRampColor = new THREE.Color(COLORS.low);
  const highRampColor = new THREE.Color(COLORS.high);
  const colorRamp = Array.from({ length: 256 }, (_, index) => {
    const t = index / 255;
    return [
      lowRampColor.r + (highRampColor.r - lowRampColor.r) * t,
      lowRampColor.g + (highRampColor.g - lowRampColor.g) * t,
      lowRampColor.b + (highRampColor.b - lowRampColor.b) * t
    ];
  });
  const accentColor = new THREE.Color(COLORS.accent);
  const missingColor = new THREE.Color(COLORS.missing);
  runtime.colorRange = null;

  function loadScriptOnce(key, path) {
    if (runtime.loadedScripts.has(key)) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = path;
      script.async = true;
      script.onload = () => {
        runtime.loadedScripts.add(key);
        script.remove();
        resolve();
      };
      script.onerror = () => {
        script.remove();
        reject(new Error("无法加载本地数据脚本: " + path));
      };
      document.head.appendChild(script);
    });
  }

  async function loadCaseMeta(caseId) {
    if (DATA.caseMeta[caseId]) return DATA.caseMeta[caseId];
    const summary = DATA.catalog.cases.find((item) => item.id === caseId);
    if (!summary) throw new Error("Case 不存在: " + caseId);
    await loadScriptOnce("meta:" + caseId, summary.metaPath);
    if (!DATA.caseMeta[caseId]) throw new Error("Case 元数据未注册: " + caseId);
    return DATA.caseMeta[caseId];
  }

  async function loadCaseCharts(caseId) {
    if (!DATA.caseCharts[caseId]) {
      const summary = DATA.catalog.cases.find((item) => item.id === caseId);
      await loadScriptOnce("charts:" + caseId, summary.chartsPath);
    }
    if (!runtime.globalChartsLoaded && DATA.catalog.meta.globalChartsPath) {
      await loadScriptOnce("charts:global", DATA.catalog.meta.globalChartsPath);
      runtime.globalChartsLoaded = true;
    }
    return (DATA.caseCharts[caseId] || []).concat(DATA.globalCharts || []);
  }

  function syncCaseVisualCapabilities(meta) {
    const metricStatus = meta.metricStatus || {};
    const supportedMetrics = ["displacement", "speed", "acceleration"].filter(
      (metric) => metricStatus[metric] === "SUPPORTED"
    );
    const chosenMetric = supportedMetrics.includes(store.get().colorMetric)
      ? store.get().colorMetric
      : (supportedMetrics[0] || "displacement");
    Array.from(byId("colorMetric").options).forEach((option) => {
      const supported = metricStatus[option.value] === "SUPPORTED";
      option.disabled = !supported;
      option.textContent = supported
        ? ({ displacement: "累计位移", speed: "速度", acceleration: "加速度" }[option.value])
        : ({ displacement: "累计位移（未采集）", speed: "速度（未采集）", acceleration: "加速度（未采集）" }[option.value]);
    });
    byId("colorMetric").disabled = supportedMetrics.length === 0;
    byId("colorMetric").value = chosenMetric;
    store.set(
      { colorMetric: chosenMetric, selectedMetric: chosenMetric },
      "case-capabilities"
    );
    const entityStatus = meta.entityStatus || {};
    const contact = byId("contactLayerControl");
    contact.hidden = entityStatus.contact !== "SUPPORTED";
    byId("showContacts").disabled = entityStatus.contact !== "SUPPORTED";
    contact.title = entityStatus.contact === "SUPPORTED"
      ? "按当前真实帧显示带端点 ID 的接触网络；线色表示接触力大小。"
      : "当前实验未采集接触端点与接触力。";
    const bond = byId("bondLayerControl");
    bond.hidden = entityStatus.bond !== "SUPPORTED";
    byId("showBonds").disabled = entityStatus.bond !== "SUPPORTED";
    bond.title = entityStatus.bond === "SUPPORTED"
      ? "按当前真实帧显示带端点 ID 的 Bond 网络；线色表示 Bond 力大小。"
      : "当前实验未采集 Bond 端点与 Bond 力。";
    body.dataset.particleMetricCapabilities = JSON.stringify(metricStatus);
    body.dataset.entityCapabilities = JSON.stringify(entityStatus);
  }

  function caseRuntime(caseId) {
    let item = runtime.caseRuntimes.get(caseId);
    if (!item) {
      item = {
        caseId,
        chunkCache: new Map(),
        chunkPromises: new Map(),
        historyCache: new Map(),
        historyPromises: new Map()
      };
      runtime.caseRuntimes.set(caseId, item);
    }
    return item;
  }

  async function ensureChunk(caseId, chunkIndex) {
    const item = caseRuntime(caseId);
    if (item.chunkCache.has(chunkIndex)) {
      const value = item.chunkCache.get(chunkIndex);
      item.chunkCache.delete(chunkIndex);
      item.chunkCache.set(chunkIndex, value);
      return value;
    }
    if (item.chunkPromises.has(chunkIndex)) return item.chunkPromises.get(chunkIndex);
    const summary = DATA.catalog.cases.find((entry) => entry.id === caseId);
    const path = summary.chunkPattern.replace("{chunk:03d}", String(chunkIndex).padStart(3, "0"));
    const key = "chunk:" + caseId + ":" + chunkIndex;
    const promise = loadScriptOnce(key, path).then(() => {
      const registered = DATA.pendingChunks[caseId] && DATA.pendingChunks[caseId][chunkIndex];
      if (!registered) throw new Error("帧块未注册: Case " + caseId + " / " + chunkIndex);
      delete DATA.pendingChunks[caseId][chunkIndex];
      item.chunkCache.set(chunkIndex, registered);
      while (item.chunkCache.size > 5) {
        const oldest = item.chunkCache.keys().next().value;
        item.chunkCache.delete(oldest);
        runtime.loadedScripts.delete("chunk:" + caseId + ":" + oldest);
      }
      return registered;
    }).finally(() => item.chunkPromises.delete(chunkIndex));
    item.chunkPromises.set(chunkIndex, promise);
    return promise;
  }

  async function ensureHistoryBucket(caseId, ballId) {
    const item = caseRuntime(caseId);
    const bucketCount = DATA.caseMeta[caseId].historyBucketCount;
    const bucket = ballId % bucketCount;
    if (item.historyCache.has(bucket)) return item.historyCache.get(bucket);
    if (item.historyPromises.has(bucket)) return item.historyPromises.get(bucket);
    const summary = DATA.catalog.cases.find((entry) => entry.id === caseId);
    const path = summary.historyPattern.replace("{bucket:03d}", String(bucket).padStart(3, "0"));
    const key = "history:" + caseId + ":" + bucket;
    const promise = loadScriptOnce(key, path).then(() => {
      const registered = DATA.pendingHistories[caseId] && DATA.pendingHistories[caseId][bucket];
      if (!registered) throw new Error("颗粒历史桶未注册: Case " + caseId + " / " + bucket);
      delete DATA.pendingHistories[caseId][bucket];
      item.historyCache.set(bucket, registered);
      while (item.historyCache.size > 6) {
        const oldest = item.historyCache.keys().next().value;
        item.historyCache.delete(oldest);
        runtime.loadedScripts.delete("history:" + caseId + ":" + oldest);
      }
      return registered;
    }).finally(() => item.historyPromises.delete(bucket));
    item.historyPromises.set(bucket, promise);
    return promise;
  }

  const viewerStarted = performance.now();
  let renderer;
  let scene;
  let camera;
  let controls;
  let staticBalls;
  let staticCases;
  let staticById;
  let particles;
  let particleMaterial;
  let particleDummy;
  let colorBuffer;
  let visibleIds = [];
  let currentFrameData = null;
  let crackTension;
  let crackShear;
  let wallLines;
  let contactLines;
  let bondLines;
  let highlightGroup;
  let axesHelper;
  let domainBox;
  let grid;
  let clippingPlane;
  let dmin;
  let dmax;
  let center;
  let span;
  let focusCenter;
  let focusSpan;
  let keyLight;
  let currentViewPreset = "fit";
  let is2D;
  let perspectiveCamera;
  let orthographicCamera;
  let orthoExtent;
  let pointerDown = null;
  let stateRenderQueued = false;
  let pendingState = null;
  let pendingReason = "update";
  let lastRenderedState = null;

  function ballFocusBounds(balls) {
    const lo = new THREE.Vector3(Infinity, Infinity, Infinity);
    const hi = new THREE.Vector3(-Infinity, -Infinity, -Infinity);
    (balls || []).forEach((ball) => {
      const radius = Math.max(0, Number(ball[4]) || 0);
      lo.min(new THREE.Vector3(ball[1] - radius, ball[2] - radius, ball[3] - radius));
      hi.max(new THREE.Vector3(ball[1] + radius, ball[2] + radius, ball[3] + radius));
    });
    if (!Number.isFinite(lo.x) || !Number.isFinite(hi.x)) {
      return { center: new THREE.Vector3(), span: 1 };
    }
    return {
      center: lo.clone().add(hi).multiplyScalar(0.5),
      span: Math.max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z, 1.0e-6)
    };
  }

  function webglProbe() {
    const canvas = document.createElement("canvas");
    for (const name of ["webgl2", "webgl", "experimental-webgl"]) {
      try {
        const context = canvas.getContext(name);
        if (context) return { available: true, context: name };
      } catch (ignored) {}
    }
    return { available: false, context: null };
  }

  function createScene() {
    staticCases = DATA.static.cases || {};
    const defaultCase = DATA.catalog.meta.defaultCase;
    if (!Object.keys(staticCases).length) {
      staticCases[String(defaultCase)] = DATA.static;
    }
    staticBalls = (staticCases[String(defaultCase)] || DATA.static).balls;
    staticById = new Map();
    const radii = new Float32Array(staticBalls.length);
    const initialXYZ = new Float32Array(staticBalls.length * 3);
    staticBalls.forEach((ball, index) => {
      staticById.set(ball[0], { index, radius: ball[4] });
      radii[index] = ball[4];
      initialXYZ[index * 3] = ball[1];
      initialXYZ[index * 3 + 1] = ball[2];
      initialXYZ[index * 3 + 2] = ball[3];
    });

    const domain = DATA.catalog.meta.domain;
    dmin = new THREE.Vector3().fromArray(domain.min);
    dmax = new THREE.Vector3().fromArray(domain.max);
    center = dmin.clone().add(dmax).multiplyScalar(0.5);
    span = Math.max(dmax.x - dmin.x, dmax.y - dmin.y, dmax.z - dmin.z, 1e-6);
    const focus = ballFocusBounds(staticBalls);
    focusCenter = focus.center;
    focusSpan = focus.span;
    is2D = Number(DATA.catalog.meta.dimension) === 2;

    scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf7f9fb);
    renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
      preserveDrawingBuffer: false
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    if ("outputColorSpace" in renderer && THREE.SRGBColorSpace) renderer.outputColorSpace = THREE.SRGBColorSpace;
    else if (THREE.sRGBEncoding != null) renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.NoToneMapping;
    renderer.toneMappingExposure = 1;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.localClippingEnabled = true;
    byId("scene").appendChild(renderer.domElement);

    perspectiveCamera = new THREE.PerspectiveCamera(40, 1, span * 0.001, span * 100);
    perspectiveCamera.position.copy(center).add(new THREE.Vector3(span * 1.18, -span * 1.48, span * 0.72));
    orthoExtent = span * 0.72;
    orthographicCamera = new THREE.OrthographicCamera(
      -orthoExtent, orthoExtent, orthoExtent, -orthoExtent, span * 0.001, span * 100
    );
    orthographicCamera.position.copy(center).add(new THREE.Vector3(0, 0, span * 2.2));
    camera = is2D ? orthographicCamera : perspectiveCamera;
    controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.target.copy(center);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    const hemisphere = new THREE.HemisphereLight(0xffffff, 0x8491b4, 0.64);
    scene.add(hemisphere);
    keyLight = new THREE.DirectionalLight(0xffffff, 1.12);
    keyLight.position.copy(focusCenter).add(new THREE.Vector3(focusSpan, -focusSpan * 0.75, focusSpan * 1.4));
    keyLight.castShadow = true;
    keyLight.shadow.mapSize.set(1024, 1024);
    keyLight.shadow.camera.near = focusSpan * 0.001;
    keyLight.shadow.camera.far = focusSpan * 6;
    keyLight.shadow.camera.left = -focusSpan;
    keyLight.shadow.camera.right = focusSpan;
    keyLight.shadow.camera.top = focusSpan;
    keyLight.shadow.camera.bottom = -focusSpan;
    keyLight.shadow.bias = -0.00015;
    keyLight.shadow.normalBias = focusSpan * 0.002;
    keyLight.shadow.camera.updateProjectionMatrix();
    keyLight.target.position.copy(focusCenter);
    scene.add(keyLight, keyLight.target);
    const fill = new THREE.DirectionalLight(0xffffff, 0.26);
    fill.position.copy(center).add(new THREE.Vector3(-span, span * 0.35, span * 0.4));
    scene.add(fill);

    grid = new THREE.GridHelper(span * 1.6, 16, 0xd5d8de, 0xebeef0);
    if (is2D) {
      grid.rotation.x = Math.PI / 2;
      grid.position.set(center.x, center.y, dmin.z - span * 0.006);
    } else {
      grid.position.set(center.x, dmin.y - span * 0.006, center.z);
    }
    grid.material.transparent = true;
    grid.material.opacity = 0.65;
    grid.visible = is2D && byId("showAxes").checked;
    scene.add(grid);
    const axesPositions = [];
    const axesColors = [];
    const axisDefinitions = [
      { end: [span * 0.28, 0, 0], color: COLORS.primary },
      { end: [0, span * 0.28, 0], color: COLORS.slate },
    ];
    if (!is2D) {
      axisDefinitions.push({ end: [0, 0, span * 0.28], color: COLORS.tan });
    }
    axisDefinitions.forEach(({ end, color }) => {
      const parsed = new THREE.Color(color);
      axesPositions.push(0, 0, 0, end[0], end[1], end[2]);
      axesColors.push(parsed.r, parsed.g, parsed.b, parsed.r, parsed.g, parsed.b);
    });
    const axesGeometry = new THREE.BufferGeometry();
    axesGeometry.setAttribute("position", new THREE.Float32BufferAttribute(axesPositions, 3));
    axesGeometry.setAttribute("color", new THREE.Float32BufferAttribute(axesColors, 3));
    axesHelper = new THREE.LineSegments(
      axesGeometry,
      new THREE.LineBasicMaterial({ vertexColors: true })
    );
    axesHelper.position.copy(dmin);
    scene.add(axesHelper);
    domainBox = new THREE.Box3Helper(new THREE.Box3(dmin.clone(), dmax.clone()), 0xb4bac6);
    domainBox.material.transparent = true;
    domainBox.material.opacity = 0.3;
    domainBox.visible = byId("showBounds").checked;
    scene.add(domainBox);
    clippingPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), dmax.z);

    particleMaterial = new THREE.MeshStandardMaterial({
      roughness: 0.74,
      metalness: 0.0,
      side: is2D ? THREE.DoubleSide : THREE.FrontSide,
      toneMapped: false,
      clippingPlanes: []
    });
    const maxStaticBalls = Math.max(
      1,
      ...Object.values(staticCases).map((item) => item.balls.length),
      staticBalls.length
    );
    particles = new THREE.InstancedMesh(
      is2D ? new THREE.CircleGeometry(1, 32) : new THREE.SphereGeometry(1, 18, 12),
      particleMaterial,
      maxStaticBalls
    );
    particles.frustumCulled = false;
    particles.castShadow = !is2D;
    particles.receiveShadow = !is2D;
    particles.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    particles.instanceColor = new THREE.InstancedBufferAttribute(
      new Float32Array(maxStaticBalls * 3), 3
    );
    particles.instanceColor.setUsage(THREE.DynamicDrawUsage);
    particles.count = 0;
    scene.add(particles);
    particleDummy = new THREE.Object3D();
    colorBuffer = particles.instanceColor.array;

    highlightGroup = new THREE.Group();
    scene.add(highlightGroup);
    wallLines = new THREE.LineSegments(
      new THREE.BufferGeometry(),
      new THREE.LineBasicMaterial({ color: 0x5f718f, transparent: true, opacity: 0.94 })
    );
    wallLines.frustumCulled = false;
    wallLines.visible = false;
    scene.add(wallLines);
    const makeNetworkLayer = () => {
      const geometry = new THREE.BufferGeometry();
      const positions = new THREE.BufferAttribute(new Float32Array(0), 3);
      const colors = new THREE.BufferAttribute(new Float32Array(0), 3);
      positions.setUsage(THREE.DynamicDrawUsage);
      colors.setUsage(THREE.DynamicDrawUsage);
      geometry.setAttribute("position", positions);
      geometry.setAttribute("color", colors);
      geometry.setDrawRange(0, 0);
      const layer = new THREE.LineSegments(
        geometry,
        new THREE.LineBasicMaterial({
          vertexColors: true,
          transparent: true,
          opacity: 0.9,
          clippingPlanes: []
        })
      );
      layer.frustumCulled = false;
      layer.visible = false;
      scene.add(layer);
      return layer;
    };
    contactLines = makeNetworkLayer();
    bondLines = makeNetworkLayer();
    buildCrackLayers([]);

    renderer.domElement.addEventListener("pointerdown", (event) => {
      pointerDown = { x: event.clientX, y: event.clientY };
    });
    renderer.domElement.addEventListener("pointerup", handleSceneClick);
    window.addEventListener("resize", resize);
  }

  function buildCrackLayers(records) {
    if (crackTension) {
      scene.remove(crackTension);
      crackTension.geometry.dispose();
      crackTension.material.dispose();
    }
    if (crackShear) {
      scene.remove(crackShear);
      crackShear.geometry.dispose();
      crackShear.material.dispose();
    }
    const make = (rows, color) => {
      const positions = new Float32Array(Math.max(2, rows.length * 6));
      const geometry = new THREE.BufferGeometry();
      const attribute = new THREE.BufferAttribute(positions, 3);
      attribute.setUsage(THREE.DynamicDrawUsage);
      geometry.setAttribute("position", attribute);
      geometry.setDrawRange(0, 0);
      const line = new THREE.LineSegments(
        geometry,
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.92, clippingPlanes: [] })
      );
      line.frustumCulled = false;
      line.userData.rows = rows;
      scene.add(line);
      return line;
    };
    crackTension = make(records.filter((row) => row[7] === 0), COLORS.primary);
    crackShear = make(records.filter((row) => row[7] === 1), COLORS.fracture);
    updateCracks(0);
  }

  function updateCracks(cycle) {
    if (!runtime.current) return;
    const rows = runtime.current.meta.cracks || [];
    const visible = rows.filter((row) => row[6] <= cycle);
    const tension = visible.filter((row) => row[7] === 0);
    const shear = visible.filter((row) => row[7] === 1);
    const write = (line, selected) => {
      const attribute = line.geometry.getAttribute("position");
      const array = attribute.array;
      array.fill(0);
      selected.forEach((row, index) => {
        const offset = index * 6;
        array[offset] = row[0];
        array[offset + 1] = row[1];
        array[offset + 2] = row[2];
        array[offset + 3] = row[3];
        array[offset + 4] = row[4];
        array[offset + 5] = row[5];
      });
      attribute.needsUpdate = true;
      line.geometry.setDrawRange(0, selected.length * 2);
    };
    write(crackTension, tension);
    write(crackShear, shear);
    const show = byId("showCracks").checked;
    crackTension.visible = show && tension.length > 0;
    crackShear.visible = show && shear.length > 0;
    body.dataset.cracksVisible = String(visible.length);
    body.dataset.tensionVisible = String(tension.length);
    body.dataset.shearVisible = String(shear.length);
  }

  function updateParticles(frame, highlightIds) {
    const ids = decodeU32(frame.ids);
    const xyz = decodeF32(frame.xyz);
    const displacement = decodeF32(frame.displacement);
    const speed = decodeF32(frame.speed);
    const acceleration = decodeF32(frame.acceleration);
    const radii = decodeF32(frame.radius);
    const colorMetric = store.get().colorMetric;
    const metricValues = colorMetric === "speed"
      ? speed
      : (colorMetric === "acceleration" ? acceleration : displacement);
    const finiteValues = [];
    for (let index = 0; index < metricValues.length; index += 1) {
      if (Number.isFinite(metricValues[index])) finiteValues.push(metricValues[index]);
    }
    finiteValues.sort((left, right) => left - right);
    const fallbackMax = colorMetric === "speed"
      ? runtime.current.summary.maxSpeed
      : (colorMetric === "acceleration"
        ? runtime.current.summary.maxAcceleration
        : runtime.current.summary.maxDisplacement);
    const low = finiteValues.length ? finiteValues[Math.floor((finiteValues.length - 1) * 0.05)] : 0;
    const high = finiteValues.length ? finiteValues[Math.floor((finiteValues.length - 1) * 0.95)] : fallbackMax;
    const colorLow = Number.isFinite(low) ? low : 0;
    const colorHigh = Number.isFinite(high) && high > colorLow ? high : Math.max(fallbackMax, colorLow, 1e-12);
    runtime.colorRange = { metric: colorMetric, low: colorLow, high: colorHigh, method: "P05_P95" };
    const selected = new Set(highlightIds);
    const staticIds = new Set(staticBalls.map((ball) => ball[0]));
    const currentIds = new Set(ids);
    let dynamicAddedCount = 0;
    for (const ballId of ids) {
      if (!staticIds.has(ballId)) dynamicAddedCount += 1;
    }
    let removedFromStaticCount = 0;
    for (const ballId of staticIds) {
      if (!currentIds.has(ballId)) removedFromStaticCount += 1;
    }
    visibleIds = Array.from(ids);
    particles.count = ids.length;
    for (let index = 0; index < ids.length; index += 1) {
      const ballId = ids[index];
      const staticBall = staticById.get(ballId);
      const fallbackRadius = staticBall ? staticBall.radius : 0;
      const radius = Number.isFinite(radii[index]) && radii[index] > 0 ? radii[index] : fallbackRadius;
      particleDummy.position.set(xyz[index * 3], xyz[index * 3 + 1], xyz[index * 3 + 2]);
      particleDummy.scale.setScalar(radius);
      particleDummy.updateMatrix();
      particles.setMatrixAt(index, particleDummy.matrix);
      const value = colorMetric === "speed"
        ? speed[index]
        : (colorMetric === "acceleration" ? acceleration[index] : displacement[index]);
      let color;
      if (selected.has(ballId)) color = accentColor;
      else if (!Number.isFinite(value)) color = missingColor;
      else color = colorRamp[Math.max(0, Math.min(255, Math.round(
        ((value - colorLow) / (colorHigh - colorLow)) * 255
      )))];
      colorBuffer[index * 3] = color.r != null ? color.r : color[0];
      colorBuffer[index * 3 + 1] = color.g != null ? color.g : color[1];
      colorBuffer[index * 3 + 2] = color.b != null ? color.b : color[2];
    }
    particles.instanceMatrix.needsUpdate = true;
    particles.instanceColor.needsUpdate = true;
    body.dataset.frameBallCount = String(ids.length);
    body.dataset.missingBallCount = String(removedFromStaticCount);
    body.dataset.dynamicAddedBallCount = String(dynamicAddedCount);
    body.dataset.highlightCount = String(selected.size);
    body.dataset.colorLow = String(colorLow);
    body.dataset.colorHigh = String(colorHigh);
    body.dataset.colorScaleMethod = runtime.colorRange.method;
    updateWalls(frame);
    updateNetworkLayers(frame, ids, xyz);
    updateTrajectories();
  }

  function updateWalls(frame) {
    if (!frame.wallIds) {
      wallLines.visible = false;
      return;
    }
    const wallIds = decodeU32(frame.wallIds);
    const vertexIds = decodeU32(frame.wallVertexIds);
    const xyz = decodeF32(frame.wallXyz);
    const positions = [];
    for (let index = 1; index < wallIds.length; index += 1) {
      if (wallIds[index] !== wallIds[index - 1]) continue;
      if (vertexIds[index] !== vertexIds[index - 1] + 1) continue;
      positions.push(
        xyz[(index - 1) * 3], xyz[(index - 1) * 3 + 1], xyz[(index - 1) * 3 + 2],
        xyz[index * 3], xyz[index * 3 + 1], xyz[index * 3 + 2]
      );
    }
    wallLines.geometry.dispose();
    wallLines.geometry = new THREE.BufferGeometry();
    wallLines.geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
    wallLines.visible = byId("showWalls").checked && positions.length > 0;
  }

  function updateNetworkLayers(frame, ids, xyz) {
    const positionsById = new Map();
    for (let index = 0; index < ids.length; index += 1) {
      positionsById.set(
        ids[index],
        [xyz[index * 3], xyz[index * 3 + 1], xyz[index * 3 + 2]]
      );
    }
    const write = (layer, payload, enabled, lowColor, highColor) => {
      if (!layer) return;
      if (!payload || !enabled) {
        layer.visible = false;
        layer.geometry.setDrawRange(0, 0);
        return;
      }
      const a = decodeU32(payload.a);
      const b = decodeU32(payload.b);
      const force = decodeF32(payload.force);
      const finiteForce = Array.from(force).filter(Number.isFinite);
      const low = finiteForce.length ? Math.min(...finiteForce) : 0;
      const high = finiteForce.length ? Math.max(...finiteForce) : low;
      const lowRgb = new THREE.Color(lowColor);
      const highRgb = new THREE.Color(highColor);
      const positions = [];
      const colors = [];
      for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
        const left = positionsById.get(a[index]);
        const right = positionsById.get(b[index]);
        if (!left || !right) continue;
        positions.push(left[0], left[1], left[2], right[0], right[1], right[2]);
        const t = Number.isFinite(force[index]) && high > low
          ? Math.max(0, Math.min(1, (force[index] - low) / (high - low)))
          : 0;
        const color = lowRgb.clone().lerp(highRgb, t);
        colors.push(color.r, color.g, color.b, color.r, color.g, color.b);
      }
      layer.geometry.dispose();
      const geometry = new THREE.BufferGeometry();
      const positionAttribute = new THREE.Float32BufferAttribute(positions, 3);
      positionAttribute.setUsage(THREE.DynamicDrawUsage);
      geometry.setAttribute("position", positionAttribute);
      geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
      geometry.setDrawRange(0, positions.length / 3);
      layer.geometry = geometry;
      layer.visible = positions.length > 0;
      body.dataset[layer === contactLines ? "contactSegments" : "bondSegments"] =
        String(positions.length / 6);
    };
    write(
      contactLines,
      frame.contacts,
      byId("showContacts").checked,
      COLORS.tan,
      COLORS.fracture
    );
    write(
      bondLines,
      frame.bonds,
      byId("showBonds").checked,
      COLORS.primary,
      COLORS.fracture
    );
  }

  function highlightIdsForState() {
    const state = store.get();
    const selected = new Set(state.selectedBallIds);
    if (state.selectedRange && currentFrameData) {
      const values = decodeF32(
        state.selectedMetric === "speed"
          ? currentFrameData.speed
          : (state.selectedMetric === "acceleration"
            ? currentFrameData.acceleration
            : currentFrameData.displacement)
      );
      const ids = decodeU32(currentFrameData.ids);
      const range = state.selectedRange;
      for (let index = 0; index < ids.length; index += 1) {
        if (Number.isFinite(values[index]) && values[index] >= range[0] && values[index] <= range[1]) {
          selected.add(ids[index]);
        }
      }
    }
    return Array.from(selected);
  }

  function updateSelectionVisuals() {
    if (!currentFrameData || !particles) return;
    const highlightIds = highlightIdsForState();
    updateParticles(currentFrameData, highlightIds);
    updateSelectionSummary(highlightIds);
  }

  function updateSelectionSummary(highlightIds) {
    const state = store.get();
    const summary = byId("selectionSummary");
    const span = summary.querySelector("span");
    const detail = summary.querySelector("small");
    if (state.selectedRange) {
      const metric = state.selectedMetric === "speed"
        ? "速度"
        : (state.selectedMetric === "acceleration" ? "加速度" : "累计位移");
      span.textContent = metric + " ∈ [" + formatNumber(state.selectedRange[0], 4) + ", " +
        formatNumber(state.selectedRange[1], 4) + "]";
      detail.textContent = "当前帧高亮 " + highlightIds.length + " 个颗粒；区间只作用于当前真实采样帧";
    } else if (state.selectedBallIds.length) {
      span.textContent = "Ball ID: " + state.selectedBallIds.slice(0, 8).join(", ") +
        (state.selectedBallIds.length > 8 ? " …" : "");
      detail.textContent = "Shift/Ctrl 点击可多选；历史曲线仅连接实测观测";
    } else {
      span.textContent = "未选择颗粒";
      detail.textContent = "点击三维颗粒，或拖动当前分布图选择区间";
    }
  }

  function handleSceneClick(event) {
    if (!pointerDown || !currentFrameData) return;
    const moved = Math.hypot(event.clientX - pointerDown.x, event.clientY - pointerDown.y);
    pointerDown = null;
    if (moved > 4) return;
    const rect = renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1
    );
    const raycaster = new THREE.Raycaster();
    raycaster.params.Points = { threshold: span * 0.01 };
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObject(particles, false);
    if (!hits.length || hits[0].instanceId == null) return;
    const ballId = visibleIds[hits[0].instanceId];
    if (ballId == null) return;
    actions.selectBalls([ballId], {
      additive: event.shiftKey || event.ctrlKey || event.metaKey,
      focus: event.altKey,
      source: "scene"
    });
  }

  function clearTrajectories() {
    runtime.trajectories.forEach((line) => {
      scene.remove(line);
      line.geometry.dispose();
      line.material.dispose();
    });
    runtime.trajectories = [];
    highlightGroup.clear();
  }

  function updateTrajectories() {
    clearTrajectories();
    if (!byId("showTrajectory").checked || !runtime.current) return;
    const palette = [COLORS.accent, COLORS.primary, COLORS.fracture, COLORS.tan, COLORS.slate];
    const ids = store.get().selectedBallIds;
    ids.slice(0, 8).forEach((ballId, index) => {
      const rows = runtime.selectedHistories.get(ballId);
      if (!rows || rows.length < 2) return;
      const points = rows.map((row) => new THREE.Vector3(row.x, row.y, row.z));
      const line = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({
          color: palette[index % palette.length],
          transparent: true,
          opacity: 0.92,
          depthTest: false
        })
      );
      line.renderOrder = 25;
      line.frustumCulled = false;
      scene.add(line);
      runtime.trajectories.push(line);
    });
  }

  function focusBall(ballId) {
    if (!currentFrameData) return;
    const ids = decodeU32(currentFrameData.ids);
    const xyz = decodeF32(currentFrameData.xyz);
    const index = Array.prototype.indexOf.call(ids, ballId);
    if (index < 0) {
      byId("ballInput").setCustomValidity("当前真实帧不包含该 Ball ID。");
      byId("ballInput").reportValidity();
      return false;
    }
    byId("ballInput").setCustomValidity("");
    const point = new THREE.Vector3(xyz[index * 3], xyz[index * 3 + 1], xyz[index * 3 + 2]);
    const direction = camera.position.clone().sub(controls.target).normalize();
    controls.target.copy(point);
    camera.position.copy(point).add(direction.multiplyScalar(Math.max(span * 0.26, 1e-9)));
    camera.lookAt(point);
    controls.update();
    return true;
  }

  function createChartPanel(title, status, wide) {
    const section = document.createElement("section");
    section.className = "chart-panel" + (wide ? " wide" : "");
    const header = document.createElement("header");
    const heading = document.createElement("h3");
    heading.textContent = title;
    const note = document.createElement("span");
    note.textContent = status || "";
    const div = document.createElement("div");
    div.className = "chart";
    header.append(heading, note);
    section.append(header, div);
    return { section, div, title: heading, status: note };
  }

  function chartColors() {
    return [
      COLORS.primary, COLORS.fracture, COLORS.slate, COLORS.tan, COLORS.accent
    ];
  }

  function axisStyle(name, unit, formatting) {
    return {
      type: "value",
      name: name + axisUnit(unit),
      nameLocation: "middle",
      nameGap: 30,
      nameTextStyle: { color: COLORS.muted, fontSize: 9 },
      axisLine: { lineStyle: { color: "#3d3d3d", width: 0.8 } },
      axisTick: { lineStyle: { color: "#8a8a86", width: 0.6 } },
      axisLabel: {
        color: COLORS.muted,
        fontSize: 9,
        hideOverlap: true,
        formatter: (value) => formatAxisValue(value, formatting)
      },
      splitLine: { show: false }
    };
  }

  function categoryStyle(name, unit, data, formatting) {
    return {
      type: "category",
      name: name + axisUnit(unit),
      data,
      boundaryGap: false,
      axisLine: { lineStyle: { color: "#3d3d3d", width: 0.8 } },
      axisTick: { show: false },
      axisLabel: {
        color: COLORS.muted,
        fontSize: 9,
        hideOverlap: true,
        formatter: (value) => formatAxisValue(value, formatting)
      },
      splitLine: { show: false }
    };
  }

  function baseOption(spec) {
    return {
      animation: false,
      textStyle: { fontFamily: "Arial, Helvetica, PingFang SC, Microsoft YaHei, sans-serif" },
      title: {
        show: false,
        text: spec && spec.title ? spec.title : "",
        left: 12,
        top: 8,
        textStyle: {
          color: COLORS.ink,
          fontSize: 12,
          fontWeight: 600,
          fontFamily: "Arial, Helvetica, PingFang SC, Microsoft YaHei, sans-serif"
        }
      },
      grid: { left: 68, right: 32, top: 58, bottom: 54, containLabel: false },
      tooltip: {
        trigger: "axis",
        confine: true,
        backgroundColor: "rgba(255,255,255,0.96)",
        borderColor: "#d9d9d5",
        textStyle: { color: COLORS.ink, fontSize: 10 },
        axisPointer: { type: "cross", lineStyle: { color: COLORS.slate, width: 0.7 } },
        formatter: (input) => {
          const rows = Array.isArray(input) ? input : [input];
          if (!rows.length) return "";
          const firstValue = rows[0].value;
          const heading = Array.isArray(firstValue)
            ? ((spec && spec.x && spec.x.name) || "x") + ": " +
              formatTooltipValue(firstValue[0], spec && spec.display && spec.display.x && spec.display.x.formatting)
            : (rows[0].axisValueLabel ?? rows[0].name ?? "");
          const seen = new Set();
          const body = rows.filter((row) => {
            const raw = Array.isArray(row.value) ? row.value[row.value.length - 1] : row.value;
            const key = String(row.seriesIndex) + ":" + String(row.seriesName) + ":" + String(raw);
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
          }).map((row) => {
            const raw = Array.isArray(row.value) ? row.value[row.value.length - 1] : row.value;
            const seriesFormatting = spec && spec.display && Array.isArray(spec.display.series)
              ? spec.display.series[row.seriesIndex || 0]
              : null;
            const valueFormatting = Array.isArray(row.value) && row.value.length === 3
              ? (spec && spec.display && spec.display.z)
              : (seriesFormatting || (spec && spec.display && spec.display.y));
            return (row.marker || "") + row.seriesName + ": " +
              formatTooltipValue(raw, valueFormatting && valueFormatting.formatting);
          });
          return [heading].concat(body).filter(Boolean).join("<br>");
        }
      },
      legend: {
        right: 10,
        top: 20,
        itemWidth: 13,
        itemHeight: 2,
        textStyle: { color: COLORS.muted, fontSize: 9 },
        selectedMode: false
      }
    };
  }

  function lineSeries(name, data, color, axisIndex) {
    return {
      name,
      type: "line",
      data,
      yAxisIndex: axisIndex || 0,
      showSymbol: false,
      connectNulls: false,
      smooth: false,
      lineStyle: { width: 1.35, color },
      itemStyle: { color },
      emphasis: { focus: "series" }
    };
  }

  function histogramOption(spec) {
    const option = baseOption(spec);
    const centers = [];
    for (let index = 0; index < spec.edges.length - 1; index += 1) {
      centers.push((spec.edges[index] + spec.edges[index + 1]) / 2);
    }
    option.grid.bottom = 48;
    option.xAxis = categoryStyle(
      "分箱中心",
      spec.unit || "",
      centers,
      spec.display && spec.display.x && spec.display.x.formatting
    );
    option.xAxis.boundaryGap = true;
    option.yAxis = axisStyle(
      "颗粒数",
      "count",
      spec.display && spec.display.y && spec.display.y.formatting
    );
    option.series = [{
      type: "bar",
      data: spec.counts,
      barCategoryGap: "2%",
      itemStyle: { color: spec.color || COLORS.slate, opacity: 0.86 }
    }];
    return option;
  }

  function heatmapOption(spec) {
    const option = baseOption(spec);
    const xCenters = spec.x.slice(0, -1).map((value, index) => (value + spec.x[index + 1]) / 2);
    const yCenters = spec.y.slice(0, -1).map((value, index) => (value + spec.y[index + 1]) / 2);
    const points = [];
    let maximum = 0;
    spec.z.forEach((row, xIndex) => row.forEach((value, yIndex) => {
      const number = finiteNumber(value);
      if (number !== null) maximum = Math.max(maximum, number);
      points.push([xIndex, yIndex, number]);
    }));
    option.grid = { left: 88, right: 58, top: 56, bottom: 58, containLabel: false };
    option.tooltip = { ...option.tooltip, trigger: "item" };
    option.xAxis = categoryStyle(
      "x 分箱中心",
      "m",
      xCenters,
      spec.display && spec.display.x && spec.display.x.formatting
    );
    option.yAxis = categoryStyle(
      "y 分箱中心",
      "m",
      yCenters,
      spec.display && spec.display.y && spec.display.y.formatting
    );
    option.xAxis.boundaryGap = false;
    option.yAxis.boundaryGap = false;
    option.xAxis.axisLabel.interval = Math.max(0, Math.floor(xCenters.length / 6));
    option.yAxis.axisLabel.interval = Math.max(0, Math.floor(yCenters.length / 7));
    option.visualMap = {
      min: 0,
      max: Math.max(1, maximum),
      calculable: false,
      orient: "vertical",
      right: 5,
      top: "middle",
      itemWidth: 8,
      itemHeight: 86,
      text: ["高", "0"],
      textStyle: { color: COLORS.muted, fontSize: 8.5 },
      inRange: { color: ["#f3f5f8", "#aab6ca", COLORS.primary] }
    };
    option.series = [{
      type: "heatmap",
      data: points,
      itemStyle: { borderWidth: 0, borderRadius: 1, opacity: 0.96 },
      emphasis: { itemStyle: { borderColor: COLORS.ink, borderWidth: 0.6 } }
    }];
    return option;
  }

  function correlationOption(spec) {
    const option = heatmapOption({
      x: spec.labels,
      y: spec.labels,
      z: spec.values,
      unit: ""
    });
    const values = [];
    spec.values.forEach((row, xIndex) => row.forEach((value, yIndex) => values.push([xIndex, yIndex, value])));
    option.grid = { left: 104, right: 64, top: 54, bottom: 80, containLabel: false };
    option.xAxis = {
      type: "category", data: spec.labels, axisLabel: { color: COLORS.muted, fontSize: 9, interval: 0, rotate: 18 }
    };
    option.yAxis = {
      type: "category", data: spec.labels, axisLabel: { color: COLORS.muted, fontSize: 9, interval: 0 }
    };
    option.visualMap = {
      min: -1, max: 1, calculable: false, orient: "vertical", right: 6, top: "middle",
      itemWidth: 8, itemHeight: 86, text: ["+1", "−1"],
      textStyle: { color: COLORS.muted, fontSize: 8.5 },
      inRange: { color: [COLORS.fracture, "#ffffff", COLORS.primary] }
    };
    option.series = [{ type: "heatmap", data: values, itemStyle: { borderWidth: 0.5, borderColor: "#fff" } }];
    return option;
  }

  function roseOption(spec) {
    const bins = new Array(16).fill(0);
    (spec.angles || []).forEach((angle) => {
      const number = finiteNumber(angle);
      if (number === null) return;
      const index = Math.max(0, Math.min(15, Math.floor((number % 360) / 22.5)));
      bins[index] += 1;
    });
    const labels = bins.map((_, index) => String(index * 22.5));
    const option = baseOption(spec);
    option.tooltip.trigger = "item";
    option.grid = null;
    option.legend = { show: false };
    option.polar = { radius: "68%" };
    option.angleAxis = {
      type: "category", data: labels, boundaryGap: true,
      axisLine: { lineStyle: { color: "#3d3d3d", width: 0.8 } },
      axisLabel: { color: COLORS.muted, fontSize: 8 },
      splitLine: { show: false }
    };
    option.radiusAxis = {
      type: "value",
      axisLabel: { color: COLORS.muted, fontSize: 8 },
      splitLine: { lineStyle: { color: COLORS.grid, width: 0.6 } }
    };
    option.series = [{
      type: "bar", coordinateSystem: "polar", data: bins,
      itemStyle: { color: spec.color || COLORS.fracture, opacity: 0.84 }
    }];
    return option;
  }

  function radarOption(spec) {
    const option = baseOption(spec);
    option.grid = null;
    option.radar = {
      indicator: spec.indicators,
      radius: "62%",
      splitLine: { lineStyle: { color: COLORS.grid } },
      axisLine: { lineStyle: { color: COLORS.grid } },
      axisName: { color: COLORS.muted, fontSize: 8 }
    };
    option.series = [{
      type: "radar",
      data: spec.series.map((item, index) => ({
        ...item,
        lineStyle: { color: chartColors()[index % 5], width: 1.2 },
        itemStyle: { color: chartColors()[index % 5] }
      }))
    }];
    return option;
  }

  function caseCompareOption(spec) {
    const option = baseOption(spec);
    option.xAxis = {
      type: "category",
      data: spec.data.map((row) => "C" + row.case_id),
      axisLine: { lineStyle: { color: "#3d3d3d", width: 0.8 } },
      axisTick: { show: false },
      axisLabel: { color: COLORS.muted, fontSize: 8.5 }
    };
    option.yAxis = axisStyle(
      spec.metric_name || "值",
      spec.metric_unit || "",
      spec.display && spec.display.values && spec.display.values.formatting
    );
    option.series = [{
      type: "bar",
      data: spec.data.map((row, index) => {
        const raw = finiteNumber(row[spec.metric_key]);
        return {
          value: raw === null ? null : raw * (spec.scale || 1),
          itemStyle: { color: (spec.colors || chartColors())[index % (spec.colors || chartColors()).length] }
        };
      }),
      barMaxWidth: 22
    }];
    return option;
  }

  function buildChartOption(spec) {
    if (!spec) return null;
    if (spec.type === "histogram") return histogramOption(spec);
    if (spec.type === "heatmap") return heatmapOption(spec);
    if (spec.type === "correlation") return correlationOption(spec);
    if (spec.type === "rose") return roseOption(spec);
    if (spec.type === "polar") {
      return Array.isArray(spec.angles) && spec.angles.length
        ? roseOption(spec)
        : null;
    }
    if (spec.type === "radar") return radarOption(spec);
    if (spec.type === "case-compare") return caseCompareOption(spec);
    if (!["line", "scatter", "area", "dual-line", "bar", "grouped-bar", "stacked-bar", "boxplot"].includes(spec.type)) {
      return null;
    }
    const option = baseOption(spec);
    if (spec.type === "dual-line") {
      option.yAxis = [
        axisStyle(
          spec.series[0].name,
          spec.series[0].unit,
          spec.display && spec.display.series && spec.display.series[0] && spec.display.series[0].formatting
        ),
        axisStyle(
          spec.series[1].name,
          spec.series[1].unit,
          spec.display && spec.display.series && spec.display.series[1] && spec.display.series[1].formatting
        )
      ];
      option.yAxis[1].splitLine = { show: false };
      option.series = spec.series.map((item, index) => lineSeries(
        item.name, item.data, item.color || chartColors()[index], item.axis || index
      ));
      option.xAxis = categoryStyle(
        spec.x.name || "Cycle",
        spec.x.unit || "",
        spec.x.data,
        spec.display && spec.display.x && spec.display.x.formatting
      );
    } else {
      option.tooltip.trigger = "item";
      option.xAxis = axisStyle(
        (spec.x && spec.x.name) || "x",
        (spec.x && spec.x.unit) || "",
        spec.display && spec.display.x && spec.display.x.formatting
      );
      option.xAxis.data = spec.x ? spec.x.data : null;
      option.xAxis.type = "value";
      option.yAxis = axisStyle(
        (spec.y && spec.y.name) || "y",
        (spec.y && spec.y.unit) || "",
        spec.display && spec.display.y && spec.display.y.formatting
      );
      if (spec.type === "bar" || spec.type === "grouped-bar" || spec.type === "stacked-bar") {
        const categories = spec.x && spec.x.data ? spec.x.data : [];
        option.xAxis = {
          ...categoryStyle(
            (spec.x && spec.x.name) || "category",
            (spec.x && spec.x.unit) || "",
            categories,
            spec.display && spec.display.x && spec.display.x.formatting
          ),
          boundaryGap: true
        };
        const series = spec.series || [{ name: spec.y && spec.y.name, data: spec.y && spec.y.data, color: spec.color }];
        option.series = series.map((item, index) => ({
          name: item.name, type: "bar", stack: spec.type === "stacked-bar" ? "total" : undefined,
          data: item.data, barMaxWidth: 24,
          itemStyle: { color: item.color || chartColors()[index] }
        }));
      } else if (spec.type === "boxplot") {
        option.xAxis = categoryStyle(
          "分组",
          "",
          spec.labels || [],
          spec.display && spec.display.x && spec.display.x.formatting
        );
        option.series = [{ type: "boxplot", data: spec.data, itemStyle: { color: spec.color || COLORS.slate } }];
      } else {
        const xyData = spec.x && Array.isArray(spec.x.data) && spec.y && Array.isArray(spec.y.data)
          ? spec.y.data.map((value, index) => {
            const xValue = finiteNumber(spec.x.data[index]);
            const yValue = finiteNumber(value);
            return xValue === null || yValue === null ? [null, null] : [xValue, yValue];
          })
          : (spec.y ? spec.y.data : []);
        const userOptions = spec.options || {};
        const seriesColor = userOptions.color || spec.color || COLORS.primary;
        option.series = [{
          name: (spec.y && spec.y.name) || spec.title,
          type: spec.type === "area" ? "line" : (spec.type === "scatter" ? "scatter" : "line"),
          data: xyData,
          showSymbol: userOptions.show_symbol != null ? !!userOptions.show_symbol : spec.type === "scatter",
          symbolSize: userOptions.symbol_size || (spec.type === "scatter" ? 4 : undefined),
          areaStyle: spec.type === "area" ? { color: seriesColor, opacity: 0.14 } : undefined,
          lineStyle: {
            color: seriesColor,
            width: userOptions.line_width || 1.5
          },
          itemStyle: { color: seriesColor }
        }];
      }
    }
    option.series = (option.series || []).filter(Boolean);
    return option;
  }

  function isTemporalSpec(spec) {
    if (!spec || spec.case_id == null || !runtime.current) return false;
    if (!["line", "scatter", "area", "dual-line"].includes(spec.type)) return false;
    return Boolean(
      spec.x &&
      Array.isArray(spec.x.data) &&
      spec.x.data.length >= 2 &&
      ["s", "cycle"].includes(spec.x.unit)
    );
  }

  function temporalFrameIndex(spec, dataIndex) {
    if (!runtime.current || !spec || !spec.x || dataIndex < 0) return -1;
    if (Array.isArray(spec.source_indices)) {
      const sourceValue = finiteNumber(spec.source_indices[dataIndex]);
      const sourceIndex = sourceValue === null ? null : Math.round(sourceValue);
      if (sourceIndex === null) return -1;
      return runtime.current.meta.frames.findIndex((frame) => (
        finiteNumber(frame.sourceIndex) === sourceIndex
      ));
    }
    const value = spec.x.data[dataIndex];
    const frameValues = runtime.current.meta.frames.map((frame) => (
      spec.x.unit === "s" ? frame.time : frame.cycle
    ));
    return nearestIndex(frameValues, Number(value));
  }

  function currentTemporalValue(spec) {
    const state = store.get();
    return spec.x.unit === "s" ? state.currentTime : state.currentCycle;
  }

  function attachTemporalInteraction(chart, spec, container) {
    if (!isTemporalSpec(spec)) return;
    const cursor = document.createElement("div");
    cursor.className = "time-cursor";
    container.appendChild(cursor);
    chart.__temporalCursor = cursor;
    chart.__temporalSpec = spec;
    chart.on("click", (event) => {
      if (event.dataIndex != null) {
        const frameIndex = temporalFrameIndex(spec, event.dataIndex);
        if (frameIndex >= 0) actions.setFrame(frameIndex, { source: "chart-click" });
      }
    });
    const zr = chart.getZr();
    let dragging = false;
    const updateFromPointer = (event) => {
      let point;
      try {
        point = chart.convertFromPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY]);
      } catch (ignored) {
        return;
      }
      if (!point) return;
      const values = spec.x.data;
      const dataIndex = nearestIndex(values, Number(point[0]));
      const frameIndex = temporalFrameIndex(spec, dataIndex);
      if (frameIndex >= 0) actions.setFrame(frameIndex, { source: "chart-drag" });
    };
    zr.on("mousedown", (event) => {
      dragging = true;
      updateFromPointer(event);
    });
    zr.on("mousemove", (event) => {
      if (!dragging) return;
      updateFromPointer(event);
    });
    zr.on("mouseup", () => { dragging = false; });
    zr.on("globalout", () => { dragging = false; });
    container.addEventListener("mouseleave", () => { dragging = false; });
    zr.setCursorStyle("crosshair");
  }

  function updateTemporalMarkers() {
    if (!runtime.ready || !runtime.current) return;
    runtime.charts.forEach((entry) => {
      const spec = entry.spec;
      const cursor = entry.chart && entry.chart.__temporalCursor;
      if (!spec || !cursor || !isTemporalSpec(spec)) return;
      const x = Number(currentTemporalValue(spec));
      let pixel;
      try {
        pixel = entry.chart.convertToPixel({ xAxisIndex: 0 }, x);
      } catch (ignored) {
        pixel = null;
      }
      if (!Number.isFinite(pixel)) {
        cursor.hidden = true;
        return;
      }
      cursor.hidden = false;
      cursor.style.left = pixel.toFixed(2) + "px";
    });
    if (runtime.historyChart && runtime.historyChart.__temporal) {
      const value = store.get().currentCycle;
      const cursor = runtime.historyChart.__temporalCursor;
      if (cursor && Number.isFinite(value)) {
        let pixel = null;
        try {
          pixel = runtime.historyChart.convertToPixel({ xAxisIndex: 0 }, value);
        } catch (ignored) {}
        if (Number.isFinite(pixel)) {
          cursor.hidden = false;
          cursor.style.left = pixel.toFixed(2) + "px";
        }
      }
    }
  }

  function makeChartEntries(specs) {
    runtime.charts.forEach((entry) => entry.chart.dispose());
    runtime.charts = [];
    byId("chartGrid").replaceChildren();
    const metricStatus = runtime.current.meta.metricStatus || {};
    runtime.currentCharts.displacement = metricStatus.displacement === "SUPPORTED"
      ? addCurrentHistogram("当前帧累计位移分布", "displacement")
      : null;
    runtime.currentCharts.speed = metricStatus.speed === "SUPPORTED"
      ? addCurrentHistogram("当前帧速度分布", "speed")
      : null;
    specs.forEach((spec) => {
      const sourceLabel = spec.case_id == null
        ? "Experiment"
        : (spec.decision && spec.decision.derived ? "DERIVED" : "REAL_PFC");
      const panel = createChartPanel(spec.title || spec.id || "数据图", sourceLabel);
      panel.section.title = spec.decision && spec.decision.reason
        ? spec.decision.reason
        : (spec.basis || "");
      byId("chartGrid").appendChild(panel.section);
      const option = buildChartOption(spec);
      if (!option) {
        const empty = document.createElement("div");
        empty.className = "empty-chart";
        empty.textContent = "该图表类型有数据声明但当前 Viewer 不支持渲染。";
        panel.section.appendChild(empty);
        return;
      }
      const chart = echarts.init(panel.div, null, { renderer: "svg" });
      chart.setOption(option, { notMerge: true, lazyUpdate: false });
      attachTemporalInteraction(chart, spec, panel.section);
      runtime.charts.push({ chart, spec, panel });
    });
    body.dataset.chartCount = String(runtime.charts.filter((entry) => !entry.linkedHistogram).length);
    body.dataset.linkedChartCount = String(runtime.charts.filter((entry) => entry.linkedHistogram).length);
    body.dataset.chartRenderer = "svg";
  }

  function histogramBins(values, lo, hi, count) {
    const bins = new Array(count).fill(0);
    if (!(hi > lo)) return { centers: bins.map((_, index) => lo + index), bins, edges: [lo, hi] };
    const width = (hi - lo) / count;
    for (let index = 0; index < values.length; index += 1) {
      const value = values[index];
      if (!Number.isFinite(value)) continue;
      const bin = Math.max(0, Math.min(count - 1, Math.floor((value - lo) / width)));
      bins[bin] += 1;
    }
    const edges = Array.from({ length: count + 1 }, (_, index) => lo + index * width);
    const centers = edges.slice(0, -1).map((value, index) => (value + edges[index + 1]) / 2);
    return { centers, bins, edges };
  }

  function addCurrentHistogram(title, metric) {
    const panel = createChartPanel(title, "linked");
    byId("chartGrid").appendChild(panel.section);
    const chart = echarts.init(panel.div, null, { renderer: "svg" });
    const unit = metric === "speed" ? "m/s" : "m";
    chart.setOption({
      ...baseOption({ title }),
      grid: { left: 48, right: 16, top: 52, bottom: 50, containLabel: false },
      tooltip: { ...baseOption({}).tooltip, trigger: "axis" },
      brush: { xAxisIndex: 0, throttleType: "debounce", throttleDelay: 80 },
      toolbox: { show: false },
      xAxis: categoryStyle(metric === "speed" ? "速度分箱" : "累计位移分箱", unit, []),
      yAxis: axisStyle("颗粒数", "count"),
      series: [{
        type: "bar",
        data: [],
        barCategoryGap: "2%",
        itemStyle: { color: metric === "speed" ? COLORS.slate : COLORS.primary, opacity: 0.86 },
        markArea: { silent: true, itemStyle: { color: "rgba(243,155,127,0.16)" }, data: [] }
      }]
    }, { notMerge: true });
    chart.__metric = metric;
    chart.__histogram = null;
    chart.on("brushSelected", (event) => {
      const batch = event.batch && event.batch[0];
      const area = batch && batch.areas && batch.areas[0];
      if (!area || !area.coordRange || !chart.__histogram) return;
      const range = area.coordRange;
      const data = chart.__histogram;
      const last = data.edges.length - 1;
      const start = Math.max(0, Math.min(last - 1, Math.floor(Number(range[0]))));
      const end = Math.max(start + 1, Math.min(last, Math.ceil(Number(range[1]))));
      actions.setRange([data.edges[start], data.edges[end]], metric, { source: "histogram-brush" });
    });
    chart.getZr().on("click", (event) => {
      const point = chart.convertFromPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY]);
      if (!point || !chart.__histogram) return;
      const index = Math.max(0, Math.min(chart.__histogram.edges.length - 2, Math.round(Number(point[0]))));
      actions.setRange([
        chart.__histogram.edges[index],
        chart.__histogram.edges[index + 1]
      ], metric, { source: "histogram-click" });
    });
    chart.getZr().setCursorStyle("crosshair");
    chart.dispatchAction({
      type: "takeGlobalCursor",
      key: "brush",
      brushOption: { brushType: "lineX", brushMode: "single" }
    });
    runtime.charts.push({ chart, spec: null, panel, linkedHistogram: true, metric });
    return chart;
  }

  function updateCurrentHistograms(frame) {
    if (!frame) return;
    const summary = runtime.current.summary;
    const specs = {
      displacement: {
        values: decodeF32(frame.displacement),
        hi: Math.max(summary.maxDisplacement, 1e-12)
      },
      speed: {
        values: decodeF32(frame.speed),
        hi: Math.max(summary.maxSpeed, 1e-12)
      }
    };
    Object.entries(runtime.currentCharts).forEach(([metric, chart]) => {
      if (!chart) return;
      const source = specs[metric];
      const finite = source.values.filter(Number.isFinite);
      const entry = runtime.charts.find((item) => item.chart === chart);
      if (!finite.length) {
        chart.__histogram = { centers: [], bins: [], edges: [] };
        chart.setOption({
          xAxis: { data: [] },
          series: [{ data: [] }]
        }, { lazyUpdate: true, silent: true });
        if (entry && entry.panel) entry.panel.status.textContent = "NOT_CAPTURED";
        return;
      }
      const hi = Math.max(finite.length ? Math.max(...finite) : 0, source.hi * 0.001, 1e-12);
      const histogram = histogramBins(source.values, 0, hi, 32);
      chart.__histogram = histogram;
      chart.setOption({
        xAxis: { data: histogram.centers },
        series: [{ data: histogram.bins }]
      }, { lazyUpdate: true, silent: true });
      if (entry && entry.panel) entry.panel.status.textContent = "linked";
    });
  }

  function mappedHistoryRows(rows, meta) {
    return (rows || []).map((row) => {
      const sourceValue = finiteNumber(row.sourceFrameIndex);
      const viewerValue = finiteNumber(row.viewerFrameIndex);
      if (sourceValue === null || viewerValue === null) return null;
      const sourceFrameIndex = Math.round(sourceValue);
      const viewerFrameIndex = Math.round(viewerValue);
      const frame = meta.frames[viewerFrameIndex];
      if (
        !frame ||
        Math.round(finiteNumber(frame.sourceIndex)) !== sourceFrameIndex
      ) return null;
      return { row, frame };
    }).filter(Boolean);
  }

  function updateHistoryChart() {
    const ids = store.get().selectedBallIds;
    const panel = byId("historyPanel");
    const status = byId("historyStatus");
    if (!ids.length) {
      panel.hidden = true;
      body.dataset.historyVisible = "0";
      if (runtime.historyChart) {
        runtime.historyChart.clear();
        runtime.historyChart.__temporal = false;
        if (runtime.historyChart.__temporalCursor) {
          runtime.historyChart.__temporalCursor.hidden = true;
        }
      }
      body.dataset.historyPointCount = "0";
      body.dataset.historySourceFrameIndices = "";
      body.dataset.historyViewerFrameIndices = "";
      body.dataset.historyCycleValues = "";
      return;
    }
    panel.hidden = false;
    body.dataset.historyVisible = "1";
    if (!runtime.historyChart) {
      runtime.historyChart = echarts.init(byId("historyChart"), null, { renderer: "svg" });
      runtime.historyChart.__temporal = true;
      const cursor = document.createElement("div");
      cursor.className = "time-cursor";
      byId("historyPanel").appendChild(cursor);
      runtime.historyChart.__temporalCursor = cursor;
      runtime.historyChart.on("click", (event) => {
        const cycle = Number(event.value && event.value[0]);
        const frames = runtime.current.meta.frames;
        const index = nearestIndex(frames.map((frame) => frame.cycle), cycle);
        if (index >= 0) actions.setFrame(index, { source: "history-chart" });
      });
    }
    const secondaryMetric = store.get().colorMetric === "acceleration"
      ? "acceleration"
      : "speed";
    const secondaryLabel = secondaryMetric === "acceleration" ? "加速度" : "速度";
    const secondaryUnit = secondaryMetric === "acceleration" ? "m/s^2" : "m/s";
    status.textContent = "位移 / " + secondaryLabel + " · 力历史 NOT_CAPTURED";
    const series = [];
    const firstMappedRows = [];
    ids.slice(0, 8).forEach((ballId, index) => {
      const rows = runtime.selectedHistories.get(ballId);
      if (!rows || !rows.length) return;
      const mapped = mappedHistoryRows(rows, runtime.current.meta);
      if (!mapped.length) return;
      if (!firstMappedRows.length) firstMappedRows.push(...mapped);
      const color = chartColors()[index % chartColors().length];
      series.push({
        name: "Ball " + ballId + " 位移",
        type: "line",
        data: mapped.map((item) => [item.frame.cycle, item.row.displacement]),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color, width: 1.25 },
        itemStyle: { color }
      });
      if (index === 0) {
        series.push({
          name: "Ball " + ballId + " " + secondaryLabel,
          type: "line",
          yAxisIndex: 1,
          data: mapped.map((item) => [
            item.frame.cycle,
            item.row[secondaryMetric]
          ]),
          showSymbol: false,
          connectNulls: false,
          lineStyle: { color, width: 1, type: "dashed", opacity: 0.8 },
          itemStyle: { color }
        });
      }
    });
    runtime.historyChart.setOption({
      animation: false,
      title: {
        show: false,
        text: "Ball 历史",
        left: 12,
        top: 8,
        textStyle: { color: COLORS.ink, fontSize: 12, fontWeight: 600 }
      },
      textStyle: { fontFamily: "Arial, Helvetica, PingFang SC, Microsoft YaHei, sans-serif" },
      grid: { left: 50, right: 48, top: 42, bottom: 42 },
      legend: {
        top: 3, right: 8, itemWidth: 13, itemHeight: 2,
        textStyle: { color: COLORS.muted, fontSize: 8.5 }, type: "scroll"
      },
      tooltip: {
        trigger: "axis", confine: true,
        backgroundColor: "rgba(255,255,255,0.96)", borderColor: "#d9d9d5",
        textStyle: { color: COLORS.ink, fontSize: 10 }
      },
      xAxis: axisStyle("Cycle", "cycle"),
      yAxis: [axisStyle("累计位移", "m"), axisStyle(secondaryLabel, secondaryUnit)],
      series
    }, { notMerge: true });
    body.dataset.historyPointCount = String(firstMappedRows.length);
    body.dataset.historySourceFrameIndices = firstMappedRows
      .map((item) => Math.round(item.row.sourceFrameIndex))
      .join(",");
    body.dataset.historyViewerFrameIndices = firstMappedRows
      .map((item) => Math.round(item.row.viewerFrameIndex))
      .join(",");
    body.dataset.historyCycleValues = firstMappedRows
      .map((item) => item.frame.cycle)
      .join(",");
    runtime.historyChart.__temporal = true;
    updateTemporalMarkers();
  }

  async function loadSelectedHistories() {
    const ids = store.get().selectedBallIds;
    const caseId = store.get().currentCase;
    if (!ids.length || caseId == null) {
      runtime.selectedHistories.clear();
      updateHistoryChart();
      updateTrajectories();
      return;
    }
    const token = runtime.frameToken;
    const loaded = [];
    for (const ballId of ids.slice(0, 8)) {
      if (runtime.selectedHistories.has(ballId)) {
        loaded.push([ballId, runtime.selectedHistories.get(ballId)]);
        continue;
      }
      const bucket = await ensureHistoryBucket(caseId, ballId);
      const entry = bucket.entries.find((item) => item.id === ballId);
      if (!entry) {
        loaded.push([ballId, []]);
        continue;
      }
      const rows = mappedHistoryRows(
        decodeHistoryRows(entry.data),
        DATA.caseMeta[caseId]
      ).map((item) => item.row);
      runtime.selectedHistories.set(ballId, rows);
      loaded.push([ballId, rows]);
    }
    if (token !== runtime.frameToken || store.get().currentCase !== caseId) return;
    runtime.selectedHistories = new Map(loaded);
    updateHistoryChart();
    updateTrajectories();
  }

  async function switchCase(caseId, source) {
    const token = ++runtime.caseToken;
    runtime.frameToken += 1;
    pausePlayback();
    loading.hidden = false;
    loading.textContent = "正在读取 Case " + caseId + " 元数据…";
    try {
      const meta = await loadCaseMeta(caseId);
      const specs = await loadCaseCharts(caseId);
      if (token !== runtime.caseToken) return;
      const summary = DATA.catalog.cases.find((item) => item.id === caseId);
      const caseStatic = staticCases[String(caseId)];
      if (!caseStatic) throw new Error("Case 静态实体未注册: " + caseId);
      staticBalls = caseStatic.balls;
      staticById = new Map();
      staticBalls.forEach((ball, index) => {
        staticById.set(ball[0], { index, radius: ball[4] });
      });
      const focus = ballFocusBounds(staticBalls);
      focusCenter = focus.center;
      focusSpan = focus.span;
      runtime.current = { meta, summary, specs };
      currentFrameData = null;
      runtime.selectedHistories.clear();
      runtime.currentHistories = Object.create(null);
      syncCaseVisualCapabilities(meta);
      makeChartEntries(specs);
      buildCrackLayers(meta.cracks || []);
      updateHistoryChart();
      updateTrajectories();
      byId("timeline").min = "0";
      byId("timeline").max = String(Math.max(0, meta.frames.length - 1));
      byId("timeline").value = "0";
      byId("caseSelect").value = String(caseId);
      byId("caseSubtitle").textContent =
        meta.viewerFrameCount + " 个实测帧 · Cycle " + meta.frames[0].cycle + "–" +
        meta.frames[meta.frames.length - 1].cycle + " · 无帧间插值";
      byId("runBadge").textContent = summary.runId + " · " +
        (meta.sampled ? "显式抽样" : "完整真实帧集") + " · " + summary.frameStatus;
      store.set({
        currentCase: caseId,
        currentFrame: 0,
        currentCycle: meta.frames[0].cycle,
        currentTime: meta.frames[0].time,
        selectedBallIds: [],
        selectedRange: null,
        selectedMetric: store.get().colorMetric
      }, "case");
      body.dataset.selectedBallIds = "";
      body.dataset.selectedRange = "";
      body.dataset.selectedMetric = store.get().selectedMetric;
      updateHistoryChart();
      updateTrajectories();
      await setFrame(0, { source, force: true, fromCaseSwitch: true });
      applyViewPreset(currentViewPreset || "fit");
      body.dataset.caseId = String(caseId);
      body.dataset.caseReady = "1";
      document.title = DATA.catalog.meta.title + " · " + summary.runId;
    } catch (error) {
      showError("CASE_LOAD_ERROR", error);
    } finally {
      if (token === runtime.caseToken) {
        loading.hidden = true;
        loading.textContent = "正在加载当前实测帧…";
      }
    }
  }

  async function setFrame(index, options) {
    if (!runtime.current) return;
    const settings = options || {};
    const caseId = store.get().currentCase;
    const token = ++runtime.frameToken;
    const meta = runtime.current.meta;
    const target = Math.max(0, Math.min(meta.frames.length - 1, Number(index)));
    if (!settings.force && target === store.get().currentFrame) return;
    const frameMeta = meta.frames[target];
    loading.hidden = false;
    loading.textContent = "正在加载实测帧 " + (target + 1) + " / " + meta.frames.length + "…";
    try {
      const chunk = await ensureChunk(caseId, frameMeta.chunk);
      if (token !== runtime.frameToken || store.get().currentCase !== caseId) return;
      const frame = chunk.frames[frameMeta.chunkOffset];
      if (!frame) throw new Error("帧块中缺少目标帧");
      currentFrameData = frame;
      updateParticles(frame, highlightIdsForState());
      const now = performance.now();
      if (!runtime.playing || now - runtime.lastHistogramUpdate >= 500) {
        runtime.lastHistogramUpdate = now;
        updateCurrentHistograms(frame);
      }
      updateCracks(frame.cycle);
      store.set({
        currentFrame: target,
        currentCycle: frame.cycle,
        currentTime: frame.time
      }, settings.source || "frame");
      const nextMeta = meta.frames[target + 1];
      if (nextMeta && nextMeta.chunk !== frameMeta.chunk) ensureChunk(caseId, nextMeta.chunk).catch(() => {});
      body.dataset.ready = "1";
      body.dataset.frameIndex = String(target);
      body.dataset.cycle = String(frame.cycle);
      body.dataset.chunkIndex = String(frameMeta.chunk);
      body.dataset.loadedChunkCount = String(caseRuntime(caseId).chunkCache.size);
    } catch (error) {
      showError("FRAME_LOAD_ERROR", error);
    } finally {
      if (token === runtime.frameToken) loading.hidden = true;
    }
  }

  const actions = {
    setCase(caseId, options) {
      const numeric = Number(caseId);
      if (Number.isFinite(numeric)) switchCase(numeric, (options && options.source) || "case-select");
    },
    setFrame(index, options) {
      return setFrame(index, options);
    },
    async selectBalls(ids, options) {
      const settings = options || {};
      const state = store.get();
      const current = settings.additive ? new Set(state.selectedBallIds) : new Set();
      ids.forEach((id) => {
        const numeric = Number(id);
        if (!Number.isFinite(numeric)) return;
        if (settings.additive && current.has(numeric)) current.delete(numeric);
        else current.add(numeric);
      });
      store.set({
        selectedBallIds: Array.from(current),
        selectedRange: null,
        selectedMetric: settings.metric || state.selectedMetric
      }, settings.source || "ball-selection");
      if (settings.focus && ids.length) focusBall(Number(ids[0]));
      if (ids.length) {
        byId("ballInput").value = String(ids[0]);
        if (!currentFrameData || !decodeU32(currentFrameData.ids).includes(Number(ids[0]))) {
          const meta = runtime.current.meta;
          for (const frame of meta.frames) {
            const chunk = await ensureChunk(store.get().currentCase, frame.chunk);
            const data = chunk.frames[frame.chunkOffset];
            if (decodeU32(data.ids).includes(Number(ids[0]))) {
              await setFrame(frame.index, { source: "select-ball" });
              break;
            }
          }
        }
      }
      await loadSelectedHistories();
    },
    async setRange(range, metric, options) {
      if (!Array.isArray(range) || range.length !== 2 || !Number.isFinite(Number(range[0])) || !Number.isFinite(Number(range[1]))) return;
      const lo = Math.min(Number(range[0]), Number(range[1]));
      const hi = Math.max(Number(range[0]), Number(range[1]));
      store.set({
        selectedRange: [lo, hi],
        selectedMetric: metric || store.get().selectedMetric,
        colorMetric: metric || store.get().colorMetric
      }, (options && options.source) || "range");
      const histogram = runtime.currentCharts[metric] && runtime.currentCharts[metric].__histogram;
      if (histogram) {
        const startIndex = Math.max(0, histogram.edges.findIndex((edge, index) =>
          index < histogram.edges.length - 1 && hi >= edge && lo <= histogram.edges[index + 1]
        ));
        const endIndex = Math.max(startIndex, histogram.edges.findIndex((edge) => edge >= hi));
        const xStart = histogram.centers[startIndex];
        const xEnd = histogram.centers[Math.max(startIndex, endIndex - 1)];
        Object.values(runtime.currentCharts).forEach((chart) => {
          if (chart) chart.setOption({ series: [{ markArea: { data: [] } }] }, { lazyUpdate: true, silent: true });
        });
        runtime.currentCharts[metric].setOption({
          series: [{ markArea: { silent: true, itemStyle: { color: "rgba(243,155,127,0.16)" }, data: [[{ xAxis: xStart }, { xAxis: xEnd }]] } }]
        }, { lazyUpdate: true, silent: true });
      }
    },
    clearSelection() {
      store.set({
        selectedBallIds: [],
        selectedRange: null
      }, "clear-selection");
      runtime.selectedHistories.clear();
      updateHistoryChart();
      updateTrajectories();
      Object.values(runtime.currentCharts).forEach((chart) => {
        if (chart) chart.setOption({ series: [{ markArea: { data: [] } }] }, { lazyUpdate: true, silent: true });
      });
    },
    setColorMetric(metric) {
      if (!["displacement", "speed", "acceleration"].includes(metric)) return false;
      if (runtime.current && runtime.current.meta.metricStatus[metric] !== "SUPPORTED") {
        body.dataset.metricRejected = metric + ":NOT_CAPTURED";
        return false;
      }
      store.set({ colorMetric: metric }, "color-metric");
      return true;
    }
  };

  function renderState(state, previous, reason) {
    if (!runtime.ready) return;
    const meta = runtime.current && runtime.current.meta;
    if (!meta) return;
    const frameMeta = meta.frames[state.currentFrame];
    if (!frameMeta) return;
    byId("timeline").value = String(state.currentFrame);
    byId("frameLabel").textContent = "实测帧 " + (state.currentFrame + 1) + " / " + meta.frames.length;
    byId("cycleLabel").textContent = "Cycle " + state.currentCycle + " · t=" + formatNumber(state.currentTime, 6) + " s";
    byId("cycleInput").value = String(state.currentCycle);
    byId("metricStress").textContent = formatMetric(frameMeta.stressMPa, "MPa", 3);
    byId("metricStrain").textContent = formatMetric(frameMeta.strain, "", 5);
    byId("metricLoad").textContent = frameMeta.loadN == null ? "未采集" : formatMetric(frameMeta.loadN / 1e6, "MN", 3);
    byId("metricShortening").textContent = formatMetric(frameMeta.shorteningM, "m", 5);
    byId("metricBalls").textContent = String(frameMeta.ballCount);
    byId("metricCracks").textContent = meta.crackStatus === "NOT_CAPTURED" ? "未采集" :
      meta.crackStatus === "INVALID_GEOMETRY" ? "几何无效" : String(
        meta.cracks.filter((row) => row[6] <= state.currentCycle).length
      );
    byId("rampLabel").textContent = state.colorMetric === "speed"
      ? "速度"
      : (state.colorMetric === "acceleration" ? "加速度" : "累计位移");
    if (runtime.colorRange) {
      byId("rampRange").textContent = " P05–P95 " +
        formatNumber(runtime.colorRange.low, 3) + "–" +
        formatNumber(runtime.colorRange.high, 3) +
        (state.colorMetric === "speed"
          ? " m/s"
          : (state.colorMetric === "acceleration" ? " m/s²" : " m"));
    }
    if (previous.currentCase !== state.currentCase || previous.colorMetric !== state.colorMetric ||
        previous.selectedBallIds !== state.selectedBallIds || previous.selectedRange !== state.selectedRange) {
      updateSelectionVisuals();
    }
    if (previous.currentFrame !== state.currentFrame || reason === "frame") {
      updateTemporalMarkers();
    }
    body.dataset.selectedBallIds = state.selectedBallIds.join(",");
    body.dataset.selectedRange = state.selectedRange ? state.selectedRange.join(",") : "";
    body.dataset.selectedMetric = state.selectedMetric;
    body.dataset.historyVisible = byId("historyPanel").hidden ? "0" : "1";
  }

  store.subscribe((state, previous, reason) => {
    pendingState = state;
    pendingReason = reason;
    if (stateRenderQueued) return;
    stateRenderQueued = true;
    requestAnimationFrame(() => {
      stateRenderQueued = false;
      const next = pendingState;
      const before = lastRenderedState || previous;
      lastRenderedState = next;
      renderState(next, before, pendingReason);
    });
  });

  function pausePlayback() {
    runtime.playing = false;
    runtime.playAccumulator = 0;
    byId("playButton").textContent = "▶ 播放";
    if (currentFrameData) updateCurrentHistograms(currentFrameData);
    updateTemporalMarkers();
  }

  function togglePlayback() {
    if (!runtime.current) return;
    const state = store.get();
    if (!runtime.playing && state.currentFrame >= runtime.current.meta.frames.length - 1) {
      actions.setFrame(0, { source: "play-reset" });
    }
    runtime.playing = !runtime.playing;
    runtime.playAccumulator = 0;
    byId("playButton").textContent = runtime.playing ? "⏸ 暂停" : "▶ 播放";
  }

  function resetCamera() {
    applyViewPreset(currentViewPreset || "fit");
  }

  function setCameraMode(mode) {
    if (!camera) return;
    const chosen = mode === "orthographic" ? orthographicCamera :
      mode === "perspective" ? perspectiveCamera : (is2D ? orthographicCamera : perspectiveCamera);
    if (chosen !== camera) {
      controls.dispose();
      camera = chosen;
      controls = new THREE.OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.08;
    }
    resetCamera();
    body.dataset.cameraMode = chosen === orthographicCamera ? "orthographic" : "perspective";
  }

  function applyViewPreset(preset) {
    if (!camera) return;
    currentViewPreset = preset || "fit";
    const direction = {
      fit: is2D ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1.18, -1.48, 0.72),
      isometric: new THREE.Vector3(1, -1, 0.72),
      front: new THREE.Vector3(0, -1, 0),
      top: new THREE.Vector3(0, 0, 1),
      side: new THREE.Vector3(1, 0, 0)
    }[currentViewPreset] || (is2D ? new THREE.Vector3(0, 0, 1) : new THREE.Vector3(1.18, -1.48, 0.72));
    direction.normalize();
    const target = focusCenter || center;
    const framedSpan = Math.max(focusSpan || span, 1.0e-9);
    const framingRadius = framedSpan * Math.sqrt(3) * 0.56;
    controls.target.copy(target);
    if (camera === perspectiveCamera) {
      const verticalFov = THREE.MathUtils.degToRad(camera.fov);
      const horizontalFov = 2 * Math.atan(
        Math.tan(verticalFov * 0.5) * Math.max(camera.aspect || 1, 0.1)
      );
      const limitingHalfFov = Math.min(verticalFov, horizontalFov) * 0.5;
      const distance = framingRadius / Math.max(Math.sin(limitingHalfFov), 1.0e-6);
      camera.position.copy(target).add(direction.multiplyScalar(distance));
      camera.near = framedSpan * 0.001;
      camera.far = framedSpan * 100;
    } else {
      orthoExtent = framingRadius;
      camera.position.copy(target).add(direction.multiplyScalar(framedSpan * 2.2));
      camera.near = framedSpan * 0.001;
      camera.far = framedSpan * 100;
      camera.zoom = 1;
    }
    camera.up.set(0, 0, 1);
    if (currentViewPreset === "top" || (currentViewPreset === "fit" && is2D)) camera.up.set(0, 1, 0);
    camera.lookAt(target);
    camera.updateProjectionMatrix();
    controls.update();
    body.dataset.viewPreset = currentViewPreset;
    body.dataset.focusSpan = String(framedSpan);
  }

  function updateClipping() {
    if (!camera) return;
    const axis = byId("clipAxis").value;
    const index = { x: 0, y: 1, z: 2 }[axis] || 2;
    const low = [dmin.x, dmin.y, dmin.z][index];
    const high = [dmax.x, dmax.y, dmax.z][index];
    const cut = low + (high - low) * (Number(byId("clipPosition").value) / 100);
    const normal = new THREE.Vector3(0, 0, 0);
    normal.setComponent(index, -1);
    clippingPlane.normal.copy(normal);
    clippingPlane.constant = cut;
    const planes = byId("showClip").checked ? [clippingPlane] : [];
    particleMaterial.clippingPlanes = planes;
    particleMaterial.needsUpdate = true;
    [crackTension, crackShear, contactLines, bondLines].forEach((line) => {
      if (!line) return;
      line.material.clippingPlanes = planes;
      line.material.needsUpdate = true;
    });
    body.dataset.clipping = byId("showClip").checked ? "ENABLED" : "DISABLED";
  }

  function niceDistance(value) {
    if (!Number.isFinite(value) || value <= 0) return 1;
    const power = Math.pow(10, Math.floor(Math.log10(value)));
    const unit = value / power;
    return (unit >= 5 ? 5 : unit >= 2 ? 2 : 1) * power;
  }

  function updateScaleBar() {
    if (!camera || !renderer) return;
    const height = Math.max(1, byId("stage").clientHeight);
    let worldPerPixel;
    if (camera === orthographicCamera) {
      worldPerPixel = (camera.top - camera.bottom) / (height * camera.zoom);
    } else {
      const distance = camera.position.distanceTo(controls.target);
      worldPerPixel = 2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.fov * 0.5)) / height;
    }
    const length = niceDistance(worldPerPixel * 110);
    const pixels = Math.max(28, Math.min(180, length / Math.max(worldPerPixel, 1e-12)));
    byId("scaleLine").style.width = pixels.toFixed(1) + "px";
    byId("scaleText").textContent = formatNumber(length, 3) + " m";
  }

  function downloadDataUrl(name, dataUrl) {
    const link = document.createElement("a");
    link.href = dataUrl;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function renderSceneAt(width, background) {
    const stageWidth = Math.max(1, byId("stage").clientWidth);
    const stageHeight = Math.max(1, byId("stage").clientHeight);
    const targetWidth = Math.max(800, Math.min(12000, Number(width) || 3200));
    const targetHeight = Math.max(1, Math.round(targetWidth * stageHeight / stageWidth));
    const priorBackground = scene.background;
    const priorRatio = renderer.getPixelRatio();
    scene.background = background === "transparent" ? null : new THREE.Color(0xffffff);
    renderer.setPixelRatio(1);
    renderer.setSize(targetWidth, targetHeight, false);
    camera.aspect = targetWidth / targetHeight;
    if (camera === orthographicCamera) {
      const aspect = camera.aspect;
      const halfHeight = orthoExtent;
      const halfWidth = halfHeight * aspect;
      camera.left = -halfWidth;
      camera.right = halfWidth;
      camera.top = halfHeight;
      camera.bottom = -halfHeight;
    }
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
    const dataUrl = renderer.domElement.toDataURL("image/png");
    scene.background = priorBackground;
    renderer.setPixelRatio(priorRatio);
    resize();
    renderer.render(scene, camera);
    return dataUrl;
  }

  function exportScene() {
    if (!runtime.current) return;
    const frame = store.get().currentFrame;
    const dataUrl = renderSceneAt(byId("exportWidth").value, byId("exportBackground").value);
    downloadDataUrl("pfc_case_" + store.get().currentCase + "_frame_" + frame + ".png", dataUrl);
    body.dataset.sceneExportStatus = "GENERATED";
  }

  async function exportFrame() {
    const raw = window.prompt("输入要导出的实测帧号（从 1 开始）", String(store.get().currentFrame + 1));
    if (raw == null) return;
    const target = Number(raw) - 1;
    if (!Number.isFinite(target)) return;
    await setFrame(target, { source: "export-frame", force: true });
    exportScene();
    body.dataset.frameExportStatus = "GENERATED";
  }

  function exportChartSVGs() {
    const caseId = store.get().currentCase;
    const jobs = [];
    runtime.charts.forEach((entry, index) => {
      const chartNumber = index + 1;
      const fileName = "pfc_case_" + caseId + "_chart_" +
        String(chartNumber).padStart(2, "0") + ".svg";
      jobs.push(new Promise((resolve) => setTimeout(() => {
        const dataUrl = chartSVGDataUrl(entry, true);
        downloadDataUrl(fileName, dataUrl);
        resolve(fileName);
      }, index * 120)));
    });
    if (runtime.historyChart && !byId("historyPanel").hidden) {
      const fileName = "pfc_case_" + caseId + "_ball_history.svg";
      jobs.push(new Promise((resolve) => setTimeout(() => {
        const dataUrl = echartSVGDataUrl(runtime.historyChart, "Ball 历史");
        downloadDataUrl(fileName, dataUrl);
        resolve(fileName);
      }, jobs.length * 120)));
    }
    body.dataset.chartExportStatus = "SCHEDULED";
    return Promise.all(jobs).then((names) => {
      body.dataset.chartExportNames = names.join("|");
      body.dataset.chartExportStatus = "GENERATED";
      return names;
    });
  }

  function chartExportEntries() {
    const caseId = store.get().currentCase;
    return runtime.charts.map((entry, index) => ({
      fileName: "pfc_case_" + caseId + "_chart_" +
        String(index + 1).padStart(2, "0") + ".svg",
      title: (entry.spec && entry.spec.title) ||
        (entry.panel && entry.panel.title && entry.panel.title.textContent) || ""
    }));
  }

  function echartSVGDataUrl(chart, title) {
    const dataUrl = chart.getDataURL({
      type: "svg",
      backgroundColor: "#ffffff",
      excludeComponents: ["toolbox", "brush"]
    });
    if (!title) return dataUrl;
    const comma = dataUrl.indexOf(",");
    if (comma < 0) return dataUrl;
    const header = dataUrl.slice(0, comma + 1);
    const svg = decodeURIComponent(dataUrl.slice(comma + 1));
    const titleMarkup =
      '<text x="12" y="24" fill="#171717" style="font:600 12px Arial, Helvetica, PingFang SC, Microsoft YaHei, sans-serif;">' +
      escapeHtml(title) +
      "</text>";
    const titledSvg = svg.replace(/(<svg\b[^>]*>)/, "$1" + titleMarkup);
    return header + encodeURIComponent(titledSvg);
  }

  function chartSVGDataUrl(entry, includeTitle) {
    const title = includeTitle && entry
      ? (
        (entry.spec && entry.spec.title) ||
        (entry.panel && entry.panel.title && entry.panel.title.textContent) ||
        ""
      )
      : "";
    return echartSVGDataUrl(entry.chart, title);
  }

  function compositeLayout(count, aspectRatio = 1.5) {
    if (count <= 0) return { template: "empty", panels: [] };
    let rows;
    let template;
    if (count === 1) {
      rows = [[1]];
      template = "single";
    } else if (count === 2) {
      rows = [[1, 1]];
      template = "two_columns";
    } else if (count === 3) {
      rows = [[1], [1, 1]];
      template = "featured_plus_two";
    } else if (count === 4) {
      rows = [[1, 1], [1, 1]];
      template = "two_by_two";
    } else if (count === 5) {
      rows = [[1], [1, 1], [1, 1]];
      template = "featured_plus_four";
    } else if (count === 6) {
      rows = [[1, 1], [1, 1], [1, 1]];
      template = "two_by_three";
    } else if (count === 7) {
      rows = [[1], [1, 1, 1], [1, 1, 1]];
      template = "featured_plus_six";
    } else if (count === 8) {
      rows = [[1, 1], [1, 1], [1, 1], [1, 1]];
      template = "two_by_four";
    } else {
      const featured = count % 2 === 1;
      const remaining = featured ? count - 1 : count;
      const columns = Math.max(2, Math.min(5, Math.round(Math.sqrt(remaining * aspectRatio))));
      rows = [];
      if (featured) rows.push([1]);
      let left = remaining;
      while (left > 0) {
        const take = Math.min(columns, left);
        rows.push(new Array(take).fill(1));
        left -= take;
      }
      template = featured ? "featured_balanced_grid" : "balanced_grid";
    }
    const heightWeights = rows.map((row, index) => (
      template.startsWith("featured") && index === 0 ? 1.2 : 1
    ));
    const totalHeight = heightWeights.reduce((sum, value) => sum + value, 0);
    const panels = [];
    let y = 0;
    let index = 0;
    rows.forEach((row, rowIndex) => {
      const rowHeight = heightWeights[rowIndex] / totalHeight;
      let x = 0;
      row.forEach((weight) => {
        const width = weight / row.reduce((sum, value) => sum + value, 0);
        panels.push({
          index,
          x,
          y,
          width,
          height: rowHeight,
          role: template.startsWith("featured") && rowIndex === 0 ? "primary" : "supporting"
        });
        x += width;
        index += 1;
      });
      y += rowHeight;
    });
    return { template, panels };
  }

  function truncateCanvasText(context, text, maxWidth) {
    const value = String(text || "");
    if (context.measureText(value).width <= maxWidth) return value;
    let output = value;
    while (output.length > 1 && context.measureText(output + "…").width > maxWidth) {
      output = output.slice(0, -1);
    }
    return output + "…";
  }

  async function compositePanelsDataUrl() {
    const entries = runtime.charts.filter((entry) => !entry.linkedHistogram);
    if (!entries.length) return null;
    const width = 3600;
    const height = 2400;
    const margin = 56;
    const gap = 24;
    const layout = compositeLayout(entries.length, width / height);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d");
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    const images = await Promise.all(entries.map((entry) => new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve(image);
      image.onerror = reject;
      image.src = entry.chart.getDataURL({ type: "svg", backgroundColor: "#ffffff", excludeComponents: ["toolbox", "brush"] });
    })));
    images.forEach((image, index) => {
      const panel = layout.panels[index];
      const x = margin + panel.x * (width - margin * 2) + gap * 0.5;
      const y = margin + panel.y * (height - margin * 2) + gap * 0.5;
      const cellWidth = panel.width * (width - margin * 2) - gap;
      const cellHeight = panel.height * (height - margin * 2) - gap;
      const entry = entries[index];
      const headerHeight = 64;
      context.fillStyle = "#ffffff";
      context.fillRect(x, y, cellWidth, cellHeight);
      context.strokeStyle = "#e5e9ee";
      context.lineWidth = 1;
      context.strokeRect(x, y, cellWidth, cellHeight);
      context.fillStyle = "#171717";
      context.font = "700 25px Arial, Helvetica, sans-serif";
      context.fillText("(" + String.fromCharCode(97 + index) + ")", x + 16, y + 38);
      context.font = "600 21px Arial, Helvetica, sans-serif";
      const titleWidth = Math.max(120, cellWidth - 360);
      context.fillText(
        truncateCanvasText(context, entry.panel.title.textContent, titleWidth),
        x + 66,
        y + 37
      );
      context.fillStyle = "#6f7074";
      context.font = "13px Arial, Helvetica, sans-serif";
      const status = entry.panel.status.textContent || "";
      context.fillText(status, x + cellWidth - context.measureText(status).width - 16, y + 35);
      context.strokeStyle = "#e5e9ee";
      context.beginPath();
      context.moveTo(x, y + headerHeight);
      context.lineTo(x + cellWidth, y + headerHeight);
      context.stroke();
      const graphicX = x + 8;
      const graphicY = y + headerHeight + 4;
      const graphicWidth = cellWidth - 16;
      const graphicHeight = cellHeight - headerHeight - 12;
      const sourceRatio = image.width / Math.max(1, image.height);
      const targetRatio = graphicWidth / Math.max(1, graphicHeight);
      let drawWidth = graphicWidth;
      let drawHeight = graphicHeight;
      if (sourceRatio > targetRatio) drawHeight = graphicWidth / sourceRatio;
      else drawWidth = graphicHeight * sourceRatio;
      context.drawImage(
        image,
        graphicX + (graphicWidth - drawWidth) * 0.5,
        graphicY + (graphicHeight - drawHeight) * 0.5,
        drawWidth,
        drawHeight
      );
    });
    return canvas.toDataURL("image/png");
  }

  async function exportCompositePanels() {
    const dataUrl = await compositePanelsDataUrl();
    if (!dataUrl) return;
    downloadDataUrl("pfc_case_" + store.get().currentCase + "_composite_panels.png", dataUrl);
    body.dataset.compositeExportStatus = "GENERATED";
  }

  function chartSVGDataUrls() {
    return runtime.charts
      .filter((entry) => !entry.linkedHistogram)
      .map((entry) => chartSVGDataUrl(entry, true));
  }

  function bindControls() {
    byId("caseSelect").addEventListener("change", (event) => actions.setCase(Number(event.target.value), { source: "case-select" }));
    byId("timeline").addEventListener("input", (event) => {
      pausePlayback();
      actions.setFrame(Number(event.target.value), { source: "timeline" });
    });
    byId("prevFrame").addEventListener("click", () => {
      pausePlayback();
      actions.setFrame(store.get().currentFrame - 1, { source: "prev" });
    });
    byId("nextFrame").addEventListener("click", () => {
      pausePlayback();
      actions.setFrame(store.get().currentFrame + 1, { source: "next" });
    });
    byId("playButton").addEventListener("click", togglePlayback);
    byId("playbackSpeed").addEventListener("change", () => {
      runtime.playAccumulator = 0;
    });
    byId("locateCycle").addEventListener("click", () => {
      const target = Number(byId("cycleInput").value);
      if (!Number.isFinite(target) || !runtime.current) return;
      const index = runtime.current.meta.frames.findIndex((frame) => frame.cycle === target);
      if (index < 0) {
        byId("cycleInput").setCustomValidity("该 Case 未精确采集此 Cycle；不会插值。");
        byId("cycleInput").reportValidity();
        return;
      }
      byId("cycleInput").setCustomValidity("");
      pausePlayback();
      actions.setFrame(index, { source: "cycle-locate", force: true });
    });
    byId("cycleInput").addEventListener("input", (event) => event.target.setCustomValidity(""));
    byId("locateBall").addEventListener("click", () => {
      const id = Number(byId("ballInput").value);
      if (Number.isFinite(id)) actions.selectBalls([id], { focus: true, source: "ball-input" });
    });
    byId("ballInput").addEventListener("input", (event) => event.target.setCustomValidity(""));
    byId("clearSelection").addEventListener("click", actions.clearSelection);
    byId("showParticles").addEventListener("change", (event) => { particles.visible = event.target.checked; });
    byId("showWalls").addEventListener("change", (event) => {
      if (wallLines) wallLines.visible = event.target.checked && !!currentFrameData && !!currentFrameData.wallIds;
    });
    byId("showCracks").addEventListener("change", () => updateCracks(store.get().currentCycle));
    byId("showContacts").addEventListener("change", () => {
      if (currentFrameData) updateParticles(currentFrameData, highlightIdsForState());
    });
    byId("showBonds").addEventListener("change", () => {
      if (currentFrameData) updateParticles(currentFrameData, highlightIdsForState());
    });
    byId("showAxes").addEventListener("change", (event) => {
      axesHelper.visible = event.target.checked;
      grid.visible = is2D && event.target.checked;
    });
    byId("showBounds").addEventListener("change", (event) => { domainBox.visible = event.target.checked; });
    byId("showTrajectory").addEventListener("change", updateTrajectories);
    byId("showClip").addEventListener("change", updateClipping);
    byId("clipAxis").addEventListener("change", updateClipping);
    byId("clipPosition").addEventListener("input", updateClipping);
    byId("colorMetric").addEventListener("change", (event) => actions.setColorMetric(event.target.value));
    byId("cameraMode").addEventListener("change", (event) => setCameraMode(event.target.value));
    byId("viewPreset").addEventListener("change", (event) => applyViewPreset(event.target.value));
    byId("resetCamera").addEventListener("click", resetCamera);
    byId("exportScene").addEventListener("click", exportScene);
    byId("exportFrame").addEventListener("click", exportFrame);
    byId("exportCharts").addEventListener("click", exportChartSVGs);
    byId("exportPanels").addEventListener("click", exportCompositePanels);
    byId("notesButton").addEventListener("click", () => {
      const notes = byId("notes");
      notes.hidden = !notes.hidden;
      byId("notesButton").setAttribute("aria-expanded", notes.hidden ? "false" : "true");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !byId("notes").hidden) byId("notes").hidden = true;
      if (event.target && /INPUT|SELECT|TEXTAREA/.test(event.target.tagName)) return;
      if (event.code === "Space") { event.preventDefault(); togglePlayback(); }
      else if (event.code === "ArrowLeft") { event.preventDefault(); pausePlayback(); actions.setFrame(store.get().currentFrame - 1, { source: "keyboard" }); }
      else if (event.code === "ArrowRight") { event.preventDefault(); pausePlayback(); actions.setFrame(store.get().currentFrame + 1, { source: "keyboard" }); }
      else if (event.code === "Home") { pausePlayback(); actions.setFrame(0, { source: "keyboard" }); }
      else if (event.code === "End") { pausePlayback(); actions.setFrame(runtime.current.meta.frames.length - 1, { source: "keyboard" }); }
    });
  }

  function populateNotes() {
    const meta = DATA.catalog.meta;
    byId("notesBody").innerHTML = [
      "<h3>真实性</h3>",
      "<ul>",
      "<li>数据边界：" + escapeHtml(meta.dataBoundary) + "；播放只切换真实采样帧，不在帧间插值。</li>",
      "<li>Ball 集合按每帧真实 ID 和变长偏移读取，不以数组下标代替 Ball ID。</li>",
      "<li>缺失值保持缺失并以灰色显示，不补零、不伪造。</li>",
      "<li>颗粒连续色标采用当前真实帧的 P05–P95 稳健区间；图例显示实际数值，超过 P95 的值饱和为高色。</li>",
      "<li>接触与 Bond 网络仅在同帧端点 ID 存在时显示；线色对应实际采集或合法派生的力值。</li>",
      "</ul>",
      "<h3>性能架构</h3>",
      "<ul>",
      "<li>HTML 仅包含页面结构；Three.js、ECharts 和帧数据分别本地加载。</li>",
      "<li>帧数据按块加载并做 LRU 淘汰；颗粒历史按 ID 桶按需加载。</li>",
      "<li>Three.js 实例、ECharts 实例和几何对象在播放及联动时不重复创建。</li>",
      "<li>组合图使用奇偶数量与主次面板自适应布局，并保留标题、来源和面板编号。</li>",
      "</ul>",
      "<h3>支持边界</h3>",
      "<ul>",
      "<li>单颗粒应力与接触力历史仅在实际采集对应字段时提供；当前基线若未采集则明确标记。</li>",
      "<li>裂纹颜色：拉伸裂纹使用主蓝色，剪切裂纹使用朱红色。</li>",
      "<li>空间热力图表示分箱颗粒数密度，不解释为物理应力场。</li>",
      "</ul>"
    ].join("");
  }

  function populateCaseSelect() {
    const select = byId("caseSelect");
    DATA.catalog.cases.forEach((item) => {
      const option = document.createElement("option");
      option.value = String(item.id);
      option.textContent = item.label + " · " + item.runId + " · " + item.viewerFrameCount + "帧";
      select.appendChild(option);
    });
  }

  function resize() {
    if (!renderer || !camera) return;
    const width = Math.max(1, byId("stage").clientWidth);
    const height = Math.max(1, byId("stage").clientHeight);
    camera.aspect = width / height;
    if (camera === orthographicCamera) {
      const aspect = camera.aspect;
      camera.left = -orthoExtent * aspect;
      camera.right = orthoExtent * aspect;
      camera.top = orthoExtent;
      camera.bottom = -orthoExtent;
    }
    camera.updateProjectionMatrix();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(width, height);
    runtime.charts.forEach((entry) => entry.chart.resize());
    if (runtime.historyChart) runtime.historyChart.resize();
  }

  function renderLoop(now) {
    requestAnimationFrame(renderLoop);
    const state = store.get();
    if (!runtime.ready) {
      if (renderer) renderer.render(scene, camera);
      return;
    }
    const last = renderLoop.last || now;
    const delta = Math.min(0.1, (now - last) / 1000);
    renderLoop.last = now;
    if (runtime.playing && runtime.current) {
      runtime.playAccumulator += delta;
      const fps = Number(byId("playbackSpeed").value) || 8;
      if (runtime.playAccumulator >= 1 / fps) {
        runtime.playAccumulator = 0;
        if (state.currentFrame >= runtime.current.meta.frames.length - 1) pausePlayback();
        else actions.setFrame(state.currentFrame + 1, { source: "playback" });
      }
    }
    controls.update();
    renderer.render(scene, camera);
    updateScaleBar();
    renderLoop.metricsFrames = (renderLoop.metricsFrames || 0) + 1;
    if (!renderLoop.metricsLast) renderLoop.metricsLast = now;
    if (now - renderLoop.metricsLast >= 500) {
      const elapsed = (now - renderLoop.metricsLast) / 1000;
      body.dataset.fps = (renderLoop.metricsFrames / elapsed).toFixed(1);
      body.dataset.drawCalls = String(renderer.info.render.calls);
      body.dataset.triangles = String(renderer.info.render.triangles);
      body.dataset.geometries = String(renderer.info.memory.geometries);
      body.dataset.textures = String(renderer.info.memory.textures);
      if (performance.memory) body.dataset.jsHeapBytes = String(performance.memory.usedJSHeapSize);
      renderLoop.metricsLast = now;
      renderLoop.metricsFrames = 0;
    }
  }

  function cleanup() {
    pausePlayback();
    runtime.charts.forEach((entry) => entry.chart.dispose());
    runtime.charts = [];
    if (runtime.historyChart) runtime.historyChart.dispose();
    clearTrajectories();
    if (particles) {
      particles.geometry.dispose();
      particles.material.dispose();
      scene.remove(particles);
    }
    if (wallLines) wallLines.geometry.dispose();
    [crackTension, crackShear].forEach((line) => {
      if (!line) return;
      line.geometry.dispose();
      line.material.dispose();
    });
    [contactLines, bondLines].forEach((line) => {
      if (!line) return;
      line.geometry.dispose();
      line.material.dispose();
    });
    if (controls) controls.dispose();
    if (renderer) {
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    }
    runtime.caseRuntimes.clear();
    window.removeEventListener("resize", resize);
  }

  async function boot() {
    try {
      if (!DATA.catalog || !DATA.static) throw new Error("DATA_PAYLOAD_MISSING");
      if (!window.THREE || !window.echarts) throw new Error("OFFLINE_VENDOR_MISSING");
      if (Array.isArray(window.PFC_VIEWER_CASE_FILTER)) {
        const allowed = new Set(window.PFC_VIEWER_CASE_FILTER.map(Number));
        DATA.catalog.cases = DATA.catalog.cases.filter((caseItem) => allowed.has(Number(caseItem.id)));
        if (!DATA.catalog.cases.length) throw new Error("CASE_FILTER_EMPTY");
        if (!DATA.catalog.cases.some((caseItem) => caseItem.id === DATA.catalog.meta.defaultCase)) {
          DATA.catalog.meta.defaultCase = DATA.catalog.cases[0].id;
        }
      }
      const probe = webglProbe();
      body.dataset.webglStatus = probe.available ? "available" : "unavailable";
      if (!probe.available) throw new Error("WEBGL_UNAVAILABLE");
      createScene();
      populateCaseSelect();
      populateNotes();
      bindControls();
      runtime.ready = true;
      setCameraMode("adaptive");
      applyViewPreset("fit");
      resize();
      requestAnimationFrame(renderLoop);
      body.dataset.payloadVersion = DATA.catalog.meta.payloadVersion;
      body.dataset.schemaVersion = DATA.catalog.meta.schemaVersion;
      body.dataset.caseCount = String(DATA.catalog.cases.length);
      body.dataset.visualSemanticsVersion = visualSemantics.version || "NOT_DECLARED";
      body.dataset.loadMs = (performance.now() - viewerStarted).toFixed(2);
      window.addEventListener("pagehide", cleanup, { once: true });
      window.PFCViewer = {
        state: store,
        actions,
        setFrame: (index) => actions.setFrame(index, { source: "api" }),
        setCase: (caseId) => actions.setCase(caseId, { source: "api" }),
        selectBall: (ballId) => actions.selectBalls([ballId], { source: "api" }),
        selectRange: (range, metric) => actions.setRange(range, metric, { source: "api" }),
        clearSelection: () => actions.clearSelection(),
        setViewPreset: (preset) => applyViewPreset(preset),
        exportPNG: () => exportScene(),
        exportFramePNG: async (frameIndex, width) => {
          if (Number.isFinite(Number(width))) byId("exportWidth").value = String(width);
          await setFrame(Number(frameIndex), { source: "api-export", force: true });
          return renderSceneAt(byId("exportWidth").value, byId("exportBackground").value);
        },
        exportChartSVGs,
        exportCompositePanels,
        getChartSVGDataURLs: chartSVGDataUrls,
        getCompositePanelDataURL: compositePanelsDataUrl,
        getCompositePanelLayout: () => compositeLayout(
          runtime.charts.filter((entry) => !entry.linkedHistogram).length,
          1.5
        ),
        formatting: Object.freeze({
          number: (value, digits) => formatNumber(value, digits),
          metric: (value, unit, digits) => formatMetric(value, unit, digits),
          tooltip: (value, formatting) => formatTooltipValue(value, formatting)
        }),
        getChartExportEntries: chartExportEntries,
        cleanup
      };
      await switchCase(DATA.catalog.meta.defaultCase, "initial");
    } catch (error) {
      showError(error.code || "VIEWER_RUNTIME_ERROR", error);
    }
  }

  boot();
})();
