import React from "react";
import { createRoot } from "react-dom/client";
import { ClerkProvider, SignedIn, SignedOut, SignIn, useAuth } from "@clerk/clerk-react";
import "leaflet/dist/leaflet.css";
import "./styles.css";
import { setTokenGetter } from "./api";
import App from "./App";
import Landing from "./Landing";

function Bridge({ cfg }) {
  const { getToken } = useAuth();
  setTokenGetter(() => getToken());
  return <App cfg={cfg} />;
}

function Boot() {
  const [cfg, setCfg] = React.useState(null);
  const [err, setErr] = React.useState("");
  React.useEffect(() => {
    fetch("/api/config").then((r) => r.json()).then(setCfg).catch(() => setErr("Cannot reach the server. Check that the backend is running."));
  }, []);
  if (err) return <div className="boot"><p>{err}</p></div>;
  if (!cfg) return <div className="boot"><div className="spinner" /></div>;
  if (cfg.auth === "clerk") {
    return (
      <ClerkProvider publishableKey={cfg.clerk_publishable_key} afterSignOutUrl="/">
        <SignedOut><Landing><SignIn routing="hash" appearance={{ variables: { colorPrimary: "#1E6B4A", borderRadius: "12px" } }} /></Landing></SignedOut>
        <SignedIn><Bridge cfg={cfg} /></SignedIn>
      </ClerkProvider>
    );
  }
  return <App cfg={cfg} />;
}

createRoot(document.getElementById("root")).render(<Boot />);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
