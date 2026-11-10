let selectedId = null;
let source = null;
let pollTimer = null;
let seenEvents = new Set();

const $ = (id) => document.getElementById(id);

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text; // textContent, so log text can never inject HTML
  return node;
}

function statusClass(status) {
  if (status === "resolved" || status === "closed_no_action") return "ok";
  if (status === "awaiting_approval") return "warn";
  if (status === "escalated") return "bad";
  return "info";
}

function severityClass(sev) {
  return sev === "critical" ? "bad" : sev === "high" ? "warn" : "info";
}

function pretty(s) {
  return (s || "").replace(/_/g, " ");
}

function ago(iso) {
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return sec + "s ago";
  if (sec < 3600) return Math.round(sec / 60) + "m ago";
  return Math.round(sec / 3600) + "h ago";
}

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error(path + " -> " + res.status);
  return res;
}

// ---------------------------------------------------------------- scenarios
async function loadScenarios() {
  const list = await (await api("/dev/scenarios")).json();
  const select = $("scenario");
  list.forEach((s) => {
    const opt = el("option", "", s.name + ": " + s.description);
    opt.value = s.name;
    select.appendChild(opt);
  });
}

$("break").onclick = async () => {
  const button = $("break");
  button.disabled = true;
  try {
    const res = await (await api("/dev/scenarios/" + $("scenario").value, { method: "POST" })).json();
    await refreshList();
    selectIncident(res.incident_id);
  } catch (e) {
    alert("Could not start the scenario: " + e.message);
  } finally {
    button.disabled = false;
  }
};

// ---------------------------------------------------------------- list
async function refreshList() {
  const incidents = await (await api("/incidents")).json();
  const ul = $("list");
  ul.replaceChildren();
  $("empty").hidden = incidents.length > 0;
  incidents.forEach((inc) => {
    const li = el("li", inc.id === selectedId ? "active" : "");
    li.appendChild(el("div", "t", inc.title));
    const meta = el("div", "m");
    meta.appendChild(el("span", "muted small", inc.service + " · " + ago(inc.opened_at)));
    meta.appendChild(el("span", "badge " + statusClass(inc.status), pretty(inc.status)));
    li.appendChild(meta);
    li.onclick = () => selectIncident(inc.id);
    ul.appendChild(li);
  });
}

// ---------------------------------------------------------------- detail
function selectIncident(id) {
  selectedId = id;
  seenEvents = new Set();
  $("timeline").replaceChildren();
  $("postmortem-card").hidden = true;
  $("detail").hidden = false;
  if (source) source.close();
  source = new EventSource("/incidents/" + id + "/stream");
  source.onmessage = (e) => addEvent(JSON.parse(e.data));
  refreshDetail();
  refreshList();
}

function addEvent(ev) {
  if (seenEvents.has(ev.id)) return;
  seenEvents.add(ev.id);
  const li = el("li", ev.type === "tool_call" ? "tool" : ev.type);
  li.appendChild(el("span", "time", ev.at.substring(11, 19)));
  li.appendChild(el("span", "agent", ev.agent));
  li.appendChild(el("span", "msg", ev.payload.message || ev.type));
  const box = $("timeline");
  const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  box.appendChild(li);
  if (atBottom) box.scrollTop = box.scrollHeight;
}

async function refreshDetail() {
  if (!selectedId) return;
  const id = selectedId;
  const inc = await (await api("/incidents/" + id)).json();
  if (id !== selectedId) return;

  $("title").textContent = inc.title;
  $("subtitle").textContent = inc.service + " · opened " + ago(inc.opened_at);
  const sev = $("severity");
  sev.textContent = inc.severity;
  sev.className = "badge " + severityClass(inc.severity);
  const st = $("status");
  st.textContent = pretty(inc.status);
  st.className = "badge " + statusClass(inc.status);

  const h = inc.hypothesis;
  if (h) {
    $("cause").textContent = h.cause;
    $("cause").className = "";
    $("confidence").textContent = "Category: " + pretty(h.category) + " · confidence " + Math.round(h.confidence * 100) + "%";
    const ul = $("evidence");
    ul.replaceChildren();
    (h.evidence || []).forEach((e) => ul.appendChild(el("li", "", e)));
  }

  const action = inc.proposed_action;
  const waiting = inc.status === "awaiting_approval" && action;
  $("approval-card").hidden = !waiting;
  if (waiting) {
    $("action-text").textContent = pretty(action.type) + " on " + action.target + (action.version ? " to " + action.version : "");
    $("action-extra").textContent = action.rationale + (action.runbook ? " Runbook: " + action.runbook : "") + " Risk: " + action.risk + ".";
  }

  const done = ["resolved", "closed_no_action", "escalated"].includes(inc.status);
  if (done && $("postmortem-card").hidden) loadPostmortem(id);
}

async function decide(decision) {
  $("approve").disabled = $("reject").disabled = true;
  try {
    await api("/incidents/" + selectedId + "/decision", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, comment: $("comment").value, decided_by: "dashboard" }),
    });
    $("comment").value = "";
  } catch (e) {
    alert("Decision failed: " + e.message);
  } finally {
    $("approve").disabled = $("reject").disabled = false;
    refreshDetail();
  }
}
$("approve").onclick = () => decide("approve");
$("reject").onclick = () => decide("reject");

// ---------------------------------------------------------------- postmortem
async function loadPostmortem(id) {
  try {
    const text = await (await api("/incidents/" + id + "/postmortem")).text();
    if (id !== selectedId) return;
    renderMarkdown($("postmortem"), text);
    $("postmortem-card").hidden = false;
  } catch (e) {
    /* not written yet, the next poll will try again */
  }
}

// tiny markdown renderer: headings, bullets, paragraphs. Everything goes through textContent.
function renderMarkdown(container, md) {
  container.replaceChildren();
  let list = null;
  md.split("\n").forEach((line) => {
    if (line.startsWith("- ")) {
      if (!list) { list = el("ul"); container.appendChild(list); }
      list.appendChild(el("li", "", line.slice(2)));
      return;
    }
    list = null;
    if (line.startsWith("#")) container.appendChild(el("h2", "", line.replace(/^#+\s*/, "")));
    else if (line.trim()) container.appendChild(el("p", "", line));
  });
}

// ---------------------------------------------------------------- start
loadScenarios().then(refreshList);
setInterval(() => { refreshList().catch(() => {}); refreshDetail().catch(() => {}); }, 2500);
