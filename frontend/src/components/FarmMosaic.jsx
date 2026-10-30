import { useMemo } from "react";
import { scaleColor, seeded } from "../util";

// The farm's own outline, filled with a 10 m-style pixel grid coloured by crop health.
export default function FarmMosaic({ geometry, health = 80, seed = 1, size = 150, cells = 15 }) {
  const { path, rects, w, h } = useMemo(() => {
    const ring = (geometry?.coordinates?.[0] || []).slice(0, -1);
    if (ring.length < 3) return { path: "", rects: [], w: 100, h: 100 };
    const lat0 = ring.reduce((s, p) => s + p[1], 0) / ring.length;
    const kx = Math.cos((lat0 * Math.PI) / 180);
    const pts = ring.map(([x, y]) => [x * kx, -y]);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const minx = Math.min(...xs), maxx = Math.max(...xs), miny = Math.min(...ys), maxy = Math.max(...ys);
    const span = Math.max(maxx - minx, maxy - miny) || 1;
    const pad = 6, scale = (100 - pad * 2) / span;
    const nx = (maxx - minx) * scale, ny = (maxy - miny) * scale;
    const ox = (100 - nx) / 2, oy = (100 - ny) / 2;
    const P = pts.map(([x, y]) => [ox + (x - minx) * scale, oy + (y - miny) * scale]);
    const inside = (x, y) => {
      let c = false;
      for (let i = 0, j = P.length - 1; i < P.length; j = i++) {
        const [xi, yi] = P[i], [xj, yj] = P[j];
        if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
      }
      return c;
    };
    const rnd = seeded(seed * 97 + 3);
    const cx = ox + rnd() * nx, cy = oy + rnd() * ny;
    const step = (100 - pad * 2) / cells;
    const base = health / 100, out = [];
    for (let gy = 0; gy < cells; gy++) {
      for (let gx = 0; gx < cells; gx++) {
        const x = pad + gx * step, y = pad + gy * step;
        if (!inside(x + step / 2, y + step / 2)) continue;
        const d = Math.hypot(x - cx, y - cy) / 60;
        const patch = Math.max(0, 1 - d) * (1 - base) * 0.9;
        const v = base + (rnd() - 0.5) * 0.16 - patch;
        out.push({ x, y, c: scaleColor(v) });
      }
    }
    return { path: P.map((p, i) => (i ? "L" : "M") + p[0].toFixed(2) + " " + p[1].toFixed(2)).join(" ") + "Z", rects: out, w: 100, h: 100, step };
  }, [geometry, health, seed, cells]);
  const id = "m" + seed + "-" + Math.round(health);
  const step = (100 - 12) / cells;
  return (
    <svg className="mosaic" viewBox={`0 0 ${w} ${h}`} width={size} height={size} role="img" aria-label="Farm outline coloured by crop health">
      <defs><clipPath id={id}><path d={path} /></clipPath></defs>
      <g clipPath={`url(#${id})`}>
        {rects.map((r, i) => <rect key={i} x={r.x} y={r.y} width={step + 0.25} height={step + 0.25} fill={r.c} />)}
      </g>
      <path d={path} fill="none" stroke="rgba(255,255,255,.9)" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  );
}
