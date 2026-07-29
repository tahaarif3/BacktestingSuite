import type { OptionStructureConfig, OptionStructureMeta, StrikeMode, VolModelConfig } from "../../types";

export const DEFAULT_OPTION_STRUCTURE: OptionStructureConfig = {
  structure_type: "bear_call_spread",
  selection: "delta",
  short_delta: 0.3,
  pct_otm: 0.05,
  width: 5,
  strikes: null,
  dte_bars: 30,
  contracts: 1,
  grid_spacing: 5,
};

export const DEFAULT_VOL: VolModelConfig = {
  risk_free_rate: 0.04,
  iv_window: 20,
  iv_multiplier: 1.0,
  iv_override: null,
  iv_floor: 0.05,
  iv_cap: 3.0,
  margin_policy: "defined_risk",
};

interface Props {
  structures: OptionStructureMeta[];
  value: OptionStructureConfig;
  onChange: (v: OptionStructureConfig) => void;
  vol: VolModelConfig;
  onVolChange: (v: VolModelConfig) => void;
}

export default function OptionsConfig({ structures, value, onChange, vol, onVolChange }: Props) {
  const meta = structures.find((s) => s.id === value.structure_type);
  const set = (patch: Partial<OptionStructureConfig>) => onChange({ ...value, ...patch });
  const setVol = (patch: Partial<VolModelConfig>) => onVolChange({ ...vol, ...patch });

  return (
    <>
      <div className="field">
        <label>Structure</label>
        <select value={value.structure_type} onChange={(e) => set({ structure_type: e.target.value })}>
          {structures.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name} · {s.direction} · {s.net}
            </option>
          ))}
        </select>
      </div>
      {meta && (
        <p className="hint">
          {meta.direction === "bullish" ? "Bullish" : meta.direction === "bearish" ? "Bearish" : "Neutral"} ·{" "}
          {meta.defined_risk ? "defined risk" : "undefined risk (needs Reg-T)"} · {meta.legs}-leg
        </p>
      )}

      <div className="row">
        <div className="field">
          <label>Strike by</label>
          <select value={value.selection} onChange={(e) => set({ selection: e.target.value as StrikeMode })}>
            <option value="delta">Delta</option>
            <option value="pct_otm">% OTM</option>
            <option value="absolute">Absolute</option>
          </select>
        </div>
        {value.selection === "delta" && (
          <div className="field">
            <label>Short delta</label>
            <input type="number" step="0.05" min="0.05" max="0.9" value={value.short_delta}
              onChange={(e) => set({ short_delta: parseFloat(e.target.value || "0.3") })} />
          </div>
        )}
        {value.selection === "pct_otm" && (
          <div className="field">
            <label>% OTM</label>
            <input type="number" step="0.01" value={value.pct_otm}
              onChange={(e) => set({ pct_otm: parseFloat(e.target.value || "0.05") })} />
          </div>
        )}
        {value.selection === "absolute" && (
          <div className="field">
            <label>Strike ($)</label>
            <input type="number" step="1" value={value.strikes?.[0] ?? 0}
              onChange={(e) => set({ strikes: [parseFloat(e.target.value || "0")] })} />
          </div>
        )}
      </div>

      <div className="row">
        {meta?.needs_width && (
          <div className="field">
            <label>Width ($)</label>
            <input type="number" step="1" min="1" value={value.width}
              onChange={(e) => set({ width: parseFloat(e.target.value || "5") })} />
          </div>
        )}
        <div className="field">
          <label>DTE (bars)</label>
          <input type="number" step="1" min="1" value={value.dte_bars}
            onChange={(e) => set({ dte_bars: parseInt(e.target.value || "30", 10) })} />
        </div>
        <div className="field">
          <label>Contracts</label>
          <input type="number" step="1" min="1" value={value.contracts}
            onChange={(e) => set({ contracts: parseInt(e.target.value || "1", 10) })} />
        </div>
      </div>

      <div className="row">
        <div className="field">
          <label>Strike grid ($)</label>
          <input type="number" step="0.5" min="0.5" value={value.grid_spacing}
            onChange={(e) => set({ grid_spacing: parseFloat(e.target.value || "5") })} />
        </div>
        <div className="field">
          <label>IV multiplier</label>
          <input type="number" step="0.05" min="0.1" value={vol.iv_multiplier}
            onChange={(e) => setVol({ iv_multiplier: parseFloat(e.target.value || "1") })} />
        </div>
        <div className="field">
          <label>Risk-free %</label>
          <input type="number" step="0.005" value={vol.risk_free_rate}
            onChange={(e) => setVol({ risk_free_rate: parseFloat(e.target.value || "0.04") })} />
        </div>
      </div>
      <p className="hint">
        Options are priced with a Black-Scholes synthetic model using the stock's realized volatility as IV.
        There's no volatility risk premium, so short-premium P&L is understated — bump the IV multiplier
        (~1.1–1.3) to approximate richer real-world premiums.
      </p>
    </>
  );
}
