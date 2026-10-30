import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, Camera, CheckCircle2, Images, Loader2, LocateFixed, RefreshCw, RotateCcw, Star, TrendingUp, TriangleAlert } from "lucide-react";
import { api, dropPhotoCache, photoUrl } from "../api";
import { useApp } from "../store";
import { DAYS, compressImage, distanceM, fmtDate } from "../util";
import FarmMap from "../components/FarmMap";
import Sheet from "../components/Sheet";
import ResultCard from "../components/ResultCard";

const statusClass = (p) => {
  const s = p?.result?.status;
  return s === "healthy" ? "ok" : s === "issue" ? "issue" : s === "unclear" ? "unclear" : s === "error" ? "err" : "todo";
};

function Thumb({ id, className }) {
  const [src, setSrc] = useState("");
  useEffect(() => { let on = true; photoUrl("checkup", id).then((u) => on && setSrc(u)).catch(() => {}); return () => { on = false; }; }, [id]);
  return src ? <img className={className} src={src} alt="" loading="lazy" /> : <div className={className + " ph"} />;
}

function TrendBars({ items }) {
  if (!items.length) return null;
  const last = items.slice(-8);
  return (
    <div className="trend" aria-label="Share of spots with a problem, by week">
      {last.map((w, i) => (
        <div key={i} className="trend-col" title={`${fmtDate(w.week)}: ${Math.round(w.rate * 100)}% of spots with a problem`}>
          <span className="trend-val">{Math.round(w.rate * 100)}%</span>
          <i className={w.rate >= 0.3 ? "bad" : w.rate >= 0.15 ? "warn" : "good"} style={{ height: Math.max(6, w.rate * 100) + "%" }} />
          <small>{fmtDate(w.week)}</small>
        </div>
      ))}
    </div>
  );
}

function Summary({ session, farm, trend, onBack }) {
  const s = session.summary || session.live;
  const healthyPct = s.analyzed ? Math.round((s.healthy / s.analyzed) * 100) : 0;
  const topPhoto = session.photos.find((p) => p.result?.status === "issue" && p.result.issue === s.top_issue);
  const byId = Object.fromEntries(session.photos.map((p) => [p.spot_index, p]));
  return (
    <div className="stack">
      <button className="back" onClick={onBack}><ArrowLeft size={18} /> Back to checkups</button>
      <section className={"card sumcard " + (s.spreading ? "bad" : s.issue_rate >= 0.15 ? "warn" : "good")}>
        <div className="sum-ring"><b>{healthyPct}%</b><small>healthy</small></div>
        <div>
          <h3>Checkup of {fmtDate(session.week_start, { day: "numeric", month: "long" })}</h3>
          <p>{s.analyzed} photos checked · {s.healthy} healthy · {s.issues} with a problem{s.unclear ? ` · ${s.unclear} unclear` : ""}</p>
          {s.delta != null && (
            <span className={"chip " + (s.delta > 0.05 ? "bad" : s.delta < -0.05 ? "good" : "idle")}>
              <TrendingUp size={14} /> {s.delta > 0 ? "Up" : s.delta < 0 ? "Down" : "Same as"} {Math.abs(Math.round(s.delta * 100))} points vs last week{s.spreading ? " · spreading" : ""}
            </span>
          )}
        </div>
      </section>
      {s.by_issue?.length > 0 && (
        <section className="card">
          <h3>What we found</h3>
          <ul className="found">{s.by_issue.map((b) => <li key={b.name}><span>{b.name}</span><b>{b.count} spot{b.count > 1 ? "s" : ""}</b></li>)}</ul>
          {topPhoto && <><h4>What to do</h4><ul className="steps">{topPhoto.result.advice.map((a, i) => <li key={i}>{a}</li>)}</ul></>}
        </section>
      )}
      <section className="card">
        <h3>Where the problems are</h3>
        <FarmMap geometry={farm.geometry} spots={session.spots} statusOf={(sp) => statusClass(byId[sp.i])} height={260} />
        <div className="legend pins"><span><i className="pin-dot ok" /> Healthy</span><span><i className="pin-dot issue" /> Problem</span><span><i className="pin-dot unclear" /> Unclear</span><span><i className="pin-dot todo" /> No photo</span></div>
      </section>
      {trend.length > 1 && <section className="card"><h3>Week by week</h3><TrendBars items={trend} /></section>}
    </div>
  );
}

