/* Rewisp landing — scroll reveal + the animated demos.
   Every demo is a small state machine that plays when it scrolls into view
   (via IntersectionObserver) and, for the looping ones, keeps cycling. */

const sleep = ms => new Promise(r => setTimeout(r, ms));
const $ = sel => document.querySelector(sel);
const $$ = sel => [...document.querySelectorAll(sel)];

/* ── scroll reveal ── */
const revealObs = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) { e.target.classList.add("in"); revealObs.unobserve(e.target); }
}, { threshold: 0.15 });
$$(".reveal").forEach(el => revealObs.observe(el));

/* Run a demo's play() once it first becomes visible. `loop` demos re-arm
   themselves; `once` demos fire a single time. */
function whenVisible(el, fn, { once = false } = {}) {
  if (!el) return;
  let started = false;
  const obs = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting && !started) { started = true; fn(); if (once) obs.unobserve(el); }
    }
  }, { threshold: 0.4 });
  obs.observe(el);
}

/* ── hero search demo ── */
(function heroDemo() {
  const demos = [
    { q: "what was due on july 12?", a: "Quiz 3.2 — due July 12 at 11:59 PM",
      d: "11-point homework quiz on Canvas, seen this afternoon.", s: "Canvas · Today 4:31 PM", e: "Apple on-device" },
    { q: "that camping video from last night?", a: "3 Days Stove Hut Camping in Heavy Snowfall",
      d: "Watched on YouTube around 1 AM.", s: "YouTube · Yesterday 1:02 AM", e: "Gemini" },
    { q: "what's my student ID?", a: "A18…4291",
      d: "Pulled straight from your Vault — no model involved.", s: "Vault · trusted", e: "Vault" },
    { q: "summarize what I did this morning", a: "Mostly Rewisp — tuning the on-device prompt in ask.py, plus a Calc III quiz on Canvas.",
      d: "Three apps, 2 hours, stitched from 14 wisps.", s: "4 sources · Today", e: "Claude" },
  ];
  const qEl = $("#q"), ans = $("#answer");
  if (!qEl) return;
  let di = 0, playing = false;
  async function type(text) {
    qEl.textContent = "";
    for (const ch of text) { qEl.textContent += ch; await sleep(42 + Math.random() * 38); }
  }
  async function loop() {
    if (playing) return; playing = true;
    for (;;) {
      const d = demos[di % demos.length]; di++;
      ans.classList.remove("show");
      await type(d.q);
      await sleep(480);
      $("#a-main").textContent = d.a;
      $("#a-detail").textContent = d.d;
      $("#a-src").textContent = d.s;
      $("#a-engine").textContent = d.e;
      ans.classList.add("show");
      await sleep(3900);
      qEl.textContent = ""; await sleep(380);
    }
  }
  whenVisible($(".demo"), loop);
})();

/* ── form autofill demo ── */
(function formDemo() {
  const el = $("#form-demo");
  if (!el) return;
  const fields = $$("#form-demo .field");
  async function play() {
    for (const f of fields) { f.classList.remove("filling", "done"); const v = f.querySelector(".val"); if (!f.classList.contains("skip")) v.textContent = ""; }
    await sleep(500);
    for (const f of fields) {
      f.classList.add("filling");
      await sleep(420);
      if (!f.classList.contains("skip")) {
        const target = f.dataset.val || "";
        const v = f.querySelector(".val");
        for (const ch of target) { v.textContent += ch; await sleep(24); }
      }
      f.classList.remove("filling"); f.classList.add("done");
      await sleep(260);
    }
    await sleep(2600);
    play();
  }
  whenVisible(el, play);
})();

/* ── engine fallback chain demo ── */
(function chainDemo() {
  const el = $("#chain-demo");
  if (!el) return;
  const nodes = $$("#chain-demo .node");
  const reset = () => nodes.forEach(n => { n.className = "node"; n.querySelector(".st").innerHTML = n.dataset.idle; });
  async function play() {
    reset();
    await sleep(600);
    // Apple tries first, whiffs
    nodes[0].classList.add("active");
    nodes[0].querySelector(".st").innerHTML = '<span class="spinner"></span>';
    await sleep(1100);
    nodes[0].classList.remove("active"); nodes[0].classList.add("whiff");
    nodes[0].querySelector(".st").textContent = "thin answer ↓";
    await sleep(700);
    // escalate to Gemini
    nodes[1].classList.add("active");
    nodes[1].querySelector(".st").innerHTML = '<span class="spinner"></span>';
    await sleep(1300);
    nodes[1].classList.remove("active"); nodes[1].classList.add("win");
    nodes[1].querySelector(".st").textContent = "answered ✓";
    await sleep(3200);
    play();
  }
  whenVisible(el, play);
})();

