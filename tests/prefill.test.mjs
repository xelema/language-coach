// Runs the numbered-reply prefill from app/static/app.js against a stub DOM,
// so the shipped functions are tested, not copies.
// Usage: node tests/prefill.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../app/static/app.js", import.meta.url), "utf8");

const extract = (re, name) => {
  const m = re.exec(src);
  assert(m, `${name} not found in app.js`);
  return m[1];
};
const fn = (name) => extract(new RegExp(`^((?:async )?function ${name}\\b[\\s\\S]*?\\n})`, "m"), name);
const cnst = (name) => extract(new RegExp(`^(const ${name}\\b[\\s\\S]*?\\n};?)`, "m"), name);
const line = (name) => extract(new RegExp(`^(const ${name} = .*)$`, "m"), name);

// ---- minimal DOM/browser stubs ----
const el = () => {
  const o = {
    textContent: "", dataset: {}, style: {}, hidden: false,
    setAttribute() {}, removeAttribute() {}, remove() { this.removed = true; },
    appendChild() {}, append() {}, replaceChildren() {}, querySelectorAll() { return []; },
    classList: { add() {}, remove() {}, toggle() {} },
  };
  Object.defineProperty(o, "innerHTML", {
    get() { return this._html || ""; },
    set(v) { this._html = v; this.textContent = v; },
  });
  return o;
};

const __els = {};
const __input = { value: "", sel: null, setSelectionRange(a, b) { this.sel = [a, b]; } };
const __sent = [];

const code = `
  const document = { getElementById: (id) => __els[id] ??= __el() };
  const $ = (id) => document.getElementById(id);
  var view = null;
  const input = __input;
  const log = __el(), slog = __el();
  let prefilled = "";
  const add = (cls, text = "", target = log) => { const e = __el(); e.textContent = text; return e; };
  const chip = () => __el();
  const toolChips = () => {};
  const markdown = (s) => s;
  const tagTarget = () => {};
  const nearBottom = () => true;
  const toBottom = () => {};
  const syncButtons = () => {};
  const renderHeader = () => {}, renderRec = () => {}, setTimer = () => {};
  const renderMessage = () => __el();
  const loadSide = async () => {}, loadThreads = async () => {};
  const requestAnimationFrame = (f) => f();
  const streamTurn = async (body) => { __sent.push(body); };
  var fetch = async () => { throw new Error("fetch not stubbed"); };
  ${line("TASK_MARK")}
  ${cnst("numberedTail")}
  ${fn("prefillNumbered")}
  ${fn("streamInto")}
  ${fn("selectThread")}
  ${fn("send")}
  __api = {
    numberedTail, prefillNumbered, streamInto, selectThread, send, input, log, slog,
    getView: () => view,
    setView: (v) => { view = v; },
    getPrefilled: () => prefilled,
    setPrefilled: (v) => { prefilled = v; },
    setFetch: (f) => { fetch = f; },
  };
`;

const __el = el;
let __api;
eval(code);

const api = __api;
const sse = (events) => new ReadableStream({
  start(c) {
    c.enqueue(new TextEncoder().encode(events.map((e) => JSON.stringify(e) + "\n").join("")));
    c.close();
  },
});

const reset = () => {
  __input.value = "";
  __input.sel = null;
  __sent.length = 0;
  api.setPrefilled("");
  api.setView({ id: 1, kind: "session", closed: false });
};

const tests = [];
const test = (name, f) => tests.push([name, f]);

// ---- numberedTail detection ----

