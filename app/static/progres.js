const $ = (id) => document.getElementById(id);
const dash = $("dash");

// Même repérage d'écriture que dans app.js : la langue du carnet (lue sur
// /api/profile) donne le motif, la mise en forme vient de la feuille de style.
const FALLBACK_SCRIPT = "[\\u1100-\\u11FF\\u3130-\\u318F\\uAC00-\\uD7AF\\u3040-\\u309F\\u30A0-\\u30FF\\u4E00-\\u9FFF]";
let TARGET_CODE = "ko";
const scriptRegex = (source) => new RegExp(`${source}+(?:[\\s?!.,~-]+${source}+)*[?!.]?`, "g");
let SCRIPT = scriptRegex(FALLBACK_SCRIPT);
function setTarget(code, script) {
  TARGET_CODE = code || TARGET_CODE;
  SCRIPT = scriptRegex(script || FALLBACK_SCRIPT);
}
function tagTarget(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const n = walker.currentNode;
    SCRIPT.lastIndex = 0;
    if (SCRIPT.test(n.data) && !n.parentElement.closest("[lang]")) nodes.push(n);
  }
  for (const n of nodes) {
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of n.data.matchAll(SCRIPT)) {
      frag.append(n.data.slice(last, m.index), Object.assign(document.createElement("span"), { lang: TARGET_CODE, textContent: m[0] }));
      last = m.index + m[0].length;
    }
    frag.append(n.data.slice(last));
    n.replaceWith(frag);
  }
}

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
};
const NS = "http://www.w3.org/2000/svg";
const svg = (tag, attrs, text) => {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (text != null) n.textContent = text;
  return n;
};

const LABELS = { complete: "Mission terminée", partielle: "Séance partielle",
                 sans_trace: "Aucune séance enregistrée", a_faire: "Aujourd'hui : à faire", avenir: "À venir" };
const KO_LABELS = { presentation: "présentation", journee: "journée", film: "film", lecture: "lecture",
                    conversation: "conversation", spontane: "spontané", entraine: "entraîné" };
const SKILLS = { ecoute: "Écoute", oral: "Oral", ecrit: "Messages", registre: "Registres" };
const TASKS = ["presentation", "journee", "film", "lecture", "conversation"];
const MODES = ["spontane", "lecture", "entraine"];
const DAY_MS = 86400000;

const parseDay = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const fmtShort = (s) => parseDay(s).toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });
const fmtFull = (s) => parseDay(s).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

let data = null, selected = null;

const card = (...kids) => { const s = el("section", "card"); s.append(...kids); return s; };

// ---- sections ----

function hero() {
  const sub = el("p", "eyebrow",
    `Semaine ${data.semaine} · depuis le ${fmtShort(data.start)}`
    + (data.target ? ` → ${fmtShort(data.target)}` : " · aucune échéance fixée"));
  const stats = el("div", "stats");
  for (const [label, value] of [
    ["Rang personnel", data.rang],
    ["Paliers démontrés", `${data.lp} / 400`],
    ["Pratique enregistrée", `${data.minutes_pratiquees} min`],
    data.target ? ["Avant l'échéance", `${data.jours_restants} j`] : ["Niveau", niveauLabel()],
  ]) {
    const s = el("div", "stat");
    s.append(el("span", "lbl", label), el("strong", "", value));
    stats.append(s);
  }
  return card(sub, stats);
}

// Le niveau affiché est celui du profil : vérifié par le diagnostic s'il l'a été,
// sinon celui que l'apprenant a déclaré.
function niveauLabel() {
  const p = data.profile || {};
  if (p.level_verified) return `${p.level_verified} vérifié`;
  return p.level ? `${p.level} déclaré` : "—";
}

function profil() {
  const p = data.profile || {};
  if (!p.objective) return null;
  const s = card(el("h2", "", "Profil d'apprentissage"));
  s.append(el("p", "", `Objectif : ${p.objective}`));
  s.append(el("p", "muted", `Niveau : ${niveauLabel()}`));
  if (p.cadence) s.append(el("p", "muted", `Cadence souhaitée : ${p.cadence}`));
  if (p.context) s.append(el("p", "muted", `Contexte donné au coach : ${p.context}`));
  return s;
}

const FELT = { trop_facile: "trop facile", bien: "juste bien", trop_dur: "trop dur", non_dit: "non dit" };

