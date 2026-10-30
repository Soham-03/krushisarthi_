import { useEffect, useState } from "react";
import L from "leaflet";
import { MapContainer, Marker, Polygon, Polyline, useMap, useMapEvents } from "react-leaflet";
import { LocateFixed, Search, Trash2, Undo2 } from "lucide-react";
import { BaseTiles, LayerToggle } from "./FarmMap";
import { areaHa, acres } from "../util";

const dot = L.divIcon({ className: "pin-wrap", html: '<div class="vtx"></div>', iconSize: [22, 22], iconAnchor: [11, 11] });

function Clicks({ onAdd }) {
  useMapEvents({ click: (e) => onAdd([e.latlng.lng, e.latlng.lat]) });
  return null;
}
function Mover({ target }) {
  const map = useMap();
  useEffect(() => { if (target) map.flyTo(target.center, target.zoom, { duration: 0.8 }); }, [map, target]);
  return null;
}

export default function DrawMap({ points, setPoints, toast }) {
  const [sat, setSat] = useState(true);
  const [q, setQ] = useState("");
  const [target, setTarget] = useState(null);
  const [searching, setSearching] = useState(false);
  const ring = points.map(([x, y]) => [y, x]);
  const ha = areaHa(points);

  const search = async (e) => {
    e.preventDefault();
    if (!q.trim()) return;
    setSearching(true);
    try {
      const r = await fetch("https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=in&q=" + encodeURIComponent(q));
      const j = await r.json();
      if (j[0]) setTarget({ center: [+j[0].lat, +j[0].lon], zoom: 16, k: Math.random() });
      else toast("Place not found. Try the village or town name.", "warn");
    } catch { toast("Search needs internet.", "bad"); }
    setSearching(false);
  };
  const locate = () => {
    if (!navigator.geolocation) return toast("Location is not available on this device.", "warn");
    navigator.geolocation.getCurrentPosition(
      (p) => setTarget({ center: [p.coords.latitude, p.coords.longitude], zoom: 18, k: Math.random() }),
      () => toast("Allow location access to jump to your position.", "warn"), { enableHighAccuracy: true, timeout: 10000 });
  };

  return (
    <div>
      <form className="search" onSubmit={search}>
        <Search size={18} />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search your village or town" aria-label="Search place" />
        <button className="btn small" disabled={searching}>Go</button>
        <button type="button" className="icon-btn" onClick={locate} aria-label="Use my location"><LocateFixed size={20} /></button>
      </form>
      <div className="map-wrap draw" style={{ height: 340 }}>
        <MapContainer center={[20.5, 78.9]} zoom={5} scrollWheelZoom style={{ height: "100%", width: "100%" }}>
          <BaseTiles sat={sat} />
          <Clicks onAdd={(p) => setPoints([...points, p])} />
          {target && <Mover key={target.k} target={target} />}
          {ring.length > 2 && <Polygon positions={ring} pathOptions={{ color: "#fff", weight: 3, fillColor: "#7CC96B", fillOpacity: 0.3 }} />}
          {ring.length === 2 && <Polyline positions={ring} pathOptions={{ color: "#fff", weight: 3 }} />}
          {ring.map((p, i) => (
            <Marker key={i} position={p} icon={dot} draggable eventHandlers={{
              dragend: (e) => { const ll = e.target.getLatLng(); setPoints(points.map((x, k) => (k === i ? [ll.lng, ll.lat] : x))); },
            }} />
          ))}
        </MapContainer>
        <LayerToggle sat={sat} setSat={setSat} />
      </div>
      <div className="draw-bar">
        <div>
          {points.length < 3
            ? <span className="muted">Tap the map at each corner of your farm ({points.length}/3 corners at least).</span>
            : ha > 2000
            ? <span className="bad-text">This area is too large ({Math.round(ha).toLocaleString("en-IN")} ha). Zoom in and tap only the corners of your farm.</span>
            : <span><b>{ha.toFixed(2)} ha</b> <span className="muted">({acres(ha).toFixed(1)} acres) · drag a corner to adjust</span></span>}
        </div>
        <div className="row gap">
          <button className="btn ghost small" disabled={!points.length} onClick={() => setPoints(points.slice(0, -1))}><Undo2 size={16} /> Undo</button>
          <button className="btn ghost small" disabled={!points.length} onClick={() => setPoints([])}><Trash2 size={16} /> Clear</button>
        </div>
      </div>
    </div>
  );
}