const tails = [
  ["simple 3 items", "Écris-moi :\n1. Ce que tu penses\n2. ta journée\n3. ton film", 3],
  ["trailing task mark", "Réponds :\n1. un\n2. deux [tâche: deux lignes]", 2],
  ["mark on its own line", "Réponds :\n1. un\n2. deux\n[tâche: deux lignes]\n", 2],
  ["paren style", "Réponds :\n1) un\n2) deux", 2],
  ["indented + bold items", "Plan :\n  1. **Sujet** : avis\n  2. **Jour** : journée", 2],
  ["list not at end", "Fais :\n1. écoute\n2. répète\n\nTu as cinq minutes.", 0],
  ["single item", "Un point :\n1. le verbe", 0],
  ["does not start at 1", "Suite :\n2. b\n3. c", 0],
  ["gap in numbering", "Réponds :\n1. a\n3. c", 0],
  ["no list", "Bonne réponse, on continue.", 0],
  ["long list", "Note :\n1. a\n2. b\n3. c\n4. d\n5. e", 5],
  ["blank line inside list", "Réponds :\n1. a\n\n2. b", 0],
];
for (const [name, text, want] of tails) {
  test(`numberedTail: ${name}`, () => assert.equal(api.numberedTail(text), want));
}

// ---- prefillNumbered guards ----

test("prefill fills an empty input and places the cursor after '1. '", () => {
  api.prefillNumbered("Écris-moi :\n1. Ce que tu penses\n2. ta journée\n3. ton film");
  assert.equal(__input.value, "1. \n2. \n3. ");
  assert.deepEqual(__input.sel, [3, 3]);
});

test("no prefill when the thread is closed", () => {
  api.setView({ id: 1, kind: "session", closed: true });
  api.prefillNumbered("Liste :\n1. a\n2. b");
  assert.equal(__input.value, "");
});

test("no prefill while a recording request is pending", () => {
  api.setView({ id: 1, kind: "session", closed: false, pending_request: { task: "journee" } });
  api.prefillNumbered("Liste :\n1. a\n2. b");
  assert.equal(__input.value, "");
});

test("a typed draft is never clobbered", () => {
  __input.value = "ma réponse en cours";
  api.prefillNumbered("Liste :\n1. a\n2. b");
  assert.equal(__input.value, "ma réponse en cours");
});

test("an untouched skeleton is cleared when the next turn has no list", () => {
  api.prefillNumbered("Liste :\n1. a\n2. b\n3. c");
  assert.equal(__input.value, "1. \n2. \n3. ");
  api.prefillNumbered("Merci, on passe à autre chose.");
  assert.equal(__input.value, "");
});

test("an untouched skeleton is replaced by the new count", () => {
  api.prefillNumbered("Liste :\n1. a\n2. b\n3. c");
  api.prefillNumbered("Encore :\n1. x\n2. y");
  assert.equal(__input.value, "1. \n2. ");
});

test("an edited skeleton counts as a draft and is kept", () => {
  api.prefillNumbered("Liste :\n1. a\n2. b");
  __input.value = "1. ma phrase\n2. ";
  api.prefillNumbered("Autre :\n1. x\n2. y\n3. z");
  assert.equal(__input.value, "1. ma phrase\n2. ");
});

// ---- streamInto end to end ----

test("stream end prefills from the last coach bubble", async () => {
  api.setFetch(async () => ({
    ok: true,
    body: sse([
      { type: "text", text: "Écris-moi trois phrases :\n1. Ce que tu penses\n" },
      { type: "text", text: "2. ta journée\n3. ton film [tâche: trois phrases]" },
      { type: "done" },
    ]),
  }));
  await api.streamInto(1, api.log, {}, async () => {});
  assert.equal(__input.value, "1. \n2. \n3. ");
  assert.deepEqual(__input.sel, [3, 3]);
});

test("a tool chip between segments keeps the last text as reference", async () => {
  api.setFetch(async () => ({
    ok: true,
    body: sse([
      { type: "text", text: "D'abord une carte." },
      { type: "tool", label: "⚙ progression enregistrée" },
      { type: "text", text: "Maintenant :\n1. un\n2. deux" },
      { type: "done" },
    ]),
  }));
  await api.streamInto(1, api.log, {}, async () => {});
  assert.equal(__input.value, "1. \n2. ");
});

