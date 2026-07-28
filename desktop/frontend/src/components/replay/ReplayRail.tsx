import type { RefObject } from "react";
import type { OrderSide, QtyMode, ReplayAccount, ReplayFill } from "../../types";
import SignalBanner from "./SignalBanner";
import OrderTicket, { type OrderTicketHandle } from "./OrderTicket";
import FillsList from "./FillsList";

export interface SignalNow {
  toSignal: number;
  kind: string;
  ohlc: { open: number; high: number; low: number; close: number };
  algoShares: number;
}

interface Props {
  barIndex: number;
  price: number;
  account: ReplayAccount | null;
  algoShares: number;
  signalNow: SignalNow | null;
  intraday: boolean;
  fills: ReplayFill[];
  disabled: boolean;
  disabledReason?: string;
  submitting: boolean;
  error: string | null;
  side: OrderSide;
  setSide: (s: OrderSide) => void;
  onSubmit: (o: { side: OrderSide; qty_mode: QtyMode; qty_value: number }) => void;
  onSkip: () => void;
  ticketRef: RefObject<OrderTicketHandle>;
}

export default function ReplayRail(props: Props) {
  return (
    <div className="replay-rail">
      {props.signalNow && (
        <SignalBanner
          toSignal={props.signalNow.toSignal}
          kind={props.signalNow.kind}
          ohlc={props.signalNow.ohlc}
          algoShares={props.signalNow.algoShares}
          price={props.price}
          onSkip={props.onSkip}
        />
      )}

      <div className="rail-section-title">Order ticket</div>
      <OrderTicket
        ref={props.ticketRef}
        barIndex={props.barIndex}
        price={props.price}
        account={props.account}
        algoShares={props.algoShares}
        disabled={props.disabled}
        disabledReason={props.disabledReason}
        submitting={props.submitting}
        error={props.error}
        side={props.side}
        setSide={props.setSide}
        onSubmit={props.onSubmit}
      />

      <div className="rail-section-title">Recent trades</div>
      <FillsList fills={props.fills} intraday={props.intraday} />
    </div>
  );
}
