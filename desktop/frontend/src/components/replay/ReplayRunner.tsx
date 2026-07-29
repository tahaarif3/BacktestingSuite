import { useEffect, useMemo, useRef, useState } from "react";
import type { OrderSide, QtyMode, OptionStructureConfig, OptionStructureMeta, SignalEvent } from "../../types";
import type { useReplaySession } from "../../hooks/useReplaySession";
import { usePlayback } from "../../hooks/usePlayback";
import { api } from "../../api";
import CandleChart, { type CandleChartHandle, type CandleFill, type PriceOverlay, type SubPanel } from "../CandleChart";
import ReplayHud from "./ReplayHud";
import OptionsHud from "./OptionsHud";
import PlaybackControls from "./PlaybackControls";
import ReplayRail, { type SignalNow } from "./ReplayRail";
import OptionsRail, { type OptionsTicketHandle } from "./OptionsRail";
import IndicatorControls from "./IndicatorControls";
import { DEFAULT_OPTION_STRUCTURE } from "../options/OptionsConfig";
import type { OrderTicketHandle } from "./OrderTicket";
import type { Indicator } from "../../indicators";
import { sma, ema, rsi, relativeStrength, regimeAt } from "../../indicators";
import { PALETTE } from "../Plot";

interface Props {
  session: ReturnType<typeof useReplaySession>;
  active: boolean;
}

function fmtDate(d: number | string | undefined, intraday: boolean): string {
  if (d === undefined) return "";
  if (typeof d === "number") {
    const dt = new Date(d * 1000);
    return intraday
      ? dt.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
      : dt.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }
  return String(d);
}