/* nightly-digest lines assemble purely in CSS (#digest-demo.in .dline) off the
   reveal class — same reason as the time bars. */

/* time-tracking bars are filled purely in CSS (#time-demo.in .fill) off the
   reveal class, so they work even if this script is cached or fails. */

/* ── capture / wisp flow ── */
(function captureViz() {
  const el = $("#capture-viz");
  if (!el) return;
  const apps = $$("#capture-viz .aname");
  const dot = $("#wisp-dot");
  const store = $("#capture-viz .stack");
  const cntEl = $("#wisp-count");
  let count = 1240;
  async function play() {
    for (let i = 0; i < apps.length; i++) {
      apps.forEach(a => a.classList.remove("hot"));
      apps[i].classList.add("hot");
      await sleep(560);
      // fling a wisp from the hot app to the store, distance computed so it lands
      const base = el.getBoundingClientRect().left;
      const from = apps[i].getBoundingClientRect().left - base + 20;
      const to = store.getBoundingClientRect().left - base + 12;
      dot.style.left = from + "px";
      dot.style.setProperty("--fx", (to - from) + "px");
      dot.classList.remove("fly"); void dot.offsetWidth; dot.classList.add("fly");
      await sleep(700);
      count += Math.floor(2 + Math.random() * 4);
      cntEl.textContent = count.toLocaleString();
      await sleep(500);
    }
    await sleep(700);
    play();
  }
  whenVisible(el, play);
})();

/* ── screenshot carousel: auto-advance 3s, arrows + dots, pause on hover ── */
(function carousel() {
  const root = document.getElementById("carousel");
  if (!root) return;
  const imgs = [...root.querySelectorAll(".car-frame img")];
  const cap = document.getElementById("car-cap");
  const dotsWrap = document.getElementById("car-dots");
  const stage = root.querySelector(".car-stage");
  let i = 0, timer = null;

  imgs.forEach((_, k) => {
    const b = document.createElement("button");
    b.setAttribute("aria-label", "Slide " + (k + 1));
    b.addEventListener("click", () => { go(k); restart(); });
    dotsWrap.appendChild(b);
  });
  const dots = [...dotsWrap.children];

  function go(k) {
    i = (k + imgs.length) % imgs.length;
    imgs.forEach((im, j) => im.classList.toggle("on", j === i));
    dots.forEach((d, j) => d.classList.toggle("on", j === i));
    cap.style.opacity = "0";
    setTimeout(() => { cap.textContent = imgs[i].dataset.cap; cap.style.opacity = "1"; }, 160);
  }
  const next = () => go(i + 1);
  const start = () => { timer = setInterval(next, 3000); };
  const restart = () => { clearInterval(timer); start(); };

  document.getElementById("car-next").addEventListener("click", () => { next(); restart(); });
  document.getElementById("car-prev").addEventListener("click", () => { go(i - 1); restart(); });
  stage.addEventListener("mouseenter", () => clearInterval(timer));
  stage.addEventListener("mouseleave", start);

  go(0);
  start();
})();

