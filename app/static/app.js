const $ = (id) => document.getElementById(id);
const log = $("log"), form = $("mainform"), input = $("input");
const slog = $("slog"), sform = $("sideform"), sinput = $("sinput");
const timerEl = $("timer"), pauseBtn = $("pause"), finishBtn = $("finish"), sideBtn = $("side");
const recEl = $("rec"), takeEl = $("take"), stakeEl = $("stake");
const micBtn = $("mic"), sendBtn = $("send"), smic = $("smic"), ssend = $("ssend"), drawer = $("drawer");
const library = $("library");
const capE = $("cap-ecoute"), capP = $("cap-parler");

// Declared audio channels: per device (localStorage), overridden by the open session's.
let caps = { ecoute: true, parle: true };
try { Object.assign(caps, JSON.parse(localStorage.caps || "{}")); } catch {}
capE.checked = caps.ecoute;
capP.checked = caps.parle;
function setCaps(c) {
  caps = { ecoute: !!c.ecoute, parle: !!c.parle };
  capE.checked = caps.ecoute;
  capP.checked = caps.parle;
  localStorage.caps = JSON.stringify(caps);
  syncButtons();
  syncSideButtons();
}

let view = null;          // current thread view {id, kind, timer_id, closed, pending_request, timer}
let sideView = null;      // the session's side thread {id, ...}, only when view is a session
let timerState = null;    // {state, elapsed_minutes, session_minutes, ...} + local clock anchor
let timerAt = 0;
let tickHandle = null;
let recorder = null, recStarted = 0, recChunks = [], recTick = null, recBusy = false;
let recLabel = "";  // mic device used by the pending/last take, shown in the preview
let pendingBlob = null, pendingSecs = 0, pendingUrl = null;
let takePane = "main";    // which pane owns the pending take ("main" or "side")

// ---- rendering ----

const TASK_MARK = /\[tâche\s*:\s*[^\]]{0,80}\]?/g;  // also hides a mark still streaming in
// Le repérage d'écriture vient du paquet de langue (exposé par /api/profile) : aucune
// écriture n'est codée en dur ici. Le repli couvre les écritures CJK et le hangul.
const FALLBACK_SCRIPT = "[\\u1100-\\u11FF\\u3130-\\u318F\\uAC00-\\uD7AF\\u3040-\\u309F\\u30A0-\\u30FF\\u4E00-\\u9FFF]";
let TARGET_CODE = "ko";
const scriptRegex = (source) => new RegExp(`${source}+(?:[\\s?!.,~-]+${source}+)*[?!.]?`, "g");
let SCRIPT = scriptRegex(FALLBACK_SCRIPT);
function setTarget(code, script) {
  TARGET_CODE = code || TARGET_CODE;
  SCRIPT = scriptRegex(script || FALLBACK_SCRIPT);
}
const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// Raw HTML in model output is shown as text, then the result is sanitized anyway.
marked.use({ gfm: true, breaks: true, renderer: { html: ({ text }) => escapeHtml(text) } });
const markdown = (src) => DOMPurify.sanitize(marked.parse(src.replace(TASK_MARK, "").trimEnd()));

// Wrap target-language runs in lang="<code>" so the right font applies without the model marking them.
// Each run is also a button that opens the listening popover.
const targetSpan = (text) => {
  const s = Object.assign(document.createElement("span"),
    { lang: TARGET_CODE, textContent: text, tabIndex: 0 });
  s.setAttribute("role", "button");
  s.dataset.sayable = "1";
  return s;
};
function tagTarget(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const n = walker.currentNode;
    SCRIPT.lastIndex = 0;
    if (SCRIPT.test(n.data) && !n.parentElement.closest("[data-sayable]")) nodes.push(n);
  }
  for (const n of nodes) {
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of n.data.matchAll(SCRIPT)) {
      frag.append(n.data.slice(last, m.index), targetSpan(m[0]));
      last = m.index + m[0].length;
    }
    frag.append(n.data.slice(last));
    n.replaceWith(frag);
  }
}

const nearBottom = (el) => el.scrollHeight - el.scrollTop - el.clientHeight < 80;
const toBottom = (el) => { el.scrollTop = el.scrollHeight; };

function add(cls, text = "", target = log) {
  const stick = nearBottom(target);
  const el = Object.assign(document.createElement("div"), { className: cls, textContent: text });
  tagTarget(el);
  target.appendChild(el);
  if (stick) toBottom(target);
  return el;
}

const chip = (label, err = false, target = log) =>
  add("chip" + (err ? " err" : ""), label.replace(/^⚙\s*/, ""), target);
// A "⬇ ko-….apkg" segment is a link to the regenerated package.
const linkChip = (label, name, target = log) => {
  const stick = nearBottom(target);
  const a = Object.assign(document.createElement("a"),
    { className: "chip", href: `/api/anki/${name}`, download: name, textContent: label });
  target.appendChild(a);
  if (stick) toBottom(target);
  return a;
};
// Tool labels read "⚙ name — reason" on failure; a stored row joins several with " / ".
const toolChips = (label, target = log) => label.split(" / ").forEach((l) => {
  const pkg = /[a-z]{2}-(?:tout|\d{4}-\d{2}-\d{2})\.apkg/.exec(l);
  if (pkg) linkChip(l, pkg[0], target);
  else chip(l, / — /.test(l), target);
});

