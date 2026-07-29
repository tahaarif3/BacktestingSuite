import type { PayoffPoint } from "../../types";

interface Props {
  payoff: PayoffPoint[];
  breakevens?: number[];
  spot?: number;
  strikes?: number[];
  height?: number;
  width?: number;
}

/** Inline-SVG expiry payoff diagram (green profit / red loss), deliberately not
 *  a Plotly instance so it costs nothing next to the candle chart. */
export default function PayoffDiagram({
  payoff,
  breakevens = [],
  spot,
  strikes = [],
  height = 120,
  width = 280,
}: Props) {
  if (payoff.length < 2) return <svg width={width} height={height} />;
  const xs = payoff.map((p) => p.s);
  const ys = payoff.map((p) => p.pnl);
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  let yMin = Math.min(...ys, 0);
  let yMax = Math.max(...ys, 0);
  if (yMin === yMax) {
    yMin -= 1;
    yMax += 1;
  }
  const pad = (yMax - yMin) * 0.08;
  yMin -= pad;
  yMax += pad;

  const sx = (s: number) => ((s - xMin) / (xMax - xMin)) * width;
  const sy = (v: number) => height - ((v - yMin) / (yMax - yMin)) * height;
  const zeroY = sy(0);

  // Split the payoff line into green (>=0) and red (<0) segments.
  const pts = payoff.map((p) => ({ x: sx(p.s), y: sy(p.pnl), pnl: p.pnl }));
  const line = pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: "block" }}
    >
      {/* zero P&L baseline */}
      <line x1={0} x2={width} y1={zeroY} y2={zeroY} stroke="#475569" strokeDasharray="3 3" strokeWidth={1} />
      {/* strike guides */}
      {strikes.map((k, i) =>
        k >= xMin && k <= xMax ? (
          <line key={`k${i}`} x1={sx(k)} x2={sx(k)} y1={0} y2={height} stroke="#334155" strokeWidth={1} />
        ) : null
      )}
      {/* breakevens */}
      {breakevens.map((b, i) =>
        b >= xMin && b <= xMax ? (
          <line key={`be${i}`} x1={sx(b)} x2={sx(b)} y1={0} y2={height} stroke="#a78bfa" strokeDasharray="2 2" strokeWidth={1} />
        ) : null
      )}
      {/* spot marker */}
      {spot !== undefined && spot >= xMin && spot <= xMax && (
        <line x1={sx(spot)} x2={sx(spot)} y1={0} y2={height} stroke="#38bdf8" strokeWidth={1.5} />
      )}
      {/* payoff line, clipped above/below zero for colour */}
      <clipPath id="above"><rect x={0} y={0} width={width} height={zeroY} /></clipPath>
      <clipPath id="below"><rect x={0} y={zeroY} width={width} height={height - zeroY} /></clipPath>
      <polyline fill="none" stroke="#34d399" strokeWidth={2} points={line} clipPath="url(#above)" vectorEffect="non-scaling-stroke" />
      <polyline fill="none" stroke="#f87171" strokeWidth={2} points={line} clipPath="url(#below)" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