test("a turn ending on a tool chip still uses the last verbal segment", async () => {
  api.setFetch(async () => ({
    ok: true,
    body: sse([
      { type: "text", text: "Note :\n1. un\n2. deux" },
      { type: "tool", label: "⚙ progression enregistrée" },
      { type: "done" },
    ]),
  }));
  await api.streamInto(1, api.log, {}, async () => {});
  assert.equal(__input.value, "1. \n2. ");
});

test("a turn with text after the list does not prefill", async () => {
  api.setFetch(async () => ({
    ok: true,
    body: sse([
      { type: "text", text: "Étapes :\n1. écoute\n2. répète\n\nPrends ton temps." },
      { type: "done" },
    ]),
  }));
  await api.streamInto(1, api.log, {}, async () => {});
  assert.equal(__input.value, "");
});

test("the side pane never prefills the main input", async () => {
  api.setFetch(async () => ({
    ok: true,
    body: sse([{ type: "text", text: "Liste :\n1. a\n2. b" }, { type: "done" }]),
  }));
  await api.streamInto(2, api.slog, {}, async () => {});
  assert.equal(__input.value, "");
});

test("a mid-typing reply is preserved when the stream ends", async () => {
  api.setFetch(async () => ({
    ok: true,
    body: sse([{ type: "text", text: "Liste :\n1. a\n2. b" }, { type: "done" }]),
  }));
  __input.value = "déjà en train d'écrire";
  await api.streamInto(1, api.log, {}, async () => {});
  assert.equal(__input.value, "déjà en train d'écrire");
});

// ---- selectThread ----

test("opening a thread prefills from its last coach message", async () => {
  api.setFetch(async (url) => ({
    ok: true,
    json: async () => url.endsWith("/messages")
      ? [
          { role: "model", text: "Écris :\n1. a\n2. b\n3. c", kind: "message" },
        ]
      : { id: 1, kind: "session", closed: false },
  }));
  await api.selectThread(1);
  assert.equal(__input.value, "1. \n2. \n3. ");
});

test("no prefill when the last message is the learner's", async () => {
  api.setFetch(async (url) => ({
    ok: true,
    json: async () => url.endsWith("/messages")
      ? [
          { role: "model", text: "Écris :\n1. a\n2. b", kind: "message" },
          { role: "user", text: "1. aa\n2. bb", kind: "message" },
        ]
      : { id: 1, kind: "session", closed: false },
  }));
  await api.selectThread(1);
  assert.equal(__input.value, "");
});

test("reopening a closed session does not prefill", async () => {
  api.setFetch(async (url) => ({
    ok: true,
    json: async () => url.endsWith("/messages")
      ? [{ role: "model", text: "Écris :\n1. a\n2. b", kind: "message" }]
      : { id: 1, kind: "session", closed: true },
  }));
  await api.selectThread(1);
  assert.equal(__input.value, "");
});

test("switching to a thread without a list clears an untouched skeleton", async () => {
  api.prefillNumbered("Liste :\n1. a\n2. b");
  assert.equal(__input.value, "1. \n2. ");
  api.setFetch(async (url) => ({
    ok: true,
    json: async () => url.endsWith("/messages")
      ? [{ role: "model", text: "On continue sans liste.", kind: "message" }]
      : { id: 2, kind: "chat", closed: false },
  }));
  await api.selectThread(2);
  assert.equal(__input.value, "");
});

// ---- send ----

test("send clears the skeleton state", async () => {
  api.prefillNumbered("Liste :\n1. a\n2. b");
  __input.value = "1. aa\n2. bb";
  await api.send();
  assert.equal(__input.value, "");
  assert.equal(api.getPrefilled(), "");
  assert.deepEqual(__sent, [{ event: "message", text: "1. aa\n2. bb" }]);
});

// ---- run ----

let failed = 0;
for (const [name, f] of tests) {
  reset();
  try {
    await f();
    console.log("ok   " + name);
  } catch (e) {
    failed++;
    console.log("FAIL " + name + " — " + e.message);
  }
}
console.log(`\n${tests.length - failed}/${tests.length} tests passed`);
process.exitCode = failed ? 1 : 0;
