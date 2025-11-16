// ===== Global state =====

// Actions come from backend config now
let ACTIONS = [];

// Expected FPS we send to the backend. Keep this in sync with
// --num-frames-per-second in src/api/server.py
const FRAMES_PER_SECOND = 2;

// ===== App state =====

let rules = []; // { id, condition_text, action_id }
const MAX_RULES = 5;

let lightsOn = false;
let curtainsOpen = true;

// Three.js state holder
let threeRoom = null;

// SSE + live capture state
let eventSource = null;
let captureIntervalId = null;
let captureCanvas = null;
let captureCtx = null;

// ===== DOM refs =====

const videoEl = document.getElementById("video");
const videoStatusEl = document.getElementById("video-status");

const conditionInputEl = document.getElementById("condition-input");
const actionSelectEl = document.getElementById("action-select");
const ruleFormEl = document.getElementById("rule-form");
const rulesListEl = document.getElementById("rules-list");
const ruleErrorEl = document.getElementById("rule-error");
const addRuleBtn = document.getElementById("add-rule-btn");

const testButtonsContainer = document.getElementById("test-buttons");
const actionStatusEl = document.getElementById("action-status");

const roomCanvasContainer = document.getElementById("room-canvas-container");

// VLM stream DOM refs
const startStreamBtn = document.getElementById("start-stream-btn");
const stopStreamBtn = document.getElementById("stop-stream-btn");
const streamStatusEl = document.getElementById("stream-status");
const streamLogEl = document.getElementById("stream-log");

// ===== Backend config sync =====

async function fetchInitialConfig() {
  try {
    const resp = await fetch("/api/config");
    if (!resp.ok) {
      console.error("Failed to fetch /api/config:", await resp.text());
      return;
    }
    const cfg = await resp.json();
    ACTIONS = Array.isArray(cfg.actions) ? cfg.actions : [];
    rules = Array.isArray(cfg.rules) ? cfg.rules : [];
  } catch (err) {
    console.error("Error fetching initial config:", err);
  }
}

// ===== Camera setup =====

async function initCamera() {
  if (!videoEl || !videoStatusEl) return;

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: false,
    });
    videoEl.srcObject = stream;
    videoStatusEl.textContent = "Camera running.";
  } catch (err) {
    console.error("Failed to init camera:", err);
    videoStatusEl.textContent =
      "Unable to access camera. Check browser permissions.";
  }
}

// ===== Rules UI =====

function initActionsDropdown() {
  if (!actionSelectEl) return;

  actionSelectEl.innerHTML = "";
  ACTIONS.forEach((action) => {
    const option = document.createElement("option");
    option.value = action.id;
    option.textContent = action.label;
    actionSelectEl.appendChild(option);
  });
}

function renderRules() {
  if (!rulesListEl || !addRuleBtn || !ruleErrorEl) return;

  rulesListEl.innerHTML = "";

  if (rules.length === 0) {
    rulesListEl.innerHTML =
      '<p class="status-msg">No rules yet. Add one above.</p>';
  } else {
    rules.forEach((rule) => {
      const action = ACTIONS.find((a) => a.id === rule.action_id || a.id === rule.actionId);

      const item = document.createElement("div");
      item.className = "rule-item";

      const textDiv = document.createElement("div");
      textDiv.className = "rule-text";
      const actionLabel = action?.label ?? rule.action_id ?? rule.actionId;
      textDiv.textContent = `IF "${rule.condition_text || rule.conditionText}" THEN ${actionLabel}`;
      item.appendChild(textDiv);

      const actionsDiv = document.createElement("div");
      actionsDiv.className = "rule-actions";

      const actionTag = document.createElement("div");
      actionTag.className = "rule-tag";
      actionTag.textContent = action?.id ?? rule.action_id ?? rule.actionId;
      actionsDiv.appendChild(actionTag);

      const runBtn = document.createElement("button");
      runBtn.className = "small-btn";
      runBtn.textContent = "Run";
      runBtn.title = "Simulate this rule being triggered";
      runBtn.addEventListener("click", () => {
        const actionId = rule.action_id || rule.actionId;
        executeAction(actionId, `rule:${rule.id}`);
      });
      actionsDiv.appendChild(runBtn);

      const delBtn = document.createElement("button");
      delBtn.className = "small-btn danger";
      delBtn.textContent = "Delete";
      delBtn.addEventListener("click", () => {
        deleteRule(rule.id);
      });
      actionsDiv.appendChild(delBtn);

      item.appendChild(actionsDiv);
      rulesListEl.appendChild(item);
    });
  }

  // Handle max rule count
  if (rules.length >= MAX_RULES) {
    addRuleBtn.disabled = true;
    ruleErrorEl.textContent = `Maximum of ${MAX_RULES} rules reached. Delete one to add another.`;
  } else {
    addRuleBtn.disabled = false;
    ruleErrorEl.textContent = "";
  }
}

