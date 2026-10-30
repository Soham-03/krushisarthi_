import { useEffect, useRef, useState } from "react";
import { FileUp, Loader2 } from "lucide-react";
import Sheet from "./Sheet";
import { api } from "../api";
import { useApp } from "../store";

const FIELDS = [
  ["n", "Nitrogen (N)", "kg/ha", "e.g. 280"], ["p", "Phosphorus (P)", "kg/ha", "e.g. 14"], ["k", "Potassium (K)", "kg/ha", "e.g. 180"],
  ["ph", "pH", "", "e.g. 7.2"], ["oc", "Organic carbon", "%", "e.g. 0.6"], ["ec", "Salinity (EC)", "dS/m", "e.g. 0.4"],
];

export default function SoilSheet({ open, onClose }) {
  const { farm, ov, reload, toast, cfg } = useApp();
  const [vals, setVals] = useState({});
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const file = useRef(null);

  useEffect(() => {
    if (open) { setVals(Object.fromEntries(FIELDS.map(([k]) => [k, ov?.soil_raw?.[k] ?? ""]))); setNote(""); }
  }, [open]); // eslint-disable-line

  const upload = async (e) => {
    const f = e.target.files?.[0]; e.target.value = "";
    if (!f) return;
    setBusy(true);
    try {
      const fd = new FormData(); fd.append("image", f);
      const r = await api.upload(`/api/farms/${farm.id}/soil/extract`, fd);
      if (r.error) { toast(r.error, "bad"); }
      else {
        setVals((v) => ({ ...v, ...Object.fromEntries(Object.entries(r).filter(([k, x]) => FIELDS.some(([f]) => f === k) && x != null)) }));
        setNote((r.units_note ? "Units on the report: " + r.units_note + ". " : "") + "Check each value against your report, then save.");
      }
    } catch (err) { toast(err.message, "bad"); }
    setBusy(false);
  };

  const save = async () => {
    const body = {};
    FIELDS.forEach(([k]) => { if (vals[k] !== "" && vals[k] != null && !isNaN(+vals[k])) body[k] = +vals[k]; });
    setBusy(true);
    try { await api.put(`/api/farms/${farm.id}/soil`, body); toast("Soil test saved", "good"); await reload(); onClose(); }
    catch (err) { toast(err.message, "bad"); }
    setBusy(false);
  };

  return (
    <Sheet open={open} onClose={onClose} title="Soil test">
      <p className="muted">Enter the values from your Soil Health Card or lab report. Leave blank what you do not have.</p>
      <input ref={file} type="file" accept="image/*" hidden onChange={upload} />
      <button className="btn ghost block" disabled={busy || !cfg.ai} onClick={() => file.current?.click()}>
        <FileUp size={18} /> {cfg.ai ? "Read values from a photo of the report" : "Report reading needs the AI key"}
      </button>
      {note && <p className="note">{note}</p>}
      <div className="form-grid">
        {FIELDS.map(([k, label, unit, ph]) => (
          <label key={k}>
            <span>{label}{unit && <small> {unit}</small>}</span>
            <input inputMode="decimal" value={vals[k] ?? ""} placeholder={ph} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      <button className="btn primary block" disabled={busy} onClick={save}>{busy ? <Loader2 className="spin" size={18} /> : "Save soil test"}</button>
    </Sheet>
  );
}
