"""Blind chart-replay export for completed breakout signals."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Dict, Iterable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from intraday_breakout.pilot import NY_TZ, normalize_ohlcv


def _candles(ax, frame: pd.DataFrame) -> None:
    d = frame.tail(180)
    for x, (_, b) in enumerate(d.iterrows()):
        color = "#18864b" if b["close"] >= b["open"] else "#c43c35"
        ax.vlines(x, b["low"], b["high"], color=color, linewidth=0.65)
        bottom = min(b["open"], b["close"])
        height = max(abs(b["close"] - b["open"]), 1e-6)
        ax.add_patch(plt.Rectangle((x - 0.32, bottom), 0.64, height, color=color, alpha=0.85))
    ax.set_xlim(-1, len(d))
    ticks = np.linspace(0, max(0, len(d) - 1), min(6, len(d)), dtype=int)
    if len(d):
        ax.set_xticks(ticks, [d.index[i].strftime("%Y-%m-%d") for i in ticks], rotation=20, ha="right")


def export_blind_replay(
    signals: pd.DataFrame,
    daily_by_symbol: Dict[str, pd.DataFrame],
    minute_by_symbol: Dict[str, pd.DataFrame],
    spy_minute: pd.DataFrame,
    output_dir: Path,
    *,
    seed: int = 75,
) -> Path:
    """Create cutoff-correct charts and an HTML decision form with no outcomes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    assets = output_dir / "assets"
    assets.mkdir(exist_ok=True)
    sm = normalize_ohlcv(spy_minute, intraday=True)
    cards = []
    shuffled = signals.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    for display_no, row in shuffled.iterrows():
        ticker = str(row["ticker"])
        day = pd.Timestamp(row["date"]).date()
        signal_id = str(row.get("signal_id", f"{ticker}_{day}"))
        daily = normalize_ohlcv(daily_by_symbol[ticker])
        daily = daily[daily.index.date < day]
        minute = normalize_ohlcv(minute_by_symbol[ticker], intraday=True)
        cutoff = pd.Timestamp.combine(day, pd.Timestamp("09:34").time()).tz_localize(NY_TZ)
        start = pd.Timestamp.combine(day, pd.Timestamp("04:00").time()).tz_localize(NY_TZ)
        intra = minute[(minute.index >= start) & (minute.index <= cutoff)]
        spy = sm[(sm.index >= start) & (sm.index <= cutoff)]

        fig, axes = plt.subplots(2, 1, figsize=(11, 7), constrained_layout=True)
        _candles(axes[0], daily)
        axes[0].axhspan(float(row["level_lower"]), float(row["level_upper"]), color="#d99721", alpha=0.22)
        axes[0].axhline(float(row["level_center"]), color="#d99721", linewidth=1)
        axes[0].set_title(f"Daily chart through {day - pd.Timedelta(days=1)} — candidate #{display_no + 1}")
        axes[0].set_ylabel("Price")
        if not intra.empty:
            rel = intra["close"] / intra["close"].iloc[0]
            axes[1].plot(intra.index, rel, label="Stock", color="#2468b4")
        if not spy.empty:
            srel = spy["close"] / spy["close"].iloc[0]
            axes[1].plot(spy.index, srel, label="SPY", color="#555", alpha=0.8)
        axes[1].axvline(pd.Timestamp.combine(day, pd.Timestamp("09:30").time()).tz_localize(NY_TZ), color="#c43c35", linestyle="--")
        axes[1].set_title("Extended-hours relative path through 9:34 ET (future hidden)")
        axes[1].set_ylabel("Normalized price")
        axes[1].legend(loc="best")
        fig.suptitle("Blind psychological-breakout review", fontsize=14)
        path = assets / f"{display_no + 1:04d}.png"
        fig.savefig(path, dpi=130)
        plt.close(fig)
        cards.append({"n": display_no + 1, "signal_id": signal_id, "image": f"assets/{path.name}"})

    payload = json.dumps(cards)
    doc = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Blind Breakout Replay</title>
<style>body{{font:16px system-ui;max-width:1180px;margin:24px auto;background:#f5f6f8;color:#17202a}}.card{{background:white;padding:18px;margin:18px 0;border-radius:10px;box-shadow:0 1px 5px #bbb}}img{{width:100%}}label{{margin-right:18px}}textarea{{width:100%;height:55px}}button{{padding:10px 16px;margin:8px}}</style></head>
<body><h1>Blind psychological-breakout replay</h1>
<p>Charts stop at 9:34 ET. Record the decision before opening the separate answer key. Tickers and dates are deliberately hidden; candidate order is randomized.</p>
<div id="cards"></div><button onclick="download()">Export decisions CSV</button>
<script>const cards={payload}; const root=document.getElementById('cards');
function key(c){{return 'blind_'+c.signal_id}}
function save(c){{const el=document.getElementById('c'+c.n);const v={{signal_id:c.signal_id,display_no:c.n,decision:el.querySelector('input:checked')?.value||'',notes:el.querySelector('textarea').value}};localStorage.setItem(key(c),JSON.stringify(v));}}
cards.forEach(c=>{{const d=document.createElement('div');d.className='card';d.id='c'+c.n;d.innerHTML=`<h2>Candidate #${{c.n}}</h2><img src="${{c.image}}"><p><label><input type="radio" name="d${{c.n}}" value="take"> Take</label><label><input type="radio" name="d${{c.n}}" value="pass"> Pass</label><label><input type="radio" name="d${{c.n}}" value="uncertain"> Uncertain</label></p><textarea placeholder="Level, entry, stop, target, and reasoning"></textarea>`;root.appendChild(d);d.querySelectorAll('input,textarea').forEach(x=>x.onchange=()=>save(c));const old=JSON.parse(localStorage.getItem(key(c))||'null');if(old){{const radio=d.querySelector(`input[value="${{old.decision}}"]`);if(radio)radio.checked=true;d.querySelector('textarea').value=old.notes||'';}}}});
function download(){{const rows=[['signal_id','display_no','decision','notes']];cards.forEach(c=>{{const v=JSON.parse(localStorage.getItem(key(c))||'null')||{{signal_id:c.signal_id,display_no:c.n,decision:'',notes:''}};rows.push([v.signal_id,v.display_no,v.decision,v.notes]);}});const esc=x=>'"'+String(x).replaceAll('"','""')+'"';const blob=new Blob([rows.map(r=>r.map(esc).join(',')).join('\n')],{{type:'text/csv'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='blind_replay_decisions.csv';a.click();}}
</script></body></html>"""
    index = output_dir / "index.html"
    index.write_text(doc, encoding="utf-8")
    return index
