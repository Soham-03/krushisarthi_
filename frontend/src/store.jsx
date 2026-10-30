import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { makeT } from "./i18n";

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

export function AppProvider({ cfg, children }) {
  const [farms, setFarms] = useState(null);
  const [farmId, setFarmIdState] = useState(() => Number(localStorage.getItem("cm_farm")) || null);
  const [ov, setOv] = useState(null);
  const [ovState, setOvState] = useState("idle"); // idle | loading | error
  const [ovError, setOvError] = useState("");
  const [lang, setLangState] = useState(() => localStorage.getItem("cm_lang") || "en");
  const [notes, setNotes] = useState({ items: [], unread: 0 });
  const [tab, setTab] = useState("home");
  const [toasts, setToasts] = useState([]);
  const seq = useRef(0);

  const t = useMemo(() => makeT(lang), [lang]);
  const setLang = (l) => { localStorage.setItem("cm_lang", l); setLangState(l); };

  const toast = useCallback((msg, kind = "info") => {
    const id = ++seq.current;
    setToasts((x) => [...x, { id, msg, kind }]);
    setTimeout(() => setToasts((x) => x.filter((y) => y.id !== id)), 4200);
  }, []);

  const loadFarms = useCallback(async () => {
    const list = await api.get("/api/farms");
    setFarms(list);
    setFarmIdState((cur) => {
      const next = list.some((f) => f.id === cur) ? cur : list[0]?.id ?? null;
      if (next) localStorage.setItem("cm_farm", String(next));
      return next;
    });
    return list;
  }, []);

  const loadOverview = useCallback(async (id, refresh = false) => {
    if (!id) { setOv(null); setOvState("idle"); return; }
    setOvState("loading");
    try {
      const data = await api.get(`/api/farms/${id}/overview${refresh ? "?refresh=true" : ""}`);
      setOv(data); setOvState("idle"); setOvError("");
    } catch (e) {
      setOvState("error"); setOvError(e.message);
    }
  }, []);

  const loadNotes = useCallback(async () => {
    try { setNotes(await api.get("/api/notifications")); } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadFarms().catch((e) => toast(e.message, "bad")); loadNotes(); }, []); // eslint-disable-line
  useEffect(() => { if (farmId) loadOverview(farmId); else setOv(null); }, [farmId, loadOverview]);
  useEffect(() => { const i = setInterval(loadNotes, 60000); return () => clearInterval(i); }, [loadNotes]);

  const setFarmId = (id) => { localStorage.setItem("cm_farm", String(id)); setFarmIdState(id); };
  const farm = farms?.find((f) => f.id === farmId) || null;

  const value = {
    cfg, farms, farm, farmId, setFarmId, loadFarms, ov, ovState, ovError, reload: (r) => loadOverview(farmId, r),
    lang, setLang, t, notes, loadNotes, tab, setTab, toast, toasts,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
