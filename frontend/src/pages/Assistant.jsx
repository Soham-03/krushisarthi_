import { useEffect, useRef, useState } from "react";
import { BookOpen, CheckCircle2, ExternalLink, Info, Loader2, Mic, RefreshCw, Send, Trash2, TriangleAlert, Volume2, XCircle } from "lucide-react";
import { api } from "../api";
import { useApp } from "../store";
import { LANGS } from "../i18n";
import { fmtDate } from "../util";

const SUGGEST = ["Why is my crop weak?", "Should I irrigate this week?", "Is there a disease risk now?", "What should I do this week?"];
const SR = typeof window !== "undefined" ? window.SpeechRecognition || window.webkitSpeechRecognition : null;

// Turns "[S1]" markers into small numbered buttons that open the matching source.
function Answer({ text, sources, onCite }) {
  const known = new Set((sources || []).map((s) => s.id));
  return (
    <p>
      {text.split(/(\[S\d+\])/g).map((part, i) => {
        const m = part.match(/^\[(S\d+)\]$/);
        if (m && known.has(m[1])) return <sup key={i}><button className="cite" onClick={() => onCite(m[1])} aria-label={`Source ${m[1].slice(1)}`}>{m[1].slice(1)}</button></sup>;
        return part;
      })}
    </p>
  );
}

