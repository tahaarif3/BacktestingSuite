import { useEffect, useMemo, useRef, useState } from "react";
import type { OptionStructureConfig, OptionStructureMeta, PortfolioCreateResponse } from "../../types";
import type { usePortfolioSession } from "../../hooks/usePortfolioSession";
import { api } from "../../api";
import { usePlayback } from "../../hooks/usePlayback";
import CandleChart, { type CandleChartHandle, type CandleFill, type CandleMarker } from "../CandleChart";
import PlaybackControls from "../replay/PlaybackControls";
import RadarPanel from "./RadarPanel";
import OptionsConfig from "../options/OptionsConfig";
import { DEFAULT_VOL } from "../options/OptionsConfig";
import MetricCard from "../MetricCard";
import Sparkline from "../Sparkline";
import { PALETTE } from "../Plot";
import { usd, dec } from "../../format";

interface Props {
  session: ReturnType<typeof usePortfolioSession>;
  created: PortfolioCreateResponse;
  defaultStructure: OptionStructureConfig;
  active: boolean;
}

// Forward-fill nulls (pre-listing bars) so the candlestick chart stays finite.
function ffill(arr: (number | null)[]): number[] {
  const out: number[] = new Array(arr.length).fill(0);
  let last = arr.find((x) => x != null) ?? 0;
  for (let i = 0; i < arr.length; i++) {
    if (arr[i] != null) last = arr[i] as number;
    out[i] = last;
  }
  return out;
}

