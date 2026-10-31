// Atlas agent orb (product: Call Crew): the bot's camera tile (M2.5a).
// Port of docs/design/agent-clips/orb-reference.jsx (shapeD, Orb, params, describe, AskText) to one
// <canvas> at 1280x720, vanilla JS, no build. The design's timeline is replaced by a live state machine:
// idle / listen / think / speak, each looping on its own period; a state change blends from the current
// frame over 0.8 s. Big blurs are drawn on small offscreen buffers and upscaled (cheap on Recall's CPU).
// API: window.CrewOrb.{init, setServerState, ask, askDone}; index.html owns WS + audio.
(function () {
  "use strict";
  var TAU = Math.PI * 2, OM = TAU / 4;
  function cl(v, a, b) { return Math.min(b, Math.max(a, v)); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function kk(t, a, b) { return cl((t - a) / (b - a), 0, 1); }
  function io(t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; }
  function out(t) { return 1 - Math.pow(1 - t, 3); }
  function md(x, D) { return ((x % D) + D) % D; }
  function hash(n) { var s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); }
  function noise(x) { var i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return hash(i) + (hash(i + 1) - hash(i)) * u; }
  function speechRaw(t, seed) {
    var syl = Math.pow(Math.max(0, Math.sin(t * 26.4 + noise(t * 0.9 + seed) * 6)), 0.7);
    var gate = cl((noise(t * 1.5 + seed + 10) - 0.22) / 0.2, 0, 1);
    return syl * gate * (0.5 + 0.5 * noise(t * 3.3 + seed + 20));
  }
  function speech(t, seed) {
    return speechRaw(t, seed) * 0.4 + speechRaw(t - 0.04, seed) * 0.3 +
      speechRaw(t - 0.08, seed) * 0.2 + speechRaw(t - 0.12, seed) * 0.1;
  }
  function sLoop(phi, D, seed, sp) {
    sp = sp || 1; var w = phi / D;
    return (1 - w) * speech(phi * sp + 40, seed) + w * speech((phi - D) * sp + 40, seed);
  }

  // ── palette ("Sunset") ──
  var COL = { O: "#FF8A1A", R: "#E0255E", PL: "#4A0F2A", CR: "#FFE3A3", INK: "#FFF3E6" };
  function hex(h) { var n = parseInt(h.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; }
  function toHex(c) { return "#" + c.map(function (v) { return Math.round(cl(v, 0, 255)).toString(16).padStart(2, "0"); }).join(""); }
  function tint(h, t) { return toHex(hex(h).map(function (v) { return v + (255 - v) * t; })); }
  function shade(h, t) { return toHex(hex(h).map(function (v) { return v * t; })); }
  function blend(a, b, t) { var B = hex(b); return toHex(hex(a).map(function (v, i) { return v + (B[i] - v) * t; })); }
  function rgba(a, b, t, al) {
    var A = hex(a), B = hex(b);
    return "rgba(" + Math.round(A[0] + (B[0] - A[0]) * t) + "," + Math.round(A[1] + (B[1] - A[1]) * t) + "," +
      Math.round(A[2] + (B[2] - A[2]) * t) + "," + (al == null ? 1 : al) + ")";
  }
  var PR = (function () {
    var a = COL.O, c = COL.R, d = COL.PL, w = COL.CR;
    return { h3: [a, shade(c, 0.75)], hm: [tint(a, 0.72), tint(a, 0.25)], h1: [c, a], top: [blend(c, d, 0.25), tint(c, 0.6)],
      mid: [tint(c, 0.18), "#fff6ea"], bot: [blend(c, a, 0.45), w], inn: [tint(a, 0.35), tint(w, 0.7)],
      rimA: [tint(a, 0.5), tint(c, 0.2)], rimB: [a, c], edge: [c, tint(a, 0.75)], shadeCol: blend(c, d, 0.6) };
  })();

  // harmonic speeds are multiples of 2π/4 s, so every loop (4 s / 8 s) is seamless
  var HARM = [[2, 0.35, OM], [3, 0.3, -OM], [4, 0.18, 2 * OM], [5, 0.12, -2 * OM]];
  var N = 180, _r = new Float32Array(N), _r2 = new Float32Array(N);
  var COS = new Float32Array(N), SIN = new Float32Array(N);
  for (var ci = 0; ci < N; ci++) { COS[ci] = Math.cos(ci / N * TAU); SIN[ci] = Math.sin(ci / N * TAU); }
  // Same math as the design's shapeD, returned as a Path2D in orb units plus its bbox.
  function shapePath(st, wa) {
    var p = st.p, R = 118 * st.scale, asp = st.aspect, i, j;
    for (i = 0; i < N; i++) {
      var th = i / N * TAU, c = Math.abs(COS[i]), sn = Math.abs(SIN[i]);
      var v = Math.pow(Math.pow(c, p) + Math.pow(sn, p), -1 / p);
      if (wa) {
        var w = 0;
        for (j = 0; j < st.hts.length; j++) {
          var hp = st.hts[j][0], hw = st.hts[j][1];
          for (var h = 0; h < 4; h++) w += hw * HARM[h][1] * Math.sin(HARM[h][0] * th + hp * HARM[h][2]);
        }
        v *= 1 + wa * w;
      }
      _r[i] = v;
    }
    for (var pass = 0; pass < 2; pass++) {
      for (i = 0; i < N; i++) _r2[i] = (_r[(i + N - 2) % N] + _r[(i + N - 1) % N] + _r[i] + _r[(i + 1) % N] + _r[(i + 2) % N]) / 5;
      _r.set(_r2);
    }
    var path = new Path2D(), x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (i = 0; i < N; i++) {
      var x = _r[i] * COS[i] * R, y = _r[i] * SIN[i] * R * asp;
      if (i) path.lineTo(x, y); else path.moveTo(x, y);
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    path.closePath();
    return { path: path, bb: [x0, y0, x1 - x0, y1 - y0] };
  }

  // ── states as periodic functions of their own phase (lvl = live 0..1 level, null = synthetic) ──
  var LOOP = { idle: 4, listen: 8, think: 4, speak: 8 };
  var STATES = ["idle", "listen", "think", "speak"];
  function params(s, f, lvl) {
    if (s === "idle") return { p: 0.6, heat: 0.04, wob: 0, scale: 0.9 + 0.035 * Math.sin(f * OM), aspect: 1.06, L: 0, sig: 0 };
    if (s === "listen") {
      var Lin = lvl == null ? sLoop(f, 8, 7, 0.9) : lvl;
      return { p: 1.6 + 0.2 * Lin, heat: 0.12 + 0.1 * Lin, wob: 0.35, scale: 0.84 + 0.05 * Lin, aspect: 1, L: 0.8 * Lin, sig: Lin };
    }
    if (s === "think") return { p: 1.22, heat: 0.28 + 0.08 * Math.sin(f * OM * 3), wob: 0.12, scale: 0.84 + 0.02 * Math.sin(f * OM * 4), aspect: 1, L: 0, sig: 0 };
    var La = lvl == null ? sLoop(f, 8, 3.1) : lvl;
    return { p: 2, heat: 0.88 + 0.12 * La, wob: 1, scale: 0.96 + 0.1 * La, aspect: 1 - 0.03 * La, L: La, sig: La };
  }
  var ALIAS = { idle: "idle", listen: "listen", listening: "listen", think: "think", thinking: "think", speak: "speak", speaking: "speak" };
  var LBL = { idle: "idle", listen: "listening", think: "thinking…", speak: "speaking", asking: "asking" };
  var TR_DUR = 0.8, SERVER_TTL = 45, MIC_THRESH = 0.12, MIC_HOLD = 0.8, FRAME_MS = 1000 / 30;

  // ── canvas setup ──
  // Everything with an edge (body, rim, rings) is drawn at full 1280x720 on the main canvas.
  // Only edge-less blurred light (halos, inner blobs) goes through a half-res full-frame buffer.
  var W = 1280, H = 720, GR = 0.5; // glow buffer = 640x360
  var cv, g, bufG, gG, hasFilter;

  function blurPx(ctx, px) { if (hasFilter) ctx.filter = px > 0.3 ? "blur(" + px.toFixed(2) + "px)" : "none"; }
  var O = { x: 0, y: 0 }; // orb centre in screen px for the current frame
  // clear the glow buffer and map orb units onto it; returns buffer px per orb unit
  function bufBegin(u) {
    gG.setTransform(1, 0, 0, 1, 0, 0); gG.globalCompositeOperation = "source-over"; gG.globalAlpha = 1;
    if (hasFilter) gG.filter = "none";
    gG.clearRect(0, 0, bufG.width, bufG.height);
    var q = u * GR; gG.setTransform(q, 0, 0, q, O.x * GR, O.y * GR); return q;
  }
  // fill the shape on the buffer with an extra translate/scale (SVG "translate() scale()"), blurred by sd orb units
  function blob(q, path, fill, alpha, sd, tx, ty, s) {
    gG.setTransform(q * s, 0, 0, q * s, O.x * GR + tx * q, O.y * GR + ty * q);
    blurPx(gG, sd * s * q); gG.globalAlpha = alpha; gG.fillStyle = fill; gG.fill(path);
  }
  function blit() { g.setTransform(1, 0, 0, 1, 0, 0); g.drawImage(bufG, 0, 0, W, H); }
  function bbGrad(ctx, bb, x1, y1, x2, y2, deg) {
    var a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    function rot(px, py) { var dx = px - 0.5, dy = py - 0.5; return [0.5 + dx * c - dy * s, 0.5 + dx * s + dy * c]; }
    var p1 = rot(x1, y1), p2 = rot(x2, y2);
    return ctx.createLinearGradient(bb[0] + p1[0] * bb[2], bb[1] + p1[1] * bb[3], bb[0] + p2[0] * bb[2], bb[1] + p2[1] * bb[3]);
  }

  function drawOrb(st, ox, oy, size, churnOp, churnPhi) {
    var u = size / 520, h = st.heat, L = st.L;
    function x(k, al) { return rgba(PR[k][0], PR[k][1], h, al); }
    var sh = shapePath(st, st.wob * (0.025 + 0.075 * L)), d = sh.path, bb = sh.bb;
    var drift = 0, i;
    for (i = 0; i < st.hts.length; i++) drift += st.hts[i][1] * Math.sin(st.hts[i][0] * OM);

    O.x = ox; O.y = oy;
    // halos (behind the body): half-res glow buffer
    var q = bufBegin(u);
    blob(q, d, x("h3"), 0.95, 38, 0, 18 - 12 * h, 1.27 + 0.1 * L);
    blob(q, d, x("hm"), Math.max(0, 0.55 - 0.2 * h), 24, 0, 8 - 4 * h, 1.17 + 0.06 * L);
    blob(q, d, x("h1"), 1, 13, 0, 0, 1.075 + 0.03 * L - 0.015 * h);
    blit();

    // body
    g.setTransform(u, 0, 0, u, ox, oy);
    var gr = bbGrad(g, bb, 0, 0, 0, 1, -16 + 10 * drift);
    gr.addColorStop(0, x("top")); gr.addColorStop(0.48, x("mid")); gr.addColorStop(1, x("bot"));
    g.fillStyle = gr; g.fill(d);

    // inner light + shade, clipped to the body
    // inner light + shade, clipped to the full-res body edge
    q = bufBegin(u);
    blob(q, d, x("inn"), 1, 24, 0, 75 * (1 - h), 0.72 + 0.38 * h);
    if (h < 0.99) blob(q, d, PR.shadeCol, 0.45 * (1 - h), 20, -10, -95, 0.75);
    g.save(); g.clip(d); blit();
    if (churnOp > 0.01) { // thinking: three blobs swirl inside, screen-blended
      q = bufBegin(u);
      var ph = churnPhi * OM, cr = 62 * st.scale, B = [[COL.O, 0, 1, 1], [COL.CR, 2.1, 2, 1], [COL.R, 4.2, 1, 2]];
      gG.globalCompositeOperation = "screen"; blurPx(gG, 26 * q); gG.globalAlpha = 0.85 * churnOp;
      for (i = 0; i < 3; i++) {
        gG.fillStyle = B[i][0]; gG.beginPath();
        gG.arc(cr * Math.sin(ph * B[i][2] + B[i][1]), cr * Math.cos(ph * B[i][3] + B[i][1] * 0.7), 70 * st.scale, 0, TAU);
        gG.fill();
      }
      g.globalCompositeOperation = "screen"; blit(); g.globalCompositeOperation = "source-over";
    }
    g.restore();

    // rim: soft wide stroke + crisp strokes, all full-res on the main canvas
    var rim = function (ctx) {
      var r = bbGrad(ctx, bb, 0.15, 0, 0.85, 1, -6 + 22 * drift);
      r.addColorStop(0, x("rimA")); r.addColorStop(0.28, x("rimB", 0.95)); r.addColorStop(0.6, x("rimB", 0)); r.addColorStop(1, x("rimB", 0));
      return r;
    };
    g.setTransform(u, 0, 0, u, ox, oy); g.lineJoin = "round";
    blurPx(g, 4 * u); g.strokeStyle = rim(g); g.lineWidth = 9; g.stroke(d); blurPx(g, 0);
    var e = bbGrad(g, bb, 0.15, 0, 0.85, 1, 0);
    e.addColorStop(0, x("edge", 0)); e.addColorStop(0.55, x("edge", 0)); e.addColorStop(1, x("edge", 0.85));
    g.globalAlpha = 0.8; g.strokeStyle = e; g.lineWidth = 3; g.stroke(d);
    g.globalAlpha = 0.9; g.strokeStyle = rim(g); g.lineWidth = 2.4; g.stroke(d);
    g.globalAlpha = 1; g.setTransform(1, 0, 0, 1, 0, 0);
  }

  function drawRings(ox, oy, size, ringOp, rPhi, Lin) {
    var k = size / 440;
    g.setTransform(1, 0, 0, 1, 0, 0); g.strokeStyle = COL.O; g.lineWidth = 2 * k;
    for (var i = 0; i < 4; i++) {
      var ph = md(rPhi * 0.5 + i / 4, 1), op = ringOp * (1 - ph) * Math.min(1, ph * 6) * (0.25 + 0.6 * Lin);
      if (op < 0.005) continue;
      g.globalAlpha = op; g.beginPath(); g.arc(ox, oy, lerp(235, 100, out(ph)) * k, 0, TAU); g.stroke();
    }
    g.globalAlpha = 1;
  }

  // ── live state ──
  var T0 = performance.now();
  function now() { return (performance.now() - T0) / 1000; }
  var forced = null;              // ?state= freeze
  var server = null, serverUntil = 0;
  var blendFrom = { idle: 1 }, target = "idle", tChange = -10;
  var sideAnim = { from: 0, to: 0, t0: 0, dur: 1 };
  var ask = null;                 // {id, question, expert, timeout, t0, phase, tPhase, frac0, typeDur, inDur}
  var lastMicHot = -10, lastPlaying = -10;
  var lvOut = 0, lvMic = 0;
  var levels = { out: null, mic: null }; // samplers set by index.html, return raw RMS or null
  var inputs = function () { return { playing: false }; };
  var sim = null;                 // ?demo=1 fake inputs
  var el = {};

  function weightsAt(t) {
    var e = io(kk(t - tChange, 0, TR_DUR)), w = {};
    for (var i = 0; i < 4; i++) { var s = STATES[i]; w[s] = (blendFrom[s] || 0) * (1 - e) + (s === target ? e : 0); }
    return w;
  }
  function sideAt(t) { return lerp(sideAnim.from, sideAnim.to, io(kk(t, sideAnim.t0, sideAnim.t0 + sideAnim.dur))); }
  function moveSide(t, to, delay) { sideAnim = { from: sideAt(t), to: to, t0: t + delay, dur: 0.9 }; }

  function targetState(t, inp, micHot) {
    if (forced) return forced;
    if (inp.playing) return "speak";
    if (ask) {
      var v = t - ask.tPhase;
      if (ask.phase === "ok") return v > 0.3 ? "think" : "listen";
      if (ask.phase === "to") return v > 0.1 ? "idle" : "listen";
      return "listen";
    }
    if (server && t < serverUntil) return server;
    if (micHot) return "listen";
    return "idle";
  }

  function setServerState(s) {
    var k = ALIAS[s];
    if (!k || k === "idle") { server = null; return; }
    server = k; serverUntil = now() + SERVER_TTL;
  }

  // ── ask overlay ──
  var chars = [], shownN = -1;
  function startAsk(msg) {
    var t = now(), q = String(msg.question || "").trim();
    if (q.length > 220) q = q.slice(0, 217).replace(/\s+\S*$/, "") + "…";
    var nChars = Math.max(1, q.length), typeDur = cl(nChars * 0.035, 1.0, 3.0);
    ask = { id: msg.id || null, question: q.toUpperCase(), expert: String(msg.expert || "the expert"),
      timeout: Math.max(5, Number(msg.timeout_s) || 120), t0: t, phase: "in", tPhase: t, frac0: 1,
      typeDur: typeDur, inDur: 1.5 + typeDur };
    moveSide(t, 1, 0);
    buildAsk();
  }
  function askDone(msg) {
    if (!ask || ask.phase === "ok" || ask.phase === "to") return;
    if (msg && msg.id && ask.id && msg.id !== ask.id) return;
    var t = now(), a = askFrame(t);
    ask.frac0 = a.frac; ask.tPhase = t;
    if (msg && msg.result === "answered") { ask.phase = "ok"; moveSide(t, 0, 0.3); }
    else { ask.phase = "to"; moveSide(t, 0, 0.1); }
  }
  function buildAsk() {
    var qEl = el.q; qEl.textContent = ""; chars = []; shownN = -1;
    var words = ask.question.split(/\s+/);
    for (var wi = 0; wi < words.length; wi++) {
      var ws = document.createElement("span"); ws.className = "w";
      for (var ci = 0; ci < words[wi].length; ci++) {
        var c = document.createElement("span"); c.textContent = words[wi][ci]; c.style.opacity = "0";
        ws.appendChild(c); chars.push(c);
      }
      qEl.appendChild(ws);
    }
    el.phrase.textContent = ("Asking " + ask.expert + " on Slack").toUpperCase();
    el.ask.style.display = "flex"; el.ask.style.opacity = "0";
    fitAsk();
    if (document.fonts && document.fonts.load) {
      document.fonts.load('50px "Druk Wide Cyr"').then(fitAsk, function () {});
    }
  }
  function fitAsk() { // long questions / names shrink so the text and plate stay in the 720 px frame
    if (!ask) return;
    var fs = 50; el.q.style.fontSize = fs + "px";
    while (el.q.scrollHeight > 500 && fs > 22) { fs -= 2; el.q.style.fontSize = fs + "px"; }
    var pf = 32; el.phrase.style.fontSize = pf + "px";
    while (el.phrase.scrollWidth > 620 && pf > 14) { pf -= 2; el.phrase.style.fontSize = pf + "px"; }
  }
  function askFrame(t) {
    var u = t - ask.t0, v = t - ask.tPhase, T = ask.typeDur;
    var a = { typeU: u - 0.75, barOp: out(kk(u, 0.9 + T, 1.4 + T)), textOp: out(kk(u, 0.45, 0.75)), frac: 1, hot: false, flash: 0 };
    if (u >= ask.inDur) a.frac = 1 - kk(u - ask.inDur, 0, Math.max(1, ask.timeout - ask.inDur));
    a.hot = a.frac < 0.1;
    if (ask.phase === "ok") {
      a.barOp = 1; a.frac = lerp(ask.frac0, 1, out(kk(v, 0, 0.22))); a.hot = false;
      a.flash = 1 - kk(v, 0.1, 0.6); a.textOp = 1 - io(kk(v, 0.32, 0.72));
    } else if (ask.phase === "to") {
      a.frac = 0; a.hot = true; a.textOp *= 1 - io(kk(v, 0, 0.4));
    }
    return a;
  }
  function renderAsk(t) {
    if (!ask) return;
    var v = t - ask.tPhase;
    if ((ask.phase === "ok" && v > 1.2) || (ask.phase === "to" && v > 1.0)) {
      if (ask.phase === "ok") setServerState("thinking"); else server = null;
      ask = null; el.ask.style.display = "none"; return;
    }
    if (ask.phase !== "ok" && ask.phase !== "to" && t - ask.t0 > ask.timeout + 15) { askDone({ result: "timeout" }); }
    var a = askFrame(t), n = chars.length, CH = ask.typeDur / Math.max(1, n);
    var shown = a.typeU < 0 ? 0 : Math.min(n, Math.floor(a.typeU / CH) + 1);
    if (shown !== shownN) {
      for (var i = Math.max(0, shownN); i < shown; i++) chars[i].style.opacity = "1";
      if (shown > 0) chars[shown - 1].after(el.caret); else el.q.insertBefore(el.caret, el.q.firstChild);
      shownN = shown;
    }
    var caret = a.typeU > -0.25 && a.typeU < ask.typeDur + 0.3 && (shown < n || (a.typeU * 2.5) % 1 < 0.5);
    el.caret.style.visibility = caret ? "visible" : "hidden";
    el.ask.style.opacity = a.textOp.toFixed(3);
    el.plate.style.opacity = a.barOp.toFixed(3);
    // no transform at rest so the Druk text stays on whole pixels (crisp)
    el.plate.style.transform = a.barOp >= 0.999 ? "none" : "translateY(" + Math.round((1 - a.barOp) * 14) + "px)";
    el.fill.style.width = (a.frac * 100).toFixed(2) + "%";
    el.fill.style.background = a.flash > 0 ? rgba("#7A2A2C", "#D95B48", a.flash) : a.hot ? "#8E1E3C" : "#7A2A2C";
  }

  // ── level helpers ──
  function smooth(prev, raw) { // raw RMS -> 0..1 with fast attack, slower release
    var x = Math.pow(cl((raw - 0.01) / 0.18, 0, 1), 0.7);
    return prev + (x - prev) * (x > prev ? 0.55 : 0.18);
  }

  // ── frame ──
  var last = 0;
  function frame(ts) {
    requestAnimationFrame(frame);
    if (ts - last < FRAME_MS - 2) return;
    last = ts;
    try { draw(); } catch (e) { if (!drawErr) { drawErr = true; console.warn("orb frame failed", e); } }
  }
  var drawErr = false;
  function draw() {
    var t = now(), inp = sim ? sim(t) : inputs();
    if (inp.playing) lastPlaying = t;

    var rawOut = !sim && levels.out ? levels.out() : null;
    var rawMic = !sim && levels.mic ? levels.mic() : null;
    lvOut = rawOut == null ? 0 : smooth(lvOut, rawOut);
    lvMic = rawMic == null ? 0 : smooth(lvMic, rawMic);
    if (sim && inp.mic) lastMicHot = t;
    if (!sim && rawMic != null && !inp.playing && t - lastPlaying > 0.6 && lvMic > MIC_THRESH) lastMicHot = t;
    var micHot = t - lastMicHot < MIC_HOLD;

    var tgt = targetState(t, inp, micHot);
    if (tgt !== target) { blendFrom = weightsAt(t); target = tgt; tChange = t; }
    var w = weightsAt(t);

    var P = {}, hts = [], tot = 0, s, i;
    for (i = 0; i < 4; i++) {
      s = STATES[i];
      if (w[s] > 0.001) {
        var lvl = null;
        if (s === "speak" && rawOut != null && inp.playing) lvl = lvOut;
        if (s === "listen" && rawMic != null) lvl = Math.max(lvMic, 0.35 * sLoop(md(t, 8), 8, 7, 0.9));
        P[s] = params(s, md(t, LOOP[s]), lvl); hts.push([md(t, LOOP[s]), w[s]]); tot += w[s];
      }
    }
    var st = { hts: hts, p: 0, heat: 0, wob: 0, scale: 0, aspect: 0, L: 0 };
    var F = ["p", "heat", "wob", "scale", "aspect", "L"];
    for (var f = 0; f < F.length; f++) {
      var acc = 0; for (s in P) acc += w[s] * P[s][F[f]]; st[F[f]] = acc / (tot || 1);
    }
    st.p = cl(st.p, 0.4, 2.6);

    var side = sideAt(t), ox = lerp(640, 360, side), size = lerp(680, 520, side);
    g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, W, H);
    if ((w.listen || 0) > 0.01) drawRings(ox, 360, size, w.listen, md(t, 8), P.listen ? P.listen.sig : 0);
    drawOrb(st, ox, 360, size, w.think || 0, md(t, 4));
    renderAsk(t);

    var label = ask ? "asking" : target;
    if (el.label && el.label.textContent !== LBL[label]) el.label.textContent = LBL[label];
    document.body.classList.toggle("asking", !!ask);
    CrewOrb.frames++;
  }

  // ?demo=1: idle → listening → thinking → speaking → ask → answered, 3 s each (ask holds 6 s), fake levels
  function demoSim() {
    var step = -1, Q = "Can we ship the Atlas migration before the Friday freeze, or is the billing service still blocked?";
    return function (t) {
      var c = md(t, 21), k = c < 12 ? Math.floor(c / 3) : c < 18 ? 4 : 5;
      if (k !== step) {
        step = k;
        if (k === 2) setServerState("thinking");
        if (k === 3 || k === 0) setServerState("idle");
        if (k === 4) startAsk({ id: "demo", question: Q, expert: "Bob", timeout_s: 9 });
        if (k === 5) askDone({ id: "demo", result: "answered" });
      }
      return { playing: k === 3 || (k === 4 && c - 12 < 2.5), mic: k === 1 };
    };
  }

  var CrewOrb = window.CrewOrb = {
    frames: 0,
    levels: levels,
    init: function (opts) {
      cv = opts.canvas; g = cv.getContext("2d");
      hasFilter = "filter" in g;
      cv.width = W; cv.height = H; // backing store exactly 1280x720, shown 1:1 by CSS
      bufG = document.createElement("canvas"); bufG.width = Math.round(W * GR); bufG.height = Math.round(H * GR);
      gG = bufG.getContext("2d");
      el = { ask: opts.ask, q: opts.question, plate: opts.plate, fill: opts.fill, phrase: opts.phrase, label: opts.label };
      el.caret = document.createElement("span"); el.caret.className = "caret";
      if (opts.inputs) inputs = opts.inputs;
      var qs = new URLSearchParams(location.search), fs = ALIAS[qs.get("state") || ""];
      if (qs.get("state") === "ask") {
        startAsk({ id: "freeze", question: qs.get("q") || "What is the current p95 latency budget for the checkout API after the October migration?",
          expert: qs.get("expert") || "Bob", timeout_s: 3600 });
      } else if (fs) { forced = fs; target = fs; blendFrom = {}; blendFrom[fs] = 1; }
      if (qs.get("demo") === "1") sim = demoSim();
      requestAnimationFrame(frame);
      return !!(forced || sim || qs.get("state") === "ask");
    },
    setServerState: setServerState,
    ask: function (msg) { if (!forced) startAsk(msg); },
    askDone: askDone,
  };
})();
