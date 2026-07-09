# ~/nixos-config/modules/nixos/homelab/article2pod-src/app.py
import os
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, HttpUrl

import db
from feedgen.feed import FeedGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("app")

ADMIN_TOKEN = os.environ["ARTICLE2POD_TOKEN"]
AUDIO_DIR = os.environ.get("ARTICLE2POD_AUDIO", "/mnt/storage/podcasts/audio")
HOSTNAME = os.environ.get("ARTICLE2POD_HOSTNAME", "reader.lan")
TITLE = os.environ.get("ARTICLE2POD_TITLE", "Article Podcast")
AUTHOR = os.environ.get("ARTICLE2POD_AUTHOR", "lando")
DESCRIPTION = os.environ.get("ARTICLE2POD_DESCRIPTION", "Articles converted to audio")
KOKORO_URL = os.environ.get("KOKORO_URL", "http://localhost:8880")
KOKORO_VOICE = os.environ.get("KOKORO_VOICE", "af_heart")

BASE_URL = f"http://{HOSTNAME}"

app = FastAPI(title="article2pod", docs_url=None, redoc_url=None)
security = HTTPBearer(auto_error=False)

db.init_db(admin_token=ADMIN_TOKEN, default_voice=KOKORO_VOICE)


def _verify(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    token = credentials.credentials if credentials else None
    user = db.get_user_by_token(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return dict(user)


def _verify_admin(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> dict:
    token = credentials.credentials if credentials else None
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    user = db.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=500, detail="Admin user not found")
    return dict(user)


class AddRequest(BaseModel):
    url: HttpUrl


class SettingsRequest(BaseModel):
    voice: str


class CreateUserRequest(BaseModel):
    username: str


class ReprocessRequest(BaseModel):
    voice: str


# ─────────────────────────────────────────────────────────────────────────────
# User dashboard template
# ─────────────────────────────────────────────────────────────────────────────

_UI_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>article2pod</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0d1117; color: #c9d1d9; margin: 0; padding: 1.5em; }
  h1 { color: #58a6ff; margin: 0 0 0.2em; font-size: 1.5em; }
  .subtitle { color: #8b949e; font-size: 0.9em; margin-bottom: 1.8em; }
  h2 { font-size: 0.8em; color: #8b949e; text-transform: uppercase; letter-spacing: 0.1em;
       margin: 1.8em 0 0.75em; border-bottom: 1px solid #21262d; padding-bottom: 0.4em; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88em; }
  th { text-align: left; color: #8b949e; font-weight: 500; padding: 0.5em 0.75em;
       border-bottom: 1px solid #21262d; }
  td { padding: 0.65em 0.75em; border-bottom: 1px solid #161b22; vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  .del-btn { background: none; border: none; color: #6e7681; cursor: pointer;
             font-size: 1.1em; padding: 0 0.25em; line-height: 1; }
  .del-btn:hover { color: #f85149; }
  .reprocess-btn { background: none; border: none; color: #6e7681; cursor: pointer;
                   font-size: 1.1em; padding: 0 0.25em; line-height: 1; }
  .reprocess-btn:hover { color: #58a6ff; }
  .badge { display: inline-block; padding: 0.15em 0.55em; border-radius: 1em;
           font-size: 0.78em; font-weight: 600; }
  .badge-done       { background: #0d4429; color: #3fb950; }
  .badge-processing { background: #3d2b00; color: #e3b341; }
  .badge-queued     { background: #0c2d6b; color: #58a6ff; }
  .badge-failed     { background: #3d0000; color: #f85149; }
  .title-link { color: #c9d1d9; text-decoration: none; font-weight: 500; }
  .title-link:hover { color: #58a6ff; }
  .url-text { color: #8b949e; font-size: 0.82em; white-space: nowrap; overflow: hidden;
              text-overflow: ellipsis; max-width: 420px; display: block; }
  .info-cell { color: #8b949e; font-size: 0.85em; white-space: nowrap; }
  .spin { display: inline-block; animation: spin 1.2s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .voice-row { display: flex; gap: 0.75em; align-items: center; flex-wrap: wrap;
               margin-bottom: 0.5em; }
  .submit-row { display: flex; gap: 0.75em; align-items: center; flex-wrap: wrap;
                margin-bottom: 0.5em; }
  select { background: #161b22; color: #c9d1d9; border: 1px solid #30363d;
           padding: 0.4em 0.6em; border-radius: 6px; font-size: 0.9em; min-width: 220px; }
  input[type=url], input[type=text] { background: #161b22; color: #c9d1d9; border: 1px solid #30363d;
                    padding: 0.4em 0.6em; border-radius: 6px; font-size: 0.9em;
                    flex: 1; min-width: 280px; }
  button { background: #238636; color: #fff; border: none; padding: 0.4em 1.1em;
           border-radius: 6px; cursor: pointer; font-size: 0.88em; }
  button:hover { background: #2ea043; }
  button:disabled { background: #21262d; color: #6e7681; cursor: default; }
  .note { color: #6e7681; font-size: 0.82em; }
  .toast { position: fixed; bottom: 1.5em; right: 1.5em; background: #1f6feb; color: #fff;
           padding: 0.6em 1.2em; border-radius: 8px; font-size: 0.88em;
           opacity: 0; transition: opacity 0.3s; pointer-events: none; }
  .toast.show { opacity: 1; }
  .error-text { color: #f85149; font-size: 0.82em; }
  .modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6);
                   z-index:100; align-items:center; justify-content:center; }
  .modal-overlay.show { display:flex; }
  .modal { background:#161b22; border:1px solid #30363d; border-radius:10px;
           padding:1.5em; min-width:300px; max-width:90vw; }
  .modal h3 { margin:0 0 0.9em; color:#c9d1d9; font-size:1em; font-weight:600; }
  .modal select { width:100%; }
  .modal-actions { display:flex; gap:0.75em; margin-top:1.1em; justify-content:flex-end; }
  .btn-cancel { background:none; border:1px solid #30363d; color:#8b949e; }
  .btn-cancel:hover { background:#21262d; color:#c9d1d9; }
</style>
</head>
<body>
<h1>article2pod</h1>
<div class="subtitle" id="counts">Loading...</div>

<h2>Queue</h2>
<table>
  <thead><tr><th>Status</th><th>Article</th><th>Info</th><th></th></tr></thead>
  <tbody id="queue-body"><tr><td colspan="4" style="color:#8b949e">Loading...</td></tr></tbody>
</table>

<h2>Submit Article</h2>
<div class="submit-row">
  <input type="url" id="url-input" placeholder="https://example.com/article" onkeydown="if(event.key==='Enter')submitUrl()" />
  <button onclick="submitUrl()">Queue</button>
</div>
<p id="submit-status" class="note"></p>

<h2>Voice</h2>
<div class="voice-row">
  <select id="voice-select"><option>Loading...</option></select>
  <button onclick="saveVoice()">Save</button>
  <button onclick="previewVoice()" id="preview-btn">Preview</button>
  <span id="current-voice" style="color:#3fb950;font-size:0.85em"></span>
</div>
<p class="note">Takes effect on the next article. Does not affect articles currently processing.</p>

<div class="modal-overlay" id="reprocess-modal">
  <div class="modal">
    <h3>Reprocess with voice</h3>
    <select id="reprocess-voice-select"></select>
    <div class="modal-actions">
      <button class="btn-cancel" onclick="closeReprocessModal()">Cancel</button>
      <button onclick="confirmReprocess()">Reprocess</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<noscript><p style="color:#f85149">JavaScript is disabled — dashboard requires JS.</p></noscript>

<script>
document.getElementById("counts").textContent = "JS OK, fetching...";
const TOKEN = "__TOKEN__";
const hdrs = {"Authorization": "Bearer " + TOKEN};

function fmtDuration(s) {
  if (!s) return "";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? h + "h " + m + "m" : m + "m";
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {month:"short", day:"numeric"}) + " " +
         d.toLocaleTimeString(undefined, {hour:"2-digit", minute:"2-digit"});
}
function badge(status) {
  return '<span class="badge badge-' + status + '">' + status + '</span>';
}

async function load() {
  try {
    const resp = await fetch("/status", {headers: hdrs});
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const rows = await resp.json();
    const counts = {};
    rows.forEach(r => counts[r.status] = (counts[r.status] || 0) + 1);
    document.getElementById("counts").textContent =
      Object.entries(counts).map(([k,v]) => v + " " + k).join(" · ") || "No articles yet";

    const tbody = document.getElementById("queue-body");
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="4" style="color:#8b949e">No articles yet.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => {
      const title = r.title && r.title !== "Untitled" ? r.title : "Untitled";
      let info = fmtDate(r.added_at);
      if (r.status === "done") {
        info = fmtDuration(r.duration) +
               (r.size_bytes ? " · " + (r.size_bytes/1048576).toFixed(1) + " MB" : "");
      } else if (r.status === "processing") {
        info = '<span class="spin">&#8635;</span> since ' + fmtDate(r.added_at);
      } else if (r.status === "failed") {
        info = '<span class="error-text" title="' + (r.error || "") + '">Error (hover)</span>';
      }
      const reprocessBtn = (r.status === 'done' || r.status === 'failed')
        ? '<button class="reprocess-btn" title="Reprocess with different voice" onclick="reprocessArticle(\\'' + r.guid + '\\')">&#8635;</button>'
        : '';
      return '<tr>' +
        '<td>' + badge(r.status) + '</td>' +
        '<td><a class="title-link" href="' + r.url + '" target="_blank">' + title + '</a>' +
            '<span class="url-text">' + r.url + '</span></td>' +
        '<td class="info-cell">' + info + '</td>' +
        '<td>' + reprocessBtn + '<button class="del-btn" title="Delete" onclick="deleteArticle(\\'' + r.guid + '\\')">&#215;</button></td>' +
        '</tr>';
    }).join("");
  } catch(e) {
    document.getElementById("counts").textContent = "Error loading queue: " + e;
    document.getElementById("queue-body").innerHTML =
      '<tr><td colspan="4" class="error-text">' + e + '</td></tr>';
  }
}

async function loadVoices() {
  try {
    const vResp = await fetch("/voices", {headers: hdrs});
    if (!vResp.ok) throw new Error("/voices HTTP " + vResp.status);
    const sResp = await fetch("/settings", {headers: hdrs});
    if (!sResp.ok) throw new Error("/settings HTTP " + sResp.status);
    const vr = await vResp.json();
    const sr = await sResp.json();
    const current = sr.voice;
    const groups = {};
    const labels = {
      af:"American Female", am:"American Male",
      bf:"British Female",  bm:"British Male",
      ef:"Spanish Female",  em:"Spanish Male",
      ff:"French Female",
      hf:"Hindi Female",    hm:"Hindi Male",
      "if":"Italian Female",im:"Italian Male",
      jf:"Japanese Female", jm:"Japanese Male",
      pf:"Portuguese Female",pm:"Portuguese Male",
      zf:"Chinese Female",  zm:"Chinese Male",
    };
    vr.voices.forEach(v => {
      const p = v.id.slice(0, 2);
      if (!groups[p]) groups[p] = [];
      groups[p].push(v);
    });
  document.getElementById("current-voice").textContent = "✓ " + current;
  const sel = document.getElementById("voice-select");
  sel.innerHTML = Object.entries(groups).map(([p, vs]) => {
    const opts = vs.map(v =>
      '<option value="' + v.id + '"' + (v.id === current ? ' selected' : '') + '>' + v.id + '</option>'
    ).join("");
    return '<optgroup label="' + (labels[p] || p) + '">' + opts + '</optgroup>';
  }).join("");
  } catch(e) {
    document.getElementById("voice-select").innerHTML = '<option>Error: ' + e + '</option>';
  }
}

async function submitUrl() {
  const input = document.getElementById("url-input");
  const status = document.getElementById("submit-status");
  const url = input.value.trim();
  if (!url) return;
  status.textContent = "Submitting...";
  status.style.color = "#8b949e";
  try {
    const resp = await fetch("/add", {
      method: "POST",
      headers: {...hdrs, "Content-Type": "application/json"},
      body: JSON.stringify({url}),
    });
    const data = await resp.json();
    if (data.status === "queued") {
      status.textContent = "Queued!";
      status.style.color = "#3fb950";
      input.value = "";
      load();
    } else if (data.status === "duplicate") {
      status.textContent = "Already in queue.";
      status.style.color = "#e3b341";
    } else {
      status.textContent = "Error: " + JSON.stringify(data);
      status.style.color = "#f85149";
    }
  } catch(e) {
    status.textContent = "Error: " + e;
    status.style.color = "#f85149";
  }
}

async function previewVoice() {
  const voice = document.getElementById("voice-select").value;
  const btn = document.getElementById("preview-btn");
  btn.textContent = "Loading...";
  btn.disabled = true;
  try {
    const resp = await fetch("/preview-voice?voice=" + encodeURIComponent(voice), {headers: hdrs});
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const blob = await resp.blob();
    const audioUrl = URL.createObjectURL(blob);
    const audio = new Audio(audioUrl);
    audio.play();
    audio.onended = () => URL.revokeObjectURL(audioUrl);
  } catch(e) {
    showToast("Preview failed: " + e);
  } finally {
    btn.textContent = "Preview";
    btn.disabled = false;
  }
}

async function deleteArticle(guid) {
  if (!confirm("Delete this episode? This removes the MP3 from the server.")) return;
  const resp = await fetch("/articles/" + guid, {method: "DELETE", headers: hdrs});
  if (resp.ok) { showToast("Deleted."); load(); }
  else showToast("Delete failed.");
}

let _reprocessGuid = null;

function reprocessArticle(guid) {
  _reprocessGuid = guid;
  const src = document.getElementById("voice-select");
  const dst = document.getElementById("reprocess-voice-select");
  dst.innerHTML = src.innerHTML;
  dst.value = src.value;
  document.getElementById("reprocess-modal").classList.add("show");
}

function closeReprocessModal() {
  document.getElementById("reprocess-modal").classList.remove("show");
  _reprocessGuid = null;
}

async function confirmReprocess() {
  const voice = document.getElementById("reprocess-voice-select").value;
  const guid = _reprocessGuid;
  closeReprocessModal();
  const resp = await fetch("/articles/" + guid + "/reprocess", {
    method: "POST",
    headers: {...hdrs, "Content-Type": "application/json"},
    body: JSON.stringify({voice}),
  });
  if (resp.ok) { showToast("Requeued!"); load(); }
  else { const e = await resp.json(); showToast("Failed: " + (e.detail || resp.status)); }
}

async function saveVoice() {
  const voice = document.getElementById("voice-select").value;
  await fetch("/settings", {
    method: "POST", headers: {...hdrs, "Content-Type": "application/json"},
    body: JSON.stringify({voice}),
  });
  document.getElementById("current-voice").textContent = "✓ " + voice;
  showToast("Voice saved.");
}

function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3000);
}

load();
loadVoices();
setInterval(load, 10000);
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# Admin dashboard template
# ─────────────────────────────────────────────────────────────────────────────

_ADMIN_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>article2pod — Admin</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0d1117; color: #c9d1d9; margin: 0; padding: 1.5em; }
  h1 { color: #f0883e; margin: 0 0 0.2em; font-size: 1.5em; }
  .subtitle { color: #8b949e; font-size: 0.9em; margin-bottom: 1.8em; }
  h2 { font-size: 0.8em; color: #8b949e; text-transform: uppercase; letter-spacing: 0.1em;
       margin: 1.8em 0 0.75em; border-bottom: 1px solid #21262d; padding-bottom: 0.4em; }
  table { width: 100%; border-collapse: collapse; font-size: 0.88em; }
  th { text-align: left; color: #8b949e; font-weight: 500; padding: 0.5em 0.75em;
       border-bottom: 1px solid #21262d; }
  td { padding: 0.65em 0.75em; border-bottom: 1px solid #161b22; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  .del-btn { background: none; border: none; color: #6e7681; cursor: pointer;
             font-size: 1.1em; padding: 0 0.25em; line-height: 1; }
  .del-btn:hover { color: #f85149; }
  .badge { display: inline-block; padding: 0.15em 0.55em; border-radius: 1em;
           font-size: 0.78em; font-weight: 600; }
  .badge-done       { background: #0d4429; color: #3fb950; }
  .badge-processing { background: #3d2b00; color: #e3b341; }
  .badge-queued     { background: #0c2d6b; color: #58a6ff; }
  .badge-failed     { background: #3d0000; color: #f85149; }
  .title-link { color: #c9d1d9; text-decoration: none; font-weight: 500; }
  .title-link:hover { color: #58a6ff; }
  .url-text { color: #8b949e; font-size: 0.82em; white-space: nowrap; overflow: hidden;
              text-overflow: ellipsis; max-width: 380px; display: block; }
  .info-cell { color: #8b949e; font-size: 0.85em; white-space: nowrap; }
  .spin { display: inline-block; animation: spin 1.2s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .add-row { display: flex; gap: 0.75em; align-items: center; flex-wrap: wrap;
             margin-bottom: 0.5em; }
  input[type=text] { background: #161b22; color: #c9d1d9; border: 1px solid #30363d;
                     padding: 0.4em 0.6em; border-radius: 6px; font-size: 0.9em;
                     flex: 1; min-width: 200px; }
  button { background: #238636; color: #fff; border: none; padding: 0.4em 1.1em;
           border-radius: 6px; cursor: pointer; font-size: 0.88em; }
  button:hover { background: #2ea043; }
  button.danger { background: none; border: 1px solid #f85149; color: #f85149; }
  button.danger:hover { background: #3d0000; }
  button:disabled { background: #21262d; color: #6e7681; cursor: default; }
  .note { color: #6e7681; font-size: 0.82em; }
  .error-text { color: #f85149; font-size: 0.82em; }
  .token-box { font-family: monospace; background: #161b22; border: 1px solid #30363d;
               border-radius: 6px; padding: 0.5em 0.75em; font-size: 0.85em;
               color: #3fb950; word-break: break-all; margin-top: 0.75em; }
  .token-box .token-label { color: #8b949e; font-size: 0.82em; margin-bottom: 0.3em; font-family: sans-serif; }
  .token-mono { font-family: monospace; font-size: 0.82em; color: #8b949e; }
  a.link { color: #58a6ff; text-decoration: none; font-size: 0.85em; }
  a.link:hover { text-decoration: underline; }
  .counts { font-size: 0.82em; color: #8b949e; }
  .user-tag { display: inline-block; background: #1c2b3a; color: #79c0ff;
              border-radius: 4px; padding: 0.1em 0.45em; font-size: 0.78em;
              font-weight: 600; margin-right: 0.3em; }
  .toast { position: fixed; bottom: 1.5em; right: 1.5em; background: #1f6feb; color: #fff;
           padding: 0.6em 1.2em; border-radius: 8px; font-size: 0.88em;
           opacity: 0; transition: opacity 0.3s; pointer-events: none; }
  .toast.show { opacity: 1; }
</style>
</head>
<body>
<h1>article2pod — Admin</h1>
<div class="subtitle">Admin dashboard · <a class="link" href="/ui/__TOKEN__">My queue</a></div>

<h2>Users</h2>
<table id="users-table">
  <thead><tr><th>Username</th><th>Articles</th><th>Voice</th><th>Token</th><th>Links</th><th></th></tr></thead>
  <tbody id="users-body"><tr><td colspan="6" style="color:#8b949e">Loading...</td></tr></tbody>
</table>

<h2>Add User</h2>
<div class="add-row">
  <input type="text" id="new-username" placeholder="username" onkeydown="if(event.key==='Enter')createUser()" />
  <button onclick="createUser()">Create</button>
</div>
<div id="new-token-box" style="display:none"></div>

<h2>All Articles</h2>
<div id="all-counts" class="note" style="margin-bottom:0.75em">Loading...</div>
<table>
  <thead><tr><th>User</th><th>Status</th><th>Article</th><th>Info</th><th></th></tr></thead>
  <tbody id="all-body"><tr><td colspan="5" style="color:#8b949e">Loading...</td></tr></tbody>
</table>

<div class="toast" id="toast"></div>
<noscript><p style="color:#f85149">JavaScript is disabled — dashboard requires JS.</p></noscript>

<script>
const TOKEN = "__TOKEN__";
const hdrs = {"Authorization": "Bearer " + TOKEN};

function fmtDuration(s) {
  if (!s) return "";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? h + "h " + m + "m" : m + "m";
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {month:"short", day:"numeric"}) + " " +
         d.toLocaleTimeString(undefined, {hour:"2-digit", minute:"2-digit"});
}
function badge(status) {
  return '<span class="badge badge-' + status + '">' + status + '</span>';
}
function showToast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3000);
}

async function loadUsers() {
  try {
    const resp = await fetch("/admin-api/users", {headers: hdrs});
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const users = await resp.json();
    const tbody = document.getElementById("users-body");
    if (!users.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:#8b949e">No users.</td></tr>';
      return;
    }
    tbody.innerHTML = users.map(u => {
      const counts = (u.queued ? u.queued + " queued" : "") +
                     (u.processing ? (u.queued ? " · " : "") + u.processing + " proc." : "") +
                     (u.done ? " · " + u.done + " done" : "") +
                     (u.failed ? " · " + u.failed + " failed" : "") || "—";
      const tok = u.token_tail ? "···" + u.token_tail : "—";
      const dashLink = '<a class="link" href="/ui/' + u.token + '" target="_blank">Dashboard</a>';
      const rssLink  = '<a class="link" href="/rss/' + u.token + '" target="_blank">RSS</a>';
      const delBtn = u.is_admin
        ? '<span class="note">admin</span>'
        : '<button class="del-btn" title="Delete user" onclick="deleteUser(\\'' + u.username + '\\')">&#215;</button>';
      return '<tr>' +
        '<td><strong>' + u.username + '</strong></td>' +
        '<td class="counts">' + counts + '</td>' +
        '<td class="token-mono">' + u.voice + '</td>' +
        '<td class="token-mono">' + tok + '</td>' +
        '<td>' + dashLink + ' · ' + rssLink + '</td>' +
        '<td>' + delBtn + '</td>' +
        '</tr>';
    }).join("");
  } catch(e) {
    document.getElementById("users-body").innerHTML =
      '<tr><td colspan="6" class="error-text">' + e + '</td></tr>';
  }
}

async function loadAllArticles() {
  try {
    const resp = await fetch("/admin-api/all-articles", {headers: hdrs});
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const rows = await resp.json();
    const counts = {};
    rows.forEach(r => counts[r.status] = (counts[r.status] || 0) + 1);
    document.getElementById("all-counts").textContent =
      Object.entries(counts).map(([k,v]) => v + " " + k).join(" · ") || "No articles";

    const tbody = document.getElementById("all-body");
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:#8b949e">No articles.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => {
      const title = r.title && r.title !== "Untitled" ? r.title : "Untitled";
      let info = fmtDate(r.added_at);
      if (r.status === "done") {
        info = fmtDuration(r.duration) +
               (r.size_bytes ? " · " + (r.size_bytes/1048576).toFixed(1) + " MB" : "");
      } else if (r.status === "processing") {
        info = '<span class="spin">&#8635;</span>';
      } else if (r.status === "failed") {
        info = '<span class="error-text" title="' + (r.error || "") + '">Error</span>';
      }
      return '<tr>' +
        '<td><span class="user-tag">' + (r.username || "?") + '</span></td>' +
        '<td>' + badge(r.status) + '</td>' +
        '<td><a class="title-link" href="' + r.url + '" target="_blank">' + title + '</a>' +
            '<span class="url-text">' + r.url + '</span></td>' +
        '<td class="info-cell">' + info + '</td>' +
        '<td><button class="del-btn" title="Delete" onclick="adminDeleteArticle(\\'' + r.guid + '\\')">&#215;</button></td>' +
        '</tr>';
    }).join("");
  } catch(e) {
    document.getElementById("all-body").innerHTML =
      '<tr><td colspan="5" class="error-text">' + e + '</td></tr>';
  }
}

async function createUser() {
  const input = document.getElementById("new-username");
  const username = input.value.trim();
  if (!username) return;
  try {
    const resp = await fetch("/admin-api/users", {
      method: "POST",
      headers: {...hdrs, "Content-Type": "application/json"},
      body: JSON.stringify({username}),
    });
    if (!resp.ok) {
      const err = await resp.json();
      showToast("Error: " + (err.detail || resp.status));
      return;
    }
    const u = await resp.json();
    input.value = "";
    const box = document.getElementById("new-token-box");
    box.style.display = "block";
    box.innerHTML = '<div class="token-box">' +
      '<div class="token-label">Token for <strong>' + u.username + '</strong> — copy this now, it cannot be retrieved later:</div>' +
      u.token +
      '</div>';
    loadUsers();
  } catch(e) {
    showToast("Error: " + e);
  }
}

async function deleteUser(username) {
  if (!confirm("Delete user \\"" + username + "\\" and all their articles? This cannot be undone.")) return;
  const resp = await fetch("/admin-api/users/" + encodeURIComponent(username), {
    method: "DELETE", headers: hdrs,
  });
  if (resp.ok) { showToast("User deleted."); loadUsers(); loadAllArticles(); }
  else showToast("Delete failed.");
}

async function adminDeleteArticle(guid) {
  if (!confirm("Delete this episode? This removes the MP3 from the server.")) return;
  const resp = await fetch("/admin-api/articles/" + guid, {method: "DELETE", headers: hdrs});
  if (resp.ok) { showToast("Deleted."); loadAllArticles(); }
  else showToast("Delete failed.");
}

loadUsers();
loadAllArticles();
setInterval(() => { loadUsers(); loadAllArticles(); }, 15000);
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# User-facing endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/ui/{token}")
def ui(token: str):
    user = db.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    return Response(
        content=_UI_TEMPLATE.replace("__TOKEN__", token),
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/voices")
def list_voices(_user: dict = Depends(_verify)):
    try:
        req = urllib.request.Request(f"{KOKORO_URL}/v1/audio/voices")
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not reach TTS backend: {e}")


@app.get("/settings")
def get_settings(user: dict = Depends(_verify)):
    return {"voice": user["voice"]}


@app.post("/settings")
def update_settings(req: SettingsRequest, user: dict = Depends(_verify)):
    db.set_user_voice(user["id"], req.voice)
    log.info("User %s voice changed to %s", user["username"], req.voice)
    return {"voice": req.voice}


@app.get("/preview-voice")
def preview_voice(voice: str, _user: dict = Depends(_verify)):
    sample = "This is a preview. Article to pod converts web articles into podcast episodes."
    try:
        payload = json.dumps({
            "model": "kokoro",
            "input": sample,
            "voice": voice,
            "response_format": "mp3",
            "speed": 1.0,
        }).encode()
        req = urllib.request.Request(
            f"{KOKORO_URL}/v1/audio/speech",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            audio_data = resp.read()
        return Response(content=audio_data, media_type="audio/mpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS error: {e}")


@app.delete("/articles/{guid}")
def delete_article(guid: str, user: dict = Depends(_verify)):
    is_admin = user["token"] == ADMIN_TOKEN
    mp3 = Path(AUDIO_DIR) / f"{guid}.mp3"
    if mp3.exists():
        mp3.unlink()
    deleted = db.delete_article(guid, user_id=None if is_admin else user["id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    log.info("Deleted article %s by %s", guid, user["username"])
    return {"status": "deleted"}


@app.post("/articles/{guid}/reprocess")
def reprocess_article(guid: str, req: ReprocessRequest, user: dict = Depends(_verify)):
    mp3 = Path(AUDIO_DIR) / f"{guid}.mp3"
    if mp3.exists():
        mp3.unlink()
    ok = db.requeue_article(guid, user_id=user["id"], voice=req.voice)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    log.info("Requeue article %s with voice %s by %s", guid, req.voice, user["username"])
    return {"status": "queued"}


@app.post("/add")
def add_url(req: AddRequest, user: dict = Depends(_verify)):
    url = str(req.url)
    result = db.enqueue(url, user_id=user["id"])
    if result is None:
        return {"status": "duplicate", "message": "URL already in queue"}
    log.info("Enqueued for %s: %s", user["username"], url)
    return {"status": "queued", "guid": result["guid"]}


@app.get("/status")
def status(user: dict = Depends(_verify)):
    rows = db.get_all(user_id=user["id"])
    return [dict(r) for r in rows]


@app.get("/rss/{token}")
def get_feed(token: str):
    user = db.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=403, detail="Forbidden")

    episodes = db.get_done(user_id=user["id"])
    feed_title = f"{TITLE} — {user['username']}"

    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.id(f"{BASE_URL}/rss/{token}")
    fg.title(feed_title)
    fg.author({"name": AUTHOR})
    fg.link(href=f"{BASE_URL}/rss/{token}", rel="self")
    fg.description(DESCRIPTION)
    fg.language("en")
    fg.podcast.itunes_author(AUTHOR)
    fg.podcast.itunes_summary(DESCRIPTION)
    fg.podcast.itunes_explicit("no")

    for ep in episodes:
        audio_url = f"{BASE_URL}/audio/{ep['guid']}.mp3"
        fe = fg.add_entry(order="append")
        fe.id(ep["guid"])
        fe.title(ep["title"] or "Untitled")
        fe.description(f"<p>{ep['title']}</p><p>Source: {ep['url']}</p>")
        fe.enclosure(audio_url, str(ep["size_bytes"] or 0), "audio/mpeg")
        fe.podcast.itunes_author(ep["author"] or AUTHOR)
        if ep["duration"]:
            fe.podcast.itunes_duration(ep["duration"])
        pub = ep["processed_at"] or ep["added_at"] or ""
        if pub:
            try:
                dt = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                fe.pubDate(dt)
            except ValueError:
                pass

    rss_bytes = fg.rss_str(pretty=True)
    return Response(content=rss_bytes, media_type="application/rss+xml")


@app.get("/submit")
def submit_url(url: str, token: str):
    user = db.get_user_by_token(token)
    if user is None:
        raise HTTPException(status_code=403, detail="Forbidden")
    result = db.enqueue(url, user_id=user["id"])
    if result is None:
        msg, color = "Already queued or processed.", "#e6a817"
    else:
        log.info("Enqueued via /submit for %s: %s", user["username"], url)
        msg, color = "Queued! Check AntennaPod in ~20-30 min.", "#4caf50"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>article2pod</title>
<style>
  body {{ font-family: sans-serif; text-align: center; padding: 3em;
         background: #111; color: #eee; }}
  h2 {{ color: {color}; }}
  p {{ color: #aaa; word-break: break-all; font-size: 0.9em; }}
  small {{ color: #555; }}
</style></head><body>
<h2>{msg}</h2>
<p>{url}</p>
<small>This tab will close in 3 seconds.</small>
<script>setTimeout(() => window.close(), 3000);</script>
</body></html>"""
    return Response(content=html, media_type="text/html")


# ─────────────────────────────────────────────────────────────────────────────
# Admin endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/admin/{token}")
def admin_ui(token: str):
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Forbidden")
    return Response(
        content=_ADMIN_TEMPLATE.replace("__TOKEN__", token),
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/admin-api/users")
def admin_list_users(_user: dict = Depends(_verify_admin)):
    users = db.get_all_users()
    all_articles = db.get_all()
    counts_by_user: dict[int, dict] = {}
    for a in all_articles:
        uid = a["user_id"]
        if uid not in counts_by_user:
            counts_by_user[uid] = {"queued": 0, "processing": 0, "done": 0, "failed": 0}
        s = a["status"]
        if s in counts_by_user[uid]:
            counts_by_user[uid][s] += 1

    result = []
    for u in users:
        uid = u["id"]
        c = counts_by_user.get(uid, {})
        result.append({
            "id": uid,
            "username": u["username"],
            "token": u["token"],
            "token_tail": u["token"][-8:],
            "voice": u["voice"],
            "created_at": u["created_at"],
            "is_admin": u["token"] == ADMIN_TOKEN,
            **c,
        })
    return result


@app.post("/admin-api/users")
def admin_create_user(req: CreateUserRequest, _user: dict = Depends(_verify_admin)):
    try:
        user = db.create_user(req.username)
        log.info("Admin created user: %s", req.username)
        return dict(user)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/admin-api/users/{username}")
def admin_delete_user(username: str, _user: dict = Depends(_verify_admin)):
    if username == "lando":
        raise HTTPException(status_code=400, detail="Cannot delete admin user")
    all_users = db.get_all_users()
    target = next((u for u in all_users if u["username"] == username), None)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    guids = db.delete_user(target["id"])
    audio_dir = Path(AUDIO_DIR)
    for guid in guids:
        mp3 = audio_dir / f"{guid}.mp3"
        if mp3.exists():
            mp3.unlink()
    log.info("Admin deleted user %s (%d articles)", username, len(guids))
    return {"status": "deleted", "articles_removed": len(guids)}


@app.get("/admin-api/all-articles")
def admin_all_articles(_user: dict = Depends(_verify_admin)):
    rows = db.get_all()
    return [dict(r) for r in rows]


@app.delete("/admin-api/articles/{guid}")
def admin_delete_article(guid: str, _user: dict = Depends(_verify_admin)):
    mp3 = Path(AUDIO_DIR) / f"{guid}.mp3"
    if mp3.exists():
        mp3.unlink()
    deleted = db.delete_article(guid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found")
    log.info("Admin deleted article %s", guid)
    return {"status": "deleted"}


# ─────────────────────────────────────────────────────────────────────────────
# Misc
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    rows = db.get_all()
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {
        "service": "article2pod",
        "endpoints": {
            "ui":     "GET  /ui/<token>",
            "admin":  "GET  /admin/<token>",
            "add":    "POST /add  {\"url\":\"...\"}  (Authorization: Bearer <token>)",
            "feed":   "GET  /rss/<token>",
            "status": "GET  /status  (Authorization: Bearer <token>)",
            "health": "GET  /health",
        },
        "queue": counts,
    }


@app.get("/health")
def health():
    try:
        db.init_db(admin_token=ADMIN_TOKEN, default_voice=KOKORO_VOICE)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
