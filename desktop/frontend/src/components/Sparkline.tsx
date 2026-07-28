interface SeriesDef {
  values: number[];
  color: string;
  label: string;
}

interface Props {
  series: SeriesDef[];
  height?: number;
  baseline?: number;
  width?: number;
}

/** Lightweight inline-SVG sparkline — deliberately NOT a Plotly instance, so it
 *  costs nothing to redraw next to the candlestick chart. */
export default function Sparkline({ series, height = 56, baseline, width = 240 }: Props) {
  const all = series.flatMap((s) => s.values);
  if (all.length < 2) return <svg width={width} height={height} />;
  let min = Math.min(...all);
  let max = Math.max(...all);
  if (baseline !== undefined) {
    min = Math.min(min, baseline);
    max = Math.max(max, baseline);
  }
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const scaleY = (v: number) => height - ((v - min) / (max - min)) * height;

  const path = (values: number[]) => {
    const n = values.length;
    return values
      .map((v, i) => `${(i / (n - 1)) * width},${scaleY(v).toFixed(1)}`)
      .join(" ");
  };

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ display: "block" }}>
      {baseline !== undefined && (
        <line x1={0} x2={width} y1={scaleY(baseline)} y2={scaleY(baseline)} stroke="#475569" strokeDasharray="3 3" strokeWidth={1} />
      )}
      {series.map((s) => (
        <polyline key={s.label} fill="none" stroke={s.color} strokeWidth={1.5} points={path(s.values)} vectorEffect="non-scaling-stroke" />
      ))}
    </svg>
  );
}
