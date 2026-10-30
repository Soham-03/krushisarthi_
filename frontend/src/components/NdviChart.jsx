import { useMemo, useState } from "react";
import { Area, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtDate } from "../util";

const INDEX = {
  ndvi: { label: "Greenness (NDVI)", color: "#1E6B4A", hint: "How green and dense the crop is." },
  ndmi: { label: "Moisture", color: "#2D79B5", hint: "Water in the leaves. Low values suggest dry stress." },
  ndre: { label: "Chlorophyll", color: "#8A6A3D", hint: "Leaf nutrition signal. Low values can mean nitrogen shortage." },
};

export default function NdviChart({ sat, crop }) {
  const [idx, setIdx] = useState("ndvi");
  const rows = useMemo(() => {
    const map = new Map();
    sat.expected_curve.forEach((c) => map.set(c.day, { day: c.day, expected: c.expected, band: [c.expected * 0.88, c.expected * 1.12] }));
    sat.series.forEach((s) => {
      const r = map.get(s.day) || { day: s.day };
      r.value = s[idx]; r.date = s.date;
      map.set(s.day, r);
    });
    return [...map.values()].sort((a, b) => a.day - b.day);
  }, [sat, idx]);
  const m = INDEX[idx];
  const ticks = [];
  for (let d = 0; d <= crop.duration; d += 20) ticks.push(d);
  return (
    <div className="chart">
      <div className="seg">
        {Object.entries(INDEX).map(([k, v]) => (
          <button key={k} className={idx === k ? "on" : ""} onClick={() => setIdx(k)}>{v.label.split(" (")[0]}</button>
        ))}
      </div>
      <p className="muted small">{m.hint}</p>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height={220}>
          <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <XAxis dataKey="day" type="number" domain={[0, crop.duration]} ticks={ticks} tickFormatter={(d) => d + "d"} tick={{ fontSize: 11, fill: "#5b6b60" }} axisLine={false} tickLine={false} />
            <YAxis domain={idx === "ndvi" ? [0, 1] : ["auto", "auto"]} tick={{ fontSize: 11, fill: "#5b6b60" }} axisLine={false} tickLine={false} width={44} tickFormatter={(v) => (+v).toFixed(1)} />
            <Tooltip
              formatter={(v, n) => (Array.isArray(v) ? ["", ""] : [(+v).toFixed(2), n === "expected" ? "Expected" : m.label])}
              labelFormatter={(d) => "Day " + d}
              contentStyle={{ borderRadius: 10, border: "1px solid #dde5da", fontSize: 12 }}
            />
            {idx === "ndvi" && <Area dataKey="band" stroke="none" fill="#7CC96B" fillOpacity={0.18} connectNulls isAnimationActive={false} />}
            {idx === "ndvi" && <Line dataKey="expected" stroke="#6b7d70" strokeDasharray="5 4" dot={false} strokeWidth={1.6} connectNulls isAnimationActive={false} name="expected" />}
            <Line dataKey="value" stroke={m.color} strokeWidth={2.4} dot={{ r: 3.2, fill: m.color, stroke: "#fff", strokeWidth: 1 }} connectNulls isAnimationActive={false} name="value" />
            <ReferenceLine x={Math.min(crop.day, crop.duration)} stroke="#d14b3f" strokeDasharray="2 3" label={{ value: "today", fontSize: 10, fill: "#d14b3f", position: "insideTopRight" }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      {idx === "ndvi" && <div className="legend"><span><i className="sw line" /> Your farm</span><span><i className="sw dash" /> Expected</span><span><i className="sw band" /> Normal range</span></div>}
      {sat.last && <p className="muted small">Latest clear satellite pass: {fmtDate(sat.last.date)}. New passes arrive about every 5 days when the sky is clear.</p>}
    </div>
  );
}
