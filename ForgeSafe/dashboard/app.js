let machines = [];
const inferenceApi = (window.FORGESAFE_API_URL || 'http://127.0.0.1:5000').replace(/\/$/, '');

let cameraStream;
let inferenceTimer;
let lastInferenceAt = 0;
let machineFilter = 'all';
let selectedMachineFeed = 'normal';
let resetMachineFeed = true;
let alerts = [];
let allIncidents = [];
let lastLiveAlertAt = 0;
const frozenMachineSnapshots = new Map();

// Default SOP map for machine models
const machineSopMap = {
    'CNC Lathe': 'SOP-03: ISO 10816-3 (Bearing & Vibration Degradation)',
    'CNC Mill': 'SOP-03: ISO 10816-3 (Rotating Machinery Vibration Limits)',
    'Hydraulic Press': 'SOP-02: ISO 4413 (Hydraulic Pressure & Press Safety)',
    'Furnace': 'SOP-04: NFPA 86 (Furnace Overheating & Shutdown Protocol)',
    'Industrial Chiller': 'SOP-05: ASHRAE 15 (Chiller Cooling Circuit Safety)',
    'Injection Molder': 'SOP-06: ANSI B151.1 (Injection Molder Clamp Safety)',
};

// DOM Elements
const machineGridFull = document.querySelector('#machine-grid-full');
const alertsListFull = document.querySelector('#alerts-list-full');
const toast = document.querySelector('#toast');
const cameraVideo = document.querySelector('#camera-video');
const detectionCanvas = document.querySelector('#detection-canvas');
const feedPlaceholder = document.querySelector('#feed-placeholder');
const feedState = document.querySelector('#feed-state');
const modelState = document.querySelector('#model-state');
const inferenceStatus = document.querySelector('#inference-status');
const inspectionModal = document.querySelector('#inspection-modal');
const inspectionModalMedia = document.querySelector('#inspection-modal-media');
const inspectionModalSummary = document.querySelector('#inspection-modal-summary');
const inspectionDownload = document.querySelector('#inspection-download');
const incidentTableBody = document.querySelector('#incident-table-body');
const incidentSummary = document.querySelector('#incident-summary');

function showToast(message) {
    toast.textContent = message;
    toast.classList.add('show');
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => toast.classList.remove('show'), 2600);
}

// Tab Switching System
function switchView(viewId) {
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewId);
    });

    document.querySelectorAll('.view-panel').forEach(panel => {
        panel.classList.remove('active');
    });

    const activePanel = document.querySelector(`#view-${viewId}`);
    if (activePanel) {
        activePanel.classList.add('active');
    }

    const titleMap = {
        overview: 'Overview',
        machines: 'Machines & Sensors',
        cctv: 'CCTV & Vision',
        incidents: 'Incident Log',
        alerts: 'Live Alerts'
    };

    document.querySelector('#breadcrumb-view').textContent = titleMap[viewId] || 'Overview';
    document.querySelector('.sidebar').classList.remove('open');
}

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
        switchView(item.dataset.view);
    });
});

document.querySelector('.mobile-menu')?.addEventListener('click', () => {
    document.querySelector('.sidebar').classList.toggle('open');
});

// Alerts System with Explicit SOP Citations
function addAlert({ source, title, detail, severity = 'attention', key = `${source}-${title}`, action = null, sop = null, machineId = null }) {
    alerts = alerts.filter(alert => alert.key !== key);
    alerts.unshift({ source, title, detail, severity, key, action, sop, machineId, time: new Date() });
    alerts = alerts.slice(0, 15);
    renderAlerts();
}