// Copy-email fallback: mailto: does nothing on plenty of setups (no default
// mail client, webmail-only, locked-down browsers), so the address is always
// available as plain text you can lift with one click.
(function () {
  var btn = document.getElementById("copyEmail");
  if (!btn) return;
  btn.addEventListener("click", function () {
    var email = btn.getAttribute("data-email");
    var done = function () {
      var was = btn.textContent;
      btn.textContent = "Copied";
      setTimeout(function () { btn.textContent = was; }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(email).then(done, fallback);
    } else {
      fallback();
    }
    function fallback() {
      var ta = document.createElement("textarea");
      ta.value = email;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { /* leave it visible */ }
      document.body.removeChild(ta);
    }
  });
})();

/* ── promises ──────────────────────────────────────────────────────────────
   Three beats, looping: the commitment is typed and caught, it's held while
   days pass, then it comes back on the morning it's due. Leads the grid
   because it's the one thing a plain screen recorder can't do. */
(function promiseDemo() {
  const root = document.getElementById("promise-demo");
  if (!root) return;

  const steps = [...root.querySelectorAll(".pr-step")];
  const typed = root.querySelector("#pr-typed");
  const t     = typed && typed.querySelector(".t");
  const caught= root.querySelector("#pr-caught");
  const due   = root.querySelector("#pr-due");
  const days  = [...root.querySelectorAll("#pr-days span")];
  const LINE  = "yeah I'll send it Friday";

  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  const show = (i) => steps.forEach((s, n) => s.classList.toggle("on", n === i));

  function reset() {
    if (t) t.textContent = "";
    typed && typed.classList.remove("done");
    caught && caught.classList.remove("on");
    due && due.classList.remove("hot");
    days.forEach(d => d.classList.remove("now"));
    show(0);
  }

  async function play() {
    reset();
    await wait(700);

    // 1 — typed, then noticed. The pause before "caught" matters: it reads as
    // Rewisp watching rather than Rewisp being told.
    for (let i = 1; i <= LINE.length; i++) {
      if (t) t.textContent = LINE.slice(0, i);
      await wait(38);
    }
    typed && typed.classList.add("done");
    await wait(500);
    caught && caught.classList.add("on");
    await wait(1500);

    // 2 — held, days ticking by
    show(1);
    await wait(700);
    for (let i = 0; i < days.length; i++) {
      days.forEach((d, n) => d.classList.toggle("now", n === i));
      if (i === days.length - 1) due && due.classList.add("hot");
      await wait(620);
    }
    await wait(700);

    // 3 — it comes back
    show(2);
    await wait(3600);

    play();
  }

  whenVisible(root, play);
})();

/* ── the day map: interactive ──────────────────────────────────────────────
   The static SVG in the markup is the fallback and renders fine on its own.
   This only ENHANCES it: controls are injected here, so a visitor with no JS
   (or a stale cache) still gets the picture rather than an empty box.

   It mirrors what the app actually does — hover to focus a place and its
   loops, click to reinstate the moment, replay or scrub the route — because
   the section above it promises these are live and not screenshots. */
(function dayMap() {
  const panel = $("#map-demo");
  if (!panel) return;
  const svg = panel.querySelector(".map-svg");
  const stage = panel.querySelector(".map-stage");
  const trace = panel.querySelector("#map-trace");
  const nodes = [...panel.querySelectorAll(".map-node")]
    .sort((a, b) => +a.dataset.i - +b.dataset.i);
  const edges = [...panel.querySelectorAll(".map-edge")];
  const labels = [...panel.querySelectorAll(".map-lab")];
  if (!svg || !trace || nodes.length === 0) return;

  // Taking over means turning off the CSS loop — otherwise the keyframes and
  // the scrubber fight over stroke-dashoffset and the line stutters.
  stage.classList.add("js");

  const len = trace.getTotalLength();
  trace.style.strokeDasharray = len;

  // Each label sits under a node; pair them up by proximity so hovering a dot
  // can lift its own label without hard-coding the mapping.
  const labelFor = new Map();
  for (const n of nodes) {
    const c = n.querySelector("circle");
    const cx = +c.getAttribute("cx"), cy = +c.getAttribute("cy");
    let best = null, bestD = 1e9;
    for (const l of labels) {
      const r = l.querySelector("rect");
      const lx = +r.getAttribute("x") + +r.getAttribute("width") / 2;
      const ly = +r.getAttribute("y");
      const d = Math.hypot(lx - cx, ly - cy);
      if (d < bestD) { bestD = d; best = l; }
    }
    if (best && bestD < 60 && !labelFor.has(best)) labelFor.set(best, n);
  }
  const ownLabel = n => [...labelFor.entries()].find(([, v]) => v === n)?.[0];

  /* controls */
  const ctl = document.createElement("div");
  ctl.className = "map-ctl";
  ctl.innerHTML =
    '<button class="map-btn" type="button" aria-label="Replay the day">' +
      '<span class="map-btn-ic">▶</span><span class="map-btn-tx">Replay</span></button>' +
    '<input class="map-scrub" type="range" min="0" max="1000" value="1000" ' +
      'aria-label="Scrub through the day">' +
    '<span class="map-time">2:30 PM</span>';
  stage.after(ctl);
  const btn = ctl.querySelector(".map-btn");
  const scrub = ctl.querySelector(".map-scrub");
  const timeEl = ctl.querySelector(".map-time");

  /* the moment card — what tapping a point does in the app */
  const card = document.createElement("div");
  card.className = "map-moment";
  card.hidden = true;
  ctl.after(card);

  const revealAt = i => nodes.length < 2 ? 0 : i / (nodes.length - 1);

  function render(p) {
    trace.style.strokeDashoffset = len * (1 - p);
    let latest = nodes[0];
    for (const n of nodes) {
      const shown = p >= revealAt(+n.dataset.i) - 0.001;
      n.classList.toggle("off", !shown);
      const l = ownLabel(n);
      if (l) l.classList.toggle("off", !shown);
      if (shown) latest = n;
    }
    for (const e of edges) {
      const on = p >= revealAt(+e.dataset.a) && p >= revealAt(+e.dataset.b);
      e.classList.toggle("off", !on);
    }
    timeEl.textContent = latest.dataset.time;
  }

  /* replay, driven by the clock rather than a stored value that gets stepped */
  let raf = 0;
  function play() {
    cancelAnimationFrame(raf);
    const dur = 4200, t0 = performance.now();
    const step = now => {
      const p = Math.min((now - t0) / dur, 1);
      scrub.value = String(Math.round(p * 1000));
      render(p);
      if (p < 1) raf = requestAnimationFrame(step);
      else btn.classList.remove("playing");
    };
    btn.classList.add("playing");
    raf = requestAnimationFrame(step);
  }

  btn.addEventListener("click", play);
  scrub.addEventListener("input", () => {
    cancelAnimationFrame(raf);
    btn.classList.remove("playing");
    render(+scrub.value / 1000);
  });

  /* hover / focus: bring one place and its loops forward, push the rest back */
  function focusNode(n) {
    panel.classList.add("focusing");
    for (const m of nodes) m.classList.toggle("hot", m === n);
    for (const l of labels) l.classList.toggle("hot", labelFor.get(l) === n);
    const i = n ? +n.dataset.i : -1;
    for (const e of edges) {
      e.classList.toggle("hot", +e.dataset.a === i || +e.dataset.b === i);
    }
  }
  function clearFocus() {
    panel.classList.remove("focusing");
    for (const m of nodes) m.classList.remove("hot");
    for (const l of labels) l.classList.remove("hot");
    for (const e of edges) e.classList.remove("hot");
  }

  /* click: reinstate the moment — the scene, and what sat either side of it */
  function reinstate(n) {
    const d = n.dataset;
    card.innerHTML =
      '<div class="mm-head"><b>' + d.label + '</b>' +
        '<span class="mm-meta">' + d.mins + ' · ' + d.visits + ' · ' + d.time + '</span></div>' +
      '<div class="mm-screen">' + d.moment + '</div>' +
      '<div class="mm-around"><span>before <b>' + d.before + '</b></span>' +
        '<span>after <b>' + d.after + '</b></span></div>';
    card.hidden = false;
    for (const m of nodes) m.classList.toggle("picked", m === n);
  }

  for (const n of nodes) {
    n.addEventListener("mouseenter", () => focusNode(n));
    n.addEventListener("mouseleave", clearFocus);
    n.addEventListener("focus", () => focusNode(n));
    n.addEventListener("blur", clearFocus);
    n.addEventListener("click", () => reinstate(n));
    n.addEventListener("keydown", e => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); reinstate(n); }
    });
  }

  // Someone who scrolls past should see it draw itself once, then it holds —
  // an endlessly looping line beside body copy is a distraction, not a demo.
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  render(1);
  if (!reduced) whenVisible(panel, () => { render(0); setTimeout(play, 220); }, { once: true });
})();