export default function Checkup() {
  const { farm, ov, toast, cfg, reload, loadNotes, notes } = useApp();
  const [session, setSession] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [count, setCount] = useState(30);
  const [sel, setSel] = useState(null);
  const [pending, setPending] = useState({});
  const [detail, setDetail] = useState(null);
  const [confirm, setConfirm] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [viewing, setViewing] = useState(null);
  const [me, setMe] = useState(null);
  const watch = useRef(null);
  const meRef = useRef(null);
  const sidRef = useRef(null);
  const queue = useRef([]);
  const running = useRef(0);
  const cam = useRef(null);
  const gal = useRef(null);
  const forced = useRef(null);

  const loadAll = useCallback(async () => {
    if (!farm) return;
    setLoading(true);
    try {
      const list = await api.get(`/api/farms/${farm.id}/checkups`);
      setHistory(list);
      const act = list.find((x) => x.status === "active");
      if (act) { const s = await api.get(`/api/checkups/${act.id}`); setSession(s); sidRef.current = s.id; } else { setSession(null); sidRef.current = null; }
    } catch (e) { toast(e.message, "bad"); }
    setLoading(false);
  }, [farm?.id]); // eslint-disable-line
  useEffect(() => { setViewing(null); setPending({}); setSel(null); loadAll(); }, [loadAll]);
  useEffect(() => () => { if (watch.current != null) navigator.geolocation.clearWatch(watch.current); }, []);

  const start = async () => {
    try { const s = await api.post(`/api/farms/${farm.id}/checkups`, { spots: count }); setSession(s); sidRef.current = s.id; setSel(null); }
    catch (e) { toast(e.message, "bad"); }
  };

  const byId = Object.fromEntries((session?.photos || []).map((p) => [p.spot_index, p]));
  const spotStatus = (sp) => (pending[sp.i] && !byId[sp.i] ? "up" : pending[sp.i]?.status === "uploading" ? "up" : statusClass(byId[sp.i]));
  const nextFree = () => session?.spots.find((s) => !byId[s.i] && !pending[s.i])?.i ?? null;
  const current = sel ?? nextFree() ?? session?.spots[0]?.i;
  const curSpot = session?.spots.find((s) => s.i === current);

  const process = async (job) => {
    const { spot } = job;
    setPending((p) => ({ ...p, [spot]: { ...p[spot], status: "uploading" } }));
    try {
      const blob = job.blob || (await compressImage(job.file));
      job.blob = blob;
      const fd = new FormData();
      fd.append("spot_index", spot);
      const pos = meRef.current;
      if (pos) { fd.append("lat", pos.lat); fd.append("lng", pos.lng); }
      fd.append("image", blob, "plant.jpg");
      const s = await api.upload(`/api/checkups/${sidRef.current}/photos`, fd);
      dropPhotoCache("checkup", (s.photos.find((x) => x.spot_index === spot) || {}).id);
      setSession(s);
      setPending((p) => { const n = { ...p }; delete n[spot]; return n; });
    } catch (e) {
      setPending((p) => ({ ...p, [spot]: { ...p[spot], status: "failed", error: e.message, job } }));
    }
  };
  const pump = () => {
    while (running.current < 2 && queue.current.length) {
      const job = queue.current.shift();
      running.current++;
      process(job).finally(() => { running.current--; pump(); });
    }
  };
  const enqueue = (files, only) => {
    const free = session.spots.filter((s) => !byId[s.i] && !pending[s.i]).map((s) => s.i);
    const jobs = [];
    if (only != null) jobs.push({ spot: only, file: files[0] });
    else {
      const order = free.slice(free.indexOf(current) >= 0 ? free.indexOf(current) : 0).concat(free.slice(0, Math.max(0, free.indexOf(current))));
      files.forEach((f, i) => { if (order[i] != null) jobs.push({ spot: order[i], file: f }); });
      if (files.length > order.length) toast(`${files.length - order.length} photo(s) left out: all spots are used.`, "warn");
    }
    setPending((p) => { const n = { ...p }; jobs.forEach((j) => { n[j.spot] = { status: "queued", preview: URL.createObjectURL(j.file) }; }); return n; });
    queue.current.push(...jobs);
    pump();
    setSel(null);
  };
  const onCam = (e) => { const f = [...(e.target.files || [])]; e.target.value = ""; if (f.length) { enqueue(f, forced.current); forced.current = null; } };
  const onGal = (e) => { const f = [...(e.target.files || [])]; e.target.value = ""; if (f.length) enqueue(f, null); };
  const takePhoto = (spot) => { forced.current = spot ?? null; cam.current?.click(); };
  const retry = (spot) => { const j = pending[spot]?.job; if (j) { queue.current.push(j); setPending((p) => ({ ...p, [spot]: { ...p[spot], status: "queued" } })); pump(); } };

  const locate = () => {
    if (!navigator.geolocation) return toast("Location is not available on this device.", "warn");
    if (watch.current != null) { navigator.geolocation.clearWatch(watch.current); watch.current = null; setMe(null); meRef.current = null; return; }
    watch.current = navigator.geolocation.watchPosition(
      (p) => { const v = { lat: p.coords.latitude, lng: p.coords.longitude }; setMe(v); meRef.current = v; },
      () => toast("Allow location access to see your position on the map.", "warn"), { enableHighAccuracy: true });
  };

  const finish = async () => {
    setFinishing(true);
    try {
      const s = await api.post(`/api/checkups/${session.id}/complete`);
      setSession(null); sidRef.current = null; setPending({}); setConfirm(false);
      await loadAll(); setViewing(s); reload(); loadNotes();
      toast("Checkup saved", "good");
    } catch (e) { toast(e.message, "bad"); }
    setFinishing(false);
  };
  const discard = async () => {
    if (!window.confirm("Discard this checkup and all its photos?")) return;
    await api.del(`/api/checkups/${session.id}`); setSession(null); sidRef.current = null; setPending({}); loadAll();
  };
  const openHistory = async (id) => { try { setViewing(await api.get(`/api/checkups/${id}`)); } catch (e) { toast(e.message, "bad"); } };

  if (!farm) return null;
  if (loading) return <div className="stack"><div className="card sk h180" /><div className="card sk h220" /></div>;

  const trend = ov?.checkup?.trend || [];
  if (viewing) return <Summary session={viewing} farm={farm} trend={trend} onBack={() => setViewing(null)} />;

  // ---------------------------------------------------------------- no active session
  if (!session) {
    const done = ov?.checkup?.this_week_done;
    const reminder = DAYS[farm.reminder_day];
    return (
      <div className="stack">
        <section className="card checkup-start">
          <div className="cs-icon"><Camera size={28} /></div>
          <h2>Weekly plant checkup</h2>
          <p className="muted">Walk the field and photograph one plant at each marked spot. The AI checks every photo for pests and disease, and compares with last week to catch problems that are spreading.</p>
          {done && <p className="note ok"><CheckCircle2 size={16} /> You already finished a checkup this week. You can still run another one.</p>}
          <div className="slider">
            <label htmlFor="spots"><b>{count} photos</b><small>about {Math.round(count * 0.75)} minutes</small></label>
            <input id="spots" type="range" min="30" max="40" value={count} onChange={(e) => setCount(+e.target.value)} />
            <div className="range-ends"><span>30</span><span>40</span></div>
          </div>
          <ul className="how">
            <li>The app marks {count} spread-out spots along an easy walking route.</li>
            <li>Take one clear photo per spot. Leaf top side, close up, in daylight.</li>
            <li>Spots the satellite flagged are marked with a star. Look closely there.</li>
          </ul>
          <button className="btn primary block" onClick={start}>Start this week's checkup</button>
          <small className="muted">Weekly reminder: every {reminder}. Change it in the Alerts tab.</small>
        </section>
        {trend.length > 1 && <section className="card"><h3>Week by week</h3><TrendBars items={trend} /></section>}
        {history.filter((h) => h.status === "done").length > 0 && (
          <section className="card flush">
            <div className="card-pad"><h3>Past checkups</h3></div>
            <div className="list">
              {history.filter((h) => h.status === "done").map((h) => (
                <button key={h.id} className="row-btn" onClick={() => openHistory(h.id)}>
                  <span><b>Week of {fmtDate(h.week_start)}</b><small>{h.summary.analyzed} photos · {h.summary.issues} with a problem</small></span>
                  <em className={"chip " + (h.summary.spreading ? "bad" : h.summary.issue_rate >= 0.15 ? "warn" : "good")}>{Math.round(h.summary.issue_rate * 100)}%</em>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    );
  }

  // ---------------------------------------------------------------- active session
  const photos = session.photos.length;
  const target = session.target;
  const dist = me && curSpot ? Math.round(distanceM(me.lat, me.lng, curSpot.lat, curSpot.lng)) : null;
  const detailPhoto = detail != null ? byId[detail] : null;

  return (
    <div className="stack checkup-live">
      {!cfg.ai && cfg.satellite !== "demo" && <div className="note"><TriangleAlert size={16} /> Demo mode: photo results are simulated. Add the AI key in the backend settings for real analysis.</div>}
      <section className="card">
        <div className="card-head"><h3>Week of {fmtDate(session.week_start)}</h3><b className="count">{photos}/{target}</b></div>
        <div className="bar"><i style={{ width: (photos / target) * 100 + "%" }} /></div>
        <small className="muted">{photos} photos taken. Follow the numbers in order. Tap any pin to jump to that spot.</small>
      </section>

      <section className="card flush">
        <FarmMap geometry={farm.geometry} spots={session.spots} statusOf={spotStatus} selected={current} onSelect={setSel} me={me} height={300} />
        <div className="legend pins pad">
          <span><i className="pin-dot todo" /> To do</span><span><i className="pin-dot ok" /> Healthy</span><span><i className="pin-dot issue" /> Problem</span><span><i className="pin-dot pri" /> Look closely</span>
          <button className="link" onClick={locate}><LocateFixed size={14} /> {me ? "Hide my position" : "Show my position"}</button>
        </div>
      </section>

      {curSpot && (
        <section className="card spotcard">
          <div>
            <b>Spot {curSpot.i} of {target}</b>
            {curSpot.priority && <span className="chip warn"><Star size={12} /> Look closely here</span>}
            <p className="muted small">{dist != null ? `About ${dist} m from you. ` : ""}Photograph one plant: close up, leaf top side, in daylight.</p>
          </div>
          {byId[curSpot.i] ? <button className="btn ghost small" onClick={() => setDetail(curSpot.i)}>See result</button> : null}
        </section>
      )}

      <section className="card">
        <h3>Your photos</h3>
        <div className="grid">
          {session.spots.map((sp) => {
            const p = byId[sp.i], pe = pending[sp.i];
            const cls = pe && !p ? "up" : statusClass(p);
            return (
              <button key={sp.i} className={"cell " + cls + (current === sp.i ? " cur" : "")} onClick={() => (p ? setDetail(sp.i) : pe?.status === "failed" ? retry(sp.i) : setSel(sp.i))}>
                {p ? <Thumb id={p.id} className="cell-img" /> : pe ? <img className="cell-img" src={pe.preview} alt="" /> : <span className="cell-num">{sp.i}</span>}
                <span className="cell-tag">{pe && !p ? (pe.status === "failed" ? <RotateCcw size={12} /> : <Loader2 size={12} className="spin" />) : p ? (cls === "ok" ? "✓" : cls === "issue" ? "!" : "?") : ""}</span>
                {pe?.status === "failed" && <span className="cell-fail">Retry</span>}
              </button>
            );
          })}
        </div>
      </section>

      <div className="row gap wrap">
        <button className="btn ghost" onClick={() => gal.current?.click()}><Images size={18} /> Add several photos at once</button>
        <button className="btn danger ghost" onClick={discard}>Discard</button>
      </div>

      <input ref={cam} type="file" accept="image/*" capture="environment" hidden onChange={onCam} />
      <input ref={gal} type="file" accept="image/*" multiple hidden onChange={onGal} />

      <div className="fab-bar">
        <button className="fab" onClick={() => takePhoto(current && !byId[current] ? current : nextFree())} disabled={!nextFree() && !current}>
          <Camera size={22} /> Take photo{current ? ` · spot ${current}` : ""}
        </button>
        <button className="fab alt" onClick={() => (photos < target ? setConfirm(true) : finish())} disabled={photos < 1 || finishing}>Finish</button>
      </div>

      <Sheet open={confirm} onClose={() => setConfirm(false)} title="Finish this checkup?">
        <p>You have <b>{photos}</b> of <b>{target}</b> photos. More photos give a more reliable picture of the field. You can still finish now.</p>
        <div className="row gap"><button className="btn ghost grow" onClick={() => setConfirm(false)}>Keep going</button><button className="btn primary grow" disabled={finishing} onClick={finish}>{finishing ? <Loader2 className="spin" size={18} /> : "Finish now"}</button></div>
      </Sheet>

      <Sheet open={!!detailPhoto} onClose={() => setDetail(null)} title={`Spot ${detail}`}>
        {detailPhoto && <>
          <Thumb id={detailPhoto.id} className="preview" />
          <ResultCard result={detailPhoto.result} />
          <button className="btn ghost block" onClick={() => { const s = detail; setDetail(null); takePhoto(s); }}><RefreshCw size={18} /> Retake this photo</button>
        </>}
      </Sheet>
    </div>
  );
}