function renderAlerts() {
    const activeAlerts = alerts.length;
    const alertSummary = document.querySelector('#alert-summary');
    if (alertSummary) alertSummary.textContent = `${activeAlerts} items`;
    document.querySelector('#machine-alerts').textContent = String(activeAlerts).padStart(2, '0');
    document.querySelector('.nav-count').textContent = activeAlerts;

    const criticals = alerts.filter(a => a.severity === 'critical').length;
    document.querySelector('#critical-alert-count').textContent = `${criticals} critical`;

    const html = activeAlerts
        ? alerts.map(alert => `
            <article class="alert-item ${alert.severity}">
                <div class="alert-copy">
                    <strong>${alert.title}</strong>
                    <span>${alert.detail}</span>
                    ${alert.sop ? `<div class="alert-sop-tag">📋 SOP: <strong>${alert.sop}</strong></div>` : ''}
                    ${alert.action ? `<div class="alert-action-tag">⚡ Action: <strong>${alert.action}</strong></div>` : ''}
                </div>
                <div class="alert-side">
                    <span class="alert-source">${alert.source}</span>
                    ${alert.machineId ? `
                        <div class="alert-controls">
                            <button class="sim-btn sim-freeze" data-machine-id="${alert.machineId}" data-action="freeze">Freeze</button>
                            <button class="sim-btn sim-estop" data-machine-id="${alert.machineId}" data-action="simulated_shutdown">E-Stop</button>
                            <button class="sim-btn sim-loto" data-machine-id="${alert.machineId}" data-action="lockout_tagout">LOTO</button>
                        </div>
                    ` : ''}
                </div>
            </article>
        `).join('')
        : '<div class="table-empty" style="padding: 18px !important;">Monitoring is nominal across all sectors.</div>';

    if (alertsListFull) alertsListFull.innerHTML = html;
    attachSimControlListeners();
}

function syncMachineAlerts(machineList) {
    alerts = alerts.filter(alert => alert.source !== 'Machine');
    machineList.filter(machine => !frozenMachineSnapshots.has(machine.id) && (machine.statusClass === 'attention' || machine.simulatedOverride)).forEach(machine => {
        const sopTitle = machine.guidanceTitle || machineSopMap[machine.name] || 'SOP-03: ISO Standard';

        if (machine.simulatedOverride) {
            addAlert({
                source: 'Machine',
                title: `${machine.name}: ${machine.simulatedOverride.state}`,
                detail: `Operator override triggered by ${machine.simulatedOverride.operator || 'Alex Rivera'}.`,
                severity: 'attention',
                key: `override-${machine.id}`,
                sop: sopTitle,
                machineId: machine.id,
            });
            return;
        }

        const isCritical = machine.risk === 'CRITICAL' || machine.demoStatus === 'FAULT';
        addAlert({
            source: 'Machine',
            title: machine.anomalyDetected ? `${machine.name}: ${machine.anomalyType}` : `${machine.name} Anomaly`,
            detail: `${machine.risk} risk (${machine.failureProbability}% failure probability within 7 days)`,
            severity: isCritical ? 'critical' : 'attention',
            key: `machine-${machine.id}`,
            action: machine.recommendedAction || (isCritical ? 'Emergency Stop & Depressurize' : 'Schedule Inspection'),
            sop: sopTitle,
            machineId: machine.id,
        });
    });
    renderAlerts();
}

// Machine Cards Rendering
function generateMachineCardHTML(machine) {
    const hasOverride = !!machine.simulatedOverride;
    const isFrozen = frozenMachineSnapshots.has(machine.id);
    const overrideState = hasOverride ? machine.simulatedOverride.state : '';
    const isAttention = machine.statusClass === 'attention' || hasOverride;
    const sopTitle = machine.guidanceTitle || machineSopMap[machine.name] || '';

    return `
    <article class="machine-card ${machine.statusClass} ${hasOverride ? (overrideState.includes('SHUTDOWN') ? 'shutdown' : 'locked') : ''}">
      <div class="machine-card-top">
        <div>
          <div class="machine-name">${machine.name}</div>
          <div class="machine-id">${machine.id}</div>
        </div>
        <div class="machine-status ${isAttention ? 'warning' : ''}">
          <i></i>${hasOverride ? overrideState : machine.status}
        </div>
      </div>

      ${hasOverride ? `
        <div class="override-banner">⚠️ ${overrideState}</div>
      ` : `
        <div class="machine-gauge">
          <span style="width: ${machine.health}%"></span>
        </div>
      `}

      <div class="machine-sensors">
        ${(machine.sensorReadings || []).map(sensor => `
            <span>${sensor.label} <strong>${sensor.value}</strong></span>
        `).join('')}
      </div>

      <div class="machine-card-bottom">
        <span>Risk: <strong>${machine.risk || 'LOW'}</strong> (${machine.failureProbability ?? 0}%)</span>
      </div>

      ${sopTitle ? `
        <div class="machine-sop-tag" title="${sopTitle}">
          📋 ${sopTitle}
        </div>
      ` : ''}

      <div class="sim-controls">
                <button class="sim-btn ${isFrozen ? 'sim-unfreeze' : 'sim-freeze'}" data-machine-id="${machine.id}" data-action="${isFrozen ? 'unfreeze' : 'freeze'}">${isFrozen ? '↺ Unfreeze' : 'Freeze sensors'}</button>
      </div>
    </article>
    `;
}

