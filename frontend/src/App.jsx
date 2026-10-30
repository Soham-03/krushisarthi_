import { useState } from "react";
import { UserButton } from "@clerk/clerk-react";
import { Bell, Camera, ChevronDown, Home as HomeIcon, MapPin, MessageCircle, Sprout, Check } from "lucide-react";
import { AppProvider, useApp } from "./store";
import { LANGS } from "./i18n";
import Home from "./pages/Home";
import Checkup from "./pages/Checkup";
import Assistant from "./pages/Assistant";
import Alerts from "./pages/Alerts";
import Farms from "./pages/Farms";
import Sheet from "./components/Sheet";

const NAV = [
  ["home", "home", HomeIcon],
  ["checkup", "checkup", Camera],
  ["assistant", "assistant", MessageCircle],
  ["alerts", "alerts", Bell],
  ["farms", "farms", MapPin],
];

function Shell() {
  const { cfg, farms, farm, setFarmId, tab, setTab, t, notes, lang, setLang, toasts } = useApp();
  const [pick, setPick] = useState(false);
  const noFarm = farms && farms.length === 0;
  const page = tab === "home" ? <Home /> : tab === "checkup" ? <Checkup /> : tab === "assistant" ? <Assistant /> : tab === "alerts" ? <Alerts /> : <Farms />;

  return (
    <div className={"app" + (tab === "assistant" ? " chat-mode" : "")}>
      <header className="topbar">
        <div className="brand"><span className="logo-dot" /> <span className="brand-name">KrushiSarthi</span></div>
        <button className="farm-pick" onClick={() => setPick(true)} disabled={!farms?.length} aria-label="Switch farm">
          <Sprout size={16} />
          <span>{farm ? farm.name : "No farm yet"}</span>
          <ChevronDown size={16} />
        </button>
        <div className="top-actions">
          <div className="lang-switch" role="group" aria-label={t("language")}>
            {LANGS.map((l) => (
              <button key={l.code} className={lang === l.code ? "on" : ""} onClick={() => setLang(l.code)} aria-label={l.label}>{l.short}</button>
            ))}
          </div>
          <button className="icon-btn bell" onClick={() => setTab("alerts")} aria-label="Notifications">
            <Bell size={20} />
            {notes.unread > 0 && <span className="badge">{notes.unread > 9 ? "9+" : notes.unread}</span>}
          </button>
          {cfg.auth === "clerk" && <UserButton afterSignOutUrl="/" />}
        </div>
      </header>

      <nav className="nav" aria-label="Main">
        {NAV.map(([id, key, Icon]) => (
          <button key={id} className={tab === id ? "on" : ""} onClick={() => setTab(id)} aria-current={tab === id ? "page" : undefined}>
            <span className="nav-ico"><Icon size={22} />{id === "alerts" && notes.unread > 0 && <i className="dot" />}</span>
            <span className="nav-label">{t(key)}</span>
          </button>
        ))}
      </nav>

      <main className="content">
        {cfg.satellite === "demo" && <div className="demo-strip">Demo data mode: satellite and photo results are simulated. See the README to connect real services.</div>}
        {noFarm && tab !== "farms" ? (
          <div className="empty-hero">
            <Sprout size={40} />
            <h2>{t("first_farm")}</h2>
            <p>Draw your farm on the map, pick the crop and sowing date. We start watching it right away.</p>
            <button className="btn primary" onClick={() => setTab("farms")}>{t("add_farm")}</button>
          </div>
        ) : page}
      </main>

      <Sheet open={pick} onClose={() => setPick(false)} title="Your farms">
        <div className="list">
          {(farms || []).map((f) => (
            <button key={f.id} className={"row-btn " + (farm?.id === f.id ? "on" : "")} onClick={() => { setFarmId(f.id); setPick(false); setTab("home"); }}>
              <span><b>{f.name}</b><small>{f.area_ha.toFixed(1)} ha</small></span>
              {farm?.id === f.id && <Check size={18} />}
            </button>
          ))}
          <button className="row-btn add" onClick={() => { setPick(false); setTab("farms"); }}>+ Add another farm</button>
        </div>
      </Sheet>

      <div className="toasts" aria-live="polite">
        {toasts.map((x) => <div key={x.id} className={"toast " + x.kind}>{x.msg}</div>)}
      </div>
    </div>
  );
}

export default function App({ cfg }) {
  return <AppProvider cfg={cfg}><Shell /></AppProvider>;
}