/* ── personas: which "you" a value belongs to ──────────────────────────────
   Interactive rather than a loop. The product decision IS the click, so the
   demo hands it over — but it also plays itself once on scroll, so a visitor
   who never touches it still sees what the feature does.

   Every value here is invented. Nothing from a real Vault goes on this page. */
(function personaDemo() {
  const el = $("#persona-demo");
  if (!el) return;
  const WHO = {
    school:   { email: "a.rivera@university.edu",  addr: "Rm 214, North Hall, Campus Dr", site: "portal.university.edu" },
    personal: { email: "alex.rivera@gmail.com",    addr: "88 Rosewood Ave, Apt 4",        site: "shop.example.com" },
    work:     { email: "alex@riveradesign.co",     addr: "1 Market St, Suite 900",        site: "invoices.example.com" },
  };
  const PHONE = "(555) 018-2245";          // shared: the same for every you
  const chips = $$("#persona-demo .pe-chip");
  const form = $("#persona-demo .pe-form");
  const note = $("#pe-note"), siteEl = $("#pe-site");
  let settled = false;

  async function pick(who, byUser) {
    const v = WHO[who];
    if (!v) return;
    for (const c of chips) c.setAttribute("aria-pressed", String(c.dataset.who === who));
    form.classList.add("swapping");
    await sleep(180);
    $("#pe-email").textContent = v.email;
    $("#pe-addr").textContent = v.addr;
    $("#pe-phone").textContent = PHONE;
    siteEl.innerHTML = '<span class="pe-dot"></span> ' + v.site;
    form.classList.remove("swapping");
    if (byUser) settled = true;
    siteEl.classList.toggle("settled", settled);
    note.textContent = settled
      ? "Settled. Rewisp won't ask again for this site — and it's one tap in Settings to change."
      : "Rewisp won't fill until you pick. After that this site is settled.";
  }

  for (const c of chips) c.addEventListener("click", () => pick(c.dataset.who, true));
  whenVisible(el, () => pick("school", false), { once: true });
})();