function calibrage() {
  const entries = data.calibrage || [];
  if (!entries.length) return null;
  const s = card(el("h2", "", "Calibrage des séances"));
  s.append(el("p", "muted",
    "Ressenti déclaré à la clôture, lecture du coach et réglage retenu pour la séance suivante."));
  const ol = el("ol", "hist");
  for (const c of entries.slice(0, 12)) {
    const li = el("li");
    li.append(el("b", "", `${fmtShort(c.date)} · ${FELT[c.felt] || c.felt}`));
    li.append(el("p", "", c.observation));
    li.append(el("p", "muted", `Réglage retenu : ${c.change}`));
    if (c.carry) li.append(el("p", "muted", `À surveiller : ${c.carry}`));
    ol.append(li);
  }
  s.append(ol);
  return s;
}

function videos() {
  const list = data.ressources || [];
  if (!list.length) return null;
  const s = card(el("h2", "", "Vidéos validées pour l'écoute"));
  s.append(el("p", "muted",
    "Cherchées puis gardées par toi à la mise en route : le coach s'en sert pour l'écoute."));
  const ul = el("ul", "hist");
  for (const r of list) {
    const li = el("li");
    li.append(Object.assign(document.createElement("a"),
      { href: r.url, target: "_blank", rel: "noopener", textContent: r.title }));
    const meta = [r.channel, r.duration ? `${Math.round(r.duration / 60)} min` : ""].filter(Boolean).join(" · ");
    if (meta) li.append(el("p", "muted", meta));
    ul.append(li);
  }
  s.append(ul);
  return s;
}

function depart() {
  const s = card(el("h2", "", "Prochain départ"));
  const p = el("p", "", data.resume || data.next);
  tagTarget(p);
  const cta = Object.assign(document.createElement("a"),
    { className: "cta", href: "/#seance", textContent: "Lancer la séance" });
  const review = el("p", "muted");
  if (data.review_engine === "anki") {
    const pkg = `${data.language}-tout.apkg`;
    review.append(Object.assign(document.createElement("a"),
      { href: `/api/anki/${pkg}`, download: pkg, textContent: "Paquet Anki complet" }),
      " · AnkiDroid gère les échéances, ses révisions ne remontent pas ici.");
  } else {
    review.textContent = `${data.cartes_dues} carte(s) à revoir.`;
  }
  s.append(p, cta, review);
  if (data.jours_sans_trace.length)
    s.append(el("p", "absence",
      `${data.jours_sans_trace.length} jour(s) passé(s) sans séance enregistrée. Une séance faite mais non sauvegardée peut être ajoutée par le coach.`));
  return s;
}

function calendar() {
  const byDate = new Map(data.days.map((d) => [d.date, d]));
  const start = parseDay(data.start);
  // Sans échéance, la chronologie s'arrête à aujourd'hui.
  const target = data.target ? parseDay(data.target) : parseDay(data.date);
  const monday = new Date(start);
  monday.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  const cal = el("div", "cal");
  for (const w = new Date(monday); w <= target; w.setDate(w.getDate() + 7)) {
    const col = el("div", "week");
    let wmin = 0;
    for (let i = 0; i < 7; i++) {
      const d = new Date(w);
      d.setDate(w.getDate() + i);
      const date = iso(d);
      if (d < start || d > target) { col.append(el("span", "day out")); continue; }
      const rec = byDate.get(date);
      const status = rec ? rec.status : "avenir";
      wmin += rec ? rec.minutes : 0;
      const b = el("button", "day d-" + status);
      b.type = "button";
      const label = `${fmtFull(date)} · ${LABELS[status]}` + (rec && rec.minutes ? ` · ${rec.minutes} min` : "");
      b.title = label;
      b.setAttribute("aria-label", label);
      b.dataset.date = date;
      if (date === data.date) b.classList.add("today");
      if (date === selected) b.classList.add("sel");
      b.onclick = () => selectDay(date);
      col.append(b);
    }
    const tot = el("small", "wtot", wmin ? `${wmin}′` : "");
    if (wmin) tot.title = `${wmin} min cette semaine`;
    col.append(tot);
    cal.append(col);
  }
  return cal;
}

function legend() {
  const l = el("p", "legend");
  for (const [cls, txt] of [["d-complete", "Terminée"], ["d-partielle", "Partielle"],
                            ["d-sans_trace", "Sans trace"], ["d-avenir", "À venir"]]) {
    const key = el("span", "lkey");
    key.append(el("i", "sw " + cls), " " + txt);
    l.append(key);
  }
  return l;
}

function selectDay(date) {
  selected = date;
  document.querySelectorAll(".day.sel").forEach((x) => x.classList.remove("sel"));
  const b = document.querySelector(`.day[data-date="${date}"]`);
  if (b) b.classList.add("sel");
  renderDetail();
}