function coachBubble(text, target = log) {
  const el = add("b coach", "", target);
  el.innerHTML = markdown(text);
  tagTarget(el);
  return el;
}

function audioBubble(path, text, target = log) {
  const el = add("b me", "", target);
  const audio = Object.assign(document.createElement("audio"), { controls: true, src: `/api/audio/${path}` });
  el.appendChild(audio);
  if (text) el.append(text);
  tagTarget(el);
  return el;
}

function renderMessage(m, target = log) {
  if (m.kind === "tool") return toolChips(m.label || "", target);
  if (m.kind === "event") return add("chip ev", m.label || "", target);
  if (m.kind === "audio" || m.attachment) return audioBubble(m.attachment, m.text, target);
  if (!m.text) return;
  return m.role === "user" ? add("b me", m.text, target) : coachBubble(m.text, target);
}

// ---- threads and header ----

async function loadThreads(selectId) {
  const threads = await (await fetch("/api/threads")).json();
  const current = selectId ?? view?.id;
  $("threads").replaceChildren(...threads.map((t) => {
    const b = Object.assign(document.createElement("button"), { type: "button", textContent: t.title || "Nouvelle conversation" });
    if (t.closed) b.append(Object.assign(document.createElement("small"), { textContent: " · terminée" }));
    b.dataset.id = t.id;
    b.setAttribute("aria-current", t.id == current);
    b.onclick = () => { drawer.close(); selectThread(t.id); };
    const li = document.createElement("li");
    li.append(b);
    return li;
  }));
  if (selectId !== undefined || !view) {
    if (threads.length) await selectThread(threads.some((t) => t.id == current) ? current : threads[0].id);
    else { view = null; renderHeader(); }
  }
}

async function selectThread(id) {
  view = await (await fetch(`/api/threads/${id}`)).json();
  renderHeader();
  log.replaceChildren();
  const msgs = await (await fetch(`/api/threads/${id}/messages`)).json();
  for (const m of msgs) renderMessage(m);
  toBottom(log);
  const last = msgs[msgs.length - 1];
  prefillNumbered(last && last.role === "model" ? last.text : "");
  $("threads").querySelectorAll("button").forEach((b) => b.setAttribute("aria-current", b.dataset.id == id));
  await loadSide();
}

function renderHeader() {
  const live = !!(view && view.kind === "session" && !view.closed);
  $("title").textContent = view ? (view.title || "Nouvelle conversation") + (view.closed ? " · terminée" : "") : "Coach de langue";
  finishBtn.hidden = pauseBtn.hidden = !live;
  timerEl.hidden = !(view && view.kind === "session" && view.timer);
  const closed = !!(view && view.closed);
  form.classList.toggle("disabled", closed);
  sform.classList.toggle("disabled", closed);
  input.placeholder = closed ? "Séance terminée" : "Message";
  sinput.placeholder = closed ? "Séance terminée" : "Question";
  if (view && view.kind === "session" && !view.closed && view.caps) setCaps(view.caps);
  syncButtons();
  syncSideButtons();
  if (view && view.timer) setTimer(view.timer);
  renderRec();
}

function renderRec() {
  const req = view && !view.closed && view.pending_request;
  recEl.hidden = !req;
  if (!req) return;
  const max = req.max_seconds ? `, max ${req.max_seconds} s` : "";
  recEl.replaceChildren(
    Object.assign(document.createElement("b"), { textContent: `Le coach demande un enregistrement : ${req.task} (${req.mode}${max})` }),
    `${req.instructions} Appuie sur le micro pour répondre.`);
  tagTarget(recEl);
}

function setTimer(t) {
  timerState = t;
  timerAt = Date.now();
  clearInterval(tickHandle);
  const render = () => {
    const paused = timerState.state === "pause";
    pauseBtn.textContent = paused ? "▶" : "⏸";
    pauseBtn.setAttribute("aria-label", paused ? "Reprendre" : "Mettre en pause");
    timerEl.classList.toggle("paused", paused);
    if (timerState.stopped) { timerEl.textContent = "⏱ terminé"; return; }
    const mins = Math.floor(timerState.session_minutes + (paused ? 0 : (Date.now() - timerAt) / 60000));
    timerEl.textContent = `${paused ? "⏸" : "⏱"} ${mins} min`;
    timerEl.setAttribute("aria-label", `${paused ? "En pause, " : ""}${mins} minutes de séance`);
  };
  render();
  tickHandle = setInterval(render, 5000);
}

// ---- turns ----

