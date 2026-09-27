/* Live neural graph: nodes pulse, sparks travel synapses. */
(function () {
  const COLORS = {
    accent: [200, 245, 66],
    ink: [236, 235, 228],
    act: [200, 245, 66],
    review: [255, 181, 71],
    abstain: [255, 107, 91],
  };
  const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
  const mix = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];

  function rng(seed) {
    let s = seed >>> 0;
    return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
  }

  class NeuralGraph {
    constructor(canvas) {
      this.c = canvas;
      this.ctx = canvas.getContext("2d");
      this.nodes = [];
      this.edges = [];
      this.sparks = [];
      this.firing = 0;        // eased 0..1
      this.firingTarget = 0;
      this.tint = COLORS.accent;
      this.tintT = 0;         // settle flash 0..1
      this.wave = -1;         // x of settle wave (0..1), -1 off
      this.last = performance.now();
      this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
      new ResizeObserver(() => this.layout()).observe(canvas);
      this.layout();
      this.loop = this.loop.bind(this);
      requestAnimationFrame(this.loop);
    }

    layout() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = this.c.clientWidth, h = this.c.clientHeight;
      if (!w || !h) return;
      this.w = w; this.h = h;
      this.c.width = Math.round(w * dpr);
      this.c.height = Math.round(h * dpr);
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const r = rng(7331);
      const count = Math.max(26, Math.min(72, Math.round((w * h) / 1300)));
      const top = 34, bot = h - 10, left = 14, right = w - 14;
      const nodes = [];
      let guard = 0;
      while (nodes.length < count && guard++ < count * 40) {
        const x = left + r() * (right - left);
        const y = top + r() * (bot - top);
        if (nodes.every((n) => (n.x - x) ** 2 + (n.y - y) ** 2 > 20 ** 2)) {
          nodes.push({ x, y, r: 1.2 + r() * 1.6, e: 0, ph: r() * Math.PI * 2, out: [] });
        }
      }
      const edges = [];
      nodes.forEach((a, i) => {
        const near = nodes
          .map((b, j) => ({ j, d: Math.hypot(b.x - a.x, b.y - a.y) }))
          .filter((o) => o.j !== i && o.d < 110)
          .sort((p, q) => p.d - q.d)
          .slice(0, 3);
        near.forEach(({ j, d }) => {
          if (edges.some((e) => (e.a === j && e.b === i))) return;
          const e = { a: i, b: j, len: d, glow: 0, bend: (r() - 0.5) * 0.35 };
          edges.push(e);
        });
      });
      edges.forEach((e, k) => { nodes[e.a].out.push(k); nodes[e.b].out.push(k); });
      this.nodes = nodes;
      this.edges = edges;
      this.sparks = [];
      if (this.reduced) this.draw(0);
    }

    setFiring(on) {
      this.firingTarget = on ? 1 : 0;
      if (on) this.tint = COLORS.accent;
    }

    settle(gate) {
      this.tint = COLORS[gate] || COLORS.accent;
      this.tintT = 1;
      this.wave = 0;
    }

    spawn(fromNode, hot) {
      const n = this.nodes[fromNode];
      if (!n || !n.out.length) return;
      // prefer rightward flow: judgments move from evidence to answer
      const opts = n.out.map((k) => {
        const e = this.edges[k];
        const to = e.a === fromNode ? e.b : e.a;
        return { k, to, bias: this.nodes[to].x > n.x ? 2.2 : 0.6 };
      });
      const tot = opts.reduce((s, o) => s + o.bias, 0);
      let pick = Math.random() * tot, o = opts[0];
      for (const c of opts) { if ((pick -= c.bias) <= 0) { o = c; break; } }
      const e = this.edges[o.k];
      this.sparks.push({
        k: o.k, from: fromNode, to: o.to, t: 0,
        v: (hot ? 380 : 90) * (0.7 + Math.random() * 0.6) / e.len,
        hot, gen: 0,
      });
    }

    pointOn(e, from, t) {
      const A = this.nodes[from], B = this.nodes[from === e.a ? e.b : e.a];
      const mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2;
      const sgn = from === e.a ? 1 : -1;
      const cx = mx - (B.y - A.y) * e.bend * sgn, cy = my + (B.x - A.x) * e.bend * sgn;
      const u = 1 - t;
      return [u * u * A.x + 2 * u * t * cx + t * t * B.x, u * u * A.y + 2 * u * t * cy + t * t * B.y];
    }

    loop(now) {
      const dt = Math.min(0.05, (now - this.last) / 1000);
      this.last = now;
      if (!this.reduced) { this.step(dt, now / 1000); this.draw(now / 1000); }
      else if (this.firingTarget !== this.firing) { this.firing = this.firingTarget; this.draw(now / 1000); }
      requestAnimationFrame(this.loop);
    }

    step(dt, t) {
      this.firing += (this.firingTarget - this.firing) * Math.min(1, dt * 4);
      const f = this.firing;
      const rate = 1.2 + f * 38; // sparks per second
      if (Math.random() < rate * dt && this.nodes.length) {
        // idle: anywhere; firing: bias to the left edge (evidence entering)
        const pool = f > 0.3 ? this.nodes.filter((n) => n.x < this.w * 0.35) : this.nodes;
        const n = pool[(Math.random() * pool.length) | 0];
        this.spawn(this.nodes.indexOf(n), f > 0.5);
      }
      const cur = this.sparks;
      this.sparks = [];
      for (const s of cur) {
        s.t += s.v * dt * (1 + f * 0.6);
        const e = this.edges[s.k];
        e.glow = Math.min(1, e.glow + dt * 6);
        if (s.t >= 1) {
          const n = this.nodes[s.to];
          n.e = Math.min(1.4, n.e + (s.hot ? 0.9 : 0.55));
          const chain = s.hot ? 0.78 : 0.35;
          if (s.gen < 7 && Math.random() < chain && cur.length < 220) {
            const before = this.sparks.length;
            this.spawn(s.to, s.hot);
            if (this.sparks.length > before) this.sparks[before].gen = s.gen + 1;
          }
          if (s.hot && Math.random() < 0.18 && cur.length < 160) this.spawn(s.to, true);
        } else this.sparks.push(s);
      }
      for (const n of this.nodes) n.e *= Math.pow(0.12, dt);
      for (const e of this.edges) e.glow *= Math.pow(0.08, dt);
      if (this.tintT > 0) this.tintT = Math.max(0, this.tintT - dt * 0.45);
      if (this.wave >= 0) {
        const prev = this.wave;
        this.wave += dt * 1.4;
        const x0 = prev * this.w, x1 = this.wave * this.w;
        this.nodes.forEach((n) => { if (n.x >= x0 && n.x < x1) n.e = 1.4; });
        if (this.wave > 1.1) this.wave = -1;
      }
    }

    draw(t) {
      const { ctx, w, h } = this;
      if (!w) return;
      ctx.clearRect(0, 0, w, h);
      const f = this.firing;
      const base = this.tintT > 0 ? mix(COLORS.accent, this.tint, Math.min(1, this.tintT * 1.6)) : COLORS.accent;

      // synapses
      ctx.lineWidth = 1;
      for (const e of this.edges) {
        const A = this.nodes[e.a], B = this.nodes[e.b];
        const mx = (A.x + B.x) / 2, my = (A.y + B.y) / 2;
        const cx = mx - (B.y - A.y) * e.bend, cy = my + (B.x - A.x) * e.bend;
        const a = 0.055 + f * 0.05 + e.glow * 0.28;
        ctx.strokeStyle = e.glow > 0.05 ? rgba(base, a) : rgba(COLORS.ink, a);
        ctx.beginPath();
        ctx.moveTo(A.x, A.y);
        ctx.quadraticCurveTo(cx, cy, B.x, B.y);
        ctx.stroke();
      }

      // sparks with trails
      ctx.globalCompositeOperation = "lighter";
      for (const s of this.sparks) {
        const e = this.edges[s.k];
        const [x, y] = this.pointOn(e, s.from, Math.min(1, s.t));
        const [tx, ty] = this.pointOn(e, s.from, Math.max(0, s.t - 18 / e.len));
        const g = ctx.createLinearGradient(tx, ty, x, y);
        g.addColorStop(0, rgba(base, 0));
        g.addColorStop(1, rgba(base, s.hot ? 0.95 : 0.6));
        ctx.strokeStyle = g;
        ctx.lineWidth = s.hot ? 1.8 : 1.2;
        ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(x, y); ctx.stroke();
        ctx.fillStyle = rgba(COLORS.ink, s.hot ? 0.95 : 0.7);
        ctx.beginPath(); ctx.arc(x, y, s.hot ? 1.6 : 1.1, 0, Math.PI * 2); ctx.fill();
      }

      // nodes
      for (const n of this.nodes) {
        const pulse = 0.5 + 0.5 * Math.sin(t * (1.3 + f * 3) + n.ph);
        const e = Math.min(1, n.e);
        const glowR = n.r + 3 + e * 9 + pulse * (1.5 + f * 2);
        const g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, glowR);
        g.addColorStop(0, rgba(base, 0.14 + e * 0.5 + f * 0.08));
        g.addColorStop(1, rgba(base, 0));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(n.x, n.y, glowR, 0, Math.PI * 2); ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";
      for (const n of this.nodes) {
        const e = Math.min(1, n.e);
        const pulse = 0.5 + 0.5 * Math.sin(t * (1.3 + f * 3) + n.ph);
        ctx.fillStyle = e > 0.2 ? rgba(mix(COLORS.ink, base, 0.6), 0.6 + e * 0.4) : rgba(COLORS.ink, 0.28 + pulse * 0.25 + f * 0.15);
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r + e * 1.2, 0, Math.PI * 2); ctx.fill();
      }
    }
  }

  window.NeuralGraph = NeuralGraph;
})();