function renderDetail() {
  const box = $("day-detail");
  const rec = data.days.find((d) => d.date === selected);
  if (!rec) { box.replaceChildren(el("b", "", `${fmtFull(selected)} · à venir`)); return; }
  const sessions = data.sessions.filter((s) => s.date === selected);
  const head = el("b", "", `${fmtFull(selected)} · ${LABELS[rec.status]} · ${rec.minutes} min`
    + (sessions.length > 1 ? ` · ${sessions.length} séances` : ""));
  const ul = el("ul");
  for (const r of rec.recaps) ul.append(el("li", "", r));
  box.replaceChildren(head, ul);
  tagTarget(box);
}

function minutesChart() {
  const days = data.days;
  const byDate = new Map();
  for (const s of data.sessions) {
    if (!byDate.has(s.date)) byDate.set(s.date, []);
    byDate.get(s.date).push(s.minutes);
  }
  const cell = 9, left = 34, top = 12, base = 132, H = 160;
  const W = left + days.length * cell + 8;
  const yMax = Math.ceil(Math.max(30, ...days.map((d) => d.minutes)) / 30) * 30;
  const Y = (v) => base - (v / yMax) * (base - top);
  const g = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, class: "bars", role: "img",
                         "aria-label": "Minutes pratiquées par jour, une colonne par jour, empilée par séance" });
  for (let v = 0; v <= yMax; v += 30)
    g.append(svg("line", { x1: left, x2: W - 4, y1: Y(v), y2: Y(v), class: "grid" }),
             svg("text", { x: 2, y: Y(v) + 3, class: "axis" }, String(v)));
  days.forEach((d, i) => {
    const x = left + 2 + i * cell;
    let y = base;
    for (const m of byDate.get(d.date) || []) {
      const h = Math.max(1, (m / yMax) * (base - top));
      y -= h;
      const r = svg("rect", { x, y, width: cell - 3, height: h, class: "seg" });
      r.append(svg("title", {}, `${d.date} · ${m} min`));
      g.append(r);
    }
    const hit = svg("rect", { x: x - 1, y: top, width: cell, height: base - top, class: "hit" });
    hit.append(svg("title", {}, `${fmtShort(d.date)} · ${d.minutes} min`));
    hit.addEventListener("click", () => {
      selectDay(d.date);
      $("day-detail").scrollIntoView({ block: "nearest" });
    });
    g.append(hit);
    const dt = parseDay(d.date);
    if (dt.getDay() === 1 || i === 0)
      g.append(svg("text", { x, y: H - 8, class: "axis" }, `${dt.getDate()}/${dt.getMonth() + 1}`));
  });
  const wrap = el("div", "chart-scroll");
  wrap.append(g);
  requestAnimationFrame(() => { wrap.scrollLeft = wrap.scrollWidth; });
  return wrap;
}

function recapTable() {
  const det = el("details", "recap");
  det.append(el("summary", "", "Récapitulatif de chaque jour"));
  const t = el("table");
  const tr = el("tr");
  for (const h of ["Date", "Statut", "Minutes", "Travail réalisé"]) tr.append(el("th", "", h));
  const thead = el("thead");
  thead.append(tr);
  const tbody = el("tbody");
  for (const d of [...data.days].reverse()) {
    const row = el("tr");
    const th = el("th", "", d.date);
    th.scope = "row";
    const work = el("td", "", d.recaps.join(" · ") || "—");
    tagTarget(work);
    row.append(th, el("td", "", LABELS[d.status]), el("td", "", String(d.minutes)), work);
    tbody.append(row);
  }
  t.append(thead, tbody);
  const wrap = el("div", "tablewrap");
  wrap.append(t);
  det.append(wrap);
  return det;
}

function takeCard(r, caption) {
  const a = el("article", "take");
  if (caption) a.append(el("span", "cap", caption));
  a.append(el("b", "", fmtShort(r.date) + (r.seconds != null ? ` · ${Math.round(r.seconds)} s` : "")));
  if (r.missing) a.append(el("p", "", "Fichier audio manquant."));
  else a.append(Object.assign(document.createElement("audio"),
    { controls: true, preload: "none", src: `/api/audio/${r.path}` }));
  if (r.note) {
    const p = el("p", "", r.note);
    tagTarget(p);
    a.append(p);
  }
  return a;
}

