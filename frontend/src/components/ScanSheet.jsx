import { useRef, useState } from "react";
import { Camera, Loader2 } from "lucide-react";
import Sheet from "./Sheet";
import ResultCard from "./ResultCard";
import { api } from "../api";
import { compressImage } from "../util";
import { useApp } from "../store";

export default function ScanSheet({ open, onClose }) {
  const { farm, toast } = useApp();
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState("");
  const [result, setResult] = useState(null);

  const pick = async (e) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f || !farm) return;
    setResult(null); setBusy(true);
    try {
      const blob = await compressImage(f);
      setPreview(URL.createObjectURL(blob));
      const fd = new FormData();
      fd.append("image", blob, "leaf.jpg");
      const r = await api.upload(`/api/farms/${farm.id}/detect`, fd);
      setResult(r.result);
    } catch (err) { toast(err.message, "bad"); }
    setBusy(false);
  };
  const close = () => { setPreview(""); setResult(null); onClose(); };

  return (
    <Sheet open={open} onClose={close} title="Scan a leaf">
      <p className="muted">Hold the phone close to one leaf in daylight. Show the top side, then the underside if you see spots or insects.</p>
      <input ref={input} type="file" accept="image/*" capture="environment" hidden onChange={pick} />
      {preview && <img className="preview" src={preview} alt="Your leaf photo" />}
      {busy && <div className="busy"><Loader2 className="spin" size={20} /> Checking your photo…</div>}
      <ResultCard result={result} />
      <button className="btn primary block" disabled={busy} onClick={() => input.current?.click()}><Camera size={18} /> {preview ? "Scan another leaf" : "Take photo"}</button>
    </Sheet>
  );
}
