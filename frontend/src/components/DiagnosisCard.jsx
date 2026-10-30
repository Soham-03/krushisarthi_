import { CheckCircle2, ChevronDown, Info } from "lucide-react";
import { useState } from "react";

const TONE = { likely: "bad", possible: "warn", unlikely: "idle" };

export default function DiagnosisCard({ diag, onSoil, onCheckup, t }) {
  const [open, setOpen] = useState(0);
  if (!diag.needed) return null;
  return (
    <section className="card">
      <h3>{diag.early ? "Early warning from your photo checkup" : "Why growth is low"}</h3>
      <p className="muted small">
        {diag.early
          ? "The satellite still shows normal growth, but your photos found a problem. Acting now is cheaper than acting later."
          : "We checked weather, water, nutrients, soil and your photo checkups together. Here is what fits best."}
      </p>
      {diag.unclear && <p className="note"><Info size={16} /> The cause is not clear yet. Add your soil test and do a photo checkup to narrow it down.</p>}
      <div className="causes">
        {diag.causes.map((c, i) => (
          <div key={c.key} className={"cause " + TONE[c.level]}>
            <button className="cause-head" onClick={() => setOpen(open === i ? -1 : i)} aria-expanded={open === i}>
              <span className="cause-title"><b>{c.title}</b><em className={"chip " + TONE[c.level]}>{c.level}</em></span>
              <span className="meter"><i style={{ width: c.score + "%" }} /></span>
              <ChevronDown size={18} className={open === i ? "flip" : ""} />
            </button>
            {open === i && (
              <div className="cause-body">
                <ul className="evidence">{c.evidence.map((e, k) => <li key={k}>{e}</li>)}</ul>
                <h4>{t("what_to_do")}</h4>
                <ul className="steps">{c.actions.map((a, k) => <li key={k}><CheckCircle2 size={16} />{a}</li>)}</ul>
              </div>
            )}
          </div>
        ))}
      </div>
      {diag.missing.length > 0 && (
        <div className="missing">
          <h4>To make this more accurate</h4>
          {diag.missing.map((m) => (
            <button key={m.key} className="link-row" onClick={m.key === "soil" ? onSoil : m.key === "checkup" ? onCheckup : undefined}>{m.text}</button>
          ))}
        </div>
      )}
      <p className="muted small">Confidence: {diag.confidence}. This is guidance, not a lab result. For serious damage, show your crop to the Taluka Agriculture Officer.</p>
    </section>
  );
}