// Each model turn gets its own bubble, so text after a tool call lands below its chips.
// target is the pane's log; after() refreshes the pane once the stream ends.
async function streamInto(threadId, target, body, after) {
  let out = null, raw = "", lastRaw = "", queued = false, discarded = false;
  const evChip = (label, err) => chip(label, err, target);
  const paint = () => {
    queued = false;
    if (!out) return;
    const stick = nearBottom(target);
    out.innerHTML = markdown(raw);
    tagTarget(out);
    if (stick) toBottom(target);
  };
  const open = () => {
    out = add("b coach", "", target);
    out.setAttribute("aria-live", "polite");
    out.setAttribute("aria-busy", "true");
  };
  const close = () => {
    if (!out) return;
    paint();
    out.setAttribute("aria-busy", "false");
    if (!out.textContent.trim()) out.remove();
    else lastRaw = raw;
    out = null;
    raw = "";
  };
  open();
  try {
    const res = await fetch(`/api/threads/${threadId}/turn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) { evChip(`Erreur ${res.status} : ${await res.text()}`, true); return; }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.type === "text") {
          if (!out) open();
          raw += ev.text;
          if (!queued) { queued = true; requestAnimationFrame(paint); }
        } else if (ev.type === "tool") { close(); toolChips(ev.label, target); open(); }
        else if (ev.type === "card") { view.pending_request = ev.card; renderRec(); }
        else if (ev.type === "timer") setTimer(ev.timer);
        else if (ev.type === "discarded") discarded = true;
        else if (ev.type === "error") evChip("Erreur : " + ev.message, true);
      }
    }
  } catch (e) {
    evChip("Connexion interrompue : " + e.message, true);
  } finally {
    close();
    if (discarded) {
      // Fin d'une séance sans aucune participation : le serveur a tout supprimé.
      view = null;
      await loadThreads(null);
      if (!view) { log.replaceChildren(); loadSide(); }
    } else {
      await after();
      if (target === log) prefillNumbered(lastRaw);
    }
  }
}

const streamTurn = (body) => streamInto(view.id, log, body, refreshView);
const streamSide = (body) => streamInto(sideView.id, slog, body, loadSide);

async function refreshView() {
  view = await (await fetch(`/api/threads/${view.id}`)).json();
  renderHeader();
  loadThreads();
}

async function send() {
  const text = input.value.trim();
  if (!text || !view || view.closed) return;
  input.value = "";
  prefilled = "";
  syncButtons();
  add("b me", text);
  toBottom(log);
  await streamTurn({ event: "message", text });
}

// ---- numbered replies: prefill "1. 2. 3." when the coach ends on a list ----

// When a coach turn ends with a numbered template ("Écris-moi : 1. … 2. …"),
// the input starts with the numbers so only the sentences remain to type.
const numberedTail = (text) => {
  const lines = text.replace(TASK_MARK, "").trimEnd().split("\n");
  const nums = [];
  for (let i = lines.length - 1; i >= 0; i--) {
    const m = /^\s*(\d+)[.)]\s+\S/.exec(lines[i]);
    if (!m) break;
    nums.unshift(+m[1]);
  }
  return nums.length >= 2 && nums.every((v, i) => v === i + 1) ? nums.length : 0;
};

// The skeleton currently in the box and still untouched by l'apprenant.
let prefilled = "";

function prefillNumbered(text) {
  if (!view || view.closed || view.pending_request) return;
  if (input.value !== prefilled && input.value.trim()) return;  // keep a real draft
  const n = numberedTail(text);
  if (!n) {
    if (input.value === prefilled && prefilled) { input.value = prefilled = ""; syncButtons(); }
    return;
  }
  input.value = prefilled = Array.from({ length: n }, (_, i) => `${i + 1}. `).join("\n");
  input.setSelectionRange(3, 3);
  syncButtons();
}

// ---- side thread: questions beside the lesson ----

async function loadSide() {
  if (!view || view.kind !== "session") {
    sideView = null;
    sideBtn.hidden = true;
    document.body.classList.remove("side-open");
    return;
  }
  sideBtn.hidden = false;
  sideView = await (await fetch(`/api/threads/${view.id}/side`)).json();
  if (!sideView.id) { sideView = null; sideBtn.hidden = true; return; }
  const msgs = await (await fetch(`/api/threads/${sideView.id}/messages`)).json();
  slog.replaceChildren();
  for (const m of msgs) renderSideMessage(m);
  toBottom(slog);
}

function renderSideMessage(m) {
  const el = renderMessage(m, slog);
  if (!el || !m.text || (view && view.closed)) return;
  const btn = Object.assign(document.createElement("button"),
    { className: "tocourse", type: "button", textContent: "Envoyer au cours" });
  btn.onclick = () => sendToCourse(m.text, btn);
  el.appendChild(btn);
}

async function sendToCourse(text, btn) {
  btn.disabled = true;
  const res = await fetch(`/api/threads/${view.id}/note`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (res.ok) {
    btn.textContent = "Envoyé";
    add("chip ev", "📌 " + (text.length > 160 ? text.slice(0, 157) + "…" : text));
  } else {
    btn.disabled = false;
    chip("Note non envoyée.", true, slog);
  }
}

async function sendSide() {
  const text = sinput.value.trim();
  if (!text || !sideView || (view && view.closed)) return;
  sinput.value = "";
  syncSideButtons();
  add("b me", text, slog);
  toBottom(slog);
  await streamSide({ event: "message", text });
}

const syncSideButtons = () => {
  const typing = !!sinput.value.trim();
  ssend.hidden = !typing;
  smic.hidden = !caps.parle || pendingBlob || (typing && !(recorder && recorder.state === "recording"));
};

sideBtn.onclick = () => {
  const open = document.body.classList.toggle("side-open");
  sideBtn.setAttribute("aria-pressed", open);
  if (open) toBottom(slog);
};

sinput.oninput = syncSideButtons;
sform.onsubmit = (e) => { e.preventDefault(); sendSide(); };
sinput.onkeydown = (e) => {
  if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229 || touch.matches) return;
  e.preventDefault();
  sendSide();
};

// ---- controls ----

const syncButtons = () => {
  const typing = !!input.value.trim();
  sendBtn.hidden = !typing;
  micBtn.hidden = !caps.parle || pendingBlob || (typing && !(recorder && recorder.state === "recording"));
};
input.oninput = syncButtons;
form.onsubmit = (e) => { e.preventDefault(); send(); };

// Desktop: Enter sends, Shift+Enter adds a line. Touch keyboards keep Enter for new lines.
const touch = matchMedia("(pointer: coarse)");
input.onkeydown = (e) => {
  if (e.key !== "Enter" || e.shiftKey || e.isComposing || e.keyCode === 229 || touch.matches) return;
  e.preventDefault();
  send();
};

// The initial theme is set by an inline script in index.html so the page never flashes light.
const root = document.documentElement, themeBtn = $("theme");
function applyTheme(theme) {
  root.dataset.theme = theme;
  themeBtn.setAttribute("aria-pressed", theme === "dark");
  document.querySelector("meta[name=theme-color]").content = getComputedStyle(root).getPropertyValue("--surface").trim();
}
themeBtn.onclick = () => applyTheme(localStorage.theme = root.dataset.theme === "dark" ? "light" : "dark");
applyTheme(root.dataset.theme);

$("menu").onclick = () => drawer.showModal();
drawer.onclick = (e) => { if (e.target === drawer) drawer.close(); };

$("new").onclick = async () => {
  drawer.close();
  const t = await (await fetch("/api/threads", { method: "POST" })).json();
  await loadThreads(t.id);
};

$("session").onclick = async () => {
  drawer.close();
  const s = await (await fetch("/api/session", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(caps) })).json();
  await loadThreads(s.id);
  if (s.created) await streamTurn({ event: "start" });
};

// Toggling a channel mid-session updates the open session on the spot.
capE.onchange = capP.onchange = async () => {
  setCaps({ ecoute: capE.checked, parle: capP.checked });
  if (!view || view.kind !== "session" || view.closed) return;
  const s = await (await fetch("/api/session", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(caps) })).json();
  if (s.caps) setCaps(s.caps);
};

$("prog").onclick = () => { location.href = "/progres"; };

$("logout").onclick = async () => {
  await fetch("/logout", { method: "POST" });
  location.href = "/login";
};

// ---- ressenti de fin de séance ----
// Le ressenti part avec l'instruction de clôture : le coach l'écrit tel quel
// dans sa calibration au lieu d'inventer une impression sur la séance.
const feltDlg = $("feltdlg"), feltComment = $("felt-comment");
let feltPick = "";

function showFelt() {
  feltPick = "";
  feltComment.value = "";
  for (const b of feltDlg.querySelectorAll("[data-felt]")) b.setAttribute("aria-pressed", "false");
  feltDlg.showModal();
}

for (const btn of feltDlg.querySelectorAll("[data-felt]")) {
  btn.onclick = () => {
    feltPick = feltPick === btn.dataset.felt ? "" : btn.dataset.felt;  // re-cliquer annule le choix
    for (const other of feltDlg.querySelectorAll("[data-felt]"))
      other.setAttribute("aria-pressed", String(other.dataset.felt === feltPick));
  };
}
$("felt-go").onclick = () => {
  feltDlg.close();
  streamTurn({ event: "finish", felt: feltPick, comment: feltComment.value.trim() });
};
$("felt-cancel").onclick = () => feltDlg.close();
feltDlg.onclick = (e) => { if (e.target === feltDlg) feltDlg.close(); };

finishBtn.onclick = showFelt;

pauseBtn.onclick = async () => {
  const paused = timerState && timerState.state === "pause";
  const res = await fetch(`/api/threads/${view.id}/${paused ? "resume" : "pause"}`, { method: "POST" });
  if (res.ok) setTimer(await res.json());
};

// ---- voice takes: record, preview, send ----

const fmtSecs = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

const paneLog = (pane) => (pane === "side" ? slog : log);
const paneTake = (pane) => (pane === "side" ? stakeEl : takeEl);
const paneMic = (pane) => (pane === "side" ? smic : micBtn);
const paneStream = (pane, body) => (pane === "side" ? streamSide(body) : streamTurn(body));

function renderRecBar() {
  const target = takePane === "main" && view && view.pending_request ? view.pending_request.max_seconds : null;
  const el = paneTake(takePane);
  const elapsed = (Date.now() - recStarted) / 1000;
  el.className = "live";
  el.hidden = false;
  el.textContent = `● ${fmtSecs(elapsed)}` + (target ? ` · reste ${fmtSecs(Math.max(0, target - elapsed))}` : "");
  // max_seconds est un plafond ; onstop n'a peut-être pas encore tiré
  if (target && elapsed >= target && recorder && recorder.state === "recording") recorder.stop();
}

function clearTake() {
  if (pendingUrl) URL.revokeObjectURL(pendingUrl);
  pendingBlob = pendingUrl = null;
  const el = paneTake(takePane);
  el.hidden = true;
  el.replaceChildren();
  syncButtons();
  syncSideButtons();
}

// MediaRecorder blobs carry no duration header: Chrome plays them as an endless
// stream. Seeking past the end makes it resolve the real length (known workaround).
function fixDur(a) {
  a.addEventListener("loadedmetadata", () => {
    if (a.duration !== Infinity) return;
    a.addEventListener("timeupdate", () => { a.currentTime = 0; }, { once: true });
    a.currentTime = 1e101;
  });
}

function previewTake(blob, seconds) {
  pendingBlob = blob;
  pendingSecs = seconds;
  pendingUrl = URL.createObjectURL(blob);
  const el = paneTake(takePane);
  el.className = "";
  el.hidden = false;
  const audio = Object.assign(document.createElement("audio"), { controls: true, src: pendingUrl });
  fixDur(audio);
  const row = document.createElement("div");
  row.className = "row";
  const send = Object.assign(document.createElement("button"), { type: "button", textContent: "Envoyer" });
  const redo = Object.assign(document.createElement("button"), { type: "button", textContent: "Refaire" });
  const cancel = Object.assign(document.createElement("button"), { type: "button", textContent: "Annuler" });
  send.onclick = sendTake;
  redo.onclick = () => { clearTake(); toggleMic(takePane); };
  cancel.onclick = clearTake;
  row.append(send, redo, cancel, Object.assign(document.createElement("b"), { textContent: fmtSecs(seconds) }),
    Object.assign(document.createElement("small"), { textContent: recLabel }));
  el.replaceChildren(audio, row);
  syncButtons();
  syncSideButtons();
}

async function sendTake() {
  const blob = pendingBlob, seconds = pendingSecs, pane = takePane;
  clearTake();
  const res = await fetch("/api/audio", {
    method: "POST",
    headers: { "X-Audio-Mime": blob.type.split(";")[0], "X-Audio-Seconds": seconds },
    body: blob,
  });
  if (!res.ok) { chip("Erreur audio : " + await res.text(), true, paneLog(pane)); return; }
  const { path } = await res.json();
  audioBubble(path, "", paneLog(pane));
  toBottom(paneLog(pane));
  await paneStream(pane, { event: "message", audio: path, seconds });
}

// Android Chrome makes a connected bluetooth or wired headset the default input:
// on touch devices prefer the built-in mic ("Speakerphone" and friends), on
// desktop the headset mic itself when one is connected. localStorage.micId is
// the manual pick from Paramètres and wins over auto-detection.
// ponytail: detection relies on labels, which some devices may report
// generically; the settings picker is the fallback.
// Raw input, no WebRTC processing: AEC/AGC/noise-suppression can gate the first
// syllables and they flatten pronunciation, which the coach must hear as-is.
const MIC_CONSTRAINTS = { echoCancellation: false, noiseSuppression: false, autoGainControl: false };

const audioInputs = async () => (await navigator.mediaDevices.enumerateDevices())
  .filter((d) => d.kind === "audioinput" && d.deviceId !== "default" && d.deviceId !== "communications");

async function micStream() {
  const headset = /bluetooth|headset|earpiece|earphone|headphone|earbud|buds|airpods|hands[- ]?free|casque|écouteur/i;
  const pick = async () => localStorage.micId
    || (await audioInputs()).find((d) => d.label
        && (touch.matches ? !headset.test(d.label) : headset.test(d.label)))?.deviceId;
  let prefer = await pick();
  if (!prefer) {
    const probe = await navigator.mediaDevices.getUserMedia({ audio: MIC_CONSTRAINTS });  // labels need an open mic
    prefer = await pick();
    if (!prefer) return ready(probe);
    probe.getTracks().forEach((t) => t.stop());
  }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { ...MIC_CONSTRAINTS, deviceId: { exact: prefer } } }); }
  catch {
    delete localStorage.micId;  // the saved pick vanished
    stream = await navigator.mediaDevices.getUserMedia({ audio: MIC_CONSTRAINTS });
  }
  return ready(stream);
}

// A fresh track can take a second to deliver audio on Android (pipeline open,
// headset route change). Starting the recorder before unmute records silence
// over the first syllables.
async function ready(stream) {
  const track = stream.getAudioTracks()[0];
  if (track?.muted) {
    await new Promise((r) => { track.onunmute = r; setTimeout(r, 1500); });
    track.onunmute = null;
  }
  await new Promise((r) => setTimeout(r, 200));
  return stream;
}

async function toggleMic(pane) {
  if (recBusy) return;  // getUserMedia still in flight
  if (recorder) {
    // stop() is async: until onstop fires the state is already "inactive", and a
    // second tap here would start a ghost take on top of the pending preview.
    if (recorder.state === "recording") recorder.stop();
    return;
  }
  recBusy = true;
  let stream;
  try { stream = await micStream(); }
  catch { chip("Micro indisponible.", true, paneLog(pane)); return; }
  finally { recBusy = false; }
  recChunks = [];
  takePane = pane;
  const track = stream.getAudioTracks()[0];
  recLabel = track?.label || "";
  console.debug("[mic]", recLabel, JSON.stringify(track?.getSettings()));
  const btn = paneMic(pane);
  const rec = new MediaRecorder(stream);
  recorder = rec;
  rec.ondataavailable = (e) => recChunks.push(e.data);
  rec.onstop = () => {
    recorder = null;
    stream.getTracks().forEach((t) => t.stop());
    clearInterval(recTick);
    btn.classList.remove("recording");
    btn.textContent = "🎙";
    btn.setAttribute("aria-label", "Enregistrer un vocal");
    const blob = new Blob(recChunks, { type: rec.mimeType || "audio/webm" });
    previewTake(blob, Math.round((Date.now() - recStarted) / 1000));
  };
  recStarted = Date.now();
  try { rec.start(); }
  catch {
    recorder = null;
    stream.getTracks().forEach((t) => t.stop());
    chip("Enregistrement impossible.", true, paneLog(pane));
    return;
  }
  renderRecBar();
  recTick = setInterval(renderRecBar, 250);
  btn.classList.add("recording");
  btn.textContent = "⏹";
  btn.setAttribute("aria-label", "Arrêter l'enregistrement");
}

micBtn.onclick = () => toggleMic("main");
smic.onclick = () => toggleMic("side");

// ---- listening: tap Korean text, then pick a speed ----
// Audio is only requested on the speed tap, so opening the popover costs no Cartesia credits.

const say = $("say"), sayMsg = $("say-msg"), player = new Audio();
let sayAnchor = null, sayText = "", sayX = null, sayBtn = null;

function placeSay() {
  if (!sayAnchor.isConnected) return;  // a streaming repaint replaced the span, keep the last spot
  const r = sayAnchor.getBoundingClientRect(), w = say.offsetWidth, h = say.offsetHeight;
  const x = sayX ?? r.left + r.width / 2;
  say.style.left = `${Math.max(8, Math.min(x - w / 2, innerWidth - w - 8))}px`;
  say.style.top = `${r.bottom + 8 + h <= innerHeight ? r.bottom + 8 : Math.max(8, r.top - h - 8)}px`;
}

function openSay(span, x, focus) {
  sayAnchor?.classList.remove("say-on");
  sayAnchor = span;
  sayText = span.textContent.trim();
  sayX = x;
  sayMsg.textContent = "";
  span.classList.add("say-on");
  if (!say.matches(":popover-open")) say.showPopover();
  placeSay();
  if (focus) say.querySelector("button").focus();
}

function onTarget(e) {
  const span = e.target.closest("[data-sayable]");
  if (!span) return;
  if (e.type === "keydown") {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    openSay(span, null, true);
  } else if (getSelection().isCollapsed) openSay(span, e.clientX || null, false);  // not while selecting text
}
for (const el of [log, slog, recEl]) { el.addEventListener("click", onTarget); el.addEventListener("keydown", onTarget); }

const sayState = (btn, state) => {
  if (sayBtn && sayBtn !== btn) sayBtn.removeAttribute("data-state");
  sayBtn = btn;
  if (!btn) return;
  if (state) btn.dataset.state = state;
  else btn.removeAttribute("data-state");
};

say.onclick = (e) => {
  const btn = e.target.closest("[data-speed]");
  if (!btn) return;
  sayMsg.textContent = "";
  sayState(btn, "loading");
  // play() stays inside the tap so iOS allows it; the server synthesizes or serves the cached clip.
  player.src = `/api/tts?${new URLSearchParams({ text: sayText, speed: btn.dataset.speed })}`;
  player.play().catch(() => {});
};
player.onplaying = () => sayState(sayBtn, "playing");
player.onended = player.onpause = () => sayState(sayBtn, null);
player.onerror = () => { sayState(sayBtn, null); sayMsg.textContent = "Voix indisponible pour le moment."; };

say.addEventListener("toggle", (e) => {
  if (e.newState !== "closed" || say.matches(":popover-open")) return;  // reopened on another word
  sayAnchor?.classList.remove("say-on");
  if (say.contains(document.activeElement)) sayAnchor?.focus();
});
addEventListener("scroll", () => { if (say.matches(":popover-open")) placeSay(); }, true);
addEventListener("resize", () => { if (say.matches(":popover-open")) placeSay(); });

// ---- recordings library ----

const KO_LABELS = { presentation: "présentation", journee: "journée", film: "film", lecture: "lecture",
                    conversation: "conversation", spontane: "spontané", entraine: "entraîné" };
const koLabel = (k) => KO_LABELS[k] || k;

async function loadLibrary() {
  const takes = await (await fetch("/api/recordings")).json();
  $("takes").replaceChildren(...takes.map((t) => {
    const li = document.createElement("li");
    li.append(Object.assign(document.createElement("b"),
      { textContent: `${t.date} · ${koLabel(t.task)} (${koLabel(t.mode)})` + (t.seconds ? ` · ${fmtSecs(t.seconds)}` : "") }));
    if (t.missing) li.append(Object.assign(document.createElement("small"), { textContent: "Fichier absent" }));
    else li.append(Object.assign(document.createElement("audio"), { controls: true, preload: "none", src: `/api/audio/${t.path}` }));
    if (t.note) li.append(Object.assign(document.createElement("p"), { textContent: t.note }));
    const send = Object.assign(document.createElement("button"), { type: "button", textContent: "Envoyer au coach" });
    send.disabled = !(view && !view.closed);
    send.onclick = async () => {
      library.close();
      audioBubble(t.path);
      toBottom(log);
      await streamTurn({ event: "message", audio: t.path });
    };
    li.append(send);
    return li;
  }));
}

$("lib").onclick = async () => {
  drawer.close();
  await loadLibrary();
  library.showModal();
};
$("lib-close").onclick = () => library.close();
library.onclick = (e) => { if (e.target === library) library.close(); };

// ---- downloads: Anki packages regenerated from the notebook ----

const downloads = $("downloads");

async function loadDownloads() {
  const pkgs = await (await fetch("/api/anki")).json();
  $("pkgs").replaceChildren(...pkgs.map((p) => {
    const li = document.createElement("li");
    const title = (p.day ? `Cartes du ${p.day}` : "Paquet complet")
      + ` · ${p.count} carte${p.count > 1 ? "s" : ""}`;
    li.append(Object.assign(document.createElement("a"),
      { href: `/api/anki/${p.name}`, download: p.name, textContent: title }),
      Object.assign(document.createElement("small"), { textContent: p.name }));
    return li;
  }));
}

$("dl").onclick = async () => {
  drawer.close();
  await loadDownloads();
  downloads.showModal();
};
$("dl-close").onclick = () => downloads.close();
downloads.onclick = (e) => { if (e.target === downloads) downloads.close(); };

// ---- settings: provider + model, stored server-side in data/settings.json ----

const prefsDlg = $("prefsdlg"), setProvider = $("set-provider"),
      setModel = $("set-model"), setMsg = $("set-msg");
let catalogs = {};

function fillModels(provider, current) {
  setModel.replaceChildren(...(catalogs[provider] || [current]).map((m) =>
    Object.assign(document.createElement("option"),
      { value: m, textContent: m, selected: m === current })));
}

function showSettings(s) {
  catalogs = s.models;
  setProvider.value = s.provider;
  fillModels(s.provider, s.model);
  $("set-timezone").value = s.timezone || "";
}

async function saveSettings(body) {
  const res = await fetch("/api/settings", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const s = await res.json();
  if (!res.ok) { setMsg.textContent = "Erreur : " + (s.detail || res.status); return; }
  showSettings(s);
}

// Voix de synthèse de la langue du carnet (Cartesia) : la liste vient de l'API,
// donc une langue ajoutée plus tard n'a rien à changer ici.
async function fillVoices() {
  const sel = $("set-voice"), hint = $("set-voice-hint");
  sel.replaceChildren(Object.assign(document.createElement("option"),
    { value: "", textContent: "Voix du paquet de langue" }));
  const res = await fetch("/api/voices");
  if (!res.ok) {
    hint.textContent = "Voix indisponible : renseigner CARTESIA_API_KEY.";
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
  const data = await res.json();
  for (const v of data.voices)
    sel.append(Object.assign(document.createElement("option"),
      { value: v.id, textContent: v.name ? `${v.name}${v.gender ? " · " + v.gender : ""}` : v.id }));
  sel.value = data.current || "";
  hint.textContent = data.voices.length
    ? "Voix du texte cliquable dans le fil."
    : "Aucune voix listée pour cette langue : le paquet décide.";
}

// Profil : objectif, niveau, cadence, échéance. Le niveau vérifié par le
// diagnostic est conservé tel quel (le coach seul le met à jour).
let profileCache = null;

async function fillProfile() {
  const p = await (await fetch("/api/profile")).json();
  profileCache = p.profile || null;
  const levels = (p.languages.find((l) => l.code === p.language) || {}).levels || [];
  $("set-niveau").replaceChildren(...levels.map((lv) =>
    Object.assign(document.createElement("option"),
      { value: lv.code, textContent: `${lv.code} — ${lv.label}`,
        selected: lv.code === (profileCache && profileCache.level) })));
  $("set-objectif").value = (profileCache && profileCache.objective) || "";
  $("set-cadence").value = (profileCache && profileCache.cadence) || "";
  $("set-echeance").value = p.deadline || "";
}

$("set-profile-save").onclick = async () => {
  if (!profileCache) return;
  const body = { profile: { ...profileCache,
      level: $("set-niveau").value || profileCache.level,
      objective: $("set-objectif").value.trim() || profileCache.objective,
      cadence: $("set-cadence").value.trim() },
    deadline: $("set-echeance").value };
  const res = await fetch("/api/profile", { method: "POST",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json();
  setMsg.textContent = res.ok ? "Profil enregistré." : "Erreur : " + (data.detail || res.status);
  if (res.ok) profileCache = data.profile;
};

// Mic picker: the saved deviceId is localStorage.micId, "" means auto.
const setMic = $("set-mic");

async function fillMics() {
  if (!navigator.mediaDevices) return;
  let mics = await audioInputs();
  if (mics.length && mics.every((d) => !d.label)) {
    // Labels stay hidden until the mic has been opened once this session.
    const probe = await navigator.mediaDevices.getUserMedia({ audio: true }).catch(() => null);
    if (!probe) return;
    probe.getTracks().forEach((t) => t.stop());
    mics = await audioInputs();
  }
  setMic.replaceChildren(
    Object.assign(document.createElement("option"), { value: "", textContent: "Automatique" }),
    ...mics.map((d, i) => Object.assign(document.createElement("option"),
      { value: d.deviceId, textContent: d.label || `Micro ${i + 1}` })));
  setMic.value = localStorage.micId || "";
}

setMic.onchange = () => {
  if (setMic.value) localStorage.micId = setMic.value;
  else delete localStorage.micId;
};

$("prefs").onclick = async () => {
  drawer.close();
  showSettings(await (await fetch("/api/settings")).json());
  setMsg.textContent = "";
  prefsDlg.showModal();
  fillMics();
  fillVoices();
  fillProfile();
};
setProvider.onchange = () => saveSettings({ provider: setProvider.value });
setModel.onchange = () => saveSettings({ model: setModel.value });
$("set-timezone").onchange = () => saveSettings({ timezone: $("set-timezone").value.trim() });
$("set-voice").onchange = () => saveSettings({ voice: $("set-voice").value });
$("prefs-close").onclick = () => prefsDlg.close();
prefsDlg.onclick = (e) => { if (e.target === prefsDlg) prefsDlg.close(); };

const setDefaultDate = () => {
  const d = new Date();
  $("imp-date").value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
setDefaultDate();

$("import").onsubmit = async (e) => {
  e.preventDefault();
  const file = $("imp-file").files[0];
  if (!file) return;
  const msg = $("imp-msg");
  msg.textContent = "Import en cours…";
  const seconds = await new Promise((res) => {
    const a = new Audio();
    a.preload = "metadata";
    a.onloadedmetadata = () => res(isFinite(a.duration) ? Math.round(a.duration * 100) / 100 : null);
    a.onerror = () => res(null);
    a.src = URL.createObjectURL(file);
  });
  const headers = {
    "X-Audio-Name": encodeURIComponent(file.name),
    "X-Audio-Task": $("imp-task").value,
    "X-Audio-Mode": $("imp-mode").value,
    "X-Audio-Date": $("imp-date").value,
    "X-Audio-Note": encodeURIComponent($("imp-note").value),
  };
  if (seconds) headers["X-Audio-Seconds"] = seconds;
  const res = await fetch("/api/recordings/import", { method: "POST", headers, body: file });
  if (res.ok) {
    const entry = await res.json();
    msg.textContent = entry.duplicate ? "Déjà dans le carnet (même fichier)." : "Importé dans le carnet.";
    e.target.reset();
    setDefaultDate();
    await loadLibrary();
  } else {
    const data = await res.json().catch(() => null);
    msg.textContent = "Erreur : " + ((data && data.detail) || res.status);
  }
};

// La langue du carnet décide de ce qui est cliquable-pour-entendre, donc on la
// lit avant d'afficher le fil. Sans carnet, direction la mise en route ; les
// capacités audio déclarées là servent de valeurs par défaut sur cet appareil.
// "/#seance" (venant de la page progression) ouvre la séance après le chargement.
(async () => {
  try {
    const p = await (await fetch("/api/profile")).json();
    if (!p.onboarded) { location.replace("/onboarding"); return; }
    setTarget(p.language, p.script);
    if (!localStorage.caps && p.profile && p.profile.audio) setCaps(p.profile.audio);
  } catch {}
  await loadThreads(null);
  if (location.hash === "#seance") {
    history.replaceState(null, "", "/");
    $("session").click();
  }
})();
