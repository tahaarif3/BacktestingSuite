import type { PlaybackState, PlaybackControls as Controls } from "../../hooks/usePlayback";

interface Props {
  state: PlaybackState;
  controls: Controls;
  onFinish: () => void;
  onRetryHere: () => void;
  onUndo: () => void;
  onReset: () => void;
  canUndo: boolean;
}

const SPEEDS = [
  { ms: 1000, label: "1×", title: "Study (1 bar/s)" },
  { ms: 500, label: "2×" },
  { ms: 200, label: "5×" },
  { ms: 100, label: "10×" },
  { ms: 50, label: "20×", title: "Fast (20 bars/s)" },
];

export default function PlaybackControls({
  state,
  controls,
  onFinish,
  onRetryHere,
  onUndo,
  onReset,
  canUndo,
}: Props) {
  const playing = state.status === "playing";
  return (
    <div className="replay-transport">
      <button className="transport-btn" title="Restart (R)" onClick={controls.restart}>
        ⟲
      </button>
      <button className="transport-btn" title="Step back (←)" onClick={() => controls.stepBack(1)}>
        ⏮
      </button>
      <button
        className="transport-btn play"
        title="Play / Pause (Space)"
        onClick={controls.toggle}
        disabled={state.status === "ended"}
      >
        {playing ? "⏸" : "▶"}
      </button>
      <button className="transport-btn" title="Step forward (→)" onClick={() => controls.stepForward(1)}>
        ⏭
      </button>
      <button className="transport-btn" title="Jump to next signal (N)" onClick={controls.jumpToNextSignal}>
        ⇥
      </button>

      {state.reviewing && (
        <>
          <button className="btn-inline" title="Return to live (End)" onClick={controls.jumpToLive}>
            Back to live
          </button>
          <button className="btn-inline" title="Discard later decisions and retry here" onClick={onRetryHere}>
            Retry here
          </button>
        </>
      )}

      <div className="speed-chips">
        {SPEEDS.map((s) => (
          <button
            key={s.ms}
            className={`speed-chip ${state.msPerBar === s.ms ? "active" : ""}`}
            title={s.title}
            onClick={() => controls.setSpeed(s.ms)}
          >
            {s.label}
          </button>
        ))}
      </div>

      <label className="autopause">
        <input
          type="checkbox"
          checked={state.autoPauseOnSignal}
          onChange={(e) => controls.setAutoPause(e.target.checked)}
        />
        Pause on signals
      </label>

      <button className="btn-inline finish" onClick={onFinish}>
        Finish &amp; score
      </button>
      <button className="btn-inline" disabled={!canUndo} onClick={onUndo}>
        Undo trade
      </button>
      <button className="btn-inline" onClick={onReset}>
        Reset
      </button>
    </div>
  );
}
