import { usd } from "../../format";

interface Props {
  toSignal: number;
  kind: string;
  ohlc: { open: number; high: number; low: number; close: number };
  algoShares: number;
  price: number;
  onSkip: () => void;
}

export default function SignalBanner({ toSignal, kind, ohlc, algoShares, price, onSkip }: Props) {
  const label = toSignal > 0 ? "LONG" : toSignal < 0 ? "SHORT" : "FLAT";
  const cls = toSignal > 0 ? "long" : toSignal < 0 ? "short" : "flat";
  const notional = Math.abs(algoShares) * price;

  return (
    <div className="signal-banner signal-flash">
      <div className="signal-head">
        <span className={`signal-badge ${cls}`}>{label}</span>
        <span className="signal-kind">{kind.replace(/_/g, " ")}</span>
        <button className="btn-inline skip" title="Skip (K)" onClick={onSkip}>
          Skip
        </button>
      </div>
      <div className="signal-ohlc">
        O {ohlc.open.toFixed(2)} · H {ohlc.high.toFixed(2)} · L {ohlc.low.toFixed(2)} · C {ohlc.close.toFixed(2)}
      </div>
      <div className="hint">
        Algo would take {algoShares.toFixed(1)} sh (~{usd(notional)})
      </div>
    </div>
  );
}
