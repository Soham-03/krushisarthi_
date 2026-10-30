import { AlertTriangle, Cloud, CloudDrizzle, CloudFog, CloudLightning, CloudRain, CloudSun, Droplets, Sun, Thermometer, Wind } from "lucide-react";
import { DAYS_SHORT } from "../util";

const ICONS = { sun: Sun, "cloud-sun": CloudSun, cloud: Cloud, fog: CloudFog, drizzle: CloudDrizzle, rain: CloudRain, storm: CloudLightning };

function dayIcon(d) {
  if (d.rain >= 20) return CloudLightning;
  if (d.rain >= 5) return CloudRain;
  if (d.rain >= 1) return CloudDrizzle;
  if (d.rh != null && d.rh > 75) return Cloud;
  return d.rh != null && d.rh > 55 ? CloudSun : Sun;
}

export function AlertList({ alerts, limit }) {
  const list = limit ? alerts.slice(0, limit) : alerts;
  if (!list.length) return null;
  return (
    <div className="alerts">
      {list.map((a) => (
        <details key={a.id} className={"alert " + a.level} open={a.level !== "watch"}>
          <summary>
            <AlertTriangle size={18} />
            <span><b>{a.title}</b><small>{a.level} · {a.when}</small></span>
          </summary>
          <p>{a.message}</p>
          <ul>{a.actions.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </details>
      ))}
    </div>
  );
}

export default function WeatherCard({ weather, today }) {
  const now = weather.now || {};
  const NowIcon = ICONS[now.icon] || CloudSun;
  const days = weather.days.filter((d) => d.date >= today).slice(0, 7);
  return (
    <div>
      <div className="wx-now">
        <NowIcon size={42} strokeWidth={1.5} />
        <div>
          <div className="wx-temp">{now.temp != null ? Math.round(now.temp) : "–"}°C</div>
          <div className="muted">{now.label || "Today"}</div>
        </div>
        <div className="wx-facts">
          <span><Droplets size={14} /> {now.rh != null ? Math.round(now.rh) : "–"}%</span>
          <span><Wind size={14} /> {now.wind != null ? Math.round(now.wind) : "–"} km/h</span>
        </div>
      </div>
      <div className="wx-strip">
        {days.map((d, i) => {
          const I = dayIcon(d);
          return (
            <div key={d.date} className="wx-day">
              <small>{i === 0 ? "Today" : DAYS_SHORT[(new Date(d.date + "T00:00:00").getDay() + 6) % 7]}</small>
              <I size={20} strokeWidth={1.6} />
              <b>{Math.round(d.tmax)}°</b>
              <small className="muted">{Math.round(d.tmin)}°</small>
              <span className="rainbar"><i style={{ height: Math.min(100, d.rain * 2.2) + "%" }} /></span>
              <small className={d.rain >= 1 ? "rain" : "muted"}>{d.rain >= 1 ? Math.round(d.rain) + "mm" : "dry"}</small>
            </div>
          );
        })}
      </div>
      {weather.warning && <p className="muted small"><Thermometer size={12} /> {weather.warning}</p>}
    </div>
  );
}
