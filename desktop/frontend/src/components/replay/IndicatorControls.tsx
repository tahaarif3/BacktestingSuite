import { useState } from "react";
import type { Indicator, IndicatorType } from "../../indicators";
import { INDICATOR_COLORS } from "../../indicators";

interface Props {
  indicators: Indicator[];
  onChange: (list: Indicator[]) => void;
  hasReference: boolean;
  showRelStrength: boolean;
  onToggleRelStrength: (v: boolean) => void;
}

let seq = 0;

export default function IndicatorControls({
  indicators,
  onChange,
  hasReference,
  showRelStrength,
  onToggleRelStrength,
}: Props) {
  const [type, setType] = useState<IndicatorType>("sma");
  const [period, setPeriod] = useState(20);

  const add = () => {
    if (period < 1) return;
    const ind: Indicator = {
      id: `ind_${seq++}`,
      type,
      period: Math.round(period),
      color: INDICATOR_COLORS[indicators.length % INDICATOR_COLORS.length],
    };
    onChange([...indicators, ind]);
  };

  const remove = (id: string) => onChange(indicators.filter((i) => i.id !== id));

  return (
    <div className="indicator-controls">
      <div className="indicator-add">
        <select value={type} onChange={(e) => setType(e.target.value as IndicatorType)}>
          <option value="sma">SMA</option>
          <option value="ema">EMA</option>
          <option value="rsi">RSI</option>
        </select>
        <input
          type="number"
          min={1}
          max={400}
          value={period}
          onChange={(e) => setPeriod(parseInt(e.target.value || "0", 10))}
          title="Period (bars)"
        />
        <button className="btn-inline" onClick={add}>
          + Add
        </button>
        {hasReference && (
          <label className="indicator-rs" title="Relative strength vs SPY">
            <input type="checkbox" checked={showRelStrength} onChange={(e) => onToggleRelStrength(e.target.checked)} />
            SPY rel-strength
          </label>
        )}
      </div>

      {indicators.length > 0 && (
        <div className="indicator-chips">
          {indicators.map((i) => (
            <span key={i.id} className="indicator-chip" style={{ borderColor: i.color }}>
              <span className="indicator-swatch" style={{ background: i.color }} />
              {i.type.toUpperCase()} {i.period}
              <button className="indicator-chip-x" onClick={() => remove(i.id)} title="Remove">
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
