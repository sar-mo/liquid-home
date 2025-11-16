// ===== Predefined actions (dropdown + logic) =====

const ACTIONS = [
    {
      id: "turn_lights_on",
      label: "Turn lights on",
    },
    {
      id: "turn_lights_off",
      label: "Turn lights off",
    },
    {
      id: "open_curtain_blinds",
      label: "Open curtain blinds",
    },
    {
      id: "close_curtain_blinds",
      label: "Close curtain blinds",
    },
  ];
  
  // ===== App state =====
  
  let rules = []; // { id, conditionText, actionId }
  const MAX_RULES = 5;
  
  let lightsOn = false;
  let curtainsOpen = true;
  
  // Three.js state holder
  let threeRoom = null;
  
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
  
  // ===== Camera setup =====
  
  async function initCamera() {
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
    ACTIONS.forEach((action) => {
      const option = document.createElement("option");
      option.value = action.id;
      option.textContent = action.label;
      actionSelectEl.appendChild(option);
    });
  }
  
  function renderRules() {
    rulesListEl.innerHTML = "";
  
    if (rules.length === 0) {
      rulesListEl.innerHTML =
        '<p class="status-msg">No rules yet. Add one above.</p>';
    } else {
      rules.forEach((rule) => {
        const action = ACTIONS.find((a) => a.id === rule.actionId);
  
        const item = document.createElement("div");
        item.className = "rule-item";
  
        const textDiv = document.createElement("div");
        textDiv.className = "rule-text";
        textDiv.textContent = `IF "${rule.conditionText}" THEN ${
          action?.label ?? rule.actionId
        }`;
        item.appendChild(textDiv);
  
        const actionsDiv = document.createElement("div");
        actionsDiv.className = "rule-actions";
  
        const actionTag = document.createElement("div");
        actionTag.className = "rule-tag";
        actionTag.textContent = action?.id ?? rule.actionId;
        actionsDiv.appendChild(actionTag);
  
        const runBtn = document.createElement("button");
        runBtn.className = "small-btn";
        runBtn.textContent = "Run";
        runBtn.title = "Simulate this rule being triggered";
        runBtn.addEventListener("click", () => {
          executeAction(rule.actionId, `rule:${rule.id}`);
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
  
  function addRule(conditionText, actionId) {
    if (rules.length >= MAX_RULES) {
      return;
    }
    const id = `rule-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    rules.push({ id, conditionText, actionId });
    renderRules();
  }
  
  function deleteRule(id) {
    rules = rules.filter((r) => r.id !== id);
    renderRules();
  }
  
  // ===== Three.js room =====
  
  function initThreeRoom() {
    const width = roomCanvasContainer.clientWidth || 480;
    const height = width * 0.75;
  
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x020617);
  
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(4, 3, 6);
    camera.lookAt(0, 1.5, 0);
  
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    roomCanvasContainer.appendChild(renderer.domElement);
  
    // Floor
    const floorGeom = new THREE.PlaneGeometry(8, 6);
    const floorMat = new THREE.MeshStandardMaterial({ color: 0x111827 });
    const floor = new THREE.Mesh(floorGeom, floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = 0;
    scene.add(floor);
  
    // Back wall
    const wallGeom = new THREE.PlaneGeometry(8, 4);
    const wallMat = new THREE.MeshStandardMaterial({ color: 0x020617 });
    const backWall = new THREE.Mesh(wallGeom, wallMat);
    backWall.position.set(0, 2, -3);
    scene.add(backWall);
  
    // Side walls (optional)
    const sideGeom = new THREE.PlaneGeometry(6, 4);
  
    const leftWall = new THREE.Mesh(
      sideGeom,
      new THREE.MeshStandardMaterial({ color: 0x020617 })
    );
    leftWall.rotation.y = Math.PI / 2;
    leftWall.position.set(-4, 2, 0);
    scene.add(leftWall);
  
    const rightWall = new THREE.Mesh(
      sideGeom,
      new THREE.MeshStandardMaterial({ color: 0x020617 })
    );
    rightWall.rotation.y = -Math.PI / 2;
    rightWall.position.set(4, 2, 0);
    scene.add(rightWall);
  
    // Window
    const windowGeom = new THREE.PlaneGeometry(3, 2);
    const windowMat = new THREE.MeshStandardMaterial({
      color: 0x1d4ed8,
      emissive: 0x0ea5e9,
      emissiveIntensity: 0.3,
      transparent: true,
      opacity: 0.95,
    });
    const windowMesh = new THREE.Mesh(windowGeom, windowMat);
    windowMesh.position.set(0, 2, -2.99);
    scene.add(windowMesh);
  
    // Curtain params
    const curtainGeom = new THREE.PlaneGeometry(1.7, 2.1);
    const curtainMat = new THREE.MeshStandardMaterial({
      color: 0x111827,
      side: THREE.DoubleSide,
    });
  
    const curtainLeft = new THREE.Mesh(curtainGeom, curtainMat.clone());
    curtainLeft.position.set(-0.85, 2, -2.98);
    scene.add(curtainLeft);
  
    const curtainRight = new THREE.Mesh(curtainGeom, curtainMat.clone());
    curtainRight.position.set(0.85, 2, -2.98);
    scene.add(curtainRight);
  
    // Ceiling lights (bulbs)
    const bulbGeom = new THREE.SphereGeometry(0.15, 16, 16);
    const bulbMatOff = new THREE.MeshStandardMaterial({
      color: 0x4b5563,
      emissive: 0x000000,
      emissiveIntensity: 0,
    });
  
    function makeBulb(x) {
      const mat = bulbMatOff.clone();
      const m = new THREE.Mesh(bulbGeom, mat);
      m.position.set(x, 3.7, -1);
      scene.add(m);
      return m;
    }
  
    const bulb1 = makeBulb(-1.5);
    const bulb2 = makeBulb(0);
    const bulb3 = makeBulb(1.5);
  
    // Lights
    const ambient = new THREE.AmbientLight(0xffffff, 0.2);
    scene.add(ambient);
  
    const mainLight = new THREE.PointLight(0xffffff, 0.0, 25);
    mainLight.position.set(0, 3.5, 0);
    scene.add(mainLight);
  
    // Curtain state for smooth animation
    const curtainState = {
      openAmount: curtainsOpen ? 1 : 0, // 0 = fully closed, 1 = fully open
      targetOpenAmount: curtainsOpen ? 1 : 0,
    };
  
    threeRoom = {
      scene,
      camera,
      renderer,
      mainLight,
      bulbs: [bulb1, bulb2, bulb3],
      curtainLeft,
      curtainRight,
      curtainState,
    };
  
    // Resize handler
    window.addEventListener("resize", () => {
      if (!threeRoom) return;
      const w = roomCanvasContainer.clientWidth || 480;
      const h = w * 0.75;
      threeRoom.renderer.setSize(w, h);
      threeRoom.camera.aspect = w / h;
      threeRoom.camera.updateProjectionMatrix();
    });
  
    // Animation loop
    function animate() {
      requestAnimationFrame(animate);
  
      if (threeRoom) {
        // Smooth curtain motion
        const s = threeRoom.curtainState;
        const speed = 0.08;
        if (Math.abs(s.targetOpenAmount - s.openAmount) > 0.001) {
          s.openAmount += (s.targetOpenAmount - s.openAmount) * speed;
        }
        updateCurtainMeshesFromState();
      }
  
      renderer.render(scene, camera);
    }
  
    function updateCurtainMeshesFromState() {
      const { curtainLeft, curtainRight, curtainState } = threeRoom;
      const t = curtainState.openAmount; // 0 closed, 1 open
  
      // When open, slide curtains outwards.
      const closedOffset = 0;
      const openOffset = 1.2;
      const offset = closedOffset + (openOffset - closedOffset) * t;
  
      curtainLeft.position.x = -0.85 - offset;
      curtainRight.position.x = 0.85 + offset;
  
      // Optional slight scale squeeze
      const minScale = 0.3;
      const scaleFactor = 1 - t * (1 - minScale);
      curtainLeft.scale.x = scaleFactor;
      curtainRight.scale.x = scaleFactor;
    }
  
    animate();
  }
  
  // Update Three.js room visuals based on lightsOn / curtainsOpen
  function updateRoomUI() {
    if (!threeRoom) return;
  
    const { mainLight, bulbs, curtainState } = threeRoom;
  
    // Lights
    if (lightsOn) {
      mainLight.intensity = 1.6;
      bulbs.forEach((b) => {
        b.material.color.setHex(0xfacc15);
        b.material.emissive.setHex(0xfacc15);
        b.material.emissiveIntensity = 1.8;
      });
    } else {
      mainLight.intensity = 0.1;
      bulbs.forEach((b) => {
        b.material.color.setHex(0x4b5563);
        b.material.emissive.setHex(0x000000);
        b.material.emissiveIntensity = 0;
      });
    }
  
    // Curtains
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
  
    actionStatusEl.textContent = `[${source}] ${message}`;
  }
  
  // ===== Test buttons =====
  
  function initTestButtons() {
    testButtonsContainer.addEventListener("click", (evt) => {
      if (evt.target.tagName !== "BUTTON") return;
      const actionId = evt.target.getAttribute("data-action-id");
      if (!actionId) return;
      executeAction(actionId, "test-button");
    });
  }
  
  // ===== Form handler =====
  
  ruleFormEl.addEventListener("submit", (evt) => {
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
    addRule(conditionText, actionId);
  
    conditionInputEl.value = "";
  });
  
  // ===== Init =====
  
  function init() {
    initCamera();
    initActionsDropdown();
    initTestButtons();
    initThreeRoom();
    renderRules();
    updateRoomUI();
  }
  
  document.addEventListener("DOMContentLoaded", init);
  