function renderMachines(filter = 'all') {
    const visibleMachines = machines.filter(machine => {
        if (filter === 'all') return true;
        if (filter === 'operational') return machine.statusClass === 'operational' && !machine.simulatedOverride;
        if (filter === 'attention') return machine.statusClass === 'attention' && !machine.simulatedOverride;
        if (filter === 'overridden') return !!machine.simulatedOverride;
        return true;
    });

    const html = visibleMachines.map(generateMachineCardHTML).join('');
    if (machineGridFull) machineGridFull.innerHTML = html;

    attachSimControlListeners();
}

function updateMachineTabs() {
    const operational = machines.filter(m => m.statusClass === 'operational' && !m.simulatedOverride).length;
    const attention = machines.filter(m => m.statusClass === 'attention' && !m.simulatedOverride).length;
    const overridden = machines.filter(m => !!m.simulatedOverride).length;

    document.querySelectorAll('[data-filter="all"] span').forEach(el => el.textContent = machines.length);
    document.querySelectorAll('[data-filter="operational"] span').forEach(el => el.textContent = operational);
    document.querySelectorAll('[data-filter="attention"] span').forEach(el => el.textContent = attention);
    document.querySelectorAll('[data-filter="overridden"] span').forEach(el => el.textContent = overridden);

    document.querySelector('#machines-online').innerHTML = `${operational} <small>/ ${machines.length}</small>`;
}