async function addRule(conditionText, actionId) {
  if (rules.length >= MAX_RULES) {
    return;
  }

  try {
    const resp = await fetch("/api/config/rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        condition_text: conditionText,
        action_id: actionId,
      }),
    });

    if (!resp.ok) {
      console.error("Failed to add rule:", await resp.text());
      if (ruleErrorEl) {
        ruleErrorEl.textContent = "Failed to add rule on server.";
      }
      return;
    }

    const newRule = await resp.json();
    rules.push(newRule);
    renderRules();
  } catch (err) {
    console.error("Error adding rule:", err);
    if (ruleErrorEl) {
      ruleErrorEl.textContent = "Network error adding rule.";
    }
  }
}

async function deleteRule(id) {
  try {
    const resp = await fetch(`/api/config/rules/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    if (!resp.ok) {
      console.error("Failed to delete rule:", await resp.text());
      return;
    }
    rules = rules.filter((r) => r.id !== id);
    renderRules();
  } catch (err) {
    console.error("Error deleting rule:", err);
  }
}

// ===== Three.js room =====

function initThreeRoom() {
  if (!roomCanvasContainer) return;

  const width = roomCanvasContainer.clientWidth || 480;
  const height = width * 0.75;

  // === Scene / Camera / Renderer ===
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x020617);

  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
  camera.position.set(5, 3.2, 7);
  camera.lookAt(0, 1.8, 0);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.2;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  roomCanvasContainer.appendChild(renderer.domElement);

  // === Simple procedural textures (no external assets) ===

  function makeStripedTexture({
    base = "#020617",
    stripe = "#030712",
    vertical = false,
    stripes = 12,
  }) {
    const size = 512;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");

    ctx.fillStyle = base;
    ctx.fillRect(0, 0, size, size);

    ctx.fillStyle = stripe;

    if (vertical) {
      const stripeWidth = size / stripes;
      for (let i = 0; i < stripes; i++) {
        if (i % 2 === 0) continue;
        ctx.globalAlpha = 0.35;
        ctx.fillRect(i * stripeWidth, 0, stripeWidth, size);
      }
    } else {
      const stripeHeight = size / stripes;
      for (let i = 0; i < stripes; i++) {
        if (i % 2 === 0) continue;
        ctx.globalAlpha = 0.28;
        ctx.fillRect(0, i * stripeHeight, size, stripeHeight);
      }
    }

    const tex = new THREE.CanvasTexture(canvas);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.anisotropy = 8;
    return tex;
  }

  const floorTex = makeStripedTexture({
    base: "#020617",
    stripe: "#030712",
    vertical: false,
    stripes: 18,
  });
  floorTex.repeat.set(3, 4);

  const wallTex = makeStripedTexture({
    base: "#020617",
    stripe: "#030712",
    vertical: true,
    stripes: 20,
  });
  wallTex.repeat.set(2, 1);

  const curtainTex = makeStripedTexture({
    base: "#020617",
    stripe: "#111827",
    vertical: true,
    stripes: 28,
  });
  curtainTex.repeat.set(1.5, 1);

  // === Lighting: bright + readable ===

  // Strong ambient feel
  const hemiLight = new THREE.HemisphereLight(0xf9fafb, 0x030712, 0.9);
  hemiLight.position.set(0, 4, 0);
  scene.add(hemiLight);

  const ambient = new THREE.AmbientLight(0xffffff, 0.5);
  scene.add(ambient);

  // Sunlight from window
  const sunLight = new THREE.DirectionalLight(0xffffff, 0.7);
  sunLight.position.set(-3, 5, -2);
  sunLight.target.position.set(0, 1.8, 0);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.set(1024, 1024);
  sunLight.shadow.camera.near = 0.5;
  sunLight.shadow.camera.far = 20;
  sunLight.shadow.camera.left = -8;
  sunLight.shadow.camera.right = 8;
  sunLight.shadow.camera.top = 8;
  sunLight.shadow.camera.bottom = -2;
  scene.add(sunLight);
  scene.add(sunLight.target);

  // Ceiling fixture (main controllable light)
  const ceilingGroup = new THREE.Group();
  ceilingGroup.position.set(0, 3.9, -0.2);
  scene.add(ceilingGroup);

  const shadeGeom = new THREE.CylinderGeometry(0.9, 1.0, 0.4, 24, 1, true);
  const shadeMat = new THREE.MeshStandardMaterial({
    color: 0x020617,
    roughness: 0.7,
    metalness: 0.2,
    side: THREE.DoubleSide,
  });
  const shadeMesh = new THREE.Mesh(shadeGeom, shadeMat);
  shadeMesh.castShadow = false;
  ceilingGroup.add(shadeMesh);

  const diffuserGeom = new THREE.CircleGeometry(0.85, 24);
  const diffuserMat = new THREE.MeshStandardMaterial({
    color: 0xfef9c3,
    emissive: 0x000000,
    emissiveIntensity: 0,
    roughness: 0.3,
    metalness: 0,
  });
  const diffuserMesh = new THREE.Mesh(diffuserGeom, diffuserMat);
  diffuserMesh.rotation.x = -Math.PI / 2;
  diffuserMesh.position.y = -0.2;
  ceilingGroup.add(diffuserMesh);

  const ceilingLight = new THREE.PointLight(0xffffff, 2.5, 20, 1.8);
  ceilingLight.position.set(0, -0.05, 0);
  ceilingLight.castShadow = true;
  ceilingLight.shadow.mapSize.set(1024, 1024);
  ceilingGroup.add(ceilingLight);

  // Decorative downlight “bulbs”
  const bulbs = [];
  const bulbGeom = new THREE.SphereGeometry(0.12, 16, 16);
  const bulbMatOff = new THREE.MeshStandardMaterial({
    color: 0x4b5563,
    emissive: 0x000000,
    emissiveIntensity: 0,
    roughness: 0.5,
    metalness: 0.4,
  });

  function makeBulb(x, z) {
    const mat = bulbMatOff.clone();
    const mesh = new THREE.Mesh(bulbGeom, mat);
    mesh.position.set(x, 3.6, z);
    mesh.castShadow = false;
    scene.add(mesh);
    bulbs.push(mesh);
    return mesh;
  }

  makeBulb(-1.8, 0.1);
  makeBulb(0, 0.3);
  makeBulb(1.8, 0.1);

  // === Room geometry ===

  const roomGroup = new THREE.Group();
  scene.add(roomGroup);

  // Floor
  const floorGeom = new THREE.PlaneGeometry(9, 7);
  const floorMat = new THREE.MeshStandardMaterial({
    color: 0x111827,
    map: floorTex,
    roughness: 0.75,
    metalness: 0.15,
  });
  const floor = new THREE.Mesh(floorGeom, floorMat);
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = 0;
  floor.receiveShadow = true;
  roomGroup.add(floor);

  // Back wall
  const backWallGeom = new THREE.PlaneGeometry(9, 4.6);
  const backWallMat = new THREE.MeshStandardMaterial({
    color: 0x020617,
    map: wallTex,
    roughness: 0.85,
    metalness: 0.1,
  });
  const backWall = new THREE.Mesh(backWallGeom, backWallMat);
  backWall.position.set(0, 2.3, -3.5);
  backWall.receiveShadow = true;
  roomGroup.add(backWall);

  // Left wall
  const leftWallGeom = new THREE.PlaneGeometry(7, 4.6);
  const leftWallMat = new THREE.MeshStandardMaterial({
    color: 0x020617,
    map: wallTex,
    roughness: 0.85,
    metalness: 0.1,
  });
  const leftWall = new THREE.Mesh(leftWallGeom, leftWallMat);
  leftWall.rotation.y = Math.PI / 2;
  leftWall.position.set(-4.5, 2.3, 0);
  leftWall.receiveShadow = true;
  roomGroup.add(leftWall);

  // Right wall
  const rightWallGeom = new THREE.PlaneGeometry(7, 4.6);
  const rightWallMat = new THREE.MeshStandardMaterial({
    color: 0x020617,
    map: wallTex,
    roughness: 0.85,
    metalness: 0.1,
  });
  const rightWall = new THREE.Mesh(rightWallGeom, rightWallMat);
  rightWall.rotation.y = -Math.PI / 2;
  rightWall.position.set(4.5, 2.3, 0);
  rightWall.receiveShadow = true;
  roomGroup.add(rightWall);

  // Ceiling
  const ceilingGeom = new THREE.PlaneGeometry(9, 7);
  const ceilingMat = new THREE.MeshStandardMaterial({
    color: 0x020617,
    roughness: 0.8,
    metalness: 0.1,
  });
  const ceiling = new THREE.Mesh(ceilingGeom, ceilingMat);
  ceiling.rotation.x = Math.PI / 2;
  ceiling.position.y = 4.6;
  ceiling.receiveShadow = false;
  roomGroup.add(ceiling);

  // === Window ===
  const windowWidth = 3.3;
  const windowHeight = 2.1;
  const windowY = 2.5;
  const windowZ = -3.49;

  const windowFrameGeom = new THREE.PlaneGeometry(windowWidth + 0.4, windowHeight + 0.4);
  const windowFrameMat = new THREE.MeshStandardMaterial({
    color: 0x020617,
    roughness: 0.7,
    metalness: 0.2,
  });
  const windowFrame = new THREE.Mesh(windowFrameGeom, windowFrameMat);
  windowFrame.position.set(0, windowY, windowZ + 0.005);
  roomGroup.add(windowFrame);

  const windowGlassGeom = new THREE.PlaneGeometry(windowWidth, windowHeight);
  const windowGlassMat = new THREE.MeshStandardMaterial({
    color: 0x1d4ed8,
    emissive: 0x0ea5e9,
    emissiveIntensity: 0.7,
    transparent: true,
    opacity: 0.96,
    roughness: 0.2,
    metalness: 0.3,
  });
  const windowGlass = new THREE.Mesh(windowGlassGeom, windowGlassMat);
  windowGlass.position.set(0, windowY, windowZ + 0.02);
  roomGroup.add(windowGlass);

  // Mullions
  const mullionMat = new THREE.MeshStandardMaterial({
    color: 0x020617,
    roughness: 0.4,
    metalness: 0.2,
  });
  const mullionH = new THREE.Mesh(
    new THREE.BoxGeometry(windowWidth + 0.06, 0.07, 0.03),
    mullionMat
  );
  mullionH.position.set(0, windowY, windowZ + 0.025);
  roomGroup.add(mullionH);

  const mullionV = new THREE.Mesh(
    new THREE.BoxGeometry(0.07, windowHeight + 0.06, 0.03),
    mullionMat
  );
  mullionV.position.set(0, windowY, windowZ + 0.025);
  roomGroup.add(mullionV);

  // === Furniture (simple but shaded) ===

  // Sofa
  const sofaGroup = new THREE.Group();
  sofaGroup.position.set(-2.3, 0, 0.4);
  roomGroup.add(sofaGroup);

  const sofaMat = new THREE.MeshStandardMaterial({
    color: 0x111827,
    roughness: 0.8,
    metalness: 0.1,
  });

  const sofaBase = new THREE.Mesh(
    new THREE.BoxGeometry(2.5, 0.45, 1.0),
    sofaMat
  );
  sofaBase.position.set(0, 0.25, 0);
  sofaBase.castShadow = true;
  sofaBase.receiveShadow = true;
  sofaGroup.add(sofaBase);

  const sofaBack = new THREE.Mesh(
    new THREE.BoxGeometry(2.5, 0.85, 0.25),
    sofaMat
  );
  sofaBack.position.set(0, 0.9, -0.35);
  sofaBack.castShadow = true;
  sofaGroup.add(sofaBack);

  // Coffee table
  const tableGroup = new THREE.Group();
  tableGroup.position.set(0.1, 0, 0.25);
  roomGroup.add(tableGroup);

  const tableTop = new THREE.Mesh(
    new THREE.BoxGeometry(1.6, 0.08, 0.9),
    new THREE.MeshStandardMaterial({
      color: 0x111827,
      roughness: 0.6,
      metalness: 0.2,
    })
  );
  tableTop.position.set(0, 0.42, 0);
  tableTop.castShadow = true;
  tableTop.receiveShadow = true;
  tableGroup.add(tableTop);

  const legGeom = new THREE.BoxGeometry(0.08, 0.4, 0.08);
  const legMat = new THREE.MeshStandardMaterial({
    color: 0x1f2937,
    roughness: 0.6,
    metalness: 0.4,
  });

  function makeLeg(x, z) {
    const leg = new THREE.Mesh(legGeom, legMat);
    leg.position.set(x, 0.2, z);
    leg.castShadow = true;
    tableGroup.add(leg);
  }

  const lx = 0.7;
  const lz = 0.4;
  makeLeg(lx, lz);
  makeLeg(-lx, lz);
  makeLeg(lx, -lz);
  makeLeg(-lx, -lz);

  // Side table + lamp
  const sideTable = new THREE.Mesh(
    new THREE.CylinderGeometry(0.45, 0.45, 0.05, 18),
    new THREE.MeshStandardMaterial({
      color: 0x111827,
      roughness: 0.7,
      metalness: 0.25,
    })
  );
  sideTable.position.set(2.6, 0.35, 0.5);
  sideTable.castShadow = true;
  sideTable.receiveShadow = true;
  roomGroup.add(sideTable);

  const sideLampBase = new THREE.Mesh(
    new THREE.CylinderGeometry(0.12, 0.12, 0.25, 16),
    new THREE.MeshStandardMaterial({
      color: 0x374151,
      roughness: 0.5,
      metalness: 0.6,
    })
  );
  sideLampBase.position.set(2.6, 0.6, 0.5);
  sideLampBase.castShadow = true;
  roomGroup.add(sideLampBase);

  const sideLampShade = new THREE.Mesh(
    new THREE.ConeGeometry(0.32, 0.5, 24),
    new THREE.MeshStandardMaterial({
      color: 0x111827,
      roughness: 0.7,
      metalness: 0.1,
    })
  );
  sideLampShade.position.set(2.6, 0.95, 0.5);
  sideLampShade.castShadow = true;
  roomGroup.add(sideLampShade);

  // === Curtains: simple, clean sliding panels ===

  const curtainWidth = 1.9;
  const curtainHeight = 2.4;
  const curtainY = windowY;
  const curtainZ = windowZ + 0.05;
  const curtainBaseXLeft = -0.95;
  const curtainBaseXRight = 0.95;
  const curtainMaxOffset = 1.5;

  function createCurtain(side = "left") {
    const geom = new THREE.PlaneGeometry(curtainWidth, curtainHeight, 8, 4);
    const mat = new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map: curtainTex,
      roughness: 0.9,
      metalness: 0.05,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.98,
    });

    const mesh = new THREE.Mesh(geom, mat);
    mesh.castShadow = true;
    mesh.receiveShadow = false;
    mesh.position.y = curtainY;
    mesh.position.z = curtainZ;

    if (side === "left") {
      mesh.position.x = curtainBaseXLeft;
    } else {
      mesh.position.x = curtainBaseXRight;
    }

    roomGroup.add(mesh);
    return mesh;
  }

  const curtainLeft = createCurtain("left");
  const curtainRight = createCurtain("right");

  const curtainState = {
    openAmount: curtainsOpen ? 1 : 0,        // 0 = closed, 1 = open
    targetOpenAmount: curtainsOpen ? 1 : 0,
  };

  function updateCurtainsFromState() {
    const t = curtainState.openAmount;

    curtainLeft.position.x = curtainBaseXLeft - curtainMaxOffset * t;
    curtainRight.position.x = curtainBaseXRight + curtainMaxOffset * t;

    const minScale = 0.35;
    const scale = 1 - t * (1 - minScale);
    curtainLeft.scale.x = scale;
    curtainRight.scale.x = scale;
  }

  // === Store in global threeRoom ===

  threeRoom = {
    scene,
    camera,
    renderer,
    mainLight: ceilingLight,
    bulbs,
    curtainLeft,
    curtainRight,
    curtainState,
    updateCurtainsFromState,
  };

  // === Resize handling ===
  window.addEventListener("resize", () => {
    if (!threeRoom) return;
    const w = roomCanvasContainer.clientWidth || 480;
    const h = w * 0.75;
    threeRoom.renderer.setSize(w, h);
    threeRoom.camera.aspect = w / h;
    threeRoom.camera.updateProjectionMatrix();
  });

  // === Animation loop ===
  function animate() {
    requestAnimationFrame(animate);

    if (threeRoom) {
      const s = threeRoom.curtainState;
      const speed = 0.09;
      if (Math.abs(s.targetOpenAmount - s.openAmount) > 0.001) {
        s.openAmount +=
          (s.targetOpenAmount - s.openAmount) * speed;
      }
      threeRoom.updateCurtainsFromState();
    }

    renderer.render(scene, camera);
  }

  animate();
}

  

// Update Three.js room visuals based on lightsOn / curtainsOpen
function updateRoomUI() {
  if (!threeRoom) return;

  const { mainLight, bulbs, curtainState } = threeRoom;

  // Lights: bright and warm when ON, still well-lit when OFF
  if (lightsOn) {
    mainLight.intensity = 14.0;

    bulbs.forEach((b) => {
      b.material.color.setHex(0xfacc15);
      b.material.emissive.setHex(0xfacc15);
      b.material.emissiveIntensity = 1.6;
      b.material.needsUpdate = true;
    });
  } else {
    // Still visible, just less punchy overhead light
    mainLight.intensity = 3.0;

    bulbs.forEach((b) => {
      b.material.color.setHex(0x4b5563);
      b.material.emissive.setHex(0x000000);
      b.material.emissiveIntensity = 0;
      b.material.needsUpdate = true;
    });
  }

  // Curtains: just set the target; animation loop interpolates
  curtainState.targetOpenAmount = curtainsOpen ? 1 : 0;
}
  

// ===== Action execution (binary semantics) =====

function executeAction(actionId, source = "manual") {
  let changed = false;
  let message = "";

  switch (actionId) {
    case "turn_lights_on":
      if (!lightsOn) {
        lightsOn = true;
        changed = true;
        message = "Lights turned ON.";
      } else {
        message = "Lights are already ON. Ignoring duplicate 'turn_lights_on'.";
      }
      break;

    case "turn_lights_off":
      if (lightsOn) {
        lightsOn = false;
        changed = true;
        message = "Lights turned OFF.";
      } else {
        message = "Lights are already OFF. Ignoring duplicate 'turn_lights_off'.";
      }
      break;

    case "open_curtain_blinds":
      if (!curtainsOpen) {
        curtainsOpen = true;
        changed = true;
        message = "Curtains opened.";
      } else {
        message =
          "Curtains are already OPEN. Ignoring duplicate 'open_curtain_blinds'.";
      }
      break;

    case "close_curtain_blinds":
      if (curtainsOpen) {
        curtainsOpen = false;
        changed = true;
        message = "Curtains closed.";
      } else {
        message =
          "Curtains are already CLOSED. Ignoring duplicate 'close_curtain_blinds'.";
      }
      break;

    default:
      message = `Unknown action: ${actionId}`;
      break;
  }

  if (changed) {
    updateRoomUI();
  }

  if (actionStatusEl) {
    actionStatusEl.textContent = `[${source}] ${message}`;
  }
}

// ===== Test buttons =====

function initTestButtons() {
  if (!testButtonsContainer) return;

  testButtonsContainer.addEventListener("click", (evt) => {
    if (evt.target.tagName !== "BUTTON") return;
    const actionId = evt.target.getAttribute("data-action-id");
    if (!actionId) return;
    executeAction(actionId, "test-button");
  });
}

// ===== Form handler =====

if (ruleFormEl) {
  ruleFormEl.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const conditionText = conditionInputEl.value.trim();
    const actionId = actionSelectEl.value;

    if (!conditionText) {
      ruleErrorEl.textContent = "Condition text cannot be empty.";
      return;
    }

    if (!actionId) {
      ruleErrorEl.textContent = "Please select an action.";
      return;
    }

    if (rules.length >= MAX_RULES) {
      ruleErrorEl.textContent = `Maximum of ${MAX_RULES} rules reached.`;
      return;
    }

    ruleErrorEl.textContent = "";
    await addRule(conditionText, actionId);

    conditionInputEl.value = "";
  });
}

// ===== Live capture helpers =====

function ensureCaptureCanvas() {
  if (!captureCanvas) {
    captureCanvas = document.createElement("canvas");
    captureCtx = captureCanvas.getContext("2d");
  }
}

function startLiveCapture() {
  if (captureIntervalId || !videoEl) return;
  ensureCaptureCanvas();

  const intervalMs = 1000 / FRAMES_PER_SECOND;

  const sendFrame = () => {
    if (!videoEl || videoEl.readyState < 2) return;

    const vw = videoEl.videoWidth || 640;
    const vh = videoEl.videoHeight || 360;

    captureCanvas.width = vw;
    captureCanvas.height = vh;
    captureCtx.drawImage(videoEl, 0, 0, vw, vh);

    const dataUrl = captureCanvas.toDataURL("image/jpeg", 0.7);

    fetch("/api/live_frame", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_base64: dataUrl }),
    }).catch((err) => console.error("Failed to send live frame:", err));
  };

  // Send one immediately, then at interval.
  sendFrame();
  captureIntervalId = setInterval(sendFrame, intervalMs);
}

function stopLiveCapture() {
  if (captureIntervalId) {
    clearInterval(captureIntervalId);
    captureIntervalId = null;
  }
}

// ===== VLM stream (SSE) =====

function appendStreamEntry(data) {
  if (!streamLogEl) return;

  const {
    window_index,
    t_start_sec,
    t_end_sec,
    description,
    delay_seconds,
    triggered_action_ids,
    triggered_rule_ids,
  } = data;

  const block = document.createElement("div");
  block.className = "stream-log-item";

  const headerEl = document.createElement("div");
  headerEl.className = "stream-log-header";
  const rangeText = `${t_start_sec.toFixed(2)}s → ${t_end_sec.toFixed(2)}s`;
  headerEl.textContent = `Window ${window_index} (${rangeText})`;
  block.appendChild(headerEl);

  if (description) {
    const descEl = document.createElement("div");
    descEl.className = "stream-log-description";
    descEl.textContent = description;
    block.appendChild(descEl);
  }

  const metaLines = [];
  if (Array.isArray(triggered_action_ids) && triggered_action_ids.length > 0) {
    metaLines.push(`Actions: ${triggered_action_ids.join(", ")}`);
  }
  if (Array.isArray(triggered_rule_ids) && triggered_rule_ids.length > 0) {
    metaLines.push(`Rules: ${triggered_rule_ids.join(", ")}`);
  }
  if (typeof delay_seconds === "number") {
    metaLines.push(`Model latency: ${delay_seconds.toFixed(2)}s`);
  }

  if (metaLines.length > 0) {
    const metaEl = document.createElement("div");
    metaEl.className = "stream-log-meta";
    metaEl.textContent = metaLines.join(" • ");
    block.appendChild(metaEl);
  }

  // Add newest at the top
  streamLogEl.prepend(block);
}

function handleModelActionsFromStream(data) {
  const { triggered_action_ids } = data;
  if (!Array.isArray(triggered_action_ids)) return;

  // Deduplicate within a window
  const uniqueActions = [...new Set(triggered_action_ids)];
  uniqueActions.forEach((actionId) => {
    executeAction(actionId, "vlm-stream");
  });
}

function startStream() {
  if (!startStreamBtn || !streamStatusEl) return;

  // Close any existing stream
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }

  if (streamLogEl) {
    streamLogEl.innerHTML = "";
  }
  streamStatusEl.textContent = "Starting live VLM stream…";

  // Start sending webcam frames to backend
  startLiveCapture();

  // Open SSE connection
  eventSource = new EventSource("/api/stream");

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      appendStreamEntry(data);
      handleModelActionsFromStream(data);
      streamStatusEl.textContent = "Streaming live webcam into VLM…";
    } catch (err) {
      console.error("Failed to parse SSE message:", err, event.data);
    }
  };

  eventSource.onerror = (err) => {
    console.error("SSE error:", err);
    streamStatusEl.textContent = "Stream ended or connection lost.";
    stopLiveCapture();
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  };
}

function stopStream() {
  if (!stopStreamBtn || !streamStatusEl) return;

  // Stop webcam frame uploads
  stopLiveCapture();

  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  streamStatusEl.textContent = "Stream stopped.";
}

function initStreamControls() {
  if (!startStreamBtn || !stopStreamBtn) return;

  startStreamBtn.addEventListener("click", () => {
    startStream();
  });

  stopStreamBtn.addEventListener("click", () => {
    stopStream();
  });
}

// ===== Init =====

async function init() {
  initCamera();
  initTestButtons();
  initThreeRoom();
  initStreamControls();

  // Fetch initial actions + rules from backend, then render UI
  await fetchInitialConfig();
  initActionsDropdown();
  renderRules();
  updateRoomUI();
}

document.addEventListener("DOMContentLoaded", () => {
  init();
});
