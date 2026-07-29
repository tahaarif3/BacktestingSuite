import { useEffect, useMemo, useRef, useState } from "react";
import type { OrderSide, QtyMode, OptionStructureConfig, OptionStructureMeta, SignalEvent } from "../../types";
import type { useReplaySession } from "../../hooks/useReplaySession";
import { usePlayback } from "../../hooks/usePlayback";
import { api } from "../../api";
import CandleChart, { type CandleChartHandle, type CandleFill } from "../CandleChart";
import ReplayHud from "./ReplayHud";
import OptionsHud from "./OptionsHud";
import PlaybackControls from "./PlaybackControls";
import ReplayRail, { type SignalNow } from "./ReplayRail";
import OptionsRail, { type OptionsTicketHandle } from "./OptionsRail";
import { DEFAULT_OPTION_STRUCTURE } from "../options/OptionsConfig";
import type { OrderTicketHandle } from "./OrderTicket";

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

  useEffect(() => {
    if (isOptions && structures.length === 0) {
      api.listOptionStructures().then(setStructures).catch(() => {});
    }
  }, [isOptions, structures.length]);

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
            intraday={state.intraday}
            sessionKey={state.sessionId ?? "none"}
            height={440}
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
