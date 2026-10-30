import { AlertTriangle, CheckCircle2, CircleHelp, ShieldAlert } from "lucide-react";

export default function ResultCard({ result }) {
  if (!result) return null;
  if (result.status === "error") return <div className="result bad"><ShieldAlert size={20} /><div><b>Could not check this photo</b><p>{result.message}</p></div></div>;
  const tone = result.status === "healthy" ? "good" : result.status === "issue" ? (result.severity === "high" ? "bad" : "warn") : "idle";
  const Icon = result.status === "healthy" ? CheckCircle2 : result.status === "issue" ? AlertTriangle : CircleHelp;
  const title = result.status === "healthy" ? "Looks healthy" : result.status === "issue" ? result.issue : "Photo not clear enough";
  return (
    <div className={"result " + tone}>
      <div className="result-head">
        <Icon size={22} />
        <div>
          <b>{title}</b>
          {result.status !== "unclear" && <small>{Math.round(result.confidence * 100)}% confident{result.type && result.type !== "none" ? ` · ${result.type}` : ""}</small>}
        </div>
      </div>
      {result.status === "unclear" && <p>{result.retake_reason || "Take a close, bright photo of one leaf, top side and underside."}</p>}
      {result.symptoms?.length > 0 && <><h4>What we see</h4><ul>{result.symptoms.map((s, i) => <li key={i}>{s}</li>)}</ul></>}
      {result.advice?.length > 0 && <><h4>What to do</h4><ul className="steps">{result.advice.map((s, i) => <li key={i}>{s}</li>)}</ul></>}
      {result.demo && <p className="demo-note">Demo result: this is simulated. Add the AI key for real photo analysis.</p>}
    </div>
  );
}
