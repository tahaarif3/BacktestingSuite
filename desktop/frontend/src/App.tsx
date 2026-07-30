import { useEffect, useState } from "react";
import { api } from "./api";
import type {
  BacktestConfig,
  BacktestResult,
  CompareRun,
  DataFile,
  OptionsBacktestResult,
  RobustnessResult,
  SizerSpec,
  StrategySpec,
} from "./types";
import ConfigPanel from "./components/ConfigPanel";
import ResultsDashboard from "./components/ResultsDashboard";
import RobustnessPanel from "./components/RobustnessPanel";
import ComparePanel from "./components/ComparePanel";
import EditorPanel from "./components/EditorPanel";
import ReplayPanel from "./components/replay/ReplayPanel";
import PortfolioPanel from "./components/portfolio/PortfolioPanel";
import ScannerPanel from "./components/ScannerPanel";
import UpdateBanner from "./components/UpdateBanner";

const DEFAULT_CONFIG: BacktestConfig = {
  strategy: "sma",
  params: { fast_window: 10, slow_window: 50 },
  short: false,
  sizer: "fixed_fractional",
  sizer_value: 0.5,
  capital: 100000,
  slippage_pct: 0.0002,
  commission_pct: 0.0005,
  commission_per_share: 0,
  min_trade_shares: 1e-8,
  timing: "next_open",
  mode: "equity",
  data: { source: "file", interval: "1d" },
};

const ALL_TESTS = ["train_test", "walk_forward", "monte_carlo", "cost_sensitivity"];
type Tab = "results" | "robustness" | "compare" | "scanner" | "replay" | "portfolio" | "editor";

