import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import type {
  OptionPreview,
  OptionsAccount,
  OptionStructureConfig,
  OptionStructureMeta,
} from "../../types";
import { usd, dec } from "../../format";
import OptionsConfig, { DEFAULT_VOL } from "../options/OptionsConfig";
import PayoffDiagram from "../options/PayoffDiagram";

export interface OptionsTicketHandle {
  submit: () => void;
}

interface Props {
  barIndex: number;
  structures: OptionStructureMeta[];
  account: OptionsAccount | null;
  structureCfg: OptionStructureConfig;
  setStructureCfg: (c: OptionStructureConfig) => void;
  disabled: boolean;
  disabledReason?: string;
  submitting: boolean;
  error: string | null;
  previewOption: (barIndex: number, structure: OptionStructureConfig) => Promise<OptionPreview | null>;
  onOpen: (cfg: OptionStructureConfig) => void;
  onClose: (positionId: string) => void;
}

const OptionsRail = forwardRef<OptionsTicketHandle, Props>(function OptionsRail(props, ref) {
  const { barIndex, structures, account, structureCfg, setStructureCfg, disabled, disabledReason,
    submitting, error, previewOption, onOpen, onClose } = props;
  const [preview, setPreview] = useState<OptionPreview | null>(null);
  const [vol, setVol] = useState(DEFAULT_VOL);

  useImperativeHandle(ref, () => ({ submit: () => { if (!disabled) onOpen(structureCfg); } }));

  // Debounced preview whenever the structure / bar changes.
  useEffect(() => {
    let cancelled = false;
    const h = setTimeout(async () => {
      const p = await previewOption(barIndex, structureCfg);
      if (!cancelled) setPreview(p);
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(h);
    };
  }, [barIndex, structureCfg, previewOption]);

  const strikes = preview?.legs.map((l) => l.strike) ?? [];

  return (
    <div className="replay-rail">
      <div className="rail-section-title">Options ticket</div>

      <div className="opt-ticket">
        <OptionsConfig
          structures={structures}
          value={structureCfg}
          onChange={setStructureCfg}
          vol={vol}
          onVolChange={setVol}
        />

        {preview && (
          <div className="opt-preview">
            <div className="opt-legs">
              {preview.legs.map((l, i) => (
                <div key={i} className={`opt-leg-row ${l.action === "sell" ? "short" : "long"}`}>
                  <span>{l.action === "sell" ? "Sell" : "Buy"} {l.kind.toUpperCase()}</span>
                  <span>K {l.strike}</span>
                  <span>Δ {dec(l.delta)}</span>
                  <span>{usd(l.mark)}</span>
                </div>
              ))}
            </div>
            <div className="opt-preview-row">
              <span>Net {preview.net_is_credit ? "credit" : "debit"}</span>
              <span className={preview.net_is_credit ? "net-credit" : "net-debit"}>
                {usd(Math.abs(preview.net_price) * preview.multiplier * preview.contracts)}
              </span>
            </div>
            <div className="opt-preview-row">
              <span>Max profit</span><span>{preview.max_profit != null ? usd(preview.max_profit) : "∞"}</span>
            </div>
            <div className="opt-preview-row">
              <span>Max loss</span><span>{preview.max_loss != null ? usd(preview.max_loss) : "undefined"}</span>
            </div>
            <div className="opt-preview-row">
              <span>Breakeven</span><span>{preview.breakevens.map((b) => b.toFixed(2)).join(", ") || "—"}</span>
            </div>
            <PayoffDiagram
              payoff={preview.payoff}
              breakevens={preview.breakevens}
              spot={preview.spot}
              strikes={strikes}
              width={280}
              height={110}
            />
          </div>
        )}

        {error && <div className="error">{error}</div>}
        {disabled && disabledReason && <div className="rail-chip">{disabledReason}</div>}
        <button className="btn btn-primary" disabled={disabled || submitting} onClick={() => onOpen(structureCfg)}>
          {submitting && <span className="spinner" />}
          Open at bar {barIndex}
        </button>
      </div>

      <div className="rail-section-title">Open positions</div>
      <div className="opt-positions">
        {(!account || account.positions.length === 0) && <div className="hint">No open positions.</div>}
        {account?.positions.map((p) => (
          <div key={p.id} className="opt-position">
            <div className="opt-position-head">
              <span>{p.structure_type.replace(/_/g, " ")}</span>
              <span className={p.value >= 0 ? "net-credit" : "net-debit"}>{usd(p.value)}</span>
            </div>
            <div className="hint">
              {p.contracts}x · {p.dte_bars} DTE · Δ {dec(p.greeks.delta)} · Θ {usd(p.greeks.theta)}
              {p.max_risk != null ? ` · risk ${usd(p.max_risk)}` : ""}
            </div>
            <button className="btn btn-inline" disabled={disabled || submitting} onClick={() => onClose(p.id)}>
              Close
            </button>
          </div>
        ))}
      </div>
    </div>
  );
});

export default OptionsRail;