function replays() {
  const s = card(el("h2", "", "Premier essai ↔ dernier essai"),
    el("p", "muted", "Même sujet et même mode : la première prise, puis la plus récente. Les durées n'indiquent pas la qualité."));
  const groups = [];
  for (const task of TASKS) for (const mode of MODES) {
    const takes = data.recordings.filter((r) => r.task === task && r.mode === mode);
    if (takes.length) groups.push({ task, mode, takes });
  }
  if (!groups.length) {
    s.append(el("div", "empty",
      "Ton premier replay attend sa voix. Enregistre 30 à 60 secondes pendant une séance : il apparaîtra ici."));
    return s;
  }
  for (const g of groups) {
    s.append(el("h3", "", `${cap(KO_LABELS[g.task])} · ${KO_LABELS[g.mode]}`));
    const pair = el("div", "pair");
    pair.append(takeCard(g.takes[0], "Première prise"));
    pair.append(g.takes.length > 1
      ? takeCard(g.takes[g.takes.length - 1], "Plus récente")
      : el("article", "take ghost", "La prochaine prise comparable apparaîtra ici."));
    s.append(pair);
    if (g.takes.length > 2) {
      const det = el("details");
      det.append(el("summary", "", `Prises intermédiaires (${g.takes.length - 2})`));
      for (const r of g.takes.slice(1, -1)) det.append(takeCard(r));
      s.append(det);
    }
  }
  return s;
}

function curves() {
  const cps = data.checkpoints;
  if (!cps.length)
    return el("p", "muted", "Les courbes apparaîtront après un bilan. « Non évalué » ne signifie pas zéro.");
  const begin = parseDay(cps[0].date), end = parseDay(cps[cps.length - 1].date);
  const span = Math.max(1, (end - begin) / DAY_MS);
  const X = (d) => 45 + 610 * (parseDay(d) - begin) / DAY_MS / span;
  const Y = (v) => 185 - 40 * v;
  const g = svg("svg", { viewBox: "0 0 710 220", class: "curves", role: "img",
                         "aria-label": "Évolution des scores de 0 à 4 ; valeurs exactes dans le tableau" });
  for (let i = 0; i <= 4; i++)
    g.append(svg("line", { x1: 45, x2: 665, y1: Y(i), y2: Y(i), class: "grid" }),
             svg("text", { x: 20, y: Y(i) + 4, class: "axis" }, String(i)));
  const legend = el("p", "serlegend");
  Object.keys(SKILLS).forEach((k, i) => {
    const name = el("span", "c", SKILLS[k]);
    name.style.setProperty("--c", `var(--ser${i + 1})`);
    legend.append(legend.children.length ? " · " : "", name);
    const pts = [];
    const dots = [];
    for (const c of cps) {
      const v = c.scores[k];
      if (v == null || c.provisional) continue;
      const x = X(c.date), y = Y(v);
      pts.push(`${x},${y}`);
      const dot = svg("circle", { cx: x, cy: y, r: 5, class: "c" });
      dot.style.setProperty("--c", `var(--ser${i + 1})`);
      dot.append(svg("title", {}, `${SKILLS[k]} · ${c.date} : ${v}/4`));
      dots.push(dot);
    }
    if (pts.length > 1) {
      const line = svg("polyline", { points: pts.join(" "), class: "c" });
      line.style.setProperty("--c", `var(--ser${i + 1})`);
      g.append(line);
    }
    for (const d of dots) g.append(d);
  });
  g.append(svg("text", { x: 45, y: 215, class: "axis" }, cps[0].date),
           svg("text", { x: 575, y: 215, class: "axis" }, cps[cps.length - 1].date));
  const box = el("div");
  box.append(legend, g);
  return box;
}

function checkpointTable() {
  if (!data.checkpoints.length) return el("div", "empty", "Aucune mesure pour le moment.");
  const t = el("table");
  t.append(el("caption", "", "Bilans observés · « — » = non évalué"));
  const tr = el("tr");
  tr.append(el("th", "", "Date"));
  for (const n of Object.values(SKILLS)) tr.append(el("th", "", n));
  tr.append(el("th", "", "Contexte"));
  const thead = el("thead");
  thead.append(tr);
  const tbody = el("tbody");
  for (const c of data.checkpoints) {
    const row = el("tr");
    const th = el("th", "", c.date);
    th.scope = "row";
    row.append(th);
    for (const k of Object.keys(SKILLS))
      row.append(el("td", "", c.scores[k] == null ? "—" : `${c.scores[k]} / 4`));
    const ctx = c.provisional ? "À reconfirmer" : (c.independent && c.unseen) ? "Validation" : "Entraînement";
    const td = el("td", "", ctx);
    const det = el("details");
    det.append(el("summary", "", "Preuves"));
    for (const k of Object.keys(SKILLS))
      if (c.evidence[k]) {
        const p = el("p", "", `${SKILLS[k]} : ${c.evidence[k]}`);
        tagTarget(p);
        det.append(p);
      }
    if (c.audit_note) det.append(el("p", "muted", c.audit_note));
    td.append(det);
    row.append(td);
    tbody.append(row);
  }
  t.append(thead, tbody);
  const wrap = el("div", "tablewrap");
  wrap.append(t);
  return wrap;
}

