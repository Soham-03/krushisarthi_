import { useState } from "react";
import { Camera, FlaskConical, Lightbulb, MessageCircle, RefreshCw, ScanLine, Satellite } from "lucide-react";
import { useApp } from "../store";
import { STATUS, fmtDate } from "../util";
import FarmMosaic from "../components/FarmMosaic";
import NdviChart from "../components/NdviChart";
import WeatherCard, { AlertList } from "../components/WeatherCard";
import DiagnosisCard from "../components/DiagnosisCard";
import SoilSheet from "../components/SoilSheet";
import ScanSheet from "../components/ScanSheet";

function Ring({ value, tone }) {
  const r = 34, c = 2 * Math.PI * r, v = value ?? 0;
  return (
    <svg className={"ring " + tone} viewBox="0 0 80 80" width="84" height="84" role="img" aria-label={`Health ${v} out of 100`}>
      <circle cx="40" cy="40" r={r} className="ring-bg" />
      <circle cx="40" cy="40" r={r} className="ring-fg" strokeDasharray={`${(c * v) / 100} ${c}`} transform="rotate(-90 40 40)" />
      <text x="40" y="46" textAnchor="middle" className="ring-num">{value ?? "–"}</text>
    </svg>
  );
}

function Skeleton() {
  return <div className="stack"><div className="card sk h180" /><div className="card sk h120" /><div className="card sk h220" /></div>;
}

export default function Home() {
  const { ov, ovState, ovError, reload, t, setTab, farm } = useApp();
  const [soil, setSoil] = useState(false);
  const [scan, setScan] = useState(false);

  if (ovState === "error") return <div className="card"><h3>Could not load your farm</h3><p className="muted">{ovError}</p><button className="btn primary" onClick={() => reload()}>Try again</button></div>;
  if (!ov) return <Skeleton />;

  const { satellite: sat, crop, weather, diagnosis: diag, tips, soil: soilR, checkup } = ov;
  const st = STATUS[sat.status];
  const tone = st.tone;
  const showScore = ["normal", "watch", "abnormal"].includes(sat.status);
  const label = ["normal", "watch", "abnormal"].includes(sat.status) ? t("status_" + sat.status) : st.label;

  return (
    <div className="home">
      <section className={"hero " + tone}>
        <div className="hero-copy">
          <div className="hero-top">
            <span className="chip light">{crop.name}</span>
            <span className="chip light">{crop.stage.name}</span>
          </div>
          <h1>{label}</h1>
          <p>{sat.message}</p>
          <div className="progress" aria-label={`Day ${crop.day} of about ${crop.duration}`}>
            <i style={{ width: crop.progress * 100 + "%" }} />
          </div>
          <small>Day {Math.max(0, crop.day)} of about {crop.duration} · sown {fmtDate(farm.sowing_date)}</small>
        </div>
        <div className="hero-visual">
          <FarmMosaic geometry={farm.geometry} health={sat.health ?? 70} seed={farm.id} size={150} />
          {showScore && <Ring value={sat.health} tone={tone} />}
        </div>
        <div className="hero-foot">
          <span><Satellite size={14} /> {sat.source === "gee" ? "Sentinel-2 satellite" : "Demo satellite data"}{sat.last ? ` · pass of ${fmtDate(sat.last.date)}` : ""}</span>
          <button className="link-light" onClick={() => reload(true)} disabled={ovState === "loading"}><RefreshCw size={14} className={ovState === "loading" ? "spin" : ""} /> Refresh</button>
        </div>
        {sat.error && <div className="hero-warn">{sat.error}</div>}
      </section>

      <div className="quick">
        <button onClick={() => setScan(true)}><ScanLine size={22} /><span>{t("scan_leaf")}</span></button>
        <button onClick={() => setTab("checkup")}><Camera size={22} /><span>{t("weekly_checkup")}</span>{!checkup.this_week_done && <i className="dot" />}</button>
        <button onClick={() => setTab("assistant")}><MessageCircle size={22} /><span>{t("ask_ai")}</span></button>
      </div>

      <div className="cols">
        <div className="stack">
          {weather.alerts.length > 0 && (
            <section className="card flush">
              <div className="card-pad"><h3>Weather warnings</h3></div>
              <AlertList alerts={weather.alerts} />
            </section>
          )}
          <DiagnosisCard diag={diag} t={t} onSoil={() => setSoil(true)} onCheckup={() => setTab("checkup")} />
          {!diag.needed && (
            <section className="card">
              <h3><Lightbulb size={18} /> {t("tips")}</h3>
              <ul className="tips">{tips.map((x, i) => <li key={i}><b>{x.title}</b><span>{x.text}</span></li>)}</ul>
            </section>
          )}
          {sat.series.length > 0 && (
            <section className="card">
              <h3>{t("growth_chart")}</h3>
              <NdviChart sat={sat} crop={crop} />
            </section>
          )}
        </div>
        <div className="stack">
          <section className="card">
            <h3>{t("weather")}</h3>
            <WeatherCard weather={weather} today={ov.today} />
          </section>
          <section className="card">
            <div className="card-head"><h3><FlaskConical size={18} /> {t("soil")}</h3><button className="btn ghost small" onClick={() => setSoil(true)}>{soilR ? "Update" : "Add soil test"}</button></div>
            {soilR ? (
              <div className="soil">
                {Object.entries(soilR).map(([k, v]) => (
                  <div key={k} className={"soil-chip " + (["low", "strongly acidic", "strongly alkaline", "saline"].includes(v.rating) ? "bad" : ["medium", "acidic", "alkaline", "slightly saline"].includes(v.rating) ? "warn" : "good")}>
                    <small>{k === "oc" ? "Org. C" : k === "ph" ? "pH" : k.toUpperCase()}</small><b>{v.value}</b><em>{v.rating}</em>
                  </div>
                ))}
              </div>
            ) : <p className="muted">No soil test yet. Add the values from your Soil Health Card to get nutrient advice that fits this farm.</p>}
          </section>
        </div>
      </div>
      <SoilSheet open={soil} onClose={() => setSoil(false)} />
      <ScanSheet open={scan} onClose={() => setScan(false)} />
    </div>
  );
}
