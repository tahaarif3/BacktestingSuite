import type { DataFile, SizerSpec, StrategySpec } from "../../types";
import type { TickerSelection } from "../TickerPicker";
import { useReplaySession } from "../../hooks/useReplaySession";
import ReplaySetup from "./ReplaySetup";
import ReplayRunner from "./ReplayRunner";
import ReplayScoreboard from "./ReplayScoreboard";

interface Props {
  strategies: StrategySpec[];
  sizers: SizerSpec[];
  dataFiles: DataFile[];
  onFetch: (sel: TickerSelection) => void;
  fetchBusy: boolean;
  active: boolean;
  prefill?: { file: string; strategy: string } | null;
}

export default function ReplayPanel(props: Props) {
  const session = useReplaySession();
  const { state } = session;

  if (state.phase === "setup" || state.phase === "loading" || state.phase === "error") {
    return (
      <ReplaySetup
        strategies={props.strategies}
        sizers={props.sizers}
        dataFiles={props.dataFiles}
        onFetch={props.onFetch}
        fetchBusy={props.fetchBusy}
        onStart={session.start}
        loading={state.phase === "loading"}
        error={state.error}
        prefill={props.prefill}
      />
    );
  }

  if (state.phase === "scored" && state.score) {
    return (
      <ReplayScoreboard
        score={state.score}
        journal={state.journal}
        intraday={state.intraday}
        onResume={session.backToRunning}
        onNewSession={session.close}
      />
    );
  }

  // running
  return (
    <div className="replay-wrap">
      <div className="replay-toolbar">
        <span className="hint">
          {state.strategyName} on {state.symbol}
        </span>
        <button className="btn-inline" onClick={session.close}>
          End session
        </button>
      </div>
      {state.bars && <ReplayRunner session={session} active={props.active} />}
    </div>
  );
}
