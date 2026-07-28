import { forwardRef, useImperativeHandle, useState } from "react";
import type { OrderSide, QtyMode, ReplayAccount } from "../../types";
import { usd } from "../../format";

export interface OrderTicketHandle {
  submit(): void;
}

interface Props {
  barIndex: number;
  price: number;
  account: ReplayAccount | null;
  algoShares: number;
  disabled: boolean;
  disabledReason?: string;
  submitting: boolean;
  error: string | null;
  // controlled from parent so keyboard shortcuts can preselect a side
  side: OrderSide;
  setSide: (s: OrderSide) => void;
  onSubmit: (o: { side: OrderSide; qty_mode: QtyMode; qty_value: number }) => void;
}

const OrderTicket = forwardRef<OrderTicketHandle, Props>(function OrderTicket(props, ref) {
  const { barIndex, price, account, algoShares, disabled, disabledReason, submitting, error, side, setSide, onSubmit } = props;
  const [qtyMode, setQtyMode] = useState<QtyMode>("shares");
  const [qty, setQty] = useState<number>(10);

  const previewShares =
    side === "close"
      ? -(account?.position ?? 0)
      : qtyMode === "shares"
        ? (side === "buy" ? 1 : -1) * qty
        : qtyMode === "fraction"
          ? ((side === "buy" ? 1 : -1) * qty * (account?.equity ?? 0)) / (price || 1)
          : (side === "buy" ? 1 : -1) * Math.abs(algoShares); // algo/algo_scaled approximate

  const cost = Math.abs(previewShares) * price;
  const cashAfter = (account?.cash ?? 0) - previewShares * price;

  const submit = () => {
    if (disabled || submitting) return;
    onSubmit({ side, qty_mode: side === "close" ? "shares" : qtyMode, qty_value: qty });
  };
  useImperativeHandle(ref, () => ({ submit }), [disabled, submitting, side, qtyMode, qty, onSubmit]);

  return (
    <div className="ticket">
      <div className="ticket-sides">
        {(["buy", "sell", "close"] as OrderSide[]).map((s) => (
          <button
            key={s}
            className={`side-btn ${s} ${side === s ? "active" : ""}`}
            onClick={() => setSide(s)}
            disabled={disabled}
          >
            {s === "buy" ? "Buy" : s === "sell" ? "Sell" : "Close"}
          </button>
        ))}
      </div>

      {side !== "close" && (
        <>
          <div className="qty-modes">
            {(["shares", "fraction", "algo"] as QtyMode[]).map((m) => (
              <button
                key={m}
                className={`qty-mode ${qtyMode === m ? "active" : ""}`}
                onClick={() => setQtyMode(m)}
                disabled={disabled}
              >
                {m === "shares" ? "Shares" : m === "fraction" ? "% equity" : "Match algo"}
              </button>
            ))}
          </div>

          {qtyMode !== "algo" ? (
            <div className="field">
              <label>{qtyMode === "shares" ? "Shares" : "Fraction of equity (0–1+)"}</label>
              <input
                type="number"
                step={qtyMode === "shares" ? 1 : 0.05}
                min={0}
                value={qty}
                disabled={disabled}
                onChange={(e) => setQty(parseFloat(e.target.value || "0"))}
              />
            </div>
          ) : (
            <div className="hint">Matches the algo's {algoShares.toFixed(1)} sh target.</div>
          )}
        </>
      )}

      <div className="ticket-preview">
        {side === "close" ? (
          <>Close {Math.abs(account?.position ?? 0).toFixed(2)} sh @ ~{usd(price)}</>
        ) : (
          <>
            {side === "buy" ? "Buy" : "Sell"} {Math.abs(previewShares).toFixed(2)} sh @ ~{usd(price)} = {usd(cost)}
            <br />
            <span className="hint">→ cash {usd(cashAfter)}</span>
          </>
        )}
      </div>

      {disabled && disabledReason && <div className="rail-chip">{disabledReason}</div>}
      {error && <div className="error">{error}</div>}

      <button className="btn btn-primary" disabled={disabled || submitting} onClick={submit}>
        {submitting && <span className="spinner" />}
        Confirm at bar {barIndex} (Enter)
      </button>
    </div>
  );
});

export default OrderTicket;
