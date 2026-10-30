import { useEffect, useState } from "react";
import { AlertTriangle, BellRing, Camera, CheckCheck, CloudRain, Info, Sprout } from "lucide-react";
import { api } from "../api";
import { useApp } from "../store";
import { DAYS, ago, currentPushSub, pushSupported, urlBase64ToUint8Array } from "../util";

const ICON = { weather: CloudRain, growth: Sprout, checkup: Camera, test: Info };

export default function Alerts() {
  const { cfg, notes, loadNotes, farm, loadFarms, toast, t } = useApp();
  const [subbed, setSubbed] = useState(false);
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "unsupported");
  const [busy, setBusy] = useState(false);

  useEffect(() => { currentPushSub().then((s) => setSubbed(!!s)).catch(() => {}); }, []);
  useEffect(() => { if (notes.unread) api.post("/api/notifications/read").then(() => setTimeout(loadNotes, 1500)).catch(() => {}); }, []); // eslint-disable-line

  const enable = async () => {
    setBusy(true);
    try {
      const p = await Notification.requestPermission(); setPerm(p);
      if (p !== "granted") throw new Error("Notifications are blocked. Allow them in your browser settings.");
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(cfg.vapid_public_key) });
      await api.post("/api/push/subscribe", { subscription: sub.toJSON() });
      setSubbed(true); toast("Phone notifications are on", "good");
    } catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };
  const disable = async () => {
    setBusy(true);
    try {
      const s = await currentPushSub();
      if (s) { await api.post("/api/push/unsubscribe", { subscription: s.toJSON() }); await s.unsubscribe(); }
      setSubbed(false); toast("Phone notifications are off");
    } catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };
  const test = async () => { try { const r = await api.post("/api/push/test"); await loadNotes(); toast(r.sent ? "Test sent to your phone" : "Test saved in the list below", "good"); } catch (e) { toast(e.message, "bad"); } };
  const runJobs = async () => { setBusy(true); try { const r = await api.post("/api/dev/run-jobs"); await loadNotes(); toast(`Daily check done: ${r.notifications} new alert(s)`, "good"); } catch (e) { toast(e.message, "bad"); } setBusy(false); };
  const setDay = async (d) => { try { await api.patch(`/api/farms/${farm.id}`, { reminder_day: d }); await loadFarms(); toast("Reminder day saved", "good"); } catch (e) { toast(e.message, "bad"); } };

  const canPush = pushSupported() && cfg.push;
  return (
    <div className="stack">
      <section className="card">
        <h3><BellRing size={18} /> Phone notifications</h3>
        {!pushSupported() ? <p className="muted">This browser cannot send phone notifications. On iPhone, add the app to your Home Screen first, then open it from there.</p>
          : !cfg.push ? <p className="muted">Phone push is not set up on the server yet (see README, step 5). Alerts still appear in this list.</p>
          : perm === "denied" ? <p className="muted">Notifications are blocked for this site. Allow them in your browser settings and come back.</p>
          : <p className="muted">Get weather warnings, growth alerts and your weekly checkup reminder even when the app is closed.</p>}
        <div className="row gap wrap">
          {canPush && !subbed && <button className="btn primary" disabled={busy} onClick={enable}>Turn on notifications</button>}
          {canPush && subbed && <button className="btn ghost" disabled={busy} onClick={disable}>Turn off</button>}
          <button className="btn ghost" onClick={test}>Send a test</button>
          {cfg.env !== "production" && <button className="btn ghost" disabled={busy} onClick={runJobs}>Run daily check now</button>}
        </div>
      </section>

      {farm && (
        <section className="card">
          <h3><Camera size={18} /> Weekly checkup reminder</h3>
          <p className="muted">We remind you for <b>{farm.name}</b> on this day at 7 am.</p>
          <div className="days">{DAYS.map((d, i) => <button key={d} className={farm.reminder_day === i ? "on" : ""} onClick={() => setDay(i)}>{d.slice(0, 3)}</button>)}</div>
        </section>
      )}

      <section className="card flush">
        <div className="card-pad"><h3>{t("notifications")}</h3></div>
        {notes.items.length === 0 ? <p className="muted card-pad">Nothing yet. Weather warnings and growth alerts will show up here.</p> : (
          <ul className="notes">
            {notes.items.map((n) => {
              const I = n.level === "urgent" || n.level === "warning" ? AlertTriangle : ICON[n.kind] || Info;
              return (
                <li key={n.id} className={n.level + (n.read ? "" : " unread")}>
                  <span className="n-ico"><I size={18} /></span>
                  <div><b>{n.title}</b><p>{n.body}</p><small>{ago(n.created_at)}</small></div>
                </li>
              );
            })}
          </ul>
        )}
        {notes.items.length > 0 && <p className="muted small card-pad"><CheckCheck size={14} /> Showing your latest {notes.items.length} alerts.</p>}
      </section>
    </div>
  );
}
