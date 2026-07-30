import { useEffect, useMemo, useState } from "react";
import type {
  DataFile,
  OptionStructureConfig,
  OptionStructureMeta,
  ReplaySessionConfig,
  SizerSpec,
  StrategySpec,
  TradeMode,
  VolModelConfig,
} from "../../types";
import { api } from "../../api";
import TickerPicker, { type TickerSelection } from "../TickerPicker";
import OptionsConfig, { DEFAULT_OPTION_STRUCTURE, DEFAULT_VOL } from "../options/OptionsConfig";

interface Props {
  strategies: StrategySpec[];
  sizers: SizerSpec[];
  dataFiles: DataFile[];
  onFetch: (sel: TickerSelection) => void;
  fetchBusy: boolean;
  onStart: (config: ReplaySessionConfig) => void;
  loading: boolean;
  error: string | null;
  prefill?: { file: string; strategy: string } | null;
}

export default function ReplaySetup(props: Props) {
  const { strategies, sizers, dataFiles, onFetch, fetchBusy, onStart, loading, error, prefill } = props;

  const [source, setSource] = useState<"file" | "ticker">("file");
  const [file, setFile] = useState<string>("");
  const [ticker, setTicker] = useState<TickerSelection>({
    ticker: "AAPL",
    start: "2018-01-01",
    end: "2024-12-31",
    interval: "1d",
  });
  const [strategy, setStrategy] = useState("sma");
  const [params, setParams] = useState<Record<string, number>>({ fast_window: 10, slow_window: 50 });
  const [short, setShort] = useState(false);
  const [sizer, setSizer] = useState("fixed_fractional");
  const [sizerValue, setSizerValue] = useState(0.5);
  const [capital, setCapital] = useState(100000);
  const [slippage, setSlippage] = useState(0.0002);
  const [commission, setCommission] = useState(0.0005);
  const [timing, setTiming] = useState("next_open");
  const [warmup, setWarmup] = useState(100);
  const [margin, setMargin] = useState<"cash_only" | "unlimited">("cash_only");
  const [tradeMode, setTradeMode] = useState<TradeMode>("equity");
  const [optStructure, setOptStructure] = useState<OptionStructureConfig>(DEFAULT_OPTION_STRUCTURE);
  const [optVol, setOptVol] = useState<VolModelConfig>(DEFAULT_VOL);
  const [structures, setStructures] = useState<OptionStructureMeta[]>([]);

  useEffect(() => {
    api.listOptionStructures().then(setStructures).catch(() => {});
  }, []);

  // Apply a prefill handed over from the scanner ("trade this hit").
  useEffect(() => {
    if (!prefill) return;
    setSource("file");
    setFile(prefill.file);
    const s = strategies.find((x) => x.id === prefill.strategy);
    if (s) {
      const p: Record<string, number> = {};
      s.params.forEach((param) => (p[param.name] = param.default));
      setStrategy(prefill.strategy);
      setParams(p);
      setShort(false);
    }
  }, [prefill, strategies]);

  const spec = useMemo(() => strategies.find((s) => s.id === strategy), [strategies, strategy]);
  const sizerSpec = sizers.find((s) => s.id === sizer);

  const onStrategyChange = (id: string) => {
    const s = strategies.find((x) => x.id === id);
    const p: Record<string, number> = {};
    s?.params.forEach((param) => (p[param.name] = param.default));
    setStrategy(id);
    setParams(p);
    setShort(false);
  };

  const build = (): ReplaySessionConfig => ({
    strategy,
    params,
    short,
    sizer,
    sizer_value: sizerValue,
    capital,
    slippage_pct: slippage,
    commission_pct: commission,
    commission_per_share: 0,
    min_trade_shares: 1e-8,
    timing,
    data:
      source === "file"
        ? { source: "file", file: file || undefined, interval: "1d" }
        : {
            source: "ticker",
            file: `${ticker.ticker.toUpperCase()}_${ticker.interval}.parquet`,
            ticker: ticker.ticker,
            interval: ticker.interval,
          },
    warmup_bars: warmup,
    margin_policy: margin,
    whole_shares: false,
    mode: tradeMode,
    options: tradeMode === "options" ? optStructure : null,
    vol: tradeMode === "options" ? optVol : null,
  });

  return (
    <div className="replay-setup">
      <div className="card setup-card">
        <h3>New replay session</h3>
        <p className="hint">
          Step through a stock bar by bar. When your strategy fires a signal, decide whether to buy,
          sell, or hold — then see how you did against the algo and buy &amp; hold.
        </p>

        <div className="section-title">Data</div>
        <div className="field">
          <label>Source</label>
          <select value={source} onChange={(e) => setSource(e.target.value as "file" | "ticker")}>
            <option value="file">Cached dataset</option>
            <option value="ticker">Fetch a stock</option>
          </select>
        </div>

        {source === "file" ? (
          <div className="field">
            <label>Dataset</label>
            <select value={file} onChange={(e) => setFile(e.target.value)}>
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
            value={ticker}
            onChange={setTicker}
            onFetch={(sel) => {
              onFetch(sel);
              setSource("file");
              setFile(`${sel.ticker.toUpperCase()}_${sel.interval}.parquet`);
            }}
            busy={fetchBusy}
          />
        )}

        <div className="section-title">Strategy (signal source)</div>
        <div className="field">
          <label>Strategy</label>
          <select value={strategy} onChange={(e) => onStrategyChange(e.target.value)}>
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
              value={params[p.name] ?? p.default}
              onChange={(e) =>
                setParams({
                  ...params,
                  [p.name]: p.type === "int" ? parseInt(e.target.value || "0", 10) : parseFloat(e.target.value || "0"),
                })
              }
            />
          </div>
        ))}
        {spec?.supports_short && (
          <div className="field checkbox">
            <input id="rp-short" type="checkbox" checked={short} onChange={(e) => setShort(e.target.checked)} />
            <label htmlFor="rp-short" style={{ margin: 0 }}>
              Allow shorting
            </label>
          </div>
        )}

        <div className="section-title">Trade mode</div>
        <div className="seg">
          <button className={`seg-btn ${tradeMode === "equity" ? "active" : ""}`} onClick={() => setTradeMode("equity")}>
            Equity (shares)
          </button>
          <button className={`seg-btn ${tradeMode === "options" ? "active" : ""}`} onClick={() => setTradeMode("options")}>
            Options
          </button>
        </div>
        {tradeMode === "options" && (
          <OptionsConfig
            structures={structures}
            value={optStructure}
            onChange={setOptStructure}
            vol={optVol}
            onVolChange={setOptVol}
          />
        )}

        <div className="section-title">Account &amp; playback</div>
        <div className="row">
          <div className="field">
            <label>Position Sizer</label>
            <select
              value={sizer}
              onChange={(e) => {
                const s = sizers.find((x) => x.id === e.target.value);
                setSizer(e.target.value);
                setSizerValue(s?.default_value ?? sizerValue);
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
            <input type="number" step="0.01" value={sizerValue} onChange={(e) => setSizerValue(parseFloat(e.target.value || "0"))} />
          </div>
        </div>
        <div className="row">
          <div className="field">
            <label>Capital ($)</label>
            <input type="number" value={capital} onChange={(e) => setCapital(parseFloat(e.target.value || "0"))} />
          </div>
          <div className="field">
            <label>Timing</label>
            <select value={timing} onChange={(e) => setTiming(e.target.value)}>
              <option value="next_open">Next open</option>
              <option value="next_close">Next close</option>
            </select>
          </div>
        </div>
        <div className="row">
          <div className="field">
            <label>Slippage %</label>
            <input type="number" step="0.0001" value={slippage} onChange={(e) => setSlippage(parseFloat(e.target.value || "0"))} />
          </div>
          <div className="field">
            <label>Commission %</label>
            <input type="number" step="0.0001" value={commission} onChange={(e) => setCommission(parseFloat(e.target.value || "0"))} />
          </div>
        </div>
        <div className="row">
          <div className="field">
            <label>Warm-up bars</label>
            <input type="number" value={warmup} onChange={(e) => setWarmup(parseInt(e.target.value || "0", 10))} />
          </div>
          <div className="field">
            <label>Margin</label>
            <select value={margin} onChange={(e) => setMargin(e.target.value as "cash_only" | "unlimited")}>
              <option value="cash_only">Cash only</option>
              <option value="unlimited">Unlimited (match engine)</option>
            </select>
          </div>
        </div>

        {error && <div className="error">{error}</div>}

        <button className="btn btn-primary" disabled={loading} onClick={() => onStart(build())}>
          {loading && <span className="spinner" />}
          Start replay
        </button>
      </div>
    </div>
  );
}
