import { useState } from "react";
import type { OptionStructureConfig } from "../../types";
import { usePortfolioSession } from "../../hooks/usePortfolioSession";
import { DEFAULT_OPTION_STRUCTURE } from "../options/OptionsConfig";
import PortfolioSetup from "./PortfolioSetup";
import PortfolioRunner from "./PortfolioRunner";
import PortfolioScoreboard from "./PortfolioScoreboard";

interface Props {
  active: boolean;
}

export default function PortfolioPanel({ active }: Props) {
  const session = usePortfolioSession();
  const [defaultStructure, setDefaultStructure] = useState<OptionStructureConfig>({
    ...DEFAULT_OPTION_STRUCTURE,
    structure_type: "bull_put_spread",
  });

  if (session.phase === "setup" || session.phase === "loading" || session.phase === "error") {
    return (
      <PortfolioSetup
        onStart={(cfg, struct) => {
          setDefaultStructure(struct);
          void session.start(cfg);
        }}
        loading={session.phase === "loading"}
        error={session.error}
      />
    );
  }

  if (session.phase === "scored" && session.score) {
    return (
      <PortfolioScoreboard
        score={session.score}
        onResume={session.backToRunning}
        onNewSession={session.close}
      />
    );
  }

  if (!session.created) return null;
  return (
    <div className="replay-wrap">
      <div className="replay-toolbar">
        <span className="hint">
          Portfolio replay · {session.created.symbols.length} symbols · SPY clock
        </span>
        <button className="btn-inline" onClick={session.close}>End session</button>
      </div>
      <PortfolioRunner session={session} created={session.created} defaultStructure={defaultStructure} active={active} />
    </div>
  );
}
