import { useEffect, useMemo, useRef, useState } from "react";
import type { OrderSide, QtyMode, SignalEvent } from "../../types";
import type { useReplaySession } from "../../hooks/useReplaySession";
import { usePlayback } from "../../hooks/usePlayback";
import CandleChart, { type CandleChartHandle, type CandleFill } from "../CandleChart";
import ReplayHud from "./ReplayHud";
import PlaybackControls from "./PlaybackControls";
import ReplayRail, { type SignalNow } from "./ReplayRail";
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
  const { state, submitOrder, seek, finish, rewind, reset, undo } = session;
  const bars = state.bars!;
  const chartRef = useRef<CandleChartHandle>(null);
  const ticketRef = useRef<OrderTicketHandle>(null);
  const [side, setSide] = useState<OrderSide>("buy");

  const signalBars = useMemo(() => new Set(state.signalEvents.map((e) => e.index)), [state.signalEvents]);
  const eventByIndex = useMemo(() => {
    const m = new Map<number, SignalEvent>();
    state.signalEvents.forEach((e) => m.set(e.index, e));
    return m;
  }, [state.signalEvents]);

  const fillMarkers: CandleFill[] = useMemo(
    () =>
      state.fills
        .filter((f) => !f.no_op)
        .map((f) => ({
          index: f.fill_index,
          side: f.trade_shares >= 0 ? "buy" : "sell",
          price: f.exec_price,
        })),
    [state.fills]
  );
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

  // Sync the playback cursor to the (possibly resumed) session cursor once.
  const syncedRef = useRef<string | null>(null);
  useEffect(() => {
    if (state.sessionId && syncedRef.current !== state.sessionId) {
      syncedRef.current = state.sessionId;
      controls.setMaxReached(state.cursor);
      requestAnimationFrame(() => chartRef.current?.draw(state.cursor));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.sessionId]);

  // Redraw / resize when the panel becomes visible again.
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

  // Preselect a side when the cursor lands on a signal bar.
  useEffect(() => {
    if (event) setSide(event.to_signal > 0 ? "buy" : event.to_signal < 0 ? "sell" : "close");
  }, [event]);

  const signalNow: SignalNow | null = event
    ? {
        toSignal: event.to_signal,
        kind: event.kind,
        ohlc: { open: bars.open[cursor], high: bars.high[cursor], low: bars.low[cursor], close: bars.close[cursor] },
        algoShares: event.algo_target_shares,
      }
    : null;

  const handleSubmit = async (o: { side: OrderSide; qty_mode: QtyMode; qty_value: number }) => {
    const c = cursor;
    const st = await submitOrder({ bar_index: c, side: o.side, qty_mode: o.qty_mode, qty_value: o.qty_value });
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
          ticketRef.current?.submit();
          break;
        case "b":
        case "B":
          setSide("buy");
          break;
        case "s":
        case "S":
          setSide("sell");
          break;
        case "c":
        case "C":
          setSide("close");
          break;
        case "k":
        case "K":
          controls.play();
          break;
        case "r":
        case "R":
          controls.restart();
          break;
        case "1":
          controls.setSpeed(1000);
          break;
        case "2":
          controls.setSpeed(500);
          break;
        case "3":
          controls.setSpeed(200);
          break;
        case "4":
          controls.setSpeed(100);
          break;
        case "5":
          controls.setSpeed(50);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [controls]);

  return (
    <div className="replay">
      <div className="replay-main">
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
          canUndo={state.orders.length > 0}
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

      <ReplayRail
        barIndex={cursor}
        price={price}
        account={state.account}
        algoShares={event?.algo_target_shares ?? 0}
        signalNow={signalNow}
        intraday={state.intraday}
        fills={state.fills}
        disabled={reviewing || state.submitting || cursor >= state.totalBars - 1}
        disabledReason={
          reviewing
            ? "Reviewing history — press End to return to live."
            : cursor >= state.totalBars - 1
              ? "End of data."
              : undefined
        }
        submitting={state.submitting}
        error={state.error}
        side={side}
        setSide={setSide}
        onSubmit={handleSubmit}
        onSkip={() => controls.play()}
        ticketRef={ticketRef}
      />
    </div>
  );
}