async function handleSimulatedAction(machineId, actionType, reportId = '') {
    try {
        if (actionType === 'freeze') {
            const machine = machines.find(item => item.id === machineId);
            if (machine) {
                frozenMachineSnapshots.set(machineId, {
                    ...machine,
                    sensorReadings: [...(machine.sensorReadings || [])],
                });
            }
            syncMachineAlerts(machines);
            renderMachines(machineFilter);
            try {
                const response = await fetch(`${inferenceApi}/machines/freeze`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ machine_id: machineId })
                });
                if (!response.ok) throw new Error('Backend freeze unavailable');
                showToast(`${machineId} telemetry and logs frozen`);
            } catch {
                showToast(`${machineId} telemetry frozen locally; restart API to stop server logs`);
            }
            return;
        }

        if (actionType === 'unfreeze') {
            const response = await fetch(`${inferenceApi}/machines/unfreeze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ machine_id: machineId })
            });
            if (!response.ok) throw new Error('Unfreeze failed');
            frozenMachineSnapshots.delete(machineId);
            await loadMachineStatus();
            showToast(`${machineId} sensor data live`);
            return;
        }

        if (actionType === 'reset') {
            const response = await fetch(`${inferenceApi}/machines/reset`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ machine_id: machineId })
            });
            if (!response.ok) throw new Error('Reset failed');
            showToast(`${machineId} reset to telemetry`);
        } else {
            const response = await fetch(`${inferenceApi}/incidents/action`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    report_id: reportId,
                    action_type: actionType,
                    target_id: machineId,
                    operator: 'Alex Rivera'
                })
            });
            if (!response.ok) throw new Error('Action failed');
            const label = actionType === 'simulated_shutdown' ? 'E-Stop' : (actionType === 'lockout_tagout' ? 'LOTO' : 'Work Order');
            showToast(`Simulated ${label} applied to ${machineId}`);
        }
        await loadMachineStatus();
        await loadIncidents();
        await loadAgentStatus();
    } catch (err) {
        showToast(`Action error: ${err.message}`);
    }
}

function attachSimControlListeners() {
    document.querySelectorAll('.sim-btn').forEach(button => {
        button.onclick = (e) => {
            e.stopPropagation();
            const machineId = button.dataset.machineId;
            const action = button.dataset.action;
            const reportId = button.dataset.reportId || '';
            handleSimulatedAction(machineId, action, reportId);
        };
    });
}

// Telemetry Poller
async function loadMachineStatus() {
    try {
        const resetQuery = resetMachineFeed ? '&reset=1' : '';
        const response = await fetch(`${inferenceApi}/machine-status?feed=${selectedMachineFeed}${resetQuery}`);
        if (!response.ok) throw new Error('Machine stream unavailable');
        const payload = await response.json();
        resetMachineFeed = false;
        machines = payload.machines.map(machine => {
            const frozenSnapshot = frozenMachineSnapshots.get(machine.id);
            return frozenSnapshot ? { ...frozenSnapshot } : machine;
        });
        updateMachineTabs();
        syncMachineAlerts(machines);
        renderMachines(machineFilter);
        const latest = payload.machines[0]?.timestamp?.split(' ')[1] || 'Live';
        const streamState = document.querySelector('#machine-stream-state');
        if (streamState) {
            streamState.textContent = `${selectedMachineFeed === 'normal' ? 'Normal' : 'Fault Demo'} · ${latest}`;
            streamState.classList.add('connected');
        }
    } catch {
        const streamState = document.querySelector('#machine-stream-state');
        if (streamState) {
            streamState.textContent = 'Stream offline';
            streamState.classList.remove('connected');
        }
    }
}

// Multi-Agent Status Poller (Powers Overview Agentic Flow Strip)
async function loadAgentStatus() {
    try {
        const response = await fetch(`${inferenceApi}/agents/status`);
        if (!response.ok) return;
        const data = await response.json();
        const stats = data.agent_stats || {};

        const safetyProcessed = stats.safety_agent?.processed || 0;
        const machineProcessed = stats.machine_agent?.processed || 0;
        const supervisorDecisions = stats.supervisor_agent?.decisions || 0;
        const ragQueries = data.knowledge_documents || 7;
        const actionCount = stats.action_agent?.actions || 0;

        // Strip Pills on Overview
        const pillSafety = document.querySelector('#pill-safety-count');
        if (pillSafety) pillSafety.textContent = `${safetyProcessed} hazards`;
        const pillMachine = document.querySelector('#pill-machine-count');
        if (pillMachine) pillMachine.textContent = `${machineProcessed} anomalies`;
        const pillSupervisor = document.querySelector('#pill-supervisor-count');
        if (pillSupervisor) pillSupervisor.textContent = `${supervisorDecisions} decisions`;
        const pillRag = document.querySelector('#pill-rag-count');
        if (pillRag) pillRag.textContent = `${ragQueries} SOPs`;
        const pillAction = document.querySelector('#pill-action-count');
        if (pillAction) pillAction.textContent = `${actionCount} executed`;

        const topBadge = document.querySelector('#top-agent-badge');
        if (topBadge) topBadge.textContent = `5 Agents Synced`;
        const overviewDec = document.querySelector('#overview-decision-count');
        if (overviewDec) overviewDec.textContent = `${supervisorDecisions} decisions`;
        const sopsIndexed = document.querySelector('#sops-indexed');
        if (sopsIndexed) sopsIndexed.innerHTML = `${ragQueries} <small>SOPs</small>`;
    } catch {
        // Standby
    }
}

// Incidents Audit Log
async function loadIncidents() {
    try {
        const response = await fetch(`${inferenceApi}/incidents?limit=25`);
        if (!response.ok) return;
        const data = await response.json();
        allIncidents = data.incidents || [];
        if (incidentSummary) incidentSummary.textContent = `${allIncidents.length} records`;

        if (!allIncidents.length) {
            if (incidentTableBody) incidentTableBody.innerHTML = `<tr><td colspan="7" class="table-empty">No incidents logged. Operational status is clear.</td></tr>`;
            return;
        }

        if (incidentTableBody) {
            incidentTableBody.innerHTML = allIncidents.map(inc => {
                const severityClass = (inc.severity || 'LOW').toLowerCase();
                const statusClass = (inc.status || 'OPEN').toLowerCase().replace('_', '-');
                const target = inc.simulated_action?.target_id || (inc.event?.metadata?.machine_id) || '';
                const sopTitle = inc.guidance?.[0]?.title || 'Safety Procedure';
                const timeStr = inc.created_at ? new Date(inc.created_at).toLocaleTimeString() : '--';

                return `
                    <tr>
                        <td><code>${inc.report_id}</code></td>
                        <td>${timeStr}</td>
                        <td><span class="source-tag">${inc.source}</span></td>
                        <td><span class="severity-badge ${severityClass}">${inc.severity}</span></td>
                        <td><strong>${inc.title}</strong></td>
                        <td>
                            <div>⚡ ${inc.action}</div>
                            <span class="sop-citation">📋 ${sopTitle}</span>
                        </td>
                        <td>
                            <span class="action-status-pill ${statusClass}">${inc.status}</span>
                            ${target && inc.status === 'OPEN' ? `
                                <button class="sim-btn sim-estop" style="margin-left: 6px;" data-machine-id="${target}" data-report-id="${inc.report_id}" data-action="simulated_shutdown">E-Stop</button>
                            ` : ''}
                        </td>
                    </tr>
                `;
            }).join('');
        }

        attachSimControlListeners();
    } catch {
        // Table standby
    }
}

// Media Inspection & Camera
function showInspectionResult(url, summary, isVideo = false) {
    if (inspectionModalMedia) {
        inspectionModalMedia.innerHTML = isVideo
            ? `<video src="${url}" controls autoplay playsinline></video>`
            : `<img src="${url}" alt="Inspection Output">`;
    }
    if (inspectionModalSummary) inspectionModalSummary.textContent = summary;
    if (inspectionDownload) inspectionDownload.href = url;
    if (inspectionModal) inspectionModal.hidden = false;
}

function closeInspectionResult() {
    if (inspectionModal) {
        inspectionModal.hidden = true;
        inspectionModalMedia.replaceChildren();
    }
}

function resetInspectionResult() {
    const result = document.querySelector('#inspection-result');
    const fileInput = document.querySelector('#inspection-file');
    if (fileInput) fileInput.value = '';
    if (result) result.innerHTML = '<span class="result-icon">⌁</span><span>No file selected</span>';
}

document.querySelectorAll('[data-close-inspection]').forEach(el => el.addEventListener('click', closeInspectionResult));

document.addEventListener('keydown', event => {
    if (event.ctrlKey && event.key === 'F5') {
        event.preventDefault();
        resetEverything();
        return;
    }
    if (event.key === 'Escape' && inspectionModal && !inspectionModal.hidden) {
        closeInspectionResult();
    }
});

async function resetEverything() {
    try {
        const response = await fetch(`${inferenceApi}/system/reset`, { method: 'POST' });
        if (!response.ok) throw new Error('System reset failed');
        stopCamera();
        closeInspectionResult();
        resetInspectionResult();
        alerts = [];
        allIncidents = [];
        lastLiveAlertAt = 0;
        selectedMachineFeed = 'normal';
        resetMachineFeed = true;
        machineFilter = 'all';
        frozenMachineSnapshots.clear();
        switchView('overview');
        document.querySelectorAll('.feed-option').forEach(option => {
            option.classList.toggle('active', option.dataset.machineFeed === 'normal');
        });
        document.querySelectorAll('.filter-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.filter === 'all');
        });
        renderAlerts();
        await Promise.all([loadMachineStatus(), loadIncidents(), loadAgentStatus()]);
        showToast('System reset to a fresh state');
    } catch (err) {
        showToast(`Reset error: ${err.message}`);
    }
}

async function checkInferenceApi() {
    try {
        const response = await fetch(`${inferenceApi}/health`);
        if (!response.ok) throw new Error('Unavailable');
        if (modelState) modelState.textContent = 'Active (YOLOv8n)';
        if (inferenceStatus) {
            inferenceStatus.textContent = 'Safety Agent ready';
            inferenceStatus.classList.add('connected');
        }
        return true;
    } catch {
        if (modelState) modelState.textContent = 'Offline';
        if (inferenceStatus) {
            inferenceStatus.textContent = 'Start backend API';
            inferenceStatus.classList.remove('connected');
        }
        return false;
    }
}

function drawDetections(detections, width, height) {
    if (!detectionCanvas || !cameraVideo) return;
    const context = detectionCanvas.getContext('2d');
    detectionCanvas.width = width;
    detectionCanvas.height = height;
    context.clearRect(0, 0, width, height);

    detections.forEach(det => {
        const [x1, y1, x2, y2] = det.box;
        const scaleX = width / cameraVideo.videoWidth;
        const scaleY = height / cameraVideo.videoHeight;
        const x = x1 * scaleX;
        const y = y1 * scaleY;
        const boxWidth = (x2 - x1) * scaleX;
        const boxHeight = (y2 - y1) * scaleY;
        const isHazard = det.class.startsWith('NO-');

        context.strokeStyle = isHazard ? '#ef4444' : '#10b981';
        context.lineWidth = 2.5;
        context.strokeRect(x, y, boxWidth, boxHeight);
        context.fillStyle = isHazard ? '#ef4444' : '#10b981';
        context.font = '600 11px "DM Mono", monospace';
        context.fillText(`${det.class} ${Math.round(det.confidence * 100)}%`, x, Math.max(14, y - 5));
    });
}

async function inferCurrentFrame() {
    if (!cameraStream || cameraVideo.readyState < 2 || Date.now() - lastInferenceAt < 350) return;
    lastInferenceAt = Date.now();
    const frame = document.createElement('canvas');
    frame.width = cameraVideo.videoWidth;
    frame.height = cameraVideo.videoHeight;
    frame.getContext('2d').drawImage(cameraVideo, 0, 0);
    const blob = await new Promise(resolve => frame.toBlob(resolve, 'image/jpeg', .85));
    const body = new FormData();
    body.append('file', blob, 'frame.jpg');

    try {
        const response = await fetch(`${inferenceApi}/predict`, { method: 'POST', body });
        if (!response.ok) throw new Error('Inference error');
        const detections = JSON.parse(response.headers.get('X-Detections') || '[]');
        const unsafe = detections.filter(d => d.class && d.class.startsWith('NO-'));
        drawDetections(detections, detectionCanvas.clientWidth, detectionCanvas.clientHeight);

        if (unsafe.length && Date.now() - lastLiveAlertAt > 6000) {
            lastLiveAlertAt = Date.now();
            addAlert({
                source: 'CCTV Safety Agent',
                title: 'Missing PPE Detected',
                detail: `${unsafe.length} hazard${unsafe.length === 1 ? '' : 's'} (${unsafe.map(u => u.class).join(', ')})`,
                severity: 'critical',
                action: 'Restrict cell entry & issue PPE',
                sop: 'SOP-01: OSHA 1910.132 / ISO 45001 (PPE Compliance Protocol)',
                key: 'cctv-live'
            });
            loadIncidents();
            loadAgentStatus();
        }
        if (inferenceStatus) inferenceStatus.textContent = `${detections.length} detections · Live`;
    } catch {
        if (inferenceStatus) inferenceStatus.textContent = 'API disconnected';
    }
}

async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
        showToast('Camera requires HTTPS or localhost');
        return;
    }
    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
        cameraVideo.srcObject = cameraStream;
        await cameraVideo.play();
        if (feedPlaceholder) feedPlaceholder.hidden = true;
        if (feedState) {
            feedState.innerHTML = '<i></i> LIVE';
            feedState.classList.add('active-recording');
        }
        document.querySelector('#start-camera').disabled = true;
        document.querySelector('#stop-camera').disabled = false;
        const resEl = document.querySelector('#feed-resolution');
        if (resEl) resEl.innerHTML = `${cameraVideo.videoWidth}×${cameraVideo.videoHeight}`;
        await checkInferenceApi();
        inferenceTimer = window.setInterval(inferCurrentFrame, 250);
        showToast('Camera active');
    } catch (err) {
        showToast('Camera access denied or unavailable');
    }
}

function stopCamera() {
    if (inferenceTimer) window.clearInterval(inferenceTimer);
    cameraStream?.getTracks().forEach(track => track.stop());
    cameraStream = undefined;
    cameraVideo.srcObject = null;
    if (detectionCanvas) {
        detectionCanvas.getContext('2d').clearRect(0, 0, detectionCanvas.width, detectionCanvas.height);
    }
    if (feedPlaceholder) feedPlaceholder.hidden = false;
    if (feedState) {
        feedState.innerHTML = '<i></i> READY';
        feedState.classList.remove('active-recording');
    }
    document.querySelector('#start-camera').disabled = false;
    document.querySelector('#stop-camera').disabled = true;
    const resEl = document.querySelector('#feed-resolution');
    if (resEl) resEl.innerHTML = '--';
    if (inferenceStatus) inferenceStatus.textContent = 'Standby';
}

document.querySelector('#start-camera')?.addEventListener('click', startCamera);
document.querySelector('#stop-camera')?.addEventListener('click', stopCamera);

// File Inspection
document.querySelector('#inspection-file')?.addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    const result = document.querySelector('#inspection-result');
    result.innerHTML = `<span class="result-icon spinning">↻</span><span>Inspecting ${file.name}...</span>`;

    try {
        const body = new FormData();
        body.append('file', file);
        const response = await fetch(`${inferenceApi}/predict`, { method: 'POST', body });
        if (!response.ok) throw new Error(`Inspection error (${response.status})`);
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const detections = JSON.parse(response.headers.get('X-Detections') || '[]');
        const unsafe = detections.filter(d => (typeof d === 'string' ? d : d.class).startsWith('NO-'));
        const isVideo = response.headers.get('X-Result-Type') === 'video';
        const summary = unsafe.length
            ? `${unsafe.length} Safety Hazard${unsafe.length === 1 ? '' : 's'} Detected`
            : `${detections.length} items · Compliant`;
        const preview = isVideo ? `<video src="${url}" muted playsinline></video>` : `<img src="${url}">`;
        const ext = isVideo ? 'mp4' : 'jpg';

        result.innerHTML = `
            ${preview}
            <span>${summary}</span>
            <button class="text-button view-result" type="button">View <span>↗</span></button>
            <a class="inspection-download-link" href="${url}" download="inspection-result.${ext}">Download</a>
        `;
        result.querySelector('.view-result').onclick = () => showInspectionResult(url, summary, isVideo);

        if (unsafe.length) {
            addAlert({
                source: 'Inspection',
                title: `PPE Hazard in ${file.name}`,
                detail: `${unsafe.length} non-compliant item${unsafe.length === 1 ? '' : 's'}`,
                severity: 'critical',
                action: 'Review safety log & issue compliance warning',
                sop: 'SOP-01: OSHA 1910.132 (PPE Compliance Protocol)',
                key: `insp-${file.name}`
            });
            await loadIncidents();
            await loadAgentStatus();
        }
        showToast('Inspection complete');
    } catch (err) {
        result.innerHTML = `<span class="result-icon">!</span><span>${err.message}</span>`;
    }
});

// Telemetry Stream Switcher
document.querySelectorAll('.feed-option').forEach(opt => {
    opt.onclick = () => {
        document.querySelectorAll('.feed-option').forEach(o => o.classList.remove('active'));
        opt.classList.add('active');
        selectedMachineFeed = opt.dataset.machineFeed;
        resetMachineFeed = true;
        loadMachineStatus();
        showToast(`${opt.textContent} active`);
    };
});

// Filter Tabs
document.querySelectorAll('.filter-tab').forEach(tab => {
    tab.onclick = () => {
        document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        machineFilter = tab.dataset.filter;
        renderMachines(machineFilter);
    };
});

document.querySelector('#refresh-button')?.addEventListener('click', async () => {
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const syncEl = document.querySelector('#footer-sync');
    if (syncEl) syncEl.textContent = time;
    await Promise.all([loadMachineStatus(), loadAgentStatus(), loadIncidents()]);
    showToast('Telemetry refreshed');
});

// Initialization
checkInferenceApi();
loadMachineStatus();
loadAgentStatus();
loadIncidents();

window.setInterval(loadMachineStatus, 1000);
window.setInterval(() => {
    loadAgentStatus();
    loadIncidents();
}, 2000);
