/* StadiumIQ fan assistant - dependency-free, CSP-safe (no inline code).
   All API responses are rendered with textContent, never innerHTML with
   user/AI text, so the UI is XSS-safe by construction. */
"use strict";

const $ = (id) => document.getElementById(id);
const state = { venueId: null, history: [] };

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
  await loadVenueDetail(select.value);
}

async function loadVenueDetail(venueId) {
  const venue = await fetchJSON(`/api/venues/${encodeURIComponent(venueId)}`);
  state.venueId = venue.id;
  state.history = [];
  const select = $("location-select");
  select.replaceChildren();
  for (const zone of venue.zones) {
    const opt = document.createElement("option");
    opt.value = zone.id;
    opt.textContent = zone.name;
    if (zone.id === venue.default_location) opt.selected = true;
    select.append(opt);
  }
  $("chat-log").replaceChildren();
  addMessage("assistant",
    `Welcome to ${venue.name}! Ask me for routes, facilities, transport, crowd levels, ` +
    `accessibility or match info - in English, espanol or francais.`);
}

/* ---------------------------- rendering -------------------------------- */

function addMessage(role, text, lang) {
  const log = $("chat-log");
  const bubble = document.createElement("div");
  bubble.className = `msg msg-${role}`;
  bubble.textContent = text;
  if (lang && lang !== "en") bubble.setAttribute("lang", lang);
  log.append(bubble);
  log.scrollTop = log.scrollHeight;
  return bubble;
}

function card(title) {
  const wrap = document.createElement("div");
  wrap.className = "msg-card";
  const heading = document.createElement("h4");
  heading.textContent = title;
  wrap.append(heading);
  return wrap;
}

function appendDataCards(bubble, data) {
  if (data.route && data.route.steps && data.route.steps.length > 1) {
    const c = card(`Route - ${data.route.total_minutes} min${data.route.accessible ? " (step-free)" : ""}`);
    const list = document.createElement("ol");
    for (const step of data.route.steps) {
      const li = document.createElement("li");
      li.textContent = step.minutes > 0 ? `${step.zone_name} (+${step.minutes} min)` : step.zone_name;
      list.append(li);
    }
    c.append(list);
    bubble.append(c);
  }
  if (data.facilities && data.facilities.length) {
    const c = card("Nearby");
    const list = document.createElement("ul");
    for (const f of data.facilities) {
      const li = document.createElement("li");
      li.textContent = `${f.name} - ${f.minutes} min (${f.zone_name})`;
      list.append(li);
    }
    c.append(list);
    bubble.append(c);
  }
  if (data.crowd && data.crowd.gates) {
    const c = card("Gate status");
    const list = document.createElement("ul");
    for (const gate of data.crowd.gates) {
      const li = document.createElement("li");
      li.textContent = `${gate.name}: ${gate.pct}% (${gate.level}, ${gate.trend})`;
      list.append(li);
    }
    c.append(list);
    bubble.append(c);
  }
  if (data.transport && data.transport.length) {
    const c = card("Transport options");
    const list = document.createElement("ul");
    for (const t of data.transport) {
      const li = document.createElement("li");
      li.textContent = `${t.name}: ${t.detail}`;
      list.append(li);
    }
    c.append(list);
    bubble.append(c);
  }
  if (data.match) {
    const c = card(data.match.status === "live" ? "Live now" : "Next match");
    const p = document.createElement("p");
    p.textContent = `${data.match.stage}: ${data.match.home} vs ${data.match.away} - ${data.match.kickoff}`;
    c.append(p);
    bubble.append(c);
  }
}

/* ------------------------------- chat ----------------------------------- */

async function sendMessage(message) {
  const trimmed = message.trim();
  if (!trimmed || !state.venueId) return;

  addMessage("user", trimmed);
  const sendBtn = $("send-btn");
  const note = $("engine-note");
  sendBtn.disabled = true;
  note.textContent = "StadiumIQ is thinking...";

  const payload = {
    message: trimmed,
    venue_id: state.venueId,
    language: $("language-select").value,
    accessible: $("accessible-toggle").checked,
    location_zone: $("location-select").value || null,
    history: state.history.slice(-12),
  };

  try {
    const result = await fetchJSON("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const bubble = addMessage("assistant", result.reply, result.language);
    appendDataCards(bubble, result.data || {});
    note.textContent = `Answered by the ${result.engine} engine - intent: ${result.intent}`;
    state.history.push({ role: "user", content: trimmed });
    state.history.push({ role: "assistant", content: result.reply });
    state.history = state.history.slice(-12);
  } catch (err) {
    addMessage("error", `Sorry - ${err.message}`);
    note.textContent = "";
  } finally {
    sendBtn.disabled = false;
    $("chat-input").focus();
  }
}

/* ------------------------------ wiring ---------------------------------- */

document.addEventListener("DOMContentLoaded", () => {
  loadVenues().catch((err) => addMessage("error", `Could not load venues: ${err.message}`));

  $("venue-select").addEventListener("change", (e) => {
    loadVenueDetail(e.target.value).catch((err) => addMessage("error", err.message));
  });

  $("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("chat-input");
    const value = input.value;
    input.value = "";
    sendMessage(value);
  });

  for (const chip of document.querySelectorAll(".chip")) {
    chip.addEventListener("click", () => sendMessage(chip.dataset.q));
  }
});
