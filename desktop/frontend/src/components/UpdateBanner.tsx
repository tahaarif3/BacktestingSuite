import { useEffect, useState } from "react";
import type { UpdateEvent } from "../api";

// Listens for auto-update events from the main process and shows a small
// banner: download progress while fetching, then a "Restart to update" prompt
// once the new version is downloaded. Errors are logged, not shown.
export default function UpdateBanner() {
  const [state, setState] = useState<UpdateEvent | null>(null);

  useEffect(() => {
    return window.backtest?.onUpdateEvent?.((e) => {
      if (e.type === "error") {
        console.warn("[updater]", e.message);
        return;
      }
      if (e.type === "checking" || e.type === "none") {
        setState(null);
        return;
      }
      setState(e);
    });
  }, []);

  if (!state) return null;

  return (
    <div className="update-banner">
      {(state.type === "available" || state.type === "progress") && (
        <span>
          Downloading update
          {state.type === "available" ? ` ${state.version}` : ""}…
          {state.type === "progress" ? ` ${state.percent}%` : ""}
        </span>
      )}
      {state.type === "downloaded" && (
        <>
          <span>Update {state.version} is ready.</span>
          <button className="update-btn" onClick={() => window.backtest?.installUpdate?.()}>
            Restart to update
          </button>
          <button className="update-dismiss" onClick={() => setState(null)}>
            Later
          </button>
        </>
      )}
    </div>
  );
}