function skills() {
  const s = card(el("h2", "", "Ce que tu arrives à faire"),
    el("p", "muted", "LP : meilleurs paliers validés sans aide sur une variante nouvelle. Le rang suit la compétence la moins avancée."));
  const measured = new Set();
  for (const c of data.checkpoints)
    if (c.independent && c.unseen && !c.provisional)
      for (const [k, v] of Object.entries(c.scores)) if (v != null) measured.add(k);
  const meters = el("div", "meters");
  for (const [k, name] of Object.entries(SKILLS)) {
    const row = el("div", "mrow");
    row.append(el("label", "", `${name} · ` + (measured.has(k) ? `meilleur palier ${data.meilleurs_paliers[k]}/4` : "à mesurer")));
    if (measured.has(k))
      row.append(Object.assign(document.createElement("meter"), { min: 0, max: 4, value: data.meilleurs_paliers[k] }));
    meters.append(row);
  }
  s.append(meters, curves(), checkpointTable());
  return s;
}

function sessionList() {
  const s = card(el("h2", "", "Historique des séances"));
  if (!data.sessions.length) {
    s.append(el("p", "muted", "Aucune séance effectuée. Le diagnostic sera le point de départ."));
    return s;
  }
  const ol = el("ol", "hist");
  for (const sess of [...data.sessions].reverse()) {
    const li = el("li");
    li.append(el("b", "", `${fmtShort(sess.date)} · ${sess.minutes} min · ${sess.kind}`));
    li.append(el("p", "", sess.summary));
    const det = el("details");
    det.append(el("summary", "", "Travail observé et corrections"));
    det.append(el("p", "", sess.evidence));
    if (sess.completion_evidence)
      det.append(el("p", "", "Preuve de complétion : " + sess.completion_evidence));
    if (sess.errors && sess.errors.length) {
      const ul = el("ul", "errs");
      for (const e of sess.errors) {
        const li2 = el("li");
        if (typeof e === "string") li2.textContent = e;
        else {
          li2.append(el("span", "", e.attempt || ""), " → ", el("b", "", e.correction || ""));
          if (e.why) li2.append(el("br"), el("small", "", e.why));
        }
        ul.append(li2);
      }
      det.append(ul);
    }
    li.append(det);
    tagTarget(li);
    ol.append(li);
  }
  s.append(ol);
  return s;
}

// ---- page ----

function render() {
  dash.replaceChildren(...[
    hero(), profil(), depart(),
    card(el("h2", "", "Activité"), calendar(), legend(), (() => {
      const d = el("div"); d.id = "day-detail"; d.setAttribute("aria-live", "polite"); return d;
    })(), el("h3", "", "Minutes par jour"), minutesChart(), recapTable()),
    replays(), skills(), sessionList(), calibrage(), videos(),
  ].filter(Boolean));
  renderDetail();
}

async function load() {
  const res = await fetch("/api/progress");
  if (res.status === 401) { location.href = "/login"; return; }
  if (!res.ok) {
    dash.replaceChildren(card(el("div", "empty",
      "Aucune progression pour l'instant : elle apparaîtra après la première séance. "
      + "Si c'est un premier lancement, la mise en route se fait sur /onboarding.")));
    return;
  }
  data = await res.json();
  selected = data.date;
  render();
}

document.addEventListener("visibilitychange", () => { if (!document.hidden && data) load(); });

const root = document.documentElement, themeBtn = $("theme");
function applyTheme(theme) {
  root.dataset.theme = theme;
  themeBtn.setAttribute("aria-pressed", theme === "dark");
  document.querySelector("meta[name=theme-color]").content = getComputedStyle(root).getPropertyValue("--surface").trim();
}
themeBtn.onclick = () => applyTheme(localStorage.theme = root.dataset.theme === "dark" ? "light" : "dark");
applyTheme(root.dataset.theme);

// Le repérage d'écriture dépend de la langue du carnet.
(async () => {
  try {
    const p = await (await fetch("/api/profile")).json();
    setTarget(p.language, p.script);
  } catch {}
  load();
})();
