import { useState } from "react";
import { Plus, Trash2, Loader2, ChevronLeft } from "lucide-react";
import { api } from "../api";
import { useApp } from "../store";
import { DAYS, acres, areaHa, fmtDate } from "../util";
import DrawMap from "../components/DrawMap";
import FarmMosaic from "../components/FarmMosaic";
import Sheet from "../components/Sheet";

const SCENARIOS = [
  ["healthy", "Healthy crop"], ["nitrogen", "Low nitrogen after heavy rain"], ["water", "Dry spell and water stress"],
  ["disease", "Humid weather and disease"], ["late", "Late or slow start"],
];
const isoDaysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };

function Details({ values, setValues, cfg, crops }) {
  return (
    <div className="form">
      <label><span>Farm name</span><input value={values.name} onChange={(e) => setValues({ ...values, name: e.target.value })} maxLength={60} /></label>
      <div className="field"><span>Crop</span>
        <div className="crop-grid">
          {crops.map((c) => <button type="button" key={c.key} className={values.crop === c.key ? "on" : ""} onClick={() => setValues({ ...values, crop: c.key })}><b>{c.name}</b><small>{c.season}</small></button>)}
        </div>
      </div>
      <label><span>Sowing date</span><input type="date" value={values.sowing_date} onChange={(e) => setValues({ ...values, sowing_date: e.target.value })} /></label>
      <div className="chips">
        {[30, 45, 60].map((n) => <button type="button" key={n} className="chip-btn" onClick={() => setValues({ ...values, sowing_date: isoDaysAgo(n) })}>{n} days ago</button>)}
      </div>
      <label><span>Weekly checkup reminder</span>
        <select value={values.reminder_day} onChange={(e) => setValues({ ...values, reminder_day: +e.target.value })}>{DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select>
      </label>
      {cfg.satellite === "demo" && (
        <label><span>Demo data pattern</span>
          <select value={values.scenario} onChange={(e) => setValues({ ...values, scenario: e.target.value })}>{SCENARIOS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          <small className="muted">Only for demo mode. Pick a sowing date 45 to 60 days ago to see the problem show up.</small>
        </label>
      )}
    </div>
  );
}

export default function Farms() {
  const { farms, farm, setFarmId, loadFarms, cfg, toast, setTab } = useApp();
  const [mode, setMode] = useState("list"); // list | draw | details
  const [points, setPoints] = useState([]);
  const [vals, setVals] = useState({ name: "My farm", crop: "soybean", sowing_date: isoDaysAgo(45), scenario: "healthy", reminder_day: 6 });
  const [busy, setBusy] = useState(false);
  const [edit, setEdit] = useState(null);

  const create = async () => {
    setBusy(true);
    try {
      const ring = [...points, points[0]];
      const f = await api.post("/api/farms", { ...vals, geometry: { type: "Polygon", coordinates: [ring] } });
      await loadFarms(); setFarmId(f.id); setMode("list"); setPoints([]); setTab("home"); toast("Farm added. We are reading the satellite data.", "good");
    } catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };
  const saveEdit = async () => {
    setBusy(true);
    try { await api.patch(`/api/farms/${edit.id}`, { name: edit.name, crop: edit.crop, sowing_date: edit.sowing_date, reminder_day: edit.reminder_day, scenario: edit.scenario }); await loadFarms(); setEdit(null); toast("Farm updated", "good"); }
    catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };
  const remove = async () => {
    if (!window.confirm(`Delete ${edit.name} and all its checkups?`)) return;
    try { await api.del(`/api/farms/${edit.id}`); setEdit(null); await loadFarms(); toast("Farm deleted"); } catch (e) { toast(e.message, "bad"); }
  };

  if (mode === "draw") return (
    <div className="stack">
      <button className="back" onClick={() => { setMode("list"); setPoints([]); }}><ChevronLeft size={18} /> Back</button>
      <section className="card">
        <h3>Mark your farm</h3>
        <p className="muted">Zoom to your field, then tap each corner around its edge. Satellite view makes field edges easier to see.</p>
        <DrawMap points={points} setPoints={setPoints} toast={toast} />
        <button className="btn primary block" disabled={points.length < 3 || areaHa(points) < 0.01 || areaHa(points) > 2000} onClick={() => setMode("details")}>Next: crop and sowing date</button>
      </section>
    </div>
  );
  if (mode === "details") return (
    <div className="stack">
      <button className="back" onClick={() => setMode("draw")}><ChevronLeft size={18} /> Back to map</button>
      <section className="card">
        <h3>About this farm</h3>
        <p className="muted">{areaHa(points).toFixed(2)} ha ({acres(areaHa(points)).toFixed(1)} acres)</p>
        <Details values={vals} setValues={setVals} cfg={cfg} crops={cfg.crops} />
        <button className="btn primary block" disabled={busy || !vals.name.trim()} onClick={create}>{busy ? <Loader2 className="spin" size={18} /> : "Save farm"}</button>
      </section>
    </div>
  );

  return (
    <div className="stack">
      <div className="card-head"><h2>Your farms</h2><button className="btn primary small" onClick={() => setMode("draw")}><Plus size={16} /> Add farm</button></div>
      {(farms || []).map((f) => (
        <button key={f.id} className={"farm-card " + (farm?.id === f.id ? "on" : "")} onClick={() => { setFarmId(f.id); setTab("home"); }}>
          <FarmMosaic geometry={f.geometry} health={78} seed={f.id} size={72} cells={11} />
          <span className="fc-body">
            <b>{f.name}</b>
            <small>{cfg.crops.find((c) => c.key === f.crop)?.name} · {f.area_ha.toFixed(1)} ha · sown {fmtDate(f.sowing_date)}</small>
          </span>
          <span className="fc-edit" role="button" tabIndex={0} onClick={(e) => { e.stopPropagation(); setEdit({ ...f }); }} onKeyDown={(e) => e.key === "Enter" && (e.stopPropagation(), setEdit({ ...f }))}>Edit</span>
        </button>
      ))}
      <Sheet open={!!edit} onClose={() => setEdit(null)} title="Edit farm">
        {edit && <>
          <Details values={edit} setValues={setEdit} cfg={cfg} crops={cfg.crops} />
          <button className="btn primary block" disabled={busy} onClick={saveEdit}>Save changes</button>
          <button className="btn danger ghost block" onClick={remove}><Trash2 size={16} /> Delete farm</button>
        </>}
      </Sheet>
    </div>
  );
}
