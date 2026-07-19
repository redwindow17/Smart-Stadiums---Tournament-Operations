/* StadiumIQ operations dashboard - dependency-free, CSP-safe.
   Zone meters are rendered via CSSOM (el.style.width), all text via
   textContent, so no markup injection is possible. */
"use strict";

const $ = (id) => document.getElementById(id);
const REFRESH_MS = 15000;
let venueId = null;
let timer = null;

async function fetchJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* keep statusText */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ------------------------------ setup ---------------------------------- */

async function loadVenues() {
  const data = await fetchJSON("/api/venues");
  const select = $("venue-select");
  select.replaceChildren();
  for (const venue of data.venues) {
    const opt = document.createElement("option");
    opt.value = venue.id;
    opt.textContent = `${venue.name} - ${venue.city}`;
    select.append(opt);
  }
  await switchVenue(select.value);
}

async function switchVenue(id) {
  venueId = id;
  const venue = await fetchJSON(`/api/venues/${encodeURIComponent(id)}`);
  const zoneSelect = $("incident-zone");
  zoneSelect.replaceChildren();
  for (const zone of venue.zones) {
    const opt = document.createElement("option");
    opt.value = zone.id;
    opt.textContent = zone.name;
    zoneSelect.append(opt);
  }
  await Promise.all([refreshDashboard(), refreshIncidents()]);
  if (timer) clearInterval(timer);
  timer = setInterval(refreshDashboard, REFRESH_MS);
}

/* ---------------------------- dashboard --------------------------------- */

async function refreshDashboard() {
  if (!venueId) return;
  const data = await fetchJSON(`/api/ops/advisory?venue_id=${encodeURIComponent(venueId)}`);
  const snap = data.snapshot;

  $("phase-note").textContent =
    `Phase: ${snap.phase} - snapshot ${new Date(snap.generated_at).toLocaleTimeString()}` +
    ` - brief by the ${data.engine} engine`;

  const list = $("zone-list");
  list.replaceChildren();
  for (const zone of snap.zones) {
    const row = document.createElement("div");
    row.className = "zone-row";

    const name = document.createElement("span");
    name.className = "zone-name";
    name.textContent = zone.zone_name;

    const pct = Math.round(zone.density * 100);
    const meter = document.createElement("div");
    meter.className = "meter";
    meter.setAttribute("role", "img");
    meter.setAttribute("aria-label", `${zone.zone_name}: ${pct}% density, ${zone.level}, ${zone.trend}`);
    const fill = document.createElement("div");
    fill.className = `meter-fill ${zone.level}`;
    fill.style.width = `${pct}%`;
    meter.append(fill);

    const badge = document.createElement("span");
    badge.className = `badge ${zone.level}`;
    badge.textContent = `${pct}% ${zone.level}`;

    row.append(name, meter, badge);
    list.append(row);
  }

  $("brief").textContent = data.brief;

  const recs = $("recommendations");
  recs.replaceChildren();
  for (const rec of data.recommendations) {
    const li = document.createElement("li");
    const strong = document.createElement("strong");
    strong.textContent = `[${rec.priority}] `;
    const span = document.createElement("span");
    span.textContent = rec.action;
    const reason = document.createElement("span");
    reason.className = "reason";
    reason.textContent = rec.reason;
    li.append(strong, span, reason);
    recs.append(li);
  }
}

/* ---------------------------- incidents --------------------------------- */

async function refreshIncidents() {
  if (!venueId) return;
  const data = await fetchJSON(`/api/ops/incidents?venue_id=${encodeURIComponent(venueId)}`);
  const list = $("incident-list");
  list.replaceChildren();
  if (!data.incidents.length) {
    const li = document.createElement("li");
    li.textContent = "No incidents reported for this venue yet.";
    list.append(li);
    return;
  }
  for (const inc of data.incidents) {
    const li = document.createElement("li");
    const badge = document.createElement("span");
    badge.className = `badge ${inc.priority}`;
    badge.textContent = inc.priority.toUpperCase();
    const title = document.createElement("strong");
    title.textContent = ` #${inc.id} ${inc.category.replace("_", " ")} - ${inc.zone_name}`;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `${inc.description} | Actions: ${inc.actions.join("; ")}`;
    li.append(badge, title, meta);
    list.append(li);
  }
}

async function submitIncident(event) {
  event.preventDefault();
  const status = $("incident-status");
  const severityRaw = $("incident-severity").value;
  const payload = {
    venue_id: venueId,
    zone_id: $("incident-zone").value,
    category: $("incident-category").value,
    description: $("incident-description").value.trim(),
    severity: severityRaw ? Number(severityRaw) : null,
  };
  try {
    const data = await fetchJSON("/api/ops/incidents", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    status.textContent =
      `Triaged as ${data.incident.priority.toUpperCase()} - ${data.incident.actions.length} action(s) dispatched.`;
    $("incident-description").value = "";
    $("incident-severity").value = "";
    await refreshIncidents();
  } catch (err) {
    status.textContent = `Could not submit: ${err.message}`;
  }
}

/* ------------------------------ wiring ---------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
  loadVenues().catch((err) => { $("phase-note").textContent = `Could not load venues: ${err.message}`; });
  $("venue-select").addEventListener("change", (e) => switchVenue(e.target.value));
  $("refresh-btn").addEventListener("click", () => { refreshDashboard(); refreshIncidents(); });
  $("incident-form").addEventListener("submit", submitIncident);
});
