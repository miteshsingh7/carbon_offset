/**
 * CarbonVerify Evidence Workbench Frontend
 * Pure JavaScript single-page application with hand-written SVG charts.
 */

let copy = {};
let currentProject = "";
let projectData = null;
let currentMode = "qm"; // "qm" or "raw"

// Load copy and initialize
async function init() {
  try {
    const resCopy = await fetch("copy.json");
    copy = await resCopy.json();
  } catch (err) {
    console.error("Failed to load copy.json:", err);
  }

  setupProjectSwitcher();
  setupHashRouting();
  setupEvidenceDrawer();
}

// 1. Project Switcher
async function setupProjectSwitcher() {
  const select = document.getElementById("project-select");
  try {
    const res = await fetch("/api/projects");
    const projects = await res.json();
    if (projects.length > 0 && (!currentProject || !projects.includes(currentProject))) {
      currentProject = projects[0];
    }
    select.innerHTML = "";
    projects.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p;
      opt.textContent = `${copy.shell?.project_prefix || ""}${p}`;
      if (p === currentProject) opt.selected = true;
      select.appendChild(opt);
    });

    select.addEventListener("change", (e) => {
      currentProject = e.target.value;
      loadProject(currentProject);
    });

    loadProject(currentProject);
  } catch (err) {
    console.error("Failed to fetch projects:", err);
    select.innerHTML = `<option value="">${copy.shell?.error_loading || copy.missing_value}</option>`;
  }
}

// 2. Fetch and Load Project
async function loadProject(pid) {
  const container = document.getElementById("app-container");
  container.innerHTML = `<div class="text-center py-12 text-on-surface-variant">${copy.shell?.loading_project || copy.missing_value}</div>`;

  try {
    const res = await fetch(`/api/project/${encodeURIComponent(pid)}`);
    if (!res.ok) {
      const notFoundTpl = copy.shell?.project_not_found || copy.missing_value;
      container.innerHTML = `<div class="p-6 bg-surface-container rounded-xl text-error">${notFoundTpl.replace("{pid}", pid)}</div>`;
      return;
    }
    projectData = await res.json();
    updateShell();
    renderRoute();
  } catch (err) {
    console.error("Error loading project data:", err);
    const errTpl = copy.shell?.error_loading_project || copy.missing_value;
    container.innerHTML = `<div class="p-6 bg-surface-container rounded-xl text-error">${errTpl.replace("{error}", err.message)}</div>`;
  }
}

// 3. Shell Updates
function updateShell() {
  if (!projectData) return;

  // Breadcrumbs
  const bcProj = document.getElementById("breadcrumb-project");
  if (bcProj) bcProj.textContent = `${copy.shell?.project_prefix || ""}${projectData.project_id}`;

  // Demo pill
  const demoPill = document.getElementById("demo-pill");
  if (demoPill) {
    if (projectData.demo) {
      demoPill.classList.remove("hidden");
    } else {
      demoPill.classList.add("hidden");
    }
  }

  // Report downloads
  const htmlLink = document.getElementById("download-html-link");
  const jsonLink = document.getElementById("download-json-link");
  if (htmlLink) htmlLink.href = `/report/${projectData.project_id}/report.html`;
  if (jsonLink) jsonLink.href = `/report/${projectData.project_id}/report.json`;

  // Footer text
  const footerText = document.getElementById("footer-text");
  const footerHashes = document.getElementById("footer-hashes");
  if (footerText) {
    footerText.textContent = `${copy.footer?.text_prefix || ""}${projectData.project_id}${copy.footer?.text_suffix || ""}`;
  }
  if (footerHashes) {
    footerHashes.textContent = `${projectData.recorded_files_count || 0} ${copy.footer?.files_recorded_suffix || ""}`;
  }

  // Sidebar Nav Labels from copy.json
  const navLblOverview = document.getElementById("nav-lbl-overview");
  if (navLblOverview && copy.nav?.overview) navLblOverview.textContent = copy.nav.overview;
  const navLblClaims = document.getElementById("nav-lbl-claims");
  if (navLblClaims && copy.nav?.claims) navLblClaims.textContent = copy.nav.claims;
  const navLblArea = document.getElementById("nav-lbl-area");
  if (navLblArea && copy.nav?.area) navLblArea.textContent = copy.nav.area;
  const navLblImagery = document.getElementById("nav-lbl-imagery");
  if (navLblImagery && copy.nav?.imagery) navLblImagery.textContent = copy.nav.imagery;
  const navLblCanopy = document.getElementById("nav-lbl-canopy");
  if (navLblCanopy && copy.nav?.canopy) navLblCanopy.textContent = copy.nav.canopy;
  const navLblLimitations = document.getElementById("nav-lbl-limitations");
  if (navLblLimitations && copy.nav?.limitations) navLblLimitations.textContent = copy.nav.limitations;
}

// 4. Hash Routing
function setupHashRouting() {
  window.addEventListener("hashchange", renderRoute);
  if (!window.location.hash) {
    window.location.hash = "#/overview";
  }
}

function renderRoute() {
  if (!projectData) return;

  const hash = window.location.hash ? window.location.hash : "#/overview";
  const bcPage = document.getElementById("breadcrumb-page");

  // Highlight active nav link
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.remove("bg-surface-high", "text-primary");
    el.classList.add("text-on-surface-variant");
  });

  const activeLink = document.querySelector(`a[href="${hash}"]`);
  if (activeLink) {
    activeLink.classList.add("bg-surface-high", "text-primary");
    activeLink.classList.remove("text-on-surface-variant");
  }

  const container = document.getElementById("app-container");

  if (hash === "#/overview") {
    if (bcPage) bcPage.textContent = copy.nav?.overview || copy.missing_value;
    renderOverview(container);
  } else if (hash === "#/claims") {
    if (bcPage) bcPage.textContent = copy.nav?.claims || copy.missing_value;
    renderClaims(container);
  } else if (hash === "#/area") {
    if (bcPage) bcPage.textContent = copy.nav?.area || copy.missing_value;
    renderAreaTest(container);
  } else if (hash === "#/imagery") {
    if (bcPage) bcPage.textContent = copy.nav?.imagery || copy.missing_value;
    renderImagery(container);
  } else if (hash === "#/canopy") {
    if (bcPage) bcPage.textContent = copy.nav?.canopy || copy.missing_value;
    renderCanopy(container);
  } else if (hash === "#/limitations") {
    if (bcPage) bcPage.textContent = copy.nav?.limitations || copy.missing_value;
    renderLimitations(container);
  } else {
    if (bcPage) bcPage.textContent = copy.nav?.module_preview || copy.missing_value;
    renderComingSoon(container);
  }
}

