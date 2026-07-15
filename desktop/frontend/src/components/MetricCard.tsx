interface Props {
  label: string;
  value: string;
  tone?: "pos" | "neg" | "neutral";
}

export default function MetricCard({ label, value, tone = "neutral" }: Props) {
  return (
    <div className={`metric-card ${tone}`}>
      <div className="label">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}
