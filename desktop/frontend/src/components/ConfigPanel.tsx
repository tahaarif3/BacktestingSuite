import { useMemo, useState } from "react";
import type { BacktestConfig, DataFile, SizerSpec, StrategySpec } from "../types";
import TickerPicker, { type TickerSelection } from "./TickerPicker";

interface Props {
  strategies: StrategySpec[];
  sizers: SizerSpec[];
  dataFiles: DataFile[];
  config: BacktestConfig;
  setConfig: (c: BacktestConfig) => void;
  onRun: () => void;
  onAddCompare: () => void;
  onRobustness: () => void;
  onFetch: (sel: TickerSelection) => void;
  busy: { run: boolean; robustness: boolean; fetch: boolean };
}

export default function ConfigPanel(props: Props) {
  const { strategies, sizers, dataFiles, config, setConfig, busy } = props;
  const [tickerForm, setTickerForm] = useState<TickerSelection>({
    ticker: "SPY",
    start: "2015-01-01",
    end: "2024-12-31",
    interval: "1d",
  });

  const spec = useMemo(
    () => strategies.find((s) => s.id === config.strategy),
    [strategies, config.strategy]
  );
  const sizerSpec = sizers.find((s) => s.id === config.sizer);

  const update = (patch: Partial<BacktestConfig>) => setConfig({ ...config, ...patch });
  const updateData = (patch: Partial<BacktestConfig["data"]>) =>
    setConfig({ ...config, data: { ...config.data, ...patch } });

  const onStrategyChange = (id: string) => {
    const s = strategies.find((x) => x.id === id);
    const params: Record<string, number> = {};
    s?.params.forEach((p) => (params[p.name] = p.default));
    update({ strategy: id, params, short: false });
  };

  const setParam = (name: string, value: number) =>
    update({ params: { ...config.params, [name]: value } });

  return (
    <div className="sidebar">
      <h1>BacktestingSuite</h1>
      <div className="subtitle">Event-driven SPY backtester</div>

      <div className="section-title">Data</div>
      <div className="field">
        <label>Source</label>
        <select
          value={config.data.source}
          onChange={(e) => updateData({ source: e.target.value as "file" | "ticker" })}
        >
          <option value="file">Local file</option>
          <option value="ticker">Fetch ticker</option>
        </select>
      </div>

      {config.data.source === "file" ? (
        <div className="field">
          <label>Dataset</label>
          <select
            value={config.data.file ?? ""}
            onChange={(e) => updateData({ file: e.target.value })}
          >
            <option value="">(default SPY)</option>
            {dataFiles.map((f) => (
              <option key={f.name} value={f.name}>
                {f.name} {f.rows ? `(${f.rows} bars)` : ""}
              </option>
            ))}
          </select>
        </div>
      ) : (
        <TickerPicker
          value={tickerForm}
          onChange={setTickerForm}
          onFetch={props.onFetch}
          busy={busy.fetch}
          compact
        />
      )}

      <div className="section-title">Strategy</div>
      <div className="field">
        <label>Strategy</label>
        <select value={config.strategy} onChange={(e) => onStrategyChange(e.target.value)}>
          {strategies.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>

      {spec?.params.map((p) => (
        <div className="field" key={p.name}>
          <label>{p.label}</label>
          <input
            type="number"
            min={p.min ?? undefined}
            max={p.max ?? undefined}
            step={p.step ?? (p.type === "int" ? 1 : 0.1)}
            value={config.params[p.name] ?? p.default}
            onChange={(e) =>
              setParam(p.name, p.type === "int" ? parseInt(e.target.value || "0", 10) : parseFloat(e.target.value || "0"))
            }
          />
        </div>
      ))}

      {spec?.supports_short && (
        <div className="field checkbox">
          <input
            id="short"
            type="checkbox"
            checked={config.short}
            onChange={(e) => update({ short: e.target.checked })}
          />
          <label htmlFor="short" style={{ margin: 0 }}>
            Allow shorting
          </label>
        </div>
      )}

      <div className="section-title">Sizing &amp; Costs</div>
      <div className="field">
        <label>Position Sizer</label>
        <select
          value={config.sizer}
          onChange={(e) => {
            const s = sizers.find((x) => x.id === e.target.value);
            update({ sizer: e.target.value, sizer_value: s?.default_value ?? config.sizer_value });
          }}
        >
          {sizers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label>{sizerSpec?.value_label ?? "Sizer value"}</label>
        <input
          type="number"
          step="0.01"
          value={config.sizer_value}
          onChange={(e) => update({ sizer_value: parseFloat(e.target.value || "0") })}
        />
      </div>
      <div className="row">
        <div className="field">
          <label>Capital ($)</label>
          <input
            type="number"
            value={config.capital}
            onChange={(e) => update({ capital: parseFloat(e.target.value || "0") })}
          />
        </div>
        <div className="field">
          <label>Timing</label>
          <select value={config.timing} onChange={(e) => update({ timing: e.target.value })}>
            <option value="next_open">Next open</option>
            <option value="next_close">Next close</option>
          </select>
        </div>
      </div>
      <div className="row">
        <div className="field">
          <label>Slippage %</label>
          <input
            type="number"
            step="0.0001"
            value={config.slippage_pct}
            onChange={(e) => update({ slippage_pct: parseFloat(e.target.value || "0") })}
          />
        </div>
        <div className="field">
          <label>Commission %</label>
          <input
            type="number"
            step="0.0001"
            value={config.commission_pct}
            onChange={(e) => update({ commission_pct: parseFloat(e.target.value || "0") })}
          />
        </div>
      </div>

      <div className="btn-group">
        <button className="btn btn-primary" disabled={busy.run} onClick={props.onRun}>
          {busy.run && <span className="spinner" />}
          Run Backtest
        </button>
        <button className="btn btn-secondary" onClick={props.onAddCompare}>
          Add to Compare
        </button>
        <button className="btn btn-secondary" disabled={busy.robustness} onClick={props.onRobustness}>
          {busy.robustness && <span className="spinner" />}
          Run Robustness
        </button>
      </div>
    </div>
  );
}