// Helper: Format numbers
function fmt(num, decimals = 1) {
  if (num === null || num === undefined || isNaN(num)) return copy.missing_value;
  return Number(num).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

// 5. VIEW: Overview Tab
function renderOverview(container) {
  const d = projectData;
  const isConsistent = d.status === "CONSISTENT";
  const statusColor = isConsistent ? "text-primary bg-primary-container/40 border-primary/40" : "text-error bg-error-container/40 border-error/40";
  const confColor = d.confidence === "HIGH" ? "text-primary bg-primary-container/30 border-primary/30" : "text-amber-400 bg-amber-500/20 border-amber-500/30";

  const detLimitRounded = d.detection_limit_pct !== null && d.detection_limit_pct !== undefined ? Math.round(d.detection_limit_pct) : copy.missing_value;
  const scenesPass = d.scenes ? d.scenes.passed : copy.missing_value;
  const scenesTotal = d.scenes ? d.scenes.in_timeseries : copy.missing_value;
  const statusLabel = copy.status_labels?.[d.status] || d.status;
  const confLabel = copy.confidence_labels?.[d.confidence] || d.confidence;

  container.innerHTML = `
    <!-- Hero Status Card -->
    <div class="bg-surface-container border border-outline-variant rounded-2xl p-6 shadow-lg">
      <div class="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 pb-6 border-b border-outline-variant">
        <div>
          <div class="flex items-center space-x-3 mb-2">
            <span class="px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider border ${statusColor}">
              ${statusLabel}
            </span>
            <span class="px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider border ${confColor}">
              ${confLabel} ${copy.confidence_labels?.confidence_suffix || copy.missing_value}
            </span>
          </div>
          <h2 class="text-xl font-bold text-on-surface">
            ${isConsistent ? copy.overview?.no_shortfall : copy.overview?.shortfall_detected}
          </h2>
          <p class="text-sm text-on-surface-variant mt-1">
            ${copy.overview?.detection_limit_prefix} <span class="font-mono text-primary font-semibold">${detLimitRounded}${copy.units?.pct}</span> ${copy.overview?.detection_limit_suffix}
          </p>
        </div>
        <div class="text-right">
          <div class="text-xs text-outline uppercase tracking-wider font-semibold">${copy.overview?.claimed_estate}</div>
          <div class="text-lg font-mono text-on-surface font-semibold">${fmt(d.claims?.estate_area_ha?.value)} ${copy.units?.ha}</div>
        </div>
      </div>

      <!-- Range Gauge -->
      <div class="pt-6">
        <div class="text-xs font-semibold text-outline uppercase tracking-wider mb-2">${copy.overview?.band_vs_claim}</div>
        <div class="w-full overflow-x-auto">
          <div id="gauge-container" class="min-w-[600px] h-28 flex items-center justify-center">
            ${renderRangeGaugeSVG(d)}
          </div>
        </div>
      </div>
    </div>

    <!-- 4 Metric Cards -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      <div class="bg-surface-container border border-outline-variant rounded-xl p-5">
        <div class="text-xs font-semibold text-outline uppercase tracking-wider">${copy.overview?.metric_claim}</div>
        <div class="text-2xl font-mono font-bold text-on-surface mt-2">${fmt(d.claim)} <span class="text-sm text-outline font-normal">${copy.units?.ha}</span></div>
        <div class="text-xs text-on-surface-variant mt-1">${copy.overview?.from_documentation}</div>
      </div>
      <div class="bg-surface-container border border-outline-variant rounded-xl p-5">
        <div class="text-xs font-semibold text-outline uppercase tracking-wider">${copy.overview?.metric_span}</div>
        <div class="text-2xl font-mono font-bold text-on-surface mt-2">${fmt(d.span_pct)}${copy.units?.pct}</div>
        <div class="text-xs text-on-surface-variant mt-1">${d.band ? fmt(d.band[1] - d.band[0]) : copy.missing_value} ${copy.units?.ha} ${copy.overview?.interval_width}</div>
      </div>
      <div class="bg-surface-container border border-outline-variant rounded-xl p-5">
        <div class="text-xs font-semibold text-outline uppercase tracking-wider">${copy.overview?.metric_detection_limit}</div>
        <div class="text-2xl font-mono font-bold text-on-surface mt-2">${fmt(d.detection_limit_pct)}${copy.units?.pct}</div>
        <div class="text-xs text-on-surface-variant mt-1">${copy.overview?.lower_bound_hint}</div>
      </div>
      <div class="bg-surface-container border border-outline-variant rounded-xl p-5">
        <div class="text-xs font-semibold text-outline uppercase tracking-wider">${copy.overview?.metric_scenes}</div>
        <div class="text-2xl font-mono font-bold text-on-surface mt-2">${scenesPass} <span class="text-sm text-outline font-normal">/ ${scenesTotal}</span></div>
        <div class="text-xs text-on-surface-variant mt-1">${copy.overview?.qc_pass_hint}</div>
      </div>
    </div>

    <!-- Grid Split: Why confidence is low & Evidence at a glance -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <!-- Why confidence is low -->
      <div class="bg-surface-container border border-outline-variant rounded-2xl p-6">
        <h3 class="text-base font-bold text-on-surface mb-4 flex items-center space-x-2">
          <span>⚠️</span>
          <span>${copy.overview?.confidence_caveats_title}</span>
        </h3>
        <div class="space-y-4">
          ${renderConfidenceReasons(d.confidence_reasons)}
        </div>
      </div>

      <!-- Evidence at a glance -->
      <div class="bg-surface-container border border-outline-variant rounded-2xl p-6 flex flex-col justify-between">
        <div>
          <h3 class="text-base font-bold text-on-surface mb-2 flex items-center space-x-2">
            <span>🗺️</span>
            <span>${copy.overview?.spatial_evidence_title}</span>
          </h3>
          <p class="text-xs text-on-surface-variant mb-4">
            ${copy.overview?.spatial_subtitle}
          </p>
          <div id="spatial-map-container" class="w-full h-56 bg-surface-low rounded-xl border border-outline-variant flex items-center justify-center overflow-hidden">
            <span class="text-xs text-outline">${copy.overview?.loading_spatial}</span>
          </div>
        </div>
        <div class="mt-4 pt-4 border-t border-outline-variant grid grid-cols-2 gap-4 text-xs">
          <div>
            <div class="text-outline uppercase tracking-wider font-semibold">${copy.overview?.first_high_2020}</div>
            <div class="font-mono text-primary font-bold text-sm mt-0.5">${fmt(d.first_high_year_areas ? d.first_high_year_areas["2020"] : null)} ${copy.units?.ha}</div>
          </div>
          <div>
            <div class="text-outline uppercase tracking-wider font-semibold">${copy.overview?.first_high_2021}</div>
            <div class="font-mono text-tertiary font-bold text-sm mt-0.5">${fmt(d.first_high_year_areas ? d.first_high_year_areas["2021"] : null)} ${copy.units?.ha}</div>
          </div>
        </div>
      </div>
    </div>
  `;

  loadSpatialMap(d.project_id);
}

// Render Range Gauge SVG
function renderRangeGaugeSVG(d) {
  if (!d.band || d.claim === null || d.claim === undefined) {
    return `<div class="text-xs text-outline">${copy.overview?.no_band || copy.missing_value}</div>`;
  }

  const [low, high] = d.band;
  const claim = d.claim;
  const central = (low + high) / 2;

  const minVal = Math.min(low, claim) - 150;
  const maxVal = Math.max(high, claim) + 150;
  const svgWidth = 700;
  const svgHeight = 90;
  const scale = (val) => 40 + ((val - minVal) / (maxVal - minVal)) * (svgWidth - 80);

  const xLow = scale(low);
  const xHigh = scale(high);
  const xClaim = scale(claim);
  const xCentral = scale(central);

  return `
    <svg width="${svgWidth}" height="${svgHeight}" viewBox="0 0 ${svgWidth} ${svgHeight}" class="overflow-visible">
      <!-- Axis line -->
      <line x1="40" y1="45" x2="${svgWidth - 40}" y2="45" stroke="#3c4a42" stroke-width="4" stroke-linecap="round" />

      <!-- Band Rect -->
      <rect x="${xLow}" y="32" width="${Math.max(2, xHigh - xLow)}" height="26" fill="rgba(90, 240, 179, 0.2)" stroke="#5af0b3" stroke-width="2" rx="4" />

      <!-- Central Marker -->
      <circle cx="${xCentral}" cy="45" r="5" fill="#8ad0ea" stroke="#0f1513" stroke-width="2" />
      <text x="${xCentral}" y="20" fill="#8ad0ea" font-size="11" font-family="'JetBrains Mono', monospace" text-anchor="middle" font-weight="600">${copy.overview?.central_prefix} ${fmt(central, 0)} ${copy.units?.ha}</text>

      <!-- Claim Marker (dashed line) -->
      <line x1="${xClaim}" y1="25" x2="${xClaim}" y2="65" stroke="#ffb4ab" stroke-width="2.5" stroke-dasharray="3 3" />
      <text x="${xClaim}" y="80" fill="#ffb4ab" font-size="11" font-family="'JetBrains Mono', monospace" text-anchor="middle" font-weight="bold">${copy.overview?.claim_prefix} ${fmt(claim, 0)} ${copy.units?.ha}</text>

      <!-- Band Boundary Labels -->
      <text x="${xLow}" y="72" fill="#bec9c2" font-size="10" font-family="'JetBrains Mono', monospace" text-anchor="middle">${fmt(low, 0)}</text>
      <text x="${xHigh}" y="72" fill="#bec9c2" font-size="10" font-family="'JetBrains Mono', monospace" text-anchor="middle">${fmt(high, 0)}</text>
    </svg>
  `;
}

// Render Confidence Reasons Rows
function renderConfidenceReasons(reasons) {
  if (!reasons || reasons.length === 0) {
    return `<div class="text-xs text-outline">${copy.overview?.no_caveats || copy.missing_value}</div>`;
  }

  return reasons.map((r) => {
    return `
      <div class="bg-surface-low p-3.5 rounded-xl border border-outline-variant">
        <div class="flex items-center justify-between mb-1">
          <span class="text-xs font-bold text-on-surface uppercase tracking-wide">${r.title}</span>
          ${r.contribution_pct !== null && r.contribution_pct !== undefined ? `<span class="text-xs font-mono text-primary font-semibold">${fmt(r.contribution_pct)}${copy.units?.pct}</span>` : ""}
        </div>
        <p class="text-xs text-on-surface-variant leading-relaxed">${r.description}</p>
      </div>
    `;
  }).join("");
}

// 6. SVG Map Loader (Local Equirectangular Transform)
async function loadSpatialMap(pid) {
  const mapContainer = document.getElementById("spatial-map-container");
  if (!mapContainer) return;

  try {
    const resB = await fetch(`/api/project/${encodeURIComponent(pid)}/geo/boundary`);
    if (!resB.ok) {
      mapContainer.innerHTML = `<span class="text-xs text-outline">${copy.overview?.no_boundary || copy.missing_value}</span>`;
      return;
    }
    const boundaryGeo = await resB.json();

    let ringGeo = null;
    try {
      const resR = await fetch(`/api/project/${encodeURIComponent(pid)}/geo/ring`);
      if (resR.ok) ringGeo = await resR.json();
    } catch (e) {
      // Ring is optional
    }

    mapContainer.innerHTML = renderGeoSVG(boundaryGeo, ringGeo);
  } catch (err) {
    console.error("Map rendering failed:", err);
    mapContainer.innerHTML = `<span class="text-xs text-outline">${copy.overview?.failed_boundary || copy.missing_value}</span>`;
  }
}

function renderGeoSVG(boundaryGeo, ringGeo) {
  // Extract all coordinates to compute bounding box
  const coords = [];
  function extractCoords(geom) {
    if (!geom) return;
    if (geom.type === "Polygon") {
      geom.coordinates.forEach((ring) => ring.forEach((pt) => coords.push(pt)));
    } else if (geom.type === "MultiPolygon") {
      geom.coordinates.forEach((poly) => poly.forEach((ring) => ring.forEach((pt) => coords.push(pt))));
    } else if (geom.type === "Feature") {
      extractCoords(geom.geometry);
    } else if (geom.type === "FeatureCollection") {
      geom.features.forEach((f) => extractCoords(f.geometry));
    }
  }

  extractCoords(boundaryGeo);
  if (ringGeo) extractCoords(ringGeo);

  if (coords.length === 0) {
    return `<span class="text-xs text-outline">${copy.overview?.no_coords || copy.missing_value}</span>`;
  }

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  coords.forEach(([x, y]) => {
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  });

  const padX = (maxX - minX) * 0.1 || 0.01;
  const padY = (maxY - minY) * 0.1 || 0.01;
  minX -= padX; maxX += padX;
  minY -= padY; maxY += padY;

  const w = 450, h = 220;
  const scaleX = (x) => ((x - minX) / (maxX - minX)) * w;
  const scaleY = (y) => h - ((y - minY) / (maxY - minY)) * h; // Invert Y (north up)

  function pathToSVG(geom) {
    if (!geom) return "";
    let paths = [];
    function processPoly(coordinates) {
      coordinates.forEach((ring) => {
        const d = ring.map((pt, i) => `${i === 0 ? "M" : "L"} ${scaleX(pt[0]).toFixed(1)} ${scaleY(pt[1]).toFixed(1)}`).join(" ") + " Z";
        paths.push(d);
      });
    }

    if (geom.type === "Polygon") processPoly(geom.coordinates);
    else if (geom.type === "MultiPolygon") geom.coordinates.forEach(processPoly);
    else if (geom.type === "Feature") return pathToSVG(geom.geometry);
    else if (geom.type === "FeatureCollection") return geom.features.map((f) => pathToSVG(f.geometry)).join(" ");

    return paths.join(" ");
  }

  const boundaryPath = pathToSVG(boundaryGeo);
  const ringPath = ringGeo ? pathToSVG(ringGeo) : "";

  return `
    <svg width="100%" height="100%" viewBox="0 0 ${w} ${h}" class="overflow-visible p-2">
      ${ringPath ? `<path d="${ringPath}" fill="rgba(138, 208, 234, 0.08)" stroke="#8ad0ea" stroke-width="1.5" stroke-dasharray="3 3" />` : ""}
      ${boundaryPath ? `<path d="${boundaryPath}" fill="rgba(90, 240, 179, 0.18)" stroke="#5af0b3" stroke-width="2" />` : ""}
      <!-- Map Legend Overlay -->
      <g transform="translate(12, 18)" class="text-[10px] font-mono">
        <rect x="0" y="0" width="130" height="42" fill="rgba(15, 21, 19, 0.85)" rx="4" stroke="#3c4a42" stroke-width="1" />
        <line x1="8" y1="14" x2="24" y2="14" stroke="#5af0b3" stroke-width="2" />
        <text x="30" y="17" fill="#dee4e0" font-size="10">${copy.overview?.boundary_label}</text>
        <line x1="8" y1="28" x2="24" y2="28" stroke="#8ad0ea" stroke-width="1.5" stroke-dasharray="2 2" />
        <text x="30" y="31" fill="#bec9c2" font-size="10">${copy.overview?.ring_label}</text>
      </g>
    </svg>
  `;
}

// 7. VIEW: Registry Claims Tab
function renderClaims(container) {
  const d = projectData;
  const claims = d.claims || {};
  const sched = d.planting_schedule || [];
  const schedSummary = d.schedule_summary || {};

  container.innerHTML = `
    <!-- Top Claims Table Card -->
    <div class="bg-surface-container border border-outline-variant rounded-2xl p-6 shadow-lg">
      <div class="mb-5">
        <h2 class="text-lg font-bold text-on-surface">${copy.claims?.title}</h2>
        <p class="text-xs text-on-surface-variant">${copy.claims?.subtitle}</p>
      </div>

      <div class="table-scroll-container">
        <table class="w-full text-left text-sm border-collapse">
          <thead>
            <tr class="border-b border-outline-variant text-xs text-outline uppercase tracking-wider">
              <th class="py-3 px-4">${copy.claims?.table_header_claim}</th>
              <th class="py-3 px-4">${copy.claims?.table_header_value}</th>
              <th class="py-3 px-4">${copy.claims?.table_header_source}</th>
              <th class="py-3 px-4 text-center">${copy.claims?.table_header_page}</th>
              <th class="py-3 px-4 text-right">${copy.claims?.table_header_evidence}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-outline-variant/60 font-mono text-xs">
            ${renderClaimsTableRows(claims)}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Planting Schedule Card -->
    <div class="bg-surface-container border border-outline-variant rounded-2xl p-6 shadow-lg">
      <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center pb-5 border-b border-outline-variant gap-4">
        <div>
          <h2 class="text-lg font-bold text-on-surface">${copy.claims?.schedule_title}</h2>
          <p class="text-xs text-on-surface-variant">${copy.claims?.schedule_subtitle}</p>
        </div>
        <div class="flex space-x-4 text-xs font-mono">
          <div class="bg-surface-low px-3 py-1.5 rounded border border-outline-variant">
            <span class="text-outline">${copy.claims?.sum_strata_label}</span> <span class="font-bold text-on-surface">${fmt(schedSummary.sum_area_ha)} ${copy.units?.ha}</span>
          </div>
          <div class="bg-surface-low px-3 py-1.5 rounded border border-outline-variant">
            <span class="text-outline">${copy.claims?.stated_total_label}</span> <span class="font-bold text-on-surface">${fmt(schedSummary.stated_total_ha)} ${copy.units?.ha}</span>
          </div>
          <div class="bg-surface-low px-3 py-1.5 rounded border border-outline-variant">
            <span class="text-outline">${copy.claims?.discrepancy_label}</span> <span class="font-bold text-primary">${fmt(schedSummary.discrepancy_ha)} ${copy.units?.ha}</span>
          </div>
        </div>
      </div>

      <!-- Cohort Stacked Bar Chart -->
      <div class="py-5">
        <div class="text-xs font-semibold text-outline uppercase tracking-wider mb-2">${copy.claims?.allocation_title}</div>
        ${renderStackedBarSVG(sched)}
      </div>

      <!-- Stratum Table -->
      <div class="table-scroll-container pt-3">
        <table class="w-full text-left text-sm border-collapse">
          <thead>
            <tr class="border-b border-outline-variant text-xs text-outline uppercase tracking-wider">
              <th class="py-2.5 px-3">${copy.claims?.col_stratum}</th>
              <th class="py-2.5 px-3 text-center">${copy.claims?.col_year}</th>
              <th class="py-2.5 px-3 text-right">${copy.claims?.col_density}</th>
              <th class="py-2.5 px-3 text-right">${copy.claims?.col_area}</th>
              <th class="py-2.5 px-3 text-right">${copy.claims?.col_trees}</th>
              <th class="py-2.5 px-3 text-center">${copy.claims?.table_header_page}</th>
              <th class="py-2.5 px-3 text-right">${copy.claims?.table_header_evidence}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-outline-variant/40 font-mono text-xs">
            ${renderStratumTableRows(sched)}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function renderClaimsTableRows(claims) {
  const claimLabels = copy.claims?.claim_labels || {};

  return Object.entries(claims).map(([k, c]) => {
    const label = claimLabels[k] || k;
    let displayVal = c.value !== null && c.value !== undefined ? c.value : copy.missing_value;
    if (typeof c.value === "number") displayVal = fmt(c.value);

    const hasQuote = Boolean(c.quote);
    const hasNote = Boolean(c.source_note);

    return `
      <tr class="hover:bg-surface-high/50 transition-colors">
        <td class="py-3 px-4 font-sans font-medium text-on-surface">
          <div>${label}</div>
          ${hasNote ? `<span class="inline-block mt-1 px-2 py-0.5 rounded text-[10px] bg-amber-500/20 text-amber-400 border border-amber-500/30">${copy.claims?.source_note_chip} ${c.source_note}</span>` : ""}
        </td>
        <td class="py-3 px-4 text-primary font-bold">${displayVal}</td>
        <td class="py-3 px-4 text-on-surface-variant">${c.source || copy.missing_value}</td>
        <td class="py-3 px-4 text-center text-outline">${c.page || copy.missing_value}</td>
        <td class="py-3 px-4 text-right">
          ${hasQuote ? `
            <button onclick="openEvidenceDrawer('${escapeQuotes(c.source)}', '${c.page}', '${escapeQuotes(c.quote)}')" class="px-2.5 py-1 bg-surface-high hover:bg-surface-highest text-on-surface rounded text-xs border border-outline-variant transition-colors">
              ${copy.claims?.inspect_quote_button}
            </button>
          ` : '<span class="text-outline">-</span>'}
        </td>
      </tr>
    `;
  }).join("");
}

function renderStackedBarSVG(sched) {
  if (!sched || sched.length === 0) {
    return `<div class="text-xs text-outline">${copy.claims?.no_schedule || copy.missing_value}</div>`;
  }

  // Aggregate by year
  const yearTotals = {};
  let grandTotal = 0;
  sched.forEach((s) => {
    const yr = s.year || copy.claims?.unknown_year || copy.missing_value;
    yearTotals[yr] = (yearTotals[yr] || 0) + (s.area_ha || 0);
    grandTotal += (s.area_ha || 0);
  });

  const colors = ["#5af0b3", "#8ad0ea", "#f59e0b", "#bec9c2"];
  let currX = 0;
  const svgW = 700;
  const barH = 28;

  const rects = Object.entries(yearTotals).map(([yr, a], i) => {
    const pct = grandTotal > 0 ? a / grandTotal : 0;
    const w = pct * svgW;
    const color = colors[i % colors.length];
    const r = `<rect x="${currX}" y="0" width="${w}" height="${barH}" fill="${color}" rx="3" />`;
    currX += w;
    return { r, yr, a, pct, color };
  });

  return `
    <div class="space-y-2">
      <svg width="100%" height="${barH}" viewBox="0 0 ${svgW} ${barH}" class="rounded overflow-hidden">
        ${rects.map((item) => item.r).join("")}
      </svg>
      <div class="flex flex-wrap gap-4 text-xs font-mono mt-2">
        ${rects.map((item) => `
          <div class="flex items-center space-x-1.5">
            <span class="w-3 h-3 rounded-sm" style="background-color: ${item.color}"></span>
            <span class="text-on-surface font-semibold">${item.yr}:</span>
            <span class="text-on-surface-variant">${fmt(item.a)} ${copy.units?.ha} (${(item.pct * 100).toFixed(1)}${copy.units?.pct})</span>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderStratumTableRows(sched) {
  if (!sched || sched.length === 0) {
    return `<tr><td colspan="7" class="py-4 text-center text-outline">${copy.claims?.no_strata || copy.missing_value}</td></tr>`;
  }

  return sched.map((s) => {
    const hasQuote = Boolean(s.evidence_quote);
    return `
      <tr class="hover:bg-surface-high/50 transition-colors">
        <td class="py-2.5 px-3 font-semibold text-on-surface">${s.stratum}</td>
        <td class="py-2.5 px-3 text-center text-outline">${s.year}</td>
        <td class="py-2.5 px-3 text-right text-on-surface-variant">${fmt(s.density, 0)}</td>
        <td class="py-2.5 px-3 text-right text-primary font-bold">${fmt(s.area_ha)}</td>
        <td class="py-2.5 px-3 text-right text-on-surface-variant">${s.trees ? fmt(s.trees, 0) : "-"}</td>
        <td class="py-2.5 px-3 text-center text-outline">${s.page}</td>
        <td class="py-2.5 px-3 text-right">
          ${hasQuote ? `
            <button onclick="openEvidenceDrawer('${escapeQuotes(s.source)}', '${s.page}', '${escapeQuotes(s.evidence_quote)}')" class="px-2 py-0.5 bg-surface-high hover:bg-surface-highest text-on-surface rounded text-[11px] border border-outline-variant transition-colors">
              ${copy.claims?.inspect_quote_button}
            </button>
          ` : '<span class="text-outline">-</span>'}
        </td>
      </tr>
    `;
  }).join("");
}

function marginWording(m) {
  if (m === null || m === undefined || isNaN(m)) return copy.missing_value;
  return m >= 0
    ? copy.area_test?.break_even_below
    : copy.area_test?.break_even_exceeds;
}

// 8. VIEW: Planted Area Test Tab
function renderAreaTest(container) {
  const d = projectData;
  const areaTest = d.area_test || {};
  const gridRows = areaTest.grid_rows || [];
  const breakEven = d.break_even;

  let breakEvenHtml = "";
  if (breakEven) {
    const t60Val = breakEven.by_threshold && breakEven.by_threshold[0] ? Number(breakEven.by_threshold[0].t).toFixed(3) : "";
    const tLowVal = breakEven.by_threshold && breakEven.by_threshold[breakEven.by_threshold.length - 1] ? Number(breakEven.by_threshold[breakEven.by_threshold.length - 1].t).toFixed(3) : "";
    const cardT60Title = (copy.area_test?.break_even_card_template || "").replace("{t}", t60Val);
    const cardTLowTitle = (copy.area_test?.break_even_card_template || "").replace("{t}", tLowVal);

    breakEvenHtml = `
      <!-- Break-Even Forest Allowance Cards -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div class="bg-surface-container border border-outline-variant rounded-xl p-5">
          <div class="text-xs font-semibold text-outline uppercase tracking-wider">${cardT60Title}</div>
          <div class="text-2xl font-mono font-bold text-on-surface mt-2">${fmt(breakEven.f_star_06_ha)} <span class="text-sm text-outline font-normal">${copy.units?.ha}</span></div>
          <div class="text-xs text-outline mt-1">${copy.area_test?.allowance_label} ${fmt(breakEven.natural_forest_ha)} ${copy.units?.ha} | ${copy.area_test?.margin_label} ${breakEven.margin_06_ha >= 0 ? "+" : ""}${fmt(breakEven.margin_06_ha)} ${copy.units?.ha}</div>
          <div class="text-xs text-on-surface-variant mt-1">${marginWording(breakEven.margin_06_ha)}</div>
        </div>
        <div class="bg-surface-container border border-outline-variant rounded-xl p-5">
          <div class="text-xs font-semibold text-outline uppercase tracking-wider">${cardTLowTitle}</div>
          <div class="text-2xl font-mono font-bold text-on-surface mt-2">${fmt(breakEven.f_star_low_end_ha)} <span class="text-sm text-outline font-normal">${copy.units?.ha}</span></div>
          <div class="text-xs text-outline mt-1">${copy.area_test?.allowance_label} ${fmt(breakEven.natural_forest_ha)} ${copy.units?.ha} | ${copy.area_test?.margin_label} ${breakEven.margin_low_end_ha >= 0 ? "+" : ""}${fmt(breakEven.margin_low_end_ha)} ${copy.units?.ha}</div>
          <div class="text-xs text-on-surface-variant mt-1">${marginWording(breakEven.margin_low_end_ha)}</div>
        </div>
        <div class="bg-surface-container border border-outline-variant rounded-xl p-5">
          <div class="text-xs font-semibold text-outline uppercase tracking-wider">${copy.area_test?.break_even_claimed}</div>
          <div class="text-2xl font-mono font-bold text-on-surface mt-2">${fmt(breakEven.natural_forest_ha)} <span class="text-sm text-outline font-normal">${copy.units?.ha}</span></div>
        </div>
      </div>

      <!-- Break-Even by Threshold Table -->
      <div class="bg-surface-container border border-outline-variant rounded-xl p-5 space-y-3">
        <div class="text-xs font-semibold text-outline uppercase tracking-wider">${copy.area_test?.break_even_table_title}</div>
        <div class="table-scroll-container">
          <table class="w-full text-left text-sm border-collapse font-mono text-xs">
            <thead>
              <tr class="border-b border-outline-variant text-outline uppercase tracking-wider text-[11px]">
                <th class="py-2.5 px-3">${copy.area_test?.col_t}</th>
                <th class="py-2.5 px-3 text-right">${copy.area_test?.col_a2022_unit}</th>
                <th class="py-2.5 px-3 text-right">${copy.area_test?.col_f_star_unit}</th>
                <th class="py-2.5 px-3 text-right">${copy.area_test?.col_margin_unit}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-outline-variant/40">
              ${renderBreakEvenRows(breakEven.by_threshold)}
            </tbody>
          </table>
        </div>
      </div>
    `;
  }

  const primaryRow = gridRows.find((r) => r.is_primary) || gridRows.find((r) => r.t === d.area_test?.primary_threshold) || gridRows[0];
  const gridT = gridRows.map((r) => r.t).sort((a, b) => a - b);
  const minT = gridT.length > 0 ? gridT[0] : null;
  const maxT = gridT.length > 0 ? gridT[gridT.length - 1] : null;
  const initialT = primaryRow ? primaryRow.t : minT;
  const initialObs = primaryRow ? fmt(primaryRow.obs_ha, 1) : fmt(null);
  const initialShortfall = primaryRow ? fmt(primaryRow.shortfall_ha, 1) : fmt(null);
  const sliderStep = gridT.length > 1 ? (Math.min(...gridT.slice(1).map((t, i) => t - gridT[i])) / 10).toFixed(3) : "0.001";

  const scaleLabels = gridT.map((t, idx) => {
    let tag = "";
    if (idx === 0) {
      tag = copy.area_test?.generous_tag || "";
    } else if (primaryRow && Math.abs(t - primaryRow.t) < 0.0001) {
      tag = copy.area_test?.primary_tag || "";
    } else if (idx === gridT.length - 1) {
      tag = copy.area_test?.strict_tag || "";
    }
    const tStr = t.toFixed(3);
    return tag ? `${tStr} ${tag}` : tStr;
  });

  const sliderHtml = gridRows.length > 0 ? `
    <!-- Interactive Slider -->
    <div class="bg-surface-low p-5 rounded-xl border border-outline-variant space-y-3">
      <div class="flex justify-between items-center text-xs font-mono">
        <div class="flex items-center space-x-2">
          <span class="text-outline uppercase tracking-wider font-semibold">${copy.area_test?.slider_label}</span>
          <span id="slider-val-display" class="text-primary font-bold text-sm">${initialT.toFixed(3)}</span>
          <span id="slider-interpolated-tag" class="hidden px-2 py-0.5 rounded bg-tertiary/20 text-tertiary text-[10px]">${copy.area_test?.slider_interpolated}</span>
        </div>
        <div>
          <span class="text-outline uppercase tracking-wider font-semibold">${copy.area_test?.observed_area_label}</span>
          <span id="slider-obs-display" class="font-bold text-on-surface text-sm">${initialObs} ${copy.units?.ha}</span>
        </div>
        <div>
          <span class="text-outline uppercase tracking-wider font-semibold">${copy.area_test?.shortfall_display_label}</span>
          <span id="slider-shortfall-display" class="font-bold text-primary text-sm">${initialShortfall} ${copy.units?.ha}</span>
        </div>
      </div>

      <input id="t-slider" type="range" min="${minT.toFixed(3)}" max="${maxT.toFixed(3)}" step="${sliderStep}" value="${initialT.toFixed(3)}" class="w-full cursor-pointer h-2 bg-surface-container rounded-lg appearance-none">
      <div class="flex justify-between text-[11px] font-mono text-outline">
        ${scaleLabels.map((lbl) => `<span>${lbl}</span>`).join("")}
      </div>

      <p class="text-xs text-on-surface-variant italic pt-1">
        "${copy.area_test?.ledger_rule_sentence}"
      </p>
    </div>
  ` : `
    <div class="text-xs text-outline py-2">${copy.missing_value}</div>
  `;

  container.innerHTML = `
    <!-- Top Sensitivity Chart Card -->
    <div class="bg-surface-container border border-outline-variant rounded-2xl p-6 shadow-lg space-y-6">
      <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <h2 class="text-lg font-bold text-on-surface">${copy.area_test?.title}</h2>
          <p class="text-xs text-on-surface-variant">${copy.area_test?.subtitle}</p>
        </div>

        <!-- Segmented Toggle: QM vs RAW -->
        <div class="flex bg-surface-low p-1 rounded-xl border border-outline-variant">
          <button id="toggle-qm" class="px-3 py-1.5 rounded-lg text-xs font-semibold ${currentMode === 'qm' ? 'bg-primary text-on-primary shadow' : 'text-on-surface-variant hover:text-on-surface'} transition-all">
            ${copy.area_test?.toggle_qm}
          </button>
          <button id="toggle-raw" class="px-3 py-1.5 rounded-lg text-xs font-semibold ${currentMode === 'raw' ? 'bg-primary text-on-primary shadow' : 'text-on-surface-variant hover:text-on-surface'} transition-all">
            ${copy.area_test?.toggle_raw}
          </button>
        </div>
      </div>

      <!-- Sensitivity Curve SVG -->
      <div class="w-full overflow-x-auto">
        <div id="curve-chart-container" class="min-w-[650px] h-64 flex items-center justify-center">
          ${renderSensitivityCurveSVG(d, currentMode, initialT)}
        </div>
      </div>

      ${sliderHtml}
    </div>

    ${breakEvenHtml}

    <!-- Threshold Sensitivity Ledger Table -->
    <div class="bg-surface-container border border-outline-variant rounded-2xl p-6 shadow-lg space-y-4">
      <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2">
        <h2 class="text-lg font-bold text-on-surface">${copy.area_test?.ledger_title}</h2>
        <span class="text-xs font-mono text-outline">${copy.area_test?.target_claim_prefix} ${fmt(d.claim)} ${copy.units?.ha}</span>
      </div>

      <div class="table-scroll-container">
        <table class="w-full text-left text-sm border-collapse">
          <thead>
            <tr class="border-b border-outline-variant text-xs text-outline uppercase tracking-wider">
              <th class="py-3 px-4">${copy.area_test?.col_t}</th>
              <th class="py-3 px-4 text-right">${copy.area_test?.col_a2022_unit}</th>
              <th class="py-3 px-4 text-right">${copy.area_test?.col_forest}</th>
              <th class="py-3 px-4 text-right">${copy.area_test?.col_obs}</th>
              <th class="py-3 px-4 text-right">${copy.area_test?.col_shortfall}</th>
              <th class="py-3 px-4 text-right">${copy.area_test?.col_discrepancy}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-outline-variant/60 font-mono text-xs">
            ${renderLedgerRows(gridRows)}
          </tbody>
        </table>
      </div>

      <p class="text-xs text-on-surface-variant italic pt-2">
        "${copy.area_test?.ledger_rule_sentence}"
      </p>
    </div>
  `;

  // Attach Slider and Toggle Events
  setupSliderAndToggles(d);
}

function renderBreakEvenRows(byThresh) {
  if (!byThresh || byThresh.length === 0) {
    return `<tr><td colspan="4" class="py-3 text-center text-outline">${copy.missing_value}</td></tr>`;
  }
  return byThresh.map((r) => {
    const marginSign = r.margin_ha >= 0 ? "+" : "";
    return `
      <tr class="hover:bg-surface-high/50 transition-colors">
        <td class="py-2.5 px-3 font-bold text-on-surface">${Number(r.t).toFixed(3)}</td>
        <td class="py-2.5 px-3 text-right text-on-surface-variant">${fmt(r.a_2022_ha)}</td>
        <td class="py-2.5 px-3 text-right text-on-surface-variant">${fmt(r.f_star_ha)}</td>
        <td class="py-2.5 px-3 text-right text-on-surface-variant font-semibold">${marginSign}${fmt(r.margin_ha)}</td>
      </tr>
    `;
  }).join("");
}

// Render Sensitivity Curve SVG
function renderSensitivityCurveSVG(d, mode, activeT) {
  let pts = [];
  let claim = d.claim;
  let crossingT = d.crossing_t;

  if (mode === "raw" && d.area_test?.raw_sensitivity?.raw_obs_grid) {
    const rawGrid = d.area_test.raw_sensitivity.raw_obs_grid;
    pts = Object.keys(rawGrid).map((k) => ({ t: parseFloat(k), obs: rawGrid[k] })).sort((a, b) => a.t - b.t);
  } else if (d.area_test?.grid_rows) {
    pts = d.area_test.grid_rows.map((r) => ({ t: r.t, obs: r.obs_ha })).sort((a, b) => a.t - b.t);
  }

  if (pts.length < 2) {
    return `<div class="text-xs text-outline">${copy.area_test?.no_sensitivity || copy.missing_value}</div>`;
  }

  const hasClaim = claim !== null && claim !== undefined;
  const svgW = 680, svgH = 220;
  const padL = 60, padR = 40, padT = 30, padB = 40;

  const obsVals = pts.map((p) => p.obs);
  const minObs = hasClaim ? Math.min(...obsVals, claim) - 100 : Math.min(...obsVals) - 100;
  const maxObs = hasClaim ? Math.max(...obsVals, claim) + 100 : Math.max(...obsVals) + 100;
  const tVals = pts.map((p) => p.t);
  const minT = Math.min(...tVals);
  const maxT = Math.max(...tVals);

  const scaleX = (t) => padL + ((t - minT) / (maxT - minT)) * (svgW - padL - padR);
  const scaleY = (obs) => svgH - padB - ((obs - minObs) / (maxObs - minObs)) * (svgH - padT - padB);

  // Path string for curve
  const pathD = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${scaleX(p.t).toFixed(1)} ${scaleY(p.obs).toFixed(1)}`).join(" ");

  // Interpolated active point on curve
  const currentT = activeT !== null && activeT !== undefined ? activeT : (d.area_test?.primary_threshold ?? minT);
  let currentObs = interpolateObs(pts, currentT);
  const activeX = scaleX(currentT);
  const activeY = scaleY(currentObs);

  const claimY = hasClaim ? scaleY(claim) : null;

  // Band area coordinates
  const bandLowY = scaleY(pts[pts.length - 1].obs);
  const bandHighY = scaleY(pts[0].obs);

  return `
    <svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}" class="overflow-visible font-mono text-[10px]">
      <!-- Shaded Band -->
      <rect x="${padL}" y="${bandHighY}" width="${svgW - padL - padR}" height="${Math.abs(bandLowY - bandHighY)}" fill="rgba(90, 240, 179, 0.08)" />

      ${hasClaim ? `
      <!-- Horizontal Claim Line -->
      <line x1="${padL}" y1="${claimY}" x2="${svgW - padR}" y2="${claimY}" stroke="#ffb4ab" stroke-width="1.5" stroke-dasharray="4 4" />
      <text x="${svgW - padR + 5}" y="${claimY + 4}" fill="#ffb4ab" font-weight="600">${copy.area_test?.claim_line_prefix || ""}${fmt(claim, 0)}</text>
      ` : ""}

      <!-- Grid Line Axes -->
      <line x1="${padL}" y1="${svgH - padB}" x2="${svgW - padR}" y2="${svgH - padB}" stroke="#3c4a42" stroke-width="1.5" />
      <line x1="${padL}" y1="${padT}" x2="${padL}" y2="${svgH - padB}" stroke="#3c4a42" stroke-width="1.5" />

      <!-- X-axis Ticks -->
      ${pts.map((p) => `
        <line x1="${scaleX(p.t)}" y1="${svgH - padB}" x2="${scaleX(p.t)}" y2="${svgH - padB + 5}" stroke="#88938c" />
        <text x="${scaleX(p.t)}" y="${svgH - padB + 18}" fill="#88938c" text-anchor="middle">${p.t.toFixed(3)}</text>
      `).join("")}

      <!-- Y-axis Ticks -->
      <text x="${padL - 8}" y="${scaleY(minObs + 100)}" fill="#88938c" text-anchor="end">${fmt(minObs + 100, 0)}</text>
      <text x="${padL - 8}" y="${scaleY((minObs + maxObs) / 2)}" fill="#88938c" text-anchor="end">${fmt((minObs + maxObs) / 2, 0)}</text>
      <text x="${padL - 8}" y="${scaleY(maxObs - 100)}" fill="#88938c" text-anchor="end">${fmt(maxObs - 100, 0)}</text>

      <!-- Crossing Marker if present -->
      ${crossingT ? `
        <line x1="${scaleX(crossingT)}" y1="${padT}" x2="${scaleX(crossingT)}" y2="${svgH - padB}" stroke="#8ad0ea" stroke-width="1.5" stroke-dasharray="2 2" />
        <text x="${scaleX(crossingT)}" y="${padT - 8}" fill="#8ad0ea" text-anchor="middle" font-weight="bold">${(copy.area_test?.crossing_marker_template || "").replace("{t}", crossingT.toFixed(3))}</text>
      ` : ""}

      <!-- Sensitivity Curve Line -->
      <path d="${pathD}" fill="none" stroke="#5af0b3" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />

      <!-- Data Dots -->
      ${pts.map((p) => `
        <circle cx="${scaleX(p.t)}" cy="${scaleY(p.obs)}" r="4.5" fill="#5af0b3" stroke="#0f1513" stroke-width="1.5" />
      `).join("")}

      <!-- Active Slider Point -->
      <circle cx="${activeX}" cy="${activeY}" r="7" fill="#8ad0ea" stroke="#0f1513" stroke-width="2" />
      <text x="${activeX}" y="${activeY - 12}" fill="#8ad0ea" text-anchor="middle" font-weight="bold">${fmt(currentObs, 1)} ${copy.units?.ha}</text>
    </svg>
  `;
}

function interpolateObs(pts, t) {
  for (let i = 0; i < pts.length - 1; i++) {
    const p1 = pts[i];
    const p2 = pts[i + 1];
    if (t >= p1.t && t <= p2.t) {
      const frac = (t - p1.t) / (p2.t - p1.t);
      return p1.obs + frac * (p2.obs - p1.obs);
    }
  }
  return pts[pts.length - 1].obs;
}

function renderLedgerRows(rows) {
  if (!rows || rows.length === 0) {
    return `<tr><td colspan="6" class="py-4 text-center text-outline">${copy.area_test?.no_ledger || copy.missing_value}</td></tr>`;
  }

  return rows.map((r) => {
    const isPrimary = r.is_primary;
    const rowClass = isPrimary ? "bg-primary/10 border-l-4 border-primary" : "hover:bg-surface-high/50";
    return `
      <tr class="${rowClass} transition-colors">
        <td class="py-3 px-4 font-bold ${isPrimary ? "text-primary" : "text-on-surface"}">
          ${r.t.toFixed(3)} ${isPrimary ? `<span class="text-[10px] uppercase font-semibold text-primary ml-1">${copy.area_test?.primary_tag}</span>` : ""}
        </td>
        <td class="py-3 px-4 text-right text-on-surface-variant">${fmt(r.a_2022_ha)}</td>
        <td class="py-3 px-4 text-right text-outline">${fmt(r.forest_allowance_ha)}</td>
        <td class="py-3 px-4 text-right font-bold text-on-surface">${fmt(r.obs_ha)}</td>
        <td class="py-3 px-4 text-right ${r.shortfall_ha > 0 ? "text-primary font-bold" : "text-outline"}">${fmt(r.shortfall_ha)}</td>
        <td class="py-3 px-4 text-right ${r.discrepancy_pct > 0 ? "text-primary font-bold" : "text-outline"}">${fmt(r.discrepancy_pct)}${copy.units?.pct}</td>
      </tr>
    `;
  }).join("");
}

function setupSliderAndToggles(d) {
  const toggleQm = document.getElementById("toggle-qm");
  const toggleRaw = document.getElementById("toggle-raw");
  if (toggleQm && toggleRaw) {
    toggleQm.addEventListener("click", () => {
      currentMode = "qm";
      renderAreaTest(document.getElementById("app-container"));
    });
    toggleRaw.addEventListener("click", () => {
      currentMode = "raw";
      renderAreaTest(document.getElementById("app-container"));
    });
  }

  const slider = document.getElementById("t-slider");
  const valDisp = document.getElementById("slider-val-display");
  const obsDisp = document.getElementById("slider-obs-display");
  const shortDisp = document.getElementById("slider-shortfall-display");
  const interpTag = document.getElementById("slider-interpolated-tag");
  const chartContainer = document.getElementById("curve-chart-container");

  if (!slider) return;

  function updateSliderView(tVal) {
    const t = parseFloat(tVal);
    valDisp.textContent = t.toFixed(3);

    // Check if on standard grid point
    const standardGrid = (d.area_test?.grid_rows || []).map((r) => r.t);
    const isExact = standardGrid.some(function(g) {
      return Math.abs(g - t) < 0.0001;
    });
    if (!isExact) {
      interpTag.classList.remove("hidden");
    } else {
      interpTag.classList.add("hidden");
    }

    let pts = [];
    if (currentMode === "raw" && d.area_test?.raw_sensitivity?.raw_obs_grid) {
      const rawGrid = d.area_test.raw_sensitivity.raw_obs_grid;
      pts = Object.keys(rawGrid).map((k) => ({ t: parseFloat(k), obs: rawGrid[k] })).sort((a, b) => a.t - b.t);
    } else if (d.area_test?.grid_rows) {
      pts = d.area_test.grid_rows.map((r) => ({ t: r.t, obs: r.obs_ha })).sort((a, b) => a.t - b.t);
    }

    const obs = interpolateObs(pts, t);
    const claim = d.claim;
    const shortfall = (claim !== null && claim !== undefined) ? Math.max(0.0, claim - obs) : 0.0;

    obsDisp.textContent = `${fmt(obs, 1)} ${copy.units?.ha}`;
    shortDisp.textContent = `${fmt(shortfall, 1)} ${copy.units?.ha}`;

    chartContainer.innerHTML = renderSensitivityCurveSVG(d, currentMode, t);
  }

  slider.addEventListener("input", (e) => {
    updateSliderView(e.target.value);
  });
}

// 9. VIEW: Coming Soon Placeholder
function renderComingSoon(container) {
  container.innerHTML = `
    <div class="bg-surface-container border border-outline-variant rounded-2xl p-12 text-center max-w-lg mx-auto shadow-lg space-y-4">
      <div class="w-16 h-16 bg-surface-high rounded-full flex items-center justify-center mx-auto text-2xl">
        🚧
      </div>
      <h2 class="text-xl font-bold text-on-surface">${copy.coming_soon?.title || copy.missing_value}</h2>
      <p class="text-sm text-on-surface-variant">
        ${copy.coming_soon?.description || copy.missing_value}
      </p>
      <div class="pt-4">
        <a href="#/overview" class="inline-block px-4 py-2 bg-primary text-on-primary font-semibold text-xs rounded-lg hover:opacity-90 transition-opacity">
          ${copy.coming_soon?.back_to_overview || copy.missing_value}
        </a>
      </div>
    </div>
  `;
}

// 8. Imagery Quality View
function renderImagery(container) {
  const d = projectData;
  const img = d.imagery;
  const imCopy = copy.imagery;

  const funnel = img?.funnel;
  const exclCounts = img?.exclusion_counts_by_reason;
  const dryCounts = img?.dry_season_qc_pass_per_year;
  const timeSeries = img?.time_series || [];
  const exclusionsLog = img?.exclusions_log || [];
  const ingestDates = img?.ingest_excluded_dates || [];

  // Funnel Step List
  const funnelKeys = ["fetched", "excluded_ingest", "in_timeseries", "excluded_qc", "passed"];
  const funnelHtml = funnelKeys.map((k) => {
    const lbl = imCopy?.funnel_steps?.[k] || copy.missing_value;
    const val = funnel && funnel[k] !== null && funnel[k] !== undefined ? fmt(funnel[k], 0) : copy.missing_value;
    return `
      <div class="p-4 rounded-xl bg-surface-container border border-outline-variant flex-1 min-w-[140px]">
        <div class="text-xs uppercase tracking-wider text-outline mb-1 font-semibold">${lbl}</div>
        <div class="text-2xl font-bold font-mono text-on-surface">${val}</div>
      </div>
    `;
  }).join("");

  // Exclusion Reasons Table
  let reasonsRows = "";
  const exclList = Array.isArray(exclCounts) ? exclCounts : [];
  if (exclList.length > 0) {
    const rowsHtml = exclList.map((item) => {
      const flags = Array.isArray(item.flags) ? item.flags : (item.flags ? [item.flags] : []);
      const label = flags.map((f) => (imCopy?.reasons && imCopy.reasons[f]) ? imCopy.reasons[f] : f).join(" + ");
      return `
        <tr class="border-b border-outline-variant/40 hover:bg-surface-high/50">
          <td class="py-2.5 px-3 text-xs text-on-surface">${label}</td>
          <td class="py-2.5 px-3 font-mono text-xs text-right text-on-surface">${fmt(item.count, 0)}</td>
        </tr>
      `;
    }).join("");

    const totalVal = funnel && funnel.excluded_qc !== null && funnel.excluded_qc !== undefined ? fmt(funnel.excluded_qc, 0) : copy.missing_value;
    const totalRow = `
      <tr class="border-t-2 border-outline-variant font-bold bg-surface-container/50">
        <td class="py-2.5 px-3 text-xs text-on-surface font-semibold">${imCopy?.reasons_total_label || copy.missing_value}</td>
        <td class="py-2.5 px-3 font-mono text-xs text-right text-on-surface">${totalVal}</td>
      </tr>
    `;
    reasonsRows = rowsHtml + totalRow;
  } else {
    reasonsRows = `
      <tr>
        <td colspan="2" class="py-4 text-center text-xs text-outline">${copy.missing_value}</td>
      </tr>
    `;
  }

  // Dry Season Counts Table
  let dryRows = "";
  if (dryCounts && Object.keys(dryCounts).length > 0) {
    dryRows = Object.entries(dryCounts).sort().map(([yr, cnt]) => {
      return `
        <tr class="border-b border-outline-variant/40 hover:bg-surface-high/50">
          <td class="py-2.5 px-3 font-mono font-medium text-xs text-on-surface">${yr}</td>
          <td class="py-2.5 px-3 font-mono text-xs text-right text-primary">${fmt(cnt, 0)}</td>
        </tr>
      `;
    }).join("");
  } else {
    dryRows = `
      <tr>
        <td colspan="2" class="py-4 text-center text-xs text-outline">${copy.missing_value}</td>
      </tr>
    `;
  }

  // Time-Series SVG Chart
  const chartSvg = renderNDVITimeSeriesSVG(timeSeries, img?.reporting_period_start, img?.reporting_period_end);

  // Exclusions Log Table
  let logRows = "";
  if (exclusionsLog && exclusionsLog.length > 0) {
    logRows = exclusionsLog.map((item) => {
      return `
        <tr class="border-b border-outline-variant/30 hover:bg-surface-high/40">
          <td class="py-2 px-3 font-mono text-xs text-on-surface whitespace-nowrap">${item.date || copy.missing_value}</td>
          <td class="py-2 px-3 font-mono text-xs text-secondary whitespace-nowrap">${item.scene_id || copy.missing_value}</td>
          <td class="py-2 px-3 font-mono text-xs text-outline">${item.reason || copy.missing_value}</td>
        </tr>
      `;
    }).join("");
  } else {
    logRows = `
      <tr>
        <td colspan="3" class="py-4 text-center text-xs text-outline">${imCopy?.no_exclusions || copy.missing_value}</td>
      </tr>
    `;
  }

  // Ingest-excluded Dates Tags
  let ingestDatesHtml = "";
  if (ingestDates && ingestDates.length > 0) {
    const badges = ingestDates.map((dt) => `<span class="px-2 py-0.5 rounded bg-surface-high text-xs font-mono text-on-surface border border-outline-variant">${dt}</span>`).join(" ");
    ingestDatesHtml = `
      <div class="mt-4 pt-3 border-t border-outline-variant">
        <div class="text-xs text-outline mb-1.5">${imCopy?.ingest_dates_desc || copy.missing_value}</div>
        <div class="flex flex-wrap gap-1.5">${badges}</div>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="space-y-6">
      <div class="flex flex-col gap-1">
        <h2 class="text-2xl font-bold tracking-tight text-on-surface">${imCopy?.title || copy.missing_value}</h2>
        <p class="text-sm text-on-surface-variant">${imCopy?.subtitle || copy.missing_value}</p>
      </div>

      <div class="space-y-2">
        <div class="text-xs uppercase tracking-wider text-outline font-semibold">${imCopy?.funnel_title || copy.missing_value}</div>
        <div class="flex flex-wrap gap-3">
          ${funnelHtml}
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div class="lg:col-span-2 p-5 rounded-xl bg-surface-container border border-outline-variant flex flex-col">
          <div class="mb-3">
            <h3 class="text-base font-bold text-on-surface">${imCopy?.reasons_title || copy.missing_value}</h3>
          </div>
          <div class="overflow-x-auto w-full flex-1">
            <table class="min-w-full text-left">
              <thead>
                <tr class="border-b border-outline-variant text-xs text-outline uppercase font-semibold">
                  <th class="py-2 px-3">${imCopy?.reasons_desc_col || copy.missing_value}</th>
                  <th class="py-2 px-3 text-right">${imCopy?.reasons_count_col || copy.missing_value}</th>
                </tr>
              </thead>
              <tbody>
                ${reasonsRows}
              </tbody>
            </table>
          </div>
          ${ingestDatesHtml}
        </div>

        <div class="p-5 rounded-xl bg-surface-container border border-outline-variant flex flex-col">
          <div class="mb-3">
            <h3 class="text-base font-bold text-on-surface">${imCopy?.dry_season_title || copy.missing_value}</h3>
            <p class="text-xs text-on-surface-variant mt-0.5">${imCopy?.dry_season_desc || copy.missing_value}</p>
          </div>
          <div class="overflow-x-auto w-full flex-1">
            <table class="min-w-full text-left">
              <thead>
                <tr class="border-b border-outline-variant text-xs text-outline uppercase font-semibold">
                  <th class="py-2 px-3">${imCopy?.year_col || copy.missing_value}</th>
                  <th class="py-2 px-3 text-right">${imCopy?.pass_count_col || copy.missing_value}</th>
                </tr>
              </thead>
              <tbody>
                ${dryRows}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <div class="flex flex-col md:flex-row items-start md:items-center justify-between gap-2 mb-4">
          <div>
            <h3 class="text-base font-bold text-on-surface">${imCopy?.chart_title || copy.missing_value}</h3>
            <p class="text-xs text-on-surface-variant">${imCopy?.chart_subtitle || copy.missing_value}</p>
          </div>
          <div class="flex flex-wrap items-center gap-4 text-xs">
            <div class="flex items-center space-x-1.5">
              <span class="w-3 h-0.5 bg-[#5af0b3] inline-block"></span>
              <span class="text-on-surface-variant">${imCopy?.chart_legend?.project || copy.missing_value}</span>
            </div>
            <div class="flex items-center space-x-1.5">
              <span class="w-3 h-0.5 border-t border-dashed border-[#8ad0ea] inline-block"></span>
              <span class="text-on-surface-variant">${imCopy?.chart_legend?.ring || copy.missing_value}</span>
            </div>
            <div class="flex items-center space-x-1.5">
              <span class="w-2 h-2 rounded-full bg-[#5af0b3] inline-block"></span>
              <span class="text-on-surface-variant">${imCopy?.chart_legend?.passed || copy.missing_value}</span>
            </div>
            <div class="flex items-center space-x-1.5">
              <span class="w-2.5 h-2.5 rounded-full border border-[#5af0b3] inline-block"></span>
              <span class="text-on-surface-variant">${imCopy?.chart_legend?.excluded || copy.missing_value}</span>
            </div>
            <div class="flex items-center space-x-1.5">
              <span class="w-3 h-3 bg-[#354c41]/50 border border-[#354c41] rounded-sm inline-block"></span>
              <span class="text-on-surface-variant">${imCopy?.chart_legend?.reporting_period || copy.missing_value}</span>
            </div>
          </div>
        </div>
        <div class="w-full overflow-x-auto">
          ${chartSvg}
        </div>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <div class="mb-3">
          <h3 class="text-base font-bold text-on-surface">${imCopy?.exclusions_log_title || copy.missing_value}</h3>
          <p class="text-xs text-on-surface-variant">${imCopy?.exclusions_log_desc || copy.missing_value}</p>
        </div>
        <div class="overflow-x-auto max-h-80 overflow-y-auto w-full border border-outline-variant rounded-lg">
          <table class="min-w-full text-left">
            <thead class="sticky top-0 bg-surface-high z-10">
              <tr class="border-b border-outline-variant text-xs text-outline uppercase font-semibold">
                <th class="py-2.5 px-3">${imCopy?.log_cols?.date || copy.missing_value}</th>
                <th class="py-2.5 px-3">${imCopy?.log_cols?.scene_id || copy.missing_value}</th>
                <th class="py-2.5 px-3">${imCopy?.log_cols?.reason || copy.missing_value}</th>
              </tr>
            </thead>
            <tbody>
              ${logRows}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;
}

function renderNDVITimeSeriesSVG(ts, periodStart, periodEnd) {
  if (!ts || ts.length < 2) {
    return `<div class="text-center py-12 text-xs text-outline">${copy.missing_value}</div>`;
  }

  const parsed = [];
  ts.forEach((pt) => {
    if (!pt.date) return;
    const t = Date.parse(pt.date);
    if (isNaN(t)) return;
    parsed.push({
      dateStr: pt.date,
      time: t,
      pNdvi: pt.project_ndvi,
      rNdvi: pt.ring_ndvi,
      pass: pt.pass,
    });
  });

  if (parsed.length < 2) {
    return `<div class="text-center py-12 text-xs text-outline">${copy.missing_value}</div>`;
  }

  parsed.sort((a, b) => a.time - b.time);

  const svgW = 860, svgH = 260;
  const padL = 55, padR = 30, padT = 25, padB = 35;

  const minT = parsed[0].time;
  const maxT = parsed[parsed.length - 1].time;

  let yMin = 0.2, yMax = 1.0;
  const allVals = [];
  parsed.forEach((p) => {
    if (p.pNdvi !== null && p.pNdvi !== undefined) allVals.push(p.pNdvi);
    if (p.rNdvi !== null && p.rNdvi !== undefined) allVals.push(p.rNdvi);
  });
  if (allVals.length > 0) {
    const rawMin = Math.min(...allVals);
    const rawMax = Math.max(...allVals);
    yMin = Math.max(0.0, Math.floor((rawMin - 0.05) * 10) / 10);
    yMax = Math.min(1.0, Math.ceil((rawMax + 0.05) * 10) / 10);
  }
  if (yMin >= yMax) {
    yMin = 0.0;
    yMax = 1.0;
  }

  const scaleX = (t) => padL + ((t - minT) / (maxT - minT)) * (svgW - padL - padR);
  const scaleY = (v) => svgH - padB - ((v - yMin) / (yMax - yMin)) * (svgH - padT - padB);

  let periodShading = "";
  if (periodStart && periodEnd) {
    const tS = Date.parse(periodStart);
    const tE = Date.parse(periodEnd);
    if (!isNaN(tS) && !isNaN(tE)) {
      const x1 = Math.max(padL, scaleX(tS));
      const x2 = Math.min(svgW - padR, scaleX(tE));
      if (x2 > x1) {
        periodShading = `
          <rect x="${x1}" y="${padT}" width="${x2 - x1}" height="${svgH - padT - padB}" fill="#354c41" fill-opacity="0.35" />
          <line x1="${x1}" y1="${padT}" x2="${x1}" y2="${svgH - padB}" stroke="#354c41" stroke-dasharray="2,2" />
          <line x1="${x2}" y1="${padT}" x2="${x2}" y2="${svgH - padB}" stroke="#354c41" stroke-dasharray="2,2" />
        `;
      }
    }
  }

  const yTicks = 5;
  let yAxisHtml = "";
  for (let i = 0; i <= yTicks; i++) {
    const val = yMin + (i / yTicks) * (yMax - yMin);
    const y = scaleY(val);
    yAxisHtml += `
      <line x1="${padL}" y1="${y}" x2="${svgW - padR}" y2="${y}" stroke="#262b2a" stroke-dasharray="3,3" />
      <text x="${padL - 10}" y="${y + 4}" text-anchor="end" font-size="10" fill="#88938c" font-family="monospace">${val.toFixed(2)}</text>
    `;
  }
  const yAxisTitle = copy.imagery?.chart_axes?.y_label || copy.missing_value;
  const yAxisLabelHtml = `
    <text x="${15}" y="${padT + (svgH - padT - padB) / 2}" text-anchor="middle" transform="rotate(-90 15 ${padT + (svgH - padT - padB) / 2})" font-size="10" fill="#88938c" font-family="sans-serif">${yAxisTitle}</text>
  `;

  let xAxisHtml = "";
  const yearSet = new Set();
  parsed.forEach((p) => {
    const yr = p.dateStr.slice(0, 4);
    if (!yearSet.has(yr)) {
      yearSet.add(yr);
      const x = scaleX(p.time);
      xAxisHtml += `
        <line x1="${x}" y1="${svgH - padB}" x2="${x}" y2="${svgH - padB + 5}" stroke="#3c4a42" />
        <text x="${x}" y="${svgH - padB + 18}" text-anchor="middle" font-size="10" fill="#88938c" font-family="monospace">${yr}</text>
      `;
    }
  });

  let ringPath = "";
  parsed.forEach((p) => {
    if (p.pass && p.rNdvi !== null && p.rNdvi !== undefined) {
      const x = scaleX(p.time);
      const y = scaleY(p.rNdvi);
      ringPath += ringPath === "" ? `M ${x.toFixed(1)} ${y.toFixed(1)}` : ` L ${x.toFixed(1)} ${y.toFixed(1)}`;
    }
  });

  let projPath = "";
  let markersHtml = "";
  parsed.forEach((p) => {
    if (p.pNdvi !== null && p.pNdvi !== undefined) {
      const x = scaleX(p.time);
      const y = scaleY(p.pNdvi);
      if (p.pass) {
        projPath += projPath === "" ? `M ${x.toFixed(1)} ${y.toFixed(1)}` : ` L ${x.toFixed(1)} ${y.toFixed(1)}`;
        markersHtml += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.5" fill="#5af0b3" />`;
      } else {
        markersHtml += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="none" stroke="#5af0b3" stroke-width="1.5" />`;
      }
    }
  });

  return `
    <svg viewBox="0 0 ${svgW} ${svgH}" class="w-full h-auto max-h-[320px] select-none">
      ${periodShading}
      ${yAxisHtml}
      ${yAxisLabelHtml}
      <line x1="${padL}" y1="${svgH - padB}" x2="${svgW - padR}" y2="${svgH - padB}" stroke="#3c4a42" />
      ${xAxisHtml}
      ${ringPath !== "" ? `<path d="${ringPath}" fill="none" stroke="#8ad0ea" stroke-width="1.5" stroke-dasharray="4,4" />` : ""}
      ${projPath !== "" ? `<path d="${projPath}" fill="none" stroke="#5af0b3" stroke-width="2" />` : ""}
      ${markersHtml}
    </svg>
  `;
}

// 9. Canopy and Biomass View
function renderCanopy(container) {
  const d = projectData;
  const can = d.canopy;
  const canCopy = copy.canopy;

  if (!can) {
    container.innerHTML = `
      <div class="space-y-6">
        <div class="flex flex-col gap-1">
          <h2 class="text-2xl font-bold tracking-tight text-on-surface">${canCopy?.title || copy.missing_value}</h2>
          <p class="text-sm text-on-surface-variant">${canCopy?.subtitle || copy.missing_value}</p>
        </div>
        <div class="p-8 rounded-xl bg-surface-container border border-outline-variant text-center">
          <p class="text-sm text-outline">${copy.missing_value}</p>
        </div>
      </div>
    `;
    return;
  }

  const thresholds = can?.thresholds || [];
  const years = can?.years || [];
  const tbl = can?.table || {};
  const primaryT = can?.primary_threshold;
  const bioByYr = can?.biomass_proxy_by_year || {};
  const ringMedians = can?.reference_buffer_raw_medians || {};

  const primaryChange = can?.canopy_change_pct !== null && can?.canopy_change_pct !== undefined ? `${fmt(can.canopy_change_pct, 1)}%` : copy.missing_value;
  let rangeStr = copy.missing_value;
  if (can?.canopy_change_grid_range && Array.isArray(can.canopy_change_grid_range) && can.canopy_change_grid_range.length === 2) {
    rangeStr = `${fmt(can.canopy_change_grid_range[0], 1)}% – ${fmt(can.canopy_change_grid_range[1], 1)}%`;
  }
  const bioChange = can?.biomass_proxy_change_pct !== null && can?.biomass_proxy_change_pct !== undefined ? `${fmt(can.biomass_proxy_change_pct, 1)}%` : copy.missing_value;

  const endYear = can?.end_year || (can?.years && can.years.length > 0 ? can.years[can.years.length - 1] : "");
  const shareVal = can?.saturation_share_pct !== null && can?.saturation_share_pct !== undefined ? fmt(can.saturation_share_pct, 1) : "";
  const satLabelTemplate = canCopy?.stats?.saturation_share || canCopy?.saturation_note || "";
  const satLabel = satLabelTemplate
    .replace("{end_year}", endYear)
    .replace("{year}", endYear)
    .replace("{share}", shareVal);

  let satDisplayVal = copy.missing_value;
  if (can?.saturation_pixel_count !== null && can?.saturation_pixel_count !== undefined && can?.saturation_total_count !== null && can?.saturation_total_count !== undefined) {
    const tmpl = canCopy?.saturation_count_template;
    satDisplayVal = tmpl ? tmpl.replace("{n}", fmt(can.saturation_pixel_count, 0)).replace("{N}", fmt(can.saturation_total_count, 0)) : copy.missing_value;
  } else if (can?.saturation_share_pct !== null && can?.saturation_share_pct !== undefined) {
    satDisplayVal = `${fmt(can.saturation_share_pct, 1)}%`;
  }

  let tableHeaderCols = "";
  years.forEach((yr) => {
    tableHeaderCols += `
      <th class="py-2.5 px-3 text-right font-medium">${yr} ${copy.units?.ha || copy.missing_value}</th>
      <th class="py-2.5 px-3 text-right font-medium">${yr} ${canCopy?.share_suffix || copy.missing_value}</th>
    `;
  });

  let tableRows = "";
  if (thresholds.length > 0 && years.length > 0) {
    thresholds.forEach((t) => {
      let cells = "";
      years.forEach((yr) => {
        const cell = tbl[t]?.[yr];
        const aVal = cell?.area_ha !== null && cell?.area_ha !== undefined ? fmt(cell.area_ha, 1) : copy.missing_value;
        const sVal = cell?.share_pct !== null && cell?.share_pct !== undefined ? `${fmt(cell.share_pct, 1)}%` : copy.missing_value;
        cells += `
          <td class="py-2.5 px-3 text-right font-mono text-xs text-on-surface">${aVal}</td>
          <td class="py-2.5 px-3 text-right font-mono text-xs text-secondary">${sVal}</td>
        `;
      });
      tableRows += `
        <tr class="border-b border-outline-variant/40 hover:bg-surface-high/50">
          <td class="py-2.5 px-3 font-mono font-semibold text-xs text-primary">${t}</td>
          ${cells}
        </tr>
      `;
    });
  } else {
    tableRows = `
      <tr>
        <td colspan="${1 + years.length * 2}" class="py-4 text-center text-xs text-outline">${copy.missing_value}</td>
      </tr>
    `;
  }

  const barChartSvg = renderCanopyBarSVG(tbl, primaryT, years);
  const lineChartSvg = renderBiomassLineSVG(bioByYr, years);

  let ringRows = "";
  if (years.length > 0 && Object.keys(ringMedians).length > 0) {
    ringRows = years.map((yr) => {
      const v = ringMedians[yr] !== null && ringMedians[yr] !== undefined ? fmt(ringMedians[yr], 4) : copy.missing_value;
      return `
        <div class="p-3 rounded-lg bg-surface-high border border-outline-variant/50 flex flex-col items-center flex-1 min-w-[90px]">
          <span class="text-xs text-outline font-mono mb-1">${yr}</span>
          <span class="text-sm font-bold font-mono text-tertiary">${v}</span>
        </div>
      `;
    }).join("");
  } else {
    ringRows = `<div class="text-xs text-outline">${copy.missing_value}</div>`;
  }
  const ringChangeStr = can?.reference_buffer_change_pct !== null && can?.reference_buffer_change_pct !== undefined ? `${fmt(can.reference_buffer_change_pct, 1)}%` : copy.missing_value;

  const notesList = [];
  if (can?.claimed_canopy_change_pct === null || can?.claimed_canopy_change_pct === undefined) {
    if (canCopy?.unscored_note) {
      notesList.push(canCopy.unscored_note);
    }
  }
  if (can?.baseline_year && canCopy?.pre_baseline_note) {
    notesList.push(canCopy.pre_baseline_note.replace("{baseline_year}", can.baseline_year));
  }
  if (Array.isArray(canCopy?.notes)) {
    canCopy.notes.forEach((n) => notesList.push(n));
  }
  if (can?.saturation_share_pct !== null && can?.saturation_share_pct !== undefined && canCopy?.saturation_note) {
    notesList.push(
      canCopy.saturation_note
        .replace("{end_year}", endYear)
        .replace("{year}", endYear)
        .replace("{share}", shareVal)
    );
  }
  const notesHtml = notesList.map((note) => `
    <li class="flex items-start gap-2">
      <span class="text-secondary select-none">&bull;</span>
      <span>${note}</span>
    </li>
  `).join("");

  const barTitleTemplate = canCopy?.chart_bar_title || copy.missing_value;
  const barTitle = barTitleTemplate.replace("{t}", primaryT !== null && primaryT !== undefined ? primaryT : copy.missing_value);

  container.innerHTML = `
    <div class="space-y-6">
      <div class="flex flex-col gap-1">
        <h2 class="text-2xl font-bold tracking-tight text-on-surface">${canCopy?.title || copy.missing_value}</h2>
        <p class="text-sm text-on-surface-variant">${canCopy?.subtitle || copy.missing_value}</p>
      </div>

      <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div class="p-4 rounded-xl bg-surface-container border border-outline-variant">
          <div class="text-xs uppercase tracking-wider text-outline mb-1 font-semibold">${canCopy?.stats?.change_primary || copy.missing_value}</div>
          <div class="text-2xl font-bold font-mono text-primary">${primaryChange}</div>
        </div>
        <div class="p-4 rounded-xl bg-surface-container border border-outline-variant">
          <div class="text-xs uppercase tracking-wider text-outline mb-1 font-semibold">${canCopy?.stats?.change_range || copy.missing_value}</div>
          <div class="text-lg font-bold font-mono text-on-surface">${rangeStr}</div>
        </div>
        <div class="p-4 rounded-xl bg-surface-container border border-outline-variant">
          <div class="text-xs uppercase tracking-wider text-outline mb-1 font-semibold">${canCopy?.stats?.biomass_change || copy.missing_value}</div>
          <div class="text-2xl font-bold font-mono text-tertiary">${bioChange}</div>
        </div>
        <div class="p-4 rounded-xl bg-surface-container border border-outline-variant">
          <div class="text-xs uppercase tracking-wider text-outline mb-1 font-semibold">${satLabel}</div>
          <div class="text-2xl font-bold font-mono text-secondary">${satDisplayVal}</div>
        </div>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <div class="mb-3">
          <h3 class="text-base font-bold text-on-surface">${canCopy?.table_title || copy.missing_value}</h3>
          <p class="text-xs text-on-surface-variant">${canCopy?.table_desc || copy.missing_value}</p>
        </div>
        <div class="overflow-x-auto w-full">
          <table class="min-w-full text-left">
            <thead>
              <tr class="border-b border-outline-variant text-xs text-outline uppercase font-semibold">
                <th class="py-2.5 px-3">${canCopy?.threshold_col || copy.missing_value}</th>
                ${tableHeaderCols}
              </tr>
            </thead>
            <tbody>
              ${tableRows}
            </tbody>
          </table>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div class="p-5 rounded-xl bg-surface-container border border-outline-variant flex flex-col">
          <div class="mb-3">
            <h3 class="text-base font-bold text-on-surface">${barTitle}</h3>
            <p class="text-xs text-on-surface-variant">${canCopy?.chart_bar_subtitle || copy.missing_value}</p>
          </div>
          <div class="w-full overflow-x-auto flex-1 flex items-center justify-center">
            ${barChartSvg}
          </div>
        </div>

        <div class="p-5 rounded-xl bg-surface-container border border-outline-variant flex flex-col">
          <div class="flex items-center justify-between gap-2 mb-3">
            <div>
              <h3 class="text-base font-bold text-on-surface">${canCopy?.chart_line_title || copy.missing_value}</h3>
              <p class="text-xs text-on-surface-variant">${canCopy?.chart_line_subtitle || copy.missing_value}</p>
            </div>
            <div class="flex items-center gap-3 text-xs">
              <div class="flex items-center space-x-1.5">
                <span class="w-2.5 h-2.5 rounded-full bg-[#5af0b3] inline-block"></span>
                <span class="text-on-surface-variant">${canCopy?.chart_legend?.mean_ndvi || copy.missing_value}</span>
              </div>
              <div class="flex items-center space-x-1.5">
                <span class="w-2.5 h-2.5 rounded-full bg-[#8ad0ea] inline-block"></span>
                <span class="text-on-surface-variant">${canCopy?.chart_legend?.p90_ndvi || copy.missing_value}</span>
              </div>
            </div>
          </div>
          <div class="w-full overflow-x-auto flex-1 flex items-center justify-center">
            ${lineChartSvg}
          </div>
        </div>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <div class="flex flex-col md:flex-row md:items-center justify-between gap-2 mb-3">
          <div>
            <h3 class="text-base font-bold text-on-surface">${canCopy?.reference_title || copy.missing_value}</h3>
            <p class="text-xs text-outline italic">${canCopy?.reference_label || copy.missing_value}</p>
          </div>
          <div class="text-xs font-mono text-on-surface-variant">
            <span>${canCopy?.reference_change || copy.missing_value}: </span>
            <span class="font-bold text-tertiary">${ringChangeStr}</span>
          </div>
        </div>
        <div class="flex flex-wrap gap-3">
          ${ringRows}
        </div>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <h3 class="text-base font-bold text-on-surface mb-3">${canCopy?.notes_title || copy.missing_value}</h3>
        <ul class="text-xs text-on-surface-variant space-y-2 leading-relaxed">
          ${notesHtml}
        </ul>
      </div>
    </div>
  `;
}

function renderCanopyBarSVG(tbl, primaryT, years) {
  if (!tbl || !primaryT || !years || years.length === 0 || !tbl[primaryT]) {
    return `<div class="text-center py-12 text-xs text-outline">${copy.missing_value}</div>`;
  }

  const items = [];
  years.forEach((yr) => {
    const a = tbl[primaryT]?.[yr]?.area_ha;
    if (a !== null && a !== undefined) {
      items.push({ year: yr, area: a });
    }
  });

  if (items.length === 0) {
    return `<div class="text-center py-12 text-xs text-outline">${copy.missing_value}</div>`;
  }

  const svgW = 420, svgH = 220;
  const padL = 50, padR = 25, padT = 30, padB = 35;

  const maxArea = Math.max(...items.map((i) => i.area)) * 1.15;
  const scaleY = (v) => svgH - padB - (v / maxArea) * (svgH - padT - padB);

  const yTicks = 4;
  let yAxisHtml = "";
  for (let i = 0; i <= yTicks; i++) {
    const val = (i / yTicks) * maxArea;
    const y = scaleY(val);
    yAxisHtml += `
      <line x1="${padL}" y1="${y}" x2="${svgW - padR}" y2="${y}" stroke="#262b2a" stroke-dasharray="3,3" />
      <text x="${padL - 8}" y="${y + 4}" text-anchor="end" font-size="10" fill="#88938c" font-family="monospace">${val.toFixed(0)}</text>
    `;
  }

  const availW = svgW - padL - padR;
  const barW = Math.min(48, (availW / items.length) * 0.55);
  let barsHtml = "";

  items.forEach((item, idx) => {
    const cx = padL + ((idx + 0.5) / items.length) * availW;
    const x = cx - barW / 2;
    const y = scaleY(item.area);
    const h = (svgH - padB) - y;
    barsHtml += `
      <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" fill="#5af0b3" rx="3" />
      <text x="${cx.toFixed(1)}" y="${y - 6}" text-anchor="middle" font-size="10" fill="#dee4e0" font-family="monospace">${fmt(item.area, 0)} ${copy.units?.ha || copy.missing_value}</text>
      <text x="${cx.toFixed(1)}" y="${svgH - padB + 18}" text-anchor="middle" font-size="10" fill="#88938c" font-family="monospace">${item.year}</text>
    `;
  });

  return `
    <svg viewBox="0 0 ${svgW} ${svgH}" class="w-full h-auto max-h-[220px] select-none">
      ${yAxisHtml}
      <line x1="${padL}" y1="${svgH - padB}" x2="${svgW - padR}" y2="${svgH - padB}" stroke="#3c4a42" />
      ${barsHtml}
    </svg>
  `;
}

function renderBiomassLineSVG(bioByYr, years) {
  if (!bioByYr || !years || years.length === 0) {
    return `<div class="text-center py-12 text-xs text-outline">${copy.missing_value}</div>`;
  }

  const items = [];
  years.forEach((yr) => {
    const mean = bioByYr[yr]?.mean;
    const p90 = bioByYr[yr]?.p90;
    if (mean !== null && mean !== undefined && p90 !== null && p90 !== undefined) {
      items.push({ year: yr, mean, p90 });
    }
  });

  if (items.length < 2) {
    return `<div class="text-center py-12 text-xs text-outline">${copy.missing_value}</div>`;
  }

  const svgW = 420, svgH = 220;
  const padL = 45, padR = 25, padT = 25, padB = 35;

  let yMin = 0.5, yMax = 1.0;
  const allVals = [];
  items.forEach((it) => {
    allVals.push(it.mean, it.p90);
  });
  if (allVals.length > 0) {
    const rawMin = Math.min(...allVals);
    const rawMax = Math.max(...allVals);
    yMin = Math.max(0.0, Math.floor((rawMin - 0.05) * 10) / 10);
    yMax = Math.min(1.0, Math.ceil((rawMax + 0.05) * 10) / 10);
  }
  if (yMin >= yMax) {
    yMin = 0.0;
    yMax = 1.0;
  }

  const scaleY = (v) => svgH - padB - ((v - yMin) / (yMax - yMin)) * (svgH - padT - padB);
  const availW = svgW - padL - padR;

  const yTicks = 4;
  let yAxisHtml = "";
  for (let i = 0; i <= yTicks; i++) {
    const val = yMin + (i / yTicks) * (yMax - yMin);
    const y = scaleY(val);
    yAxisHtml += `
      <line x1="${padL}" y1="${y}" x2="${svgW - padR}" y2="${y}" stroke="#262b2a" stroke-dasharray="3,3" />
      <text x="${padL - 8}" y="${y + 4}" text-anchor="end" font-size="10" fill="#88938c" font-family="monospace">${val.toFixed(2)}</text>
    `;
  }

  let meanPath = "";
  let p90Path = "";
  let markersHtml = "";
  let xAxisHtml = "";

  items.forEach((it, idx) => {
    const x = padL + ((idx + 0.5) / items.length) * availW;
    const yMean = scaleY(it.mean);
    const yP90 = scaleY(it.p90);

    meanPath += idx === 0 ? `M ${x.toFixed(1)} ${yMean.toFixed(1)}` : ` L ${x.toFixed(1)} ${yMean.toFixed(1)}`;
    p90Path += idx === 0 ? `M ${x.toFixed(1)} ${yP90.toFixed(1)}` : ` L ${x.toFixed(1)} ${yP90.toFixed(1)}`;

    markersHtml += `
      <circle cx="${x.toFixed(1)}" cy="${yMean.toFixed(1)}" r="3" fill="#5af0b3" />
      <circle cx="${x.toFixed(1)}" cy="${yP90.toFixed(1)}" r="3" fill="#8ad0ea" />
    `;

    xAxisHtml += `
      <line x1="${x.toFixed(1)}" y1="${svgH - padB}" x2="${x.toFixed(1)}" y2="${svgH - padB + 5}" stroke="#3c4a42" />
      <text x="${x.toFixed(1)}" y="${svgH - padB + 18}" text-anchor="middle" font-size="10" fill="#88938c" font-family="monospace">${it.year}</text>
    `;
  });

  return `
    <svg viewBox="0 0 ${svgW} ${svgH}" class="w-full h-auto max-h-[220px] select-none">
      ${yAxisHtml}
      <line x1="${padL}" y1="${svgH - padB}" x2="${svgW - padR}" y2="${svgH - padB}" stroke="#3c4a42" />
      ${xAxisHtml}
      <path d="${p90Path}" fill="none" stroke="#8ad0ea" stroke-width="2" />
      <path d="${meanPath}" fill="none" stroke="#5af0b3" stroke-width="2" />
      ${markersHtml}
    </svg>
  `;
}

// 10. Limitations and Provenance View
function renderLimitations(container) {
  const d = projectData;
  const lim = d.limitations;
  const limCopy = copy.limitations;

  const limitationsList = lim?.limitations || [];
  const fileHashes = lim?.file_hashes || {};
  const extractor = lim?.extractor;
  const pdfSha = lim?.pdf_sha256;
  const pdfDoc = lim?.pdf_sha256_document;
  const imagerySrc = lim?.imagery_source;
  const hansenHashes = lim?.hansen_file_hashes;
  const sourceNotes = lim?.source_notes || [];
  const thresh = lim?.thresholds;

  let limItemsHtml = "";
  if (limitationsList && limitationsList.length > 0) {
    limItemsHtml = limitationsList.map((item, idx) => {
      const numStr = String(idx + 1).padStart(2, "0");
      return `
        <div class="flex items-start gap-4 p-4 rounded-lg bg-surface-container-high/40 border border-outline-variant/30">
          <span class="px-2 py-0.5 rounded bg-surface-high text-xs font-mono font-bold text-tertiary select-none">${numStr}</span>
          <p class="text-xs text-on-surface leading-relaxed flex-1">${item}</p>
        </div>
      `;
    }).join("");
  } else {
    limItemsHtml = `<div class="p-4 text-xs text-outline text-center">${copy.missing_value}</div>`;
  }

  const methodLimitationsList = Array.isArray(limCopy?.method_limitations) ? limCopy.method_limitations : [];
  let methodLimHtml = "";
  if (methodLimitationsList.length > 0) {
    methodLimHtml = methodLimitationsList.map((item, idx) => {
      const numStr = String(idx + 1).padStart(2, "0");
      return `
        <div class="flex items-start gap-4 p-4 rounded-lg bg-surface-container-high/40 border border-outline-variant/30">
          <span class="px-2 py-0.5 rounded bg-surface-high text-xs font-mono font-bold text-tertiary select-none">${numStr}</span>
          <p class="text-xs text-on-surface leading-relaxed flex-1">${item}</p>
        </div>
      `;
    }).join("");
  } else {
    methodLimHtml = `<div class="p-4 text-xs text-outline text-center">${copy.missing_value}</div>`;
  }

  let hashRows = "";
  if (fileHashes && Object.keys(fileHashes).length > 0) {
    hashRows = Object.entries(fileHashes).map(([fname, fhash]) => {
      return `
        <tr class="border-b border-outline-variant/30 hover:bg-surface-high/40">
          <td class="py-2.5 px-3 font-mono text-xs font-semibold text-on-surface whitespace-nowrap">${fname}</td>
          <td class="py-2.5 px-3 font-mono text-xs text-secondary break-all select-all">${fhash}</td>
          <td class="py-2.5 px-3 text-right whitespace-nowrap">
            <button class="copy-hash-btn px-2.5 py-1 text-xs rounded bg-surface-high hover:bg-surface-highest border border-outline-variant text-on-surface transition-colors" data-hash="${fhash}">
              ${limCopy?.copy_btn || copy.missing_value}
            </button>
          </td>
        </tr>
      `;
    }).join("");
  } else {
    hashRows = `
      <tr>
        <td colspan="3" class="py-4 text-center text-xs text-outline">${copy.missing_value}</td>
      </tr>
    `;
  }

  let hansenRows = "";
  if (hansenHashes && Object.keys(hansenHashes).length > 0) {
    hansenRows = Object.entries(hansenHashes).map(([hname, hhash]) => {
      return `
        <tr class="border-b border-outline-variant/30 hover:bg-surface-high/40">
          <td class="py-2.5 px-3 font-mono text-xs font-semibold text-on-surface whitespace-nowrap">${hname}</td>
          <td class="py-2.5 px-3 font-mono text-xs text-secondary break-all select-all">${hhash}</td>
          <td class="py-2.5 px-3 text-right whitespace-nowrap">
            <button class="copy-hash-btn px-2.5 py-1 text-xs rounded bg-surface-high hover:bg-surface-highest border border-outline-variant text-on-surface transition-colors" data-hash="${hhash}">
              ${limCopy?.copy_btn || copy.missing_value}
            </button>
          </td>
        </tr>
      `;
    }).join("");
  } else {
    hansenRows = `
      <tr>
        <td colspan="3" class="py-4 text-center text-xs text-outline">${copy.missing_value}</td>
      </tr>
    `;
  }

  let notesHtml = "";
  if (sourceNotes && sourceNotes.length > 0) {
    notesHtml = sourceNotes.map((sn) => `
      <div class="p-3 rounded-lg bg-surface-high border border-outline-variant/40 text-xs text-on-surface leading-relaxed">
        ${sn}
      </div>
    `).join("");
  } else {
    notesHtml = `<div class="text-xs text-outline">${copy.missing_value}</div>`;
  }

  let gridTStr = copy.missing_value;
  if (thresh?.grid_thresholds && Array.isArray(thresh.grid_thresholds)) {
    gridTStr = thresh.grid_thresholds.map((t) => fmt(t, 2)).join(", ");
  }

  container.innerHTML = `
    <div class="space-y-6">
      <div class="flex flex-col gap-1">
        <h2 class="text-2xl font-bold tracking-tight text-on-surface">${limCopy?.title || copy.missing_value}</h2>
        <p class="text-sm text-on-surface-variant">${limCopy?.subtitle || copy.missing_value}</p>
      </div>

      <div class="p-3.5 rounded-xl bg-surface-container border border-outline-variant flex items-center gap-3">
        <span class="text-secondary text-base select-none">ℹ️</span>
        <p class="text-xs text-on-surface-variant leading-relaxed">
          ${limCopy?.registry_pdf_notice || copy.missing_value}
        </p>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <div class="mb-4">
          <h3 class="text-base font-bold text-on-surface">${limCopy?.caveats_title || copy.missing_value}</h3>
          <p class="text-xs text-on-surface-variant mt-0.5">${limCopy?.caveats_desc || copy.missing_value}</p>
        </div>
        <div class="space-y-2.5">
          ${limItemsHtml}
        </div>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <div class="mb-4">
          <h3 class="text-base font-bold text-on-surface">${limCopy?.method_limitations_title || copy.missing_value}</h3>
          <p class="text-xs text-on-surface-variant mt-0.5">${limCopy?.method_limitations_desc || copy.missing_value}</p>
        </div>
        <div class="space-y-2.5">
          ${methodLimHtml}
        </div>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <div class="mb-3">
          <h3 class="text-base font-bold text-on-surface">${limCopy?.hashes_title || copy.missing_value}</h3>
          <p class="text-xs text-on-surface-variant">${limCopy?.hashes_desc || copy.missing_value}</p>
        </div>
        <div class="overflow-x-auto w-full border border-outline-variant rounded-lg">
          <table class="min-w-full text-left">
            <thead>
              <tr class="border-b border-outline-variant bg-surface-high text-xs text-outline uppercase font-semibold">
                <th class="py-2.5 px-3">${limCopy?.hashes_cols?.file || copy.missing_value}</th>
                <th class="py-2.5 px-3">${limCopy?.hashes_cols?.hash || copy.missing_value}</th>
                <th class="py-2.5 px-3 text-right">${limCopy?.hashes_cols?.action || copy.missing_value}</th>
              </tr>
            </thead>
            <tbody>
              ${hashRows}
            </tbody>
          </table>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div class="p-5 rounded-xl bg-surface-container border border-outline-variant space-y-4">
          <div>
            <h3 class="text-base font-bold text-on-surface mb-1">${limCopy?.provenance_title || copy.missing_value}</h3>
          </div>
          <div class="space-y-3 text-xs">
            <div>
              <div class="text-outline uppercase font-semibold mb-0.5">${limCopy?.extractor_label || copy.missing_value}</div>
              <div class="font-mono text-on-surface">${extractor || copy.missing_value}</div>
            </div>
            <div>
              <div class="text-outline uppercase font-semibold mb-0.5">${pdfDoc ? (limCopy?.pdf_sha_label || copy.missing_value) : (limCopy?.pdf_sha_unrecorded_label || limCopy?.pdf_sha_label || copy.missing_value)}</div>
              <div class="font-mono text-secondary break-all select-all">${pdfSha ? (pdfDoc ? `${pdfSha} (${pdfDoc})` : pdfSha) : copy.missing_value}</div>
            </div>
            <div>
              <div class="text-outline uppercase font-semibold mb-0.5">${limCopy?.imagery_source_label || copy.missing_value}</div>
              <div class="text-on-surface">${imagerySrc || copy.missing_value}</div>
            </div>
          </div>
        </div>

        <div class="p-5 rounded-xl bg-surface-container border border-outline-variant space-y-4">
          <div>
            <h3 class="text-base font-bold text-on-surface mb-1">${limCopy?.thresholds_label || copy.missing_value}</h3>
          </div>
          <div class="space-y-3 text-xs">
            <div>
              <div class="text-outline uppercase font-semibold mb-0.5">${limCopy?.threshold_minor || copy.missing_value}</div>
              <div class="font-mono font-bold text-on-surface">${thresh?.minor_discrepancy_pct !== null && thresh?.minor_discrepancy_pct !== undefined ? `${fmt(thresh.minor_discrepancy_pct, 1)}%` : copy.missing_value}</div>
            </div>
            <div>
              <div class="text-outline uppercase font-semibold mb-0.5">${limCopy?.threshold_major || copy.missing_value}</div>
              <div class="font-mono font-bold text-on-surface">${thresh?.major_discrepancy_pct !== null && thresh?.major_discrepancy_pct !== undefined ? `${fmt(thresh.major_discrepancy_pct, 1)}%` : copy.missing_value}</div>
            </div>
            <div>
              <div class="text-outline uppercase font-semibold mb-0.5">${limCopy?.grid_thresholds_label || copy.missing_value}</div>
              <div class="font-mono text-primary">${gridTStr}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <div class="mb-3">
          <h3 class="text-base font-bold text-on-surface">${limCopy?.hansen_title || copy.missing_value}</h3>
          <p class="text-xs text-on-surface-variant">${limCopy?.hansen_desc || copy.missing_value}</p>
        </div>
        <div class="overflow-x-auto w-full border border-outline-variant rounded-lg">
          <table class="min-w-full text-left">
            <thead>
              <tr class="border-b border-outline-variant bg-surface-high text-xs text-outline uppercase font-semibold">
                <th class="py-2.5 px-3">${limCopy?.hashes_cols?.file || copy.missing_value}</th>
                <th class="py-2.5 px-3">${limCopy?.hashes_cols?.hash || copy.missing_value}</th>
                <th class="py-2.5 px-3 text-right">${limCopy?.hashes_cols?.action || copy.missing_value}</th>
              </tr>
            </thead>
            <tbody>
              ${hansenRows}
            </tbody>
          </table>
        </div>
      </div>

      <div class="p-5 rounded-xl bg-surface-container border border-outline-variant">
        <div class="mb-3">
          <h3 class="text-base font-bold text-on-surface">${limCopy?.source_notes_title || copy.missing_value}</h3>
          <p class="text-xs text-on-surface-variant">${limCopy?.source_notes_desc || copy.missing_value}</p>
        </div>
        <div class="space-y-2">
          ${notesHtml}
        </div>
      </div>
    </div>
  `;

  container.querySelectorAll(".copy-hash-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const hash = btn.getAttribute("data-hash");
      if (hash && navigator.clipboard) {
        navigator.clipboard.writeText(hash).then(() => {
          const original = btn.textContent;
          btn.textContent = limCopy?.copied_btn || copy.missing_value;
          setTimeout(() => {
            btn.textContent = original;
          }, 2000);
        }).catch((err) => {
          console.error("Failed to copy hash:", err);
        });
      }
    });
  });
}

// 11. Evidence Drawer Functions
function setupEvidenceDrawer() {
  const backdrop = document.getElementById("evidence-drawer-backdrop");
  const closeBtn = document.getElementById("drawer-close-btn");
  const closeAction = document.getElementById("drawer-close-action");

  function closeDrawer() {
    if (backdrop) backdrop.classList.add("hidden");
  }

  if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
  if (closeAction) closeAction.addEventListener("click", closeDrawer);
  if (backdrop) {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeDrawer();
    });
  }
}

function openEvidenceDrawer(doc, page, quote) {
  const backdrop = document.getElementById("evidence-drawer-backdrop");
  const docEl = document.getElementById("drawer-doc-name");
  const pageEl = document.getElementById("drawer-doc-page");
  const quoteEl = document.getElementById("drawer-doc-quote");

  if (docEl) docEl.textContent = doc || copy.missing_value;
  if (pageEl) pageEl.textContent = page || copy.missing_value;
  if (quoteEl) quoteEl.textContent = quote || copy.missing_value;

  if (backdrop) backdrop.classList.remove("hidden");
}

function escapeQuotes(str) {
  if (!str) return "";
  return String(str).replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// Boot application on DOM ready
document.addEventListener("DOMContentLoaded", init);
