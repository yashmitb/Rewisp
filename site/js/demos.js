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
