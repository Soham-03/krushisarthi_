import { useEffect, useMemo, useState } from "react";
import L from "leaflet";
import { CircleMarker, MapContainer, Marker, Polygon, TileLayer, useMap } from "react-leaflet";
import { Layers } from "lucide-react";

export const SAT = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
export const OSM = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
export const ATTR_SAT = "Imagery © Esri, Maxar, Earthstar Geographics";
export const ATTR_OSM = "© OpenStreetMap contributors";

function Fit({ ring }) {
  const map = useMap();
  useEffect(() => {
    if (ring.length) map.fitBounds(L.latLngBounds(ring), { padding: [36, 36], maxZoom: 18, animate: false });
  }, [map, ring]);
  return null;
}

export function BaseTiles({ sat }) {
  return sat
    ? <TileLayer key="sat" url={SAT} attribution={ATTR_SAT} maxZoom={19} />
    : <TileLayer key="osm" url={OSM} attribution={ATTR_OSM} maxZoom={19} />;
}

export function LayerToggle({ sat, setSat }) {
  return <button className="map-toggle" onClick={() => setSat(!sat)} aria-label="Switch map style"><Layers size={16} /> {sat ? "Map" : "Satellite"}</button>;
}

const pinIcon = (n, cls) => L.divIcon({ className: "pin-wrap", html: `<div class="pin ${cls}">${n}</div>`, iconSize: [30, 30], iconAnchor: [15, 15] });

export default function FarmMap({ geometry, spots = [], statusOf, selected, onSelect, me, height = 280 }) {
  const [sat, setSat] = useState(true);
  const ring = useMemo(() => (geometry?.coordinates?.[0] || []).map(([lng, lat]) => [lat, lng]), [geometry]);
  const center = ring[0] || [20.5, 78.9];
  return (
    <div className="map-wrap" style={{ height }}>
      <MapContainer center={center} zoom={16} scrollWheelZoom={false} style={{ height: "100%", width: "100%" }} attributionControl>
        <BaseTiles sat={sat} />
        <Fit ring={ring} />
        {ring.length > 2 && <Polygon positions={ring} pathOptions={{ color: "#ffffff", weight: 2.5, fillColor: "#7CC96B", fillOpacity: 0.12 }} />}
        {spots.map((s) => {
          const st = statusOf ? statusOf(s) : "todo";
          const cls = st + (selected === s.i ? " sel" : "") + (s.priority && st === "todo" ? " pri" : "");
          return <Marker key={s.i + st + (selected === s.i)} position={[s.lat, s.lng]} icon={pinIcon(s.i, cls)} eventHandlers={{ click: () => onSelect && onSelect(s.i) }} />;
        })}
        {me && <CircleMarker center={[me.lat, me.lng]} radius={8} pathOptions={{ color: "#fff", weight: 3, fillColor: "#2D79B5", fillOpacity: 1 }} />}
      </MapContainer>
      <LayerToggle sat={sat} setSat={setSat} />
    </div>
  );
}