function Evidence({ m, open, setOpen }) {
  const cited = (m.sources || []).filter((s) => s.cited);
  const failed = (m.tools || []).filter((t) => !t.ok);
  const noSource = (m.notes || []).includes("no_source_found");
  return (
    <div className="evidence-box">
      {m.mode === "ai" && (
        <div className={"ground " + (m.grounded ? "ok" : "gen")}>
          {m.grounded ? <BookOpen size={14} /> : <Info size={14} />}
          {m.grounded ? `Based on ${cited.length} source${cited.length > 1 ? "s" : ""}` : noSource ? "No source found: general knowledge" : "General knowledge, not from a source"}
        </div>
      )}
      {m.tools?.length > 0 && (
        <div className="trace" aria-label="What was checked">
          {m.tools.map((t, i) => (
            <span key={i} className={t.ok ? "ok" : "bad"} title={t.summary}>{t.ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />} {t.label}</span>
          ))}
        </div>
      )}
      {failed.length > 0 && <p className="small bad-text">Could not read: {failed.map((t) => t.label).join(", ")}. The answer does not use that data.</p>}
      {m.sources?.length > 0 && (
        <div className="srcs">
          {m.sources.map((s) => (
            <details key={s.id} open={open === s.id} onToggle={(e) => e.target.open ? setOpen(s.id) : open === s.id && setOpen(null)} className={s.cited ? "" : "uncited"}>
              <summary><b>{s.id.slice(1)}</b><span>{s.title}</span></summary>
              <div className="src-body">
                <small>{[s.publisher, s.published && fmtDate(s.published, { year: "numeric", month: "short" }), s.page && `page ${s.page}`].filter(Boolean).join(" · ")}</small>
                <em>"{s.excerpt}{s.excerpt?.length >= 300 ? "…" : ""}"</em>
                {s.url && <a href={s.url} target="_blank" rel="noreferrer noopener">Open source <ExternalLink size={12} /></a>}
                {!s.cited && <small className="muted">Looked at, but not used in this answer.</small>}
              </div>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}

export default function Assistant() {
  const { farm, lang, t, cfg, toast } = useApp();
  const key = "cm_chat2_" + farm?.id;
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [openSrc, setOpenSrc] = useState(null);
  const end = useRef(null);
  const speech = LANGS.find((l) => l.code === lang)?.speech || "en-IN";

  useEffect(() => { try { setMsgs(JSON.parse(localStorage.getItem(key)) || []); } catch { setMsgs([]); } }, [key]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs, busy]);
  const save = (m) => { setMsgs(m); try { localStorage.setItem(key, JSON.stringify(m.filter((x) => !x.error).slice(-24))); } catch { /* storage full */ } };

  const send = async (q, base) => {
    const message = (q ?? text).trim();
    if (!message || busy) return;
    const prior = base ?? msgs.filter((m) => !m.error);
    const history = prior.map((m) => ({ role: m.role, content: m.content }));
    const next = [...prior, { role: "user", content: message }];
    save(next); setText(""); setBusy(true);
    try {
      const r = await api.post("/api/chat", { farm_id: farm.id, message, history, language: lang });
      save([...next, { role: "assistant", content: r.reply, mode: r.mode, sources: r.sources, tools: r.tools, grounded: r.grounded, notes: r.notes }]);
    } catch (e) {
      setMsgs([...next, { role: "assistant", error: true, content: e.message || "Something went wrong.", retry: { message, base: prior } }]);
    }
    setBusy(false);
  };

  const listen = () => {
    if (!SR) return toast("Voice input is not supported in this browser. Try Chrome on Android.", "warn");
    const r = new SR();
    r.lang = speech; r.interimResults = false;
    r.onresult = (e) => setText(e.results[0][0].transcript);
    r.onend = () => setListening(false);
    r.onerror = () => { setListening(false); toast("Could not hear you. Check microphone permission.", "warn"); };
    setListening(true); r.start();
  };
  const speak = (s) => {
    if (!("speechSynthesis" in window)) return toast("Reading aloud is not supported here.", "warn");
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(s.replace(/\[S\d+\]/g, "")); u.lang = speech; window.speechSynthesis.speak(u);
  };
  const clear = () => { if (window.confirm("Clear this conversation?")) { localStorage.removeItem(key); setMsgs([]); } };
  const kb = cfg.kb;

  return (
    <div className="chat">
      <div className="chat-scroll">
        {msgs.length === 0 && (
          <div className="chat-hello">
            <h2>Ask about {farm?.name}</h2>
            <p className="muted">Ask about any crop, pest, disease, soil or weather question. I also look at your farm's own satellite data, weather, soil test and photo checkups. Ask in English, हिन्दी or मराठी.</p>
            {!cfg.assistant && <p className="note">Basic helper mode. Set up an AI provider in the backend settings for full answers in your language.</p>}
            {cfg.assistant && kb && (kb.documents > 0
              ? <p className="small muted"><BookOpen size={13} /> {kb.documents} reference document{kb.documents > 1 ? "s" : ""} loaded. Answers that use them show their sources.</p>
              : <p className="note"><Info size={16} /> No reference documents are loaded yet, so general questions are answered from the AI's general knowledge and say so. See the README to add trusted documents.</p>)}
            <div className="chips">{SUGGEST.map((s) => <button key={s} className="chip-btn" onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        )}
        {msgs.map((m, i) => m.error ? (
          <div key={i} className="bubble assistant error" role="alert">
            <p><TriangleAlert size={15} /> {m.content}</p>
            {m.retry && <button className="btn small ghost" disabled={busy} onClick={() => send(m.retry.message, m.retry.base)}><RefreshCw size={14} /> Try again</button>}
          </div>
        ) : (
          <div key={i} className={"bubble " + m.role}>
            {m.role === "assistant" ? <Answer text={m.content} sources={m.sources} onCite={setOpenSrc} /> : <p>{m.content}</p>}
            {m.role === "assistant" && <button className="bubble-act" onClick={() => speak(m.content)} aria-label="Read aloud"><Volume2 size={15} /></button>}
            {m.role === "assistant" && m.mode && <Evidence m={m} open={openSrc} setOpen={setOpenSrc} />}
          </div>
        ))}
        {busy && <div className="bubble assistant typing" aria-live="polite"><i /><i /><i /><span className="typing-note">Checking sources and your farm data…</span></div>}
        <div ref={end} />
      </div>
      {msgs.length > 0 && (
        <div className="chips row-scroll">
          <button className="chip-btn" onClick={clear}><Trash2 size={13} /> Clear</button>
          {SUGGEST.map((s) => <button key={s} className="chip-btn" onClick={() => send(s)}>{s}</button>)}
        </div>
      )}
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <button type="button" className={"icon-btn mic " + (listening ? "on" : "")} onClick={listen} aria-label="Speak your question"><Mic size={20} /></button>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={t("type_message")} aria-label="Your question" maxLength={1500} />
        <button className="send" disabled={busy || !text.trim()} aria-label="Send">{busy ? <Loader2 className="spin" size={18} /> : <Send size={18} />}</button>
      </form>
    </div>
  );
}