export default function PortfolioRunner({ session, created, defaultStructure, active }: Props) {
  const { state } = session;
  const chartRef = useRef<CandleChartHandle>(null);
  const [structureCfg, setStructureCfg] = useState<OptionStructureConfig>(defaultStructure);
  const [vol, setVol] = useState(DEFAULT_VOL);
  const [structures, setStructures] = useState<OptionStructureMeta[]>([]);
  useEffect(() => {
    api.listOptionStructures().then(setStructures).catch(() => {});
  }, []);

  const signalBars = useMemo(() => new Set(created.signal_bars), [created.signal_bars]);

  const [play, controls] = usePlayback({
    lastIndex: created.total_bars - 1,
    startIndex: created.start_index,
    signalBars,
    onDraw: (cursor) => chartRef.current?.draw(cursor),
    onCursorSettled: (c) => session.seek(c),
    enabled: active,
  });

  const cursor = play.cursor;
  const reviewing = play.reviewing;
  const selected = session.selected;
  const chartSym = selected ?? "SPY";

  // Which OHLCV drives the chart: the selected symbol, else the SPY clock.
  const chart = useMemo(() => {
    if (selected && session.symbolBars && session.symbolBars.symbol === selected) {
      const sb = session.symbolBars;
      const markers: CandleMarker[] = [];
      for (let i = 1; i < sb.signal.length; i++) {
        if (sb.signal[i] >= 0.5 && sb.signal[i - 1] < 0.5) markers.push({ index: i, to_signal: 1 });
      }
      return {
        dates: sb.dates, o: ffill(sb.o), h: ffill(sb.h), l: ffill(sb.l), c: ffill(sb.c), v: ffill(sb.v),
        signals: markers,
      };
    }
    const s = created.spy;
    return {
      dates: created.dates, o: ffill(s.o), h: ffill(s.h), l: ffill(s.l), c: ffill(s.c), v: ffill(s.v),
      signals: [] as CandleMarker[],
    };
  }, [selected, session.symbolBars, created]);

  const fills: CandleFill[] = useMemo(
    () => (state?.fills ?? [])
      .filter((f) => f.symbol === chartSym && f.action !== "expiry")
      .map((f) => ({ index: f.fill_index, side: f.action === "open" ? "buy" : "sell", price: f.spot })),
    [state?.fills, chartSym]
  );

  const syncedRef = useRef<string | null>(null);
  useEffect(() => {
    if (created.session_id && syncedRef.current !== created.session_id) {
      syncedRef.current = created.session_id;
      controls.setMaxReached(created.cursor);
      requestAnimationFrame(() => chartRef.current?.draw(created.cursor));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [created.session_id]);

  useEffect(() => {
    if (active) {
      chartRef.current?.resize();
      chartRef.current?.draw(play.cursor);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, chartSym]);

  const acct = state?.account ?? null;
  const equityTail = state?.equity_tail ?? [created.capital];

  const openOn = async () => {
    if (!selected) return;
    const st = await session.submitOrder({
      bar_index: cursor, symbol: selected, action: "open", structure: structureCfg,
    });
    if (st) {
      controls.setMaxReached(st.cursor);
      requestAnimationFrame(() => chartRef.current?.draw(st.cursor));
    }
  };
  const closePos = async (symbol: string, id: string) => {
    const st = await session.submitOrder({ bar_index: cursor, symbol, action: "close", target_structure_id: id });
    if (st) controls.setMaxReached(st.cursor);
  };

  const disabled = reviewing || session.submitting || cursor >= created.total_bars - 1;

  return (
    <div className="replay">
      <div className="replay-main">
        <div className="replay-hud">
          <div className="replay-hud-top">
            <div className="hud-symbol">
              <span className="hud-ticker">{chartSym}</span>
              <span className="pill">portfolio</span>
              {selected && <span className="pill">trading {selected}</span>}
              {reviewing && <span className="warn-tag">reviewing history</span>}
            </div>
            <div className="hud-date">{chart.dates[cursor] ?? ""}</div>
            <div className="hud-spark">
              <Sparkline
                series={[{ values: equityTail.length ? equityTail : [created.capital], color: PALETTE.primary, label: "You" }]}
                baseline={created.capital}
                height={44}
                width={180}
              />
              <div className="hint">net liq</div>
            </div>
          </div>
          <div className="metrics replay-metrics">
            <MetricCard label="Cash" value={acct ? usd(acct.cash) : "—"} tone="neutral" />
            <MetricCard label="Net Liq" value={acct ? usd(acct.net_liq) : "—"} tone="neutral" />
            <MetricCard label="Unrealized" value={acct ? usd(acct.unrealized_pnl) : "—"} tone={acct && acct.unrealized_pnl >= 0 ? "pos" : "neg"} />
            <MetricCard label="Realized" value={acct ? usd(acct.realized_pnl) : "—"} tone={acct && acct.realized_pnl >= 0 ? "pos" : "neg"} />
            <MetricCard label="Max Risk" value={acct ? usd(acct.max_risk) : "—"} tone="neutral" />
            <MetricCard label="Net Δ" value={acct ? dec(acct.net_delta) : "—"} tone="neutral" />
            <MetricCard label="Net Θ / day" value={acct ? usd(acct.net_theta) : "—"} tone="neutral" />
          </div>
        </div>

        <div className="replay-chart">
          <CandleChart
            ref={chartRef}
            dates={chart.dates}
            open={chart.o}
            high={chart.h}
            low={chart.l}
            close={chart.c}
            volume={chart.v}
            signals={chart.signals}
            fills={fills}
            sessionKey={`${created.session_id}:${chartSym}`}
            height={440}
          />
        </div>

        <PlaybackControls
          state={play}
          controls={controls}
          onFinish={() => session.finish()}
          canUndo={(state?.fills.length ?? 0) > 0}
          onUndo={() => void session.undo()}
          onRetryHere={() => {
            if (!window.confirm(`Discard trades at or after bar ${cursor} and retry?`)) return;
            void session.rewind(cursor).then((st) => st && controls.replaceProgress(st.cursor));
          }}
          onReset={() => {
            if (!window.confirm("Reset this replay and remove every trade?")) return;
            void session.reset().then((st) => st && controls.replaceProgress(st.cursor));
          }}
        />
      </div>

      <div className="replay-rail">
        <RadarPanel radar={state?.radar ?? []} selected={selected} onSelect={session.selectSymbol} />

        <div className="rail-section-title">Options ticket {selected ? `— ${selected}` : ""}</div>
        {!selected && <div className="hint">Pick a symbol from the radar to trade it.</div>}
        {selected && (
          <div className="opt-ticket">
            <OptionsConfig structures={structures} value={structureCfg} onChange={setStructureCfg} vol={vol} onVolChange={setVol} />
            <button className="btn btn-primary" disabled={disabled} onClick={openOn}>
              {session.submitting && <span className="spinner" />}
              Open {structureCfg.structure_type.replace(/_/g, " ")} on {selected} @ bar {cursor}
            </button>
          </div>
        )}

        <div className="rail-section-title">Open positions</div>
        <div className="opt-positions">
          {(!acct || acct.positions.length === 0) && <div className="hint">No open positions.</div>}
          {acct?.positions.map((p) => (
            <div key={`${p.symbol}:${p.id}`} className="opt-position">
              <div className="opt-position-head">
                <span>{p.symbol} · {p.structure_type.replace(/_/g, " ")}</span>
                <span className={p.value >= 0 ? "net-credit" : "net-debit"}>{usd(p.value)}</span>
              </div>
              <div className="hint">
                {p.contracts}x · {p.dte_bars} DTE · Δ {dec(p.greeks.delta)} · Θ {usd(p.greeks.theta)}
                {p.max_risk != null ? ` · risk ${usd(p.max_risk)}` : ""}
              </div>
              <button className="btn btn-inline" disabled={disabled} onClick={() => closePos(p.symbol, p.id)}>Close</button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
