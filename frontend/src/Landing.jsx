import FarmMosaic from "./components/FarmMosaic";

const DEMO = { type: "Polygon", coordinates: [[[0, 0], [10, 1], [12, 8], [6, 11], [-1, 8], [0, 0]]] };

export default function Landing({ children }) {
  return (
    <div className="landing">
      <div className="landing-copy">
        <div className="brand big"><span className="logo-dot" /> KrushiSarthi</div>
        <h1>See trouble in your field before it spreads</h1>
        <p>Satellite growth tracking, weekly plant photo checks and weather warnings, with an assistant that speaks your language.</p>
        <div className="landing-mosaic"><FarmMosaic geometry={DEMO} health={78} seed={11} size={220} /></div>
      </div>
      <div className="landing-form">{children}</div>
    </div>
  );
}