export default function ReplayRunner({ session, active }: Props) {
  const { state, submitOrder, submitOptionOrder, previewOption, seek, finish, rewind, reset, undo } = session;
  const isOptions = state.mode === "options";
  const bars = state.bars!;
  const chartRef = useRef<CandleChartHandle>(null);
  const ticketRef = useRef<OrderTicketHandle>(null);
  const optTicketRef = useRef<OptionsTicketHandle>(null);
  const [side, setSide] = useState<OrderSide>("buy");
  const [structureCfg, setStructureCfg] = useState<OptionStructureConfig>(
    () => state.optionsAccount !== null || isOptions ? DEFAULT_OPTION_STRUCTURE : DEFAULT_OPTION_STRUCTURE
  );
  const [structures, setStructures] = useState<OptionStructureMeta[]>([]);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [reference, setReference] = useState<number[] | null>(null);
  const [showRS, setShowRS] = useState(false);

  useEffect(() => {
    if (isOptions && structures.length === 0) {
      api.listOptionStructures().then(setStructures).catch(() => {});
    }
  }, [isOptions, structures.length]);

  // Fetch the SPY reference series once per session (for relative strength + regime).
  useEffect(() => {
    if (!state.sessionId) return;
    let cancelled = false;
    api.getReplayReference(state.sessionId)
      .then((r) => {
        if (!cancelled) setReference(r.close && r.close.length ? r.close : null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [state.sessionId]);

  const hasReference = !!reference && reference.length === (bars?.close.length ?? -1);

  // Price-panel overlays (SMA/EMA) computed from the full close series.
  const overlays: PriceOverlay[] = useMemo(() => {
    const close = bars?.close ?? [];
    return indicators
      .filter((i) => i.type === "sma" || i.type === "ema")
      .map((i) => ({
        id: i.id,
        label: `${i.type.toUpperCase()} ${i.period}`,
        color: i.color,
        values: i.type === "sma" ? sma(close, i.period) : ema(close, i.period),
      }));
  }, [indicators, bars]);

  // Lower sub-panels: one per RSI indicator, plus relative strength when enabled.
  const panels: SubPanel[] = useMemo(() => {
    const close = bars?.close ?? [];
    const out: SubPanel[] = [];
    if (hasReference && showRS && reference) {
      out.push({
        id: "rs",
        label: "Rel-Strength vs SPY",
        color: PALETTE.accent,
        values: relativeStrength(close, reference),
        guides: [100],
      });
    }
    indicators
      .filter((i) => i.type === "rsi")
      .forEach((i) =>
        out.push({
          id: i.id,
          label: `RSI ${i.period}`,
          color: i.color,
          values: rsi(close, i.period),
          fixedRange: [0, 100],
          guides: [30, 70],
        })
      );
    return out;
  }, [indicators, bars, hasReference, showRS, reference]);

  const signalBars = useMemo(() => new Set(state.signalEvents.map((e) => e.index)), [state.signalEvents]);
  const eventByIndex = useMemo(() => {
    const m = new Map<number, SignalEvent>();
    state.signalEvents.forEach((e) => m.set(e.index, e));
    return m;
  }, [state.signalEvents]);

  const fillMarkers: CandleFill[] = useMemo(() => {
    if (isOptions) {
      return state.optionFills
        .filter((f) => f.action !== "expiry")
        .map((f) => ({ index: f.fill_index, side: f.action === "open" ? "buy" : "sell", price: f.spot }));
    }
    return state.fills
      .filter((f) => !f.no_op)
      .map((f) => ({ index: f.fill_index, side: f.trade_shares >= 0 ? "buy" : "sell", price: f.exec_price }));
  }, [state.fills, state.optionFills, isOptions]);

  const signalMarkers = useMemo(
    () => state.signalEvents.map((e) => ({ index: e.index, to_signal: e.to_signal })),
    [state.signalEvents]
  );

  const [play, controls] = usePlayback({
    lastIndex: state.totalBars - 1,
    startIndex: state.startIndex,
    signalBars,
    onDraw: (cursor) => chartRef.current?.draw(cursor),
    onCursorSettled: (c) => seek(c),
    enabled: active,
  });

  const syncedRef = useRef<string | null>(null);
  useEffect(() => {
    if (state.sessionId && syncedRef.current !== state.sessionId) {
      syncedRef.current = state.sessionId;
      controls.setMaxReached(state.cursor);
      requestAnimationFrame(() => chartRef.current?.draw(state.cursor));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.sessionId]);

  useEffect(() => {
    if (active) {
      chartRef.current?.resize();
      chartRef.current?.draw(play.cursor);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const cursor = play.cursor;
  const price = bars.close[cursor] ?? 0;
  const reviewing = play.reviewing;
  const event = eventByIndex.get(cursor) ?? null;

  const regime = useMemo(
    () => (hasReference && reference ? regimeAt(bars.close, reference, cursor) : null),
    [hasReference, reference, bars, cursor]
  );

  // Preselect an equity side on a signal bar (equity mode only).
  useEffect(() => {
    if (!isOptions && event) setSide(event.to_signal > 0 ? "buy" : event.to_signal < 0 ? "sell" : "close");
  }, [event, isOptions]);

  const signalNow: SignalNow | null = event
    ? {
        toSignal: event.to_signal,
        kind: event.kind,
        ohlc: { open: bars.open[cursor], high: bars.high[cursor], low: bars.low[cursor], close: bars.close[cursor] },
        algoShares: event.algo_target_shares,
      }
    : null;

  const handleSubmit = async (o: { side: OrderSide; qty_mode: QtyMode; qty_value: number }) => {
    const st = await submitOrder({ bar_index: cursor, side: o.side, qty_mode: o.qty_mode, qty_value: o.qty_value });
    if (st) {
      controls.setMaxReached(st.cursor);
      requestAnimationFrame(() => chartRef.current?.draw(st.cursor));
    }
  };

  const handleOpenOption = async (cfg: OptionStructureConfig) => {
    const st = await submitOptionOrder({ bar_index: cursor, action: "open", structure: cfg });
    if (st) {
      controls.setMaxReached(st.cursor);
      requestAnimationFrame(() => chartRef.current?.draw(st.cursor));
    }
  };

  const handleCloseOption = async (positionId: string) => {
    const st = await submitOptionOrder({ bar_index: cursor, action: "close", target_structure_id: positionId });
    if (st) {
      controls.setMaxReached(st.cursor);
      requestAnimationFrame(() => chartRef.current?.draw(st.cursor));
    }
  };

  // Keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t.isContentEditable) return;
      switch (e.key) {
        case " ":
          e.preventDefault();
          controls.toggle();
          break;
        case "ArrowRight":
          controls.stepForward(e.shiftKey ? 10 : 1);
          break;
        case "ArrowLeft":
          controls.stepBack(e.shiftKey ? 10 : 1);
          break;
        case "n":
        case "N":
          controls.jumpToNextSignal();
          break;
        case "End":
          controls.jumpToLive();
          break;
        case "Enter":
          e.preventDefault();
          if (isOptions) optTicketRef.current?.submit();
          else ticketRef.current?.submit();
          break;
        case "b":
        case "B":
          if (!isOptions) setSide("buy");
          break;
        case "s":
        case "S":
          if (!isOptions) setSide("sell");
          break;
        case "c":
        case "C":
          if (!isOptions) setSide("close");
          break;
        case "r":
        case "R":
          controls.restart();
          break;
        case "1": controls.setSpeed(1000); break;
        case "2": controls.setSpeed(500); break;
        case "3": controls.setSpeed(200); break;
        case "4": controls.setSpeed(100); break;
        case "5": controls.setSpeed(50); break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [controls, isOptions]);

  const disabled = reviewing || state.submitting || cursor >= state.totalBars - 1;
  const disabledReason = reviewing
    ? "Reviewing history — press End to return to live."
    : cursor >= state.totalBars - 1
      ? "End of data."
      : undefined;

  return (
    <div className="replay">
      <div className="replay-main">
        {isOptions ? (
          <OptionsHud
            symbol={state.symbol}
            interval={state.interval}
            dateLabel={fmtDate(bars.dates[cursor], state.intraday)}
            cursor={cursor}
            startIndex={state.startIndex}
            totalBars={state.totalBars}
            account={state.optionsAccount}
            equityTail={state.equityTail}
            capital={state.capital}
            reviewing={reviewing}
          />
        ) : (
          <ReplayHud
            symbol={state.symbol}
            interval={state.interval}
            dateLabel={fmtDate(bars.dates[cursor], state.intraday)}
            cursor={cursor}
            startIndex={state.startIndex}
            totalBars={state.totalBars}
            account={state.account}
            equityTail={state.equityTail}
            capital={state.capital}
            reviewing={reviewing}
          />
        )}

        {state.causalityWarning && <div className="error">{state.causalityWarning}</div>}

        <div className="chart-toolbar">
          <IndicatorControls
            indicators={indicators}
            onChange={setIndicators}
            hasReference={hasReference}
            showRelStrength={showRS}
            onToggleRelStrength={setShowRS}
          />
          {regime && (
            <div className="regime-strip">
              <span className={`regime-tag ${regime.spyWeak ? "on" : ""}`}>
                SPY {regime.spyWeak ? "weak ✓" : "not weak"}
              </span>
              <span className={`regime-tag ${regime.stockStrong ? "on" : ""}`}>
                Stock {regime.stockStrong ? "strong ✓" : "not strong"}
              </span>
              <span className={`regime-tag ${regime.rsPct > 0 ? "on" : ""}`}>
                RS(20) {(regime.rsPct * 100).toFixed(1)}%
              </span>
              <span className={`regime-tag ${regime.armed ? "armed" : ""}`}>
                {regime.armed ? "setup armed" : "waiting"}
              </span>
            </div>
          )}
        </div>

        <div className="replay-chart">
          <CandleChart
            ref={chartRef}
            dates={bars.dates}
            open={bars.open}
            high={bars.high}
            low={bars.low}
            close={bars.close}
            volume={bars.volume}
            signals={signalMarkers}
            fills={fillMarkers}
            overlays={overlays}
            panels={panels}
            intraday={state.intraday}
            sessionKey={state.sessionId ?? "none"}
            height={panels.length > 0 ? 520 : 440}
          />
        </div>

        <PlaybackControls
          state={play}
          controls={controls}
          onFinish={() => finish(cursor)}
          canUndo={isOptions ? state.optionOrders.length > 0 : state.orders.length > 0}
          onUndo={() => {
            void undo();
          }}
          onRetryHere={() => {
            if (!window.confirm(`Discard decisions at or after bar ${cursor} and retry from here?`)) return;
            void rewind(cursor, true).then((st) => {
              if (st) controls.replaceProgress(st.cursor);
            });
          }}
          onReset={() => {
            if (!window.confirm("Reset this replay and remove every manual trade?")) return;
            void reset().then((st) => {
              if (st) controls.replaceProgress(st.cursor);
            });
          }}
        />
      </div>

      {isOptions ? (
        <OptionsRail
          ref={optTicketRef}
          barIndex={cursor}
          structures={structures}
          account={state.optionsAccount}
          structureCfg={structureCfg}
          setStructureCfg={setStructureCfg}
          disabled={disabled}
          disabledReason={disabledReason}
          submitting={state.submitting}
          error={state.error}
          previewOption={previewOption}
          onOpen={handleOpenOption}
          onClose={handleCloseOption}
        />
      ) : (
        <ReplayRail
          barIndex={cursor}
          price={price}
          account={state.account}
          algoShares={event?.algo_target_shares ?? 0}
          signalNow={signalNow}
          intraday={state.intraday}
          fills={state.fills}
          disabled={disabled}
          disabledReason={disabledReason}
          submitting={state.submitting}
          error={state.error}
          side={side}
          setSide={setSide}
          onSubmit={handleSubmit}
          onSkip={() => controls.play()}
          ticketRef={ticketRef}
        />
      )}
    </div>
  );
}