export default function App() {
  const [strategies, setStrategies] = useState<StrategySpec[]>([]);
  const [sizers, setSizers] = useState<SizerSpec[]>([]);
  const [dataFiles, setDataFiles] = useState<DataFile[]>([]);

  const [config, setConfig] = useState<BacktestConfig>(DEFAULT_CONFIG);
  const [result, setResult] = useState<BacktestResult | OptionsBacktestResult | null>(null);
  const [robustness, setRobustness] = useState<RobustnessResult | null>(null);
  const [compareConfigs, setCompareConfigs] = useState<{ cfg: BacktestConfig; label: string }[]>([]);
  const [compareRuns, setCompareRuns] = useState<CompareRun[]>([]);

  const [tab, setTab] = useState<Tab>("results");
  const [replayVisited, setReplayVisited] = useState(false);
  const [portfolioVisited, setPortfolioVisited] = useState(false);
  const [replayPrefill, setReplayPrefill] = useState<{ file: string; strategy: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState({ run: false, robustness: false, fetch: false });

  const goTab = (t: Tab) => {
    if (t === "replay") setReplayVisited(true);
    if (t === "portfolio") setPortfolioVisited(true);
    setTab(t);
  };

  const fullTab = tab === "replay" || tab === "portfolio";

  const rsBreakoutParams = (): Record<string, number> => {
    const spec = strategies.find((s) => s.id === "rs_breakout");
    const p: Record<string, number> = {};
    spec?.params.forEach((pp) => (p[pp.name] = pp.default));
    return p;
  };

  const onScanBacktest = (file: string) => {
    const cfg: BacktestConfig = {
      ...DEFAULT_CONFIG,
      strategy: "rs_breakout",
      params: rsBreakoutParams(),
      mode: "equity",
      options: null,
      vol: null,
      data: { source: "file", file, interval: "1d" },
    };
    setConfig(cfg);
    void guard("run", async () => {
      const res = await api.runBacktest(cfg);
      setResult(res);
      setTab("results");
    });
  };

  const onScanReplay = (file: string) => {
    setReplayPrefill({ file, strategy: "rs_breakout" });
    setReplayVisited(true);
    setTab("replay");
  };

  useEffect(() => {
    (async () => {
      try {
        const [strats, szs, files] = await Promise.all([
          api.getStrategies(),
          api.getSizers(),
          api.listData(),
        ]);
        setStrategies(strats);
        setSizers(szs);
        setDataFiles(files);
      } catch (e) {
        setError(`Cannot reach backend: ${(e as Error).message}`);
      }
    })();
  }, []);

  const labelFor = (cfg: BacktestConfig): string => {
    const spec = strategies.find((s) => s.id === cfg.strategy);
    const params = Object.values(cfg.params).join("/");
    return `${spec?.name ?? cfg.strategy}${params ? ` ${params}` : ""}${cfg.short ? " (short)" : ""}`;
  };

  const guard = async (key: keyof typeof busy, fn: () => Promise<void>) => {
    setBusy((b) => ({ ...b, [key]: true }));
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy((b) => ({ ...b, [key]: false }));
    }
  };

  const onRun = () =>
    guard("run", async () => {
      const res = await api.runBacktest(config);
      setResult(res);
      setTab("results");
    });

  const onRobustness = () =>
    guard("robustness", async () => {
      const res = await api.runRobustness(config, ALL_TESTS);
      setRobustness(res);
      setTab("robustness");
    });

  const onFetch = (sel: { ticker: string; start: string; end: string; interval: string }) =>
    guard("fetch", async () => {
      const file = await api.fetchTicker(sel.ticker, sel.start, sel.end, sel.interval);
      setDataFiles(await api.listData());
      setConfig({ ...config, data: { ...config.data, source: "file", file: file.name } });
    });

  const refreshCompare = async (items: { cfg: BacktestConfig; label: string }[]) => {
    if (items.length === 0) {
      setCompareRuns([]);
      return;
    }
    const runs = await api.compare(items.map((i) => i.cfg), items.map((i) => i.label));
    setCompareRuns(runs);
  };

  const onAddCompare = () =>
    guard("run", async () => {
      const item = { cfg: { ...config, params: { ...config.params } }, label: labelFor(config) };
      const next = [...compareConfigs, item];
      setCompareConfigs(next);
      await refreshCompare(next);
      setTab("compare");
    });

  const onRemoveCompare = (index: number) => {
    const next = compareConfigs.filter((_, i) => i !== index);
    setCompareConfigs(next);
    refreshCompare(next).catch((e) => setError((e as Error).message));
  };

  const onClearCompare = () => {
    setCompareConfigs([]);
    setCompareRuns([]);
  };

  const onStrategiesChanged = async () => {
    try {
      setStrategies(await api.getStrategies());
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className={`app ${fullTab ? "app--full" : ""}`}>
      {!fullTab && (
        <ConfigPanel
          strategies={strategies}
          sizers={sizers}
          dataFiles={dataFiles}
          config={config}
          setConfig={setConfig}
          onRun={onRun}
          onAddCompare={onAddCompare}
          onRobustness={onRobustness}
          onFetch={onFetch}
          busy={busy}
        />
      )}

      <div className="main">
        <div className="tabs">
          <div className={`tab ${tab === "results" ? "active" : ""}`} onClick={() => goTab("results")}>
            Results
          </div>
          <div className={`tab ${tab === "robustness" ? "active" : ""}`} onClick={() => goTab("robustness")}>
            Robustness
          </div>
          <div className={`tab ${tab === "compare" ? "active" : ""}`} onClick={() => goTab("compare")}>
            Compare
            {compareRuns.length > 0 && <span className="badge">{compareRuns.length}</span>}
          </div>
          <div className={`tab ${tab === "scanner" ? "active" : ""}`} onClick={() => goTab("scanner")}>
            Scanner
          </div>
          <div className={`tab ${tab === "replay" ? "active" : ""}`} onClick={() => goTab("replay")}>
            Replay
          </div>
          <div className={`tab ${tab === "portfolio" ? "active" : ""}`} onClick={() => goTab("portfolio")}>
            Portfolio
          </div>
          <div className={`tab ${tab === "editor" ? "active" : ""}`} onClick={() => goTab("editor")}>
            Editor
          </div>

          <div className="tabs-right">
            <button
              className="tabs-link"
              onClick={() => window.backtest?.checkForUpdates?.()}
              title="Check GitHub for a newer version"
            >
              Check for updates
            </button>
            <button
              className="tabs-link"
              onClick={() => window.backtest?.reportBug?.()}
              title="Open a prefilled GitHub issue"
            >
              Report a bug
            </button>
            <span className="app-version">v{window.backtest?.appVersion ?? "dev"}</span>
          </div>
        </div>

        <div className={`content ${fullTab ? "content--flush" : ""}`}>
          <UpdateBanner />
          {error && <div className="error">{error}</div>}
          {tab === "results" && <ResultsDashboard result={result} />}
          {tab === "robustness" && <RobustnessPanel result={robustness} />}
          {tab === "compare" && (
            <ComparePanel runs={compareRuns} onClear={onClearCompare} onRemove={onRemoveCompare} />
          )}
          {tab === "editor" && <EditorPanel onStrategiesChanged={onStrategiesChanged} />}
          {tab === "scanner" && <ScannerPanel onBacktest={onScanBacktest} onReplay={onScanReplay} />}
          {replayVisited && (
            <div style={{ display: tab === "replay" ? "block" : "none", height: "100%" }}>
              <ReplayPanel
                strategies={strategies}
                sizers={sizers}
                dataFiles={dataFiles}
                onFetch={onFetch}
                fetchBusy={busy.fetch}
                active={tab === "replay"}
                prefill={replayPrefill}
              />
            </div>
          )}
          {portfolioVisited && (
            <div style={{ display: tab === "portfolio" ? "block" : "none", height: "100%" }}>
              <PortfolioPanel active={tab === "portfolio"} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
