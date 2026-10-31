// Agent clips: every state loop + every state-to-state transition + the asking sequence,
// each a scene on one timeline. Every clip starts and ends on its state's rest frame, so clips butt-join seamlessly.
(() => {
const TAU = Math.PI * 2, OM = TAU / 4;
const cl = (v, a, b) => Math.min(b, Math.max(a, v));
const lerp = (a, b, t) => a + (b - a) * t;
const kk = (t, a, b) => cl((t - a) / (b - a), 0, 1);
const io = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const out = t => 1 - Math.pow(1 - t, 3);
const md = (x, D) => ((x % D) + D) % D;
const hash = n => { const s = Math.sin(n * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };
const noise = x => { const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f); return hash(i) + (hash(i + 1) - hash(i)) * u; };
const speechRaw = (t, seed) => {
  const syl = Math.pow(Math.max(0, Math.sin(t * 26.4 + noise(t * .9 + seed) * 6)), .7);
  const gate = cl((noise(t * 1.5 + seed + 10) - .22) / .2, 0, 1);
  return syl * gate * (.5 + .5 * noise(t * 3.3 + seed + 20));
};
const speech = (t, seed) => speechRaw(t, seed) * .4 + speechRaw(t - .04, seed) * .3 + speechRaw(t - .08, seed) * .2 + speechRaw(t - .12, seed) * .1;
const sLoop = (phi, D, seed, sp = 1) => { const w = phi / D; return (1 - w) * speech(phi * sp + 40, seed) + w * speech((phi - D) * sp + 40, seed); };

const COL = { O: '#FF8A1A', R: '#E0255E', PL: '#4A0F2A', CR: '#FFE3A3', INK: '#FFF3E6' };
const DRUK = "'Druk Wide Cyr', 'Arial Black', sans-serif", SANS = "Onest, system-ui, sans-serif", MONO = "'JetBrains Mono', ui-monospace, monospace";
const hex = h => { const n = parseInt(h.slice(1), 16); return [n >> 16, (n >> 8) & 255, n & 255]; };
const toHex = c => '#' + c.map(v => Math.round(cl(v, 0, 255)).toString(16).padStart(2, '0')).join('');
const tint = (h, t) => toHex(hex(h).map(v => v + (255 - v) * t));
const shade = (h, t) => toHex(hex(h).map(v => v * t));
const blend = (a, b, t) => toHex(hex(a).map((v, i) => v + (hex(b)[i] - v) * t));
const mixc = (a, b, t) => { const A = hex(a), B = hex(b); return `rgb(${A.map((v, i) => Math.round(v + (B[i] - v) * t)).join(',')})`; };
const PR = (() => {
  const a = COL.O, c = COL.R, d = COL.PL, w = COL.CR;
  return { h3: [a, shade(c, .75)], hm: [tint(a, .72), tint(a, .25)], h1: [c, a], top: [blend(c, d, .25), tint(c, .6)], mid: [tint(c, .18), '#fff6ea'], bot: [blend(c, a, .45), w], inn: [tint(a, .35), tint(w, .7)], rimA: [tint(a, .5), tint(c, .2)], rimB: [a, c], edge: [c, tint(a, .75)], shadeCol: blend(c, d, .6) };
})();

// harmonic speeds are multiples of 2π/4 s, so every loop (4 s / 8 s) is seamless
const HARM = [[2, .35, OM], [3, .3, -OM], [4, .18, 2 * OM], [5, .12, -2 * OM]];
const _r = new Float32Array(180), _r2 = new Float32Array(180);
function shapeD(st, wa) {
  const N = 180, p = st.p, R = 118 * st.scale, asp = st.aspect;
  for (let i = 0; i < N; i++) {
    const th = i / N * TAU, c = Math.abs(Math.cos(th)), sn = Math.abs(Math.sin(th));
    let v = Math.pow(Math.pow(c, p) + Math.pow(sn, p), -1 / p);
    if (wa) { let w = 0; for (const [hp, hw] of st.hts) for (const h of HARM) w += hw * h[1] * Math.sin(h[0] * th + hp * h[2]); v *= 1 + wa * w; }
    _r[i] = v;
  }
  for (let pass = 0; pass < 2; pass++) {
    for (let i = 0; i < N; i++) _r2[i] = (_r[(i + N - 2) % N] + _r[(i + N - 1) % N] + _r[i] + _r[(i + 1) % N] + _r[(i + 2) % N]) / 5;
    _r.set(_r2);
  }
  let d = '';
  for (let i = 0; i < N; i++) { const th = i / N * TAU; d += (i ? 'L' : 'M') + (_r[i] * Math.cos(th) * R).toFixed(1) + ' ' + (_r[i] * Math.sin(th) * R * asp).toFixed(1); }
  return d + 'Z';
}
const BLURS = [38, 24, 13, 20, 26, 4, 1.2, .8];
function Orb({ st, size, churnOp, churnPhi }) {
  const uid = 'ac';
  const h = st.heat, L = st.L, x = k => mixc(PR[k][0], PR[k][1], h);
  const d = shapeD(st, st.wob * (.025 + .075 * L));
  let drift = 0; for (const [hp, hw] of st.hts) drift += hw * Math.sin(hp * OM);
  const B = sd => `url(#${uid}b${String(sd).replace('.', '_')})`, U = s => `url(#${uid}${s})`;
  const ph = churnPhi * OM, cr = 62 * st.scale;
  return (
    <svg viewBox="-260 -260 520 520" width={size} height={size} style={{ display: 'block', overflow: 'visible', isolation: 'isolate' }}>
      <defs>
        {BLURS.map(sd => <filter key={sd} id={`${uid}b${String(sd).replace('.', '_')}`} x="-75%" y="-75%" width="250%" height="250%" colorInterpolationFilters="sRGB"><feGaussianBlur stdDeviation={sd} /></filter>)}
        <linearGradient id={uid + 'g'} x1="0" y1="0" x2="0" y2="1" gradientTransform={`rotate(${-16 + 10 * drift} .5 .5)`}>
          <stop offset="0" stopColor={x('top')} /><stop offset=".48" stopColor={x('mid')} /><stop offset="1" stopColor={x('bot')} />
        </linearGradient>
        <linearGradient id={uid + 'r'} x1=".15" y1="0" x2=".85" y2="1" gradientTransform={`rotate(${-6 + 22 * drift} .5 .5)`}>
          <stop offset="0" stopColor={x('rimA')} /><stop offset=".28" stopColor={x('rimB')} stopOpacity=".95" /><stop offset=".6" stopColor={x('rimB')} stopOpacity="0" /><stop offset="1" stopColor={x('rimB')} stopOpacity="0" />
        </linearGradient>
        <linearGradient id={uid + 'e'} x1=".15" y1="0" x2=".85" y2="1">
          <stop offset="0" stopColor={x('edge')} stopOpacity="0" /><stop offset=".55" stopColor={x('edge')} stopOpacity="0" /><stop offset="1" stopColor={x('edge')} stopOpacity=".85" />
        </linearGradient>
        <clipPath id={uid + 'c'}><path d={d} /></clipPath>
      </defs>
      <path d={d} fill={x('h3')} opacity=".95" filter={B(38)} transform={`translate(0 ${18 - 12 * h}) scale(${1.27 + .1 * L})`} />
      <path d={d} fill={x('hm')} opacity={.55 - .2 * h} filter={B(24)} transform={`translate(0 ${8 - 4 * h}) scale(${1.17 + .06 * L})`} />
      <path d={d} fill={x('h1')} filter={B(13)} transform={`scale(${1.075 + .03 * L - .015 * h})`} />
      <path d={d} fill={U('g')} />
      <g clipPath={U('c')}>
        <path d={d} fill={x('inn')} filter={B(24)} transform={`translate(0 ${75 * (1 - h)}) scale(${.72 + .38 * h})`} />
        <path d={d} fill={PR.shadeCol} opacity={.45 * (1 - h)} filter={B(20)} transform="translate(-10 -95) scale(.75)" />
        {churnOp > .01 && [[COL.O, 0, 1, 1], [COL.CR, 2.1, 2, 1], [COL.R, 4.2, 1, 2]].map(([c, o, a, b], i) => (
          <circle key={i} cx={cr * Math.sin(ph * a + o)} cy={cr * Math.cos(ph * b + o * .7)} r={70 * st.scale} fill={c} opacity={.85 * churnOp} filter={B(26)} style={{ mixBlendMode: 'screen' }} />
        ))}
      </g>
      <path d={d} fill="none" stroke={U('e')} strokeWidth="3" filter={B(1.2)} />
      <path d={d} fill="none" stroke={U('r')} strokeWidth="9" filter={B(4)} />
      <path d={d} fill="none" stroke={U('r')} strokeWidth="2.4" filter={B(.8)} />
    </svg>
  );
}

// ── states as periodic functions of their own phase ──
const LOOP = { idle: 4, listen: 8, think: 4, speak: 8 };
function params(s, f) {
  if (s === 'idle') return { p: .6, heat: .04, wob: 0, scale: .9 + .035 * Math.sin(f * OM), aspect: 1.06, L: 0, sig: 0 };
  if (s === 'listen') { const Lin = sLoop(f, 8, 7, .9); return { p: 1.6 + .2 * Lin, heat: .12 + .1 * Lin, wob: .35, scale: .84 + .05 * Lin, aspect: 1, L: .8 * Lin, sig: Lin }; }
  if (s === 'think') return { p: 1.22, heat: .28 + .08 * Math.sin(f * OM * 3), wob: .12, scale: .84 + .02 * Math.sin(f * OM * 4), aspect: 1, L: 0, sig: 0 };
  const La = sLoop(f, 8, 3.1); return { p: 2, heat: .88 + .12 * La, wob: 1, scale: .96 + .1 * La, aspect: 1 - .03 * La, L: La, sig: La };
}
const NAMES = { idle: 'Idle', listen: 'Listening', think: 'Thinking', speak: 'Speaking' };
const KEY = Object.fromEntries(Object.entries(NAMES).map(([k, v]) => [v, k]));
const TR_DUR = .8, ASK_IN = 3.5, ASK_WAIT = 8, ASK_OK = 1.2, ASK_TO = 1;

// scene name → frame description at local time u
function describe(name, u) {
  const F = { w: {}, ph: {}, side: 0, ask: null };
  if (KEY[name]) { const s = KEY[name]; F.w[s] = 1; F.ph[s] = md(u, LOOP[s]); return F; }
  const m = name.match(/^(\w+) → (\w+)$/);
  if (m && KEY[m[1]] && KEY[m[2]]) {
    const a = KEY[m[1]], b = KEY[m[2]], e = io(kk(u, 0, TR_DUR));
    F.w[a] = 1 - e; F.w[b] = e; F.ph[a] = md(u, LOOP[a]); F.ph[b] = md(u - TR_DUR, LOOP[b]); return F;
  }
  if (name === 'Ask in') {
    const eI = io(kk(u, 0, .6)), eL = io(kk(u, ASK_IN - .6, ASK_IN));
    F.w = { idle: 1 - eI, speak: eI * (1 - eL), listen: eL }; F.ph = { idle: md(u, 4), speak: md(u, 8), listen: md(u - ASK_IN, 8) };
    F.side = io(kk(u, 0, .9));
    F.ask = { typeU: u - .75, typeDur: 2.0, barOp: out(kk(u, 2.9, 3.4)), frac: 1, textOp: out(kk(u, .45, .75)), hot: false, flash: 0 };
    return F;
  }
  if (name === 'Ask countdown') {
    F.w = { listen: 1 }; F.ph = { listen: md(u, 8) }; F.side = 1;
    F.ask = { typeU: 99, typeDur: 2, barOp: 1, frac: 1 - kk(u, 0, ASK_WAIT), textOp: 1, hot: u > ASK_WAIT - 3, flash: 0 };
    return F;
  }
  if (name === 'Ask confirmed') {
    const e = io(kk(u, .3, ASK_OK));
    F.w = { listen: 1 - e, think: e }; F.ph = { listen: md(u, 8), think: md(u - ASK_OK, 4) }; F.side = 1 - e;
    F.ask = { typeU: 99, typeDur: 2, barOp: 1, frac: out(kk(u, 0, .22)), textOp: 1 - io(kk(u, .32, .72)), hot: false, flash: 1 - kk(u, .1, .6) };
    return F;
  }
  if (name === 'Ask timeout') {
    const e = io(kk(u, .1, ASK_TO));
    F.w = { listen: 1 - e, idle: e }; F.ph = { listen: md(u, 8), idle: md(u - ASK_TO, 4) }; F.side = 1 - e;
    F.ask = { typeU: 99, typeDur: 2, barOp: 1, frac: 0, textOp: 1 - io(kk(u, 0, .4)), hot: true, flash: 0 };
    return F;
  }
  F.w.idle = 1; F.ph.idle = 0; return F;
}

function AskText({ a, question, phrase }) {
  const q = question.toUpperCase(), chars = [...q], N = chars.length, CH = a.typeDur / Math.max(1, N);
  const shown = a.typeU < 0 ? 0 : Math.min(N, Math.floor(a.typeU / CH) + 1);
  const caret = a.typeU > -.25 && a.typeU < a.typeDur + .3 && (shown < N || (a.typeU * 2.5) % 1 < .5);
  let k = 0;
  const words = q.split(' ').map(w => { const o = { w, k0: k }; k += w.length + 1; return o; });
  const caretEl = <span style={{ display: 'inline-block', width: '.12em', height: '.84em', marginLeft: '.06em', background: COL.O, verticalAlign: '-.06em' }} />;
  return (
    <div style={{ position: 'absolute', left: 625, right: 70, top: 0, bottom: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 40, opacity: a.textOp }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', columnGap: '.3em', rowGap: '.1em', font: `400 50px/1.02 ${DRUK}`, color: COL.INK }}>
        {shown === 0 && caret && caretEl}
        {words.map((o, wi) => (
          <span key={wi} style={{ whiteSpace: 'nowrap' }}>
            {[...o.w].map((c, i) => { const idx = o.k0 + i; return <React.Fragment key={i}><span style={{ opacity: idx < shown ? 1 : 0 }}>{c}</span>{caret && idx === shown - 1 && caretEl}</React.Fragment>; })}
          </span>
        ))}
      </div>
      <div style={{ position: 'relative', width: 620, height: 90, opacity: a.barOp, transform: `translateY(${(1 - a.barOp) * 14}px)`, background: '#2A0814', boxShadow: 'inset 0 0 0 1px rgba(255,227,163,.08)' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${a.frac * 100}%`, background: a.flash > 0 ? mixc('#7A2A2C', '#D95B48', a.flash) : a.hot ? '#8E1E3C' : '#7A2A2C' }} />
        <div style={{ position: 'relative', height: '100%', display: 'flex', alignItems: 'center', padding: '0 36px', font: `400 32px/1 ${DRUK}`, color: COL.INK, whiteSpace: 'nowrap' }}>{phrase.toUpperCase()}</div>
      </div>
    </div>
  );
}

function Clips({ tw }) {
  const { T, CUES } = useComposition();
  let name = null, start = 0;
  for (const [n, s] of Object.entries(CUES)) if (s <= T + 1e-6 && s >= start) { name = n; start = s; }
  const F = describe(name, T - start);
  const P = {}, hts = [];
  for (const s in F.w) { if (F.w[s] > 0) { P[s] = params(s, F.ph[s]); hts.push([F.ph[s], F.w[s]]); } }
  const st = { hts, p: 0, heat: 0, wob: 0, scale: 0, aspect: 0, L: 0 };
  let tot = 0; for (const s in P) tot += F.w[s];
  for (const f of ['p', 'heat', 'wob', 'scale', 'aspect', 'L']) { let v = 0; for (const s in P) v += F.w[s] * P[s][f]; st[f] = v / (tot || 1); }
  st.p = cl(st.p, .4, 2.6);
  const ox = lerp(640, 360, F.side), size = lerp(680, 520, F.side), k = size / 440;
  const ringOp = F.w.listen || 0, rPhi = F.ph.listen || 0, Lin = P.listen ? P.listen.sig : 0;
  const label = F.ask ? 'asking' : (Object.entries(F.w).sort((a, b) => b[1] - a[1])[0] || ['idle'])[0];
  const LBL = { idle: 'idle', listen: 'listening', think: 'thinking…', speak: 'speaking', asking: 'asking' };
  return (
    <div data-screen-label={name || 'clip'} style={{ position: 'absolute', inset: 0, overflow: 'hidden', background: 'radial-gradient(75% 95% at 50% 50%, #5E1636 0%, #3A0A21 55%, #1E0411 100%)' }}>
      <div style={{ position: 'absolute', left: 0, top: 0, width: 1280, height: 720, transform: 'scale(1.5)', transformOrigin: '0 0' }}>
        {ringOp > .01 && (
          <svg viewBox="0 0 1280 720" width="1280" height="720" style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
            <g fill="none" stroke={COL.O} strokeWidth={2 * k}>
              {[0, 1, 2, 3].map(i => { const ph = md(rPhi * .5 + i / 4, 1); return <circle key={i} cx={ox} cy={360} r={lerp(235, 100, out(ph)) * k} opacity={ringOp * (1 - ph) * Math.min(1, ph * 6) * (.25 + .6 * Lin)} />; })}
            </g>
          </svg>
        )}
        <div style={{ position: 'absolute', left: ox - size / 2, top: 360 - size / 2, width: size, height: size }}>
          <Orb st={st} size={size} churnOp={F.w.think || 0} churnPhi={F.ph.think || 0} />
        </div>
        {F.ask && <AskText a={F.ask} question={tw.question} phrase={tw.phrase} />}
        {tw.nameTag && (
          <div style={{ position: 'absolute', left: 22, bottom: 22, display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderRadius: 10, background: 'rgba(20,4,12,.55)', font: `500 20px ${SANS}`, color: COL.INK }}>
            CT Agent<span style={{ font: `400 17px ${MONO}`, color: '#FFB36B', padding: '3px 8px', borderRadius: 6, background: 'rgba(255,138,26,.16)' }}>{LBL[label]}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function AgentClipsApp() {
  const [t, setTweak] = useTweaks(window.TWEAK_DEFAULTS);
  const all = window.OM_SCENES, list = JSON.parse(all);
  const frag = t.fragment && t.fragment !== 'All clips' ? list.find(s => s.name === t.fragment) : null;
  const scenes = frag ? JSON.stringify([frag]) : all;
  return (
    <React.Fragment>
      <CompositionStage key={t.fragment} width={1920} height={1080} bg="#1E0411" scenes={scenes} playback={window.OM_PLAYBACK}>
        <Clips tw={t} />
      </CompositionStage>
      <TweaksPanel>
        <TweakSection label="Export" />
        <TweakSelect label="Fragment" value={t.fragment} options={['All clips', ...list.map(s => s.name)]} onChange={v => setTweak('fragment', v)} />
        <TweakToggle label="Name tag" value={t.nameTag} onChange={v => setTweak('nameTag', v)} />
        <TweakSection label="Asking" />
        <TweakText label="Question" value={t.question} onChange={v => setTweak('question', v)} />
        <TweakText label="Phrase" value={t.phrase} onChange={v => setTweak('phrase', v)} />
        <TweakToggle label="Motion editor" value={t.motionEditor} onChange={v => setTweak('motionEditor', v)} />
      </TweaksPanel>
    </React.Fragment>
  );
}
window.AgentClipsApp = AgentClipsApp;
})();
