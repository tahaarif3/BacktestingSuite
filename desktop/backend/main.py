"""FastAPI backend for the BacktestingSuite desktop app.

Runs as a localhost sidecar spawned by the Electron main process. Imports the
existing suite engine directly. Start with:

    python -m desktop.backend.main --port 8765
"""

import argparse

# paths must be imported first so the repo root is on sys.path before suite imports.
from desktop.backend import paths  # noqa: F401

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from desktop.backend.schemas import (
    BacktestConfig,
    CompareRequest,
    CreateReplaySessionRequest,
    FetchRequest,
    OptionPreviewRequest,
    ReplayOptionOrderRequest,
    ReplayOrderRequest,
    RewindRequest,
    RobustnessRequest,
    SaveStrategyRequest,
    SeekRequest,
    TickerValidateRequest,
)
from desktop.backend.services import (
    backtest_service,
    data_service,
    market_meta,
    replay_service,
    robustness_service,
    strategy_editor_service,
)

from strategy_registry import list_strategies, list_sizers

app = FastAPI(title="BacktestingSuite API", version="1.0.0")

# Permissive CORS: this is a local, single-user desktop app.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/strategies")
def get_strategies():
    return {"strategies": list_strategies()}


@app.get("/api/sizers")
def get_sizers():
    return {"sizers": list_sizers()}


@app.get("/api/data/list")
def get_data_list():
    return {"files": data_service.list_data_files()}


@app.post("/api/data/fetch")
def post_data_fetch(req: FetchRequest):
    try:
        return data_service.fetch_ticker(
            req.ticker, req.start, req.end, req.interval, merge=req.merge, refresh=req.refresh
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/backtest/run")
def post_backtest_run(config: BacktestConfig):
    try:
        return backtest_service.run_backtest(config)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/backtest/report", response_class=HTMLResponse)
def post_backtest_report(config: BacktestConfig):
    try:
        return HTMLResponse(content=backtest_service.generate_report(config))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/robustness/run")
def post_robustness_run(req: RobustnessRequest):
    try:
        return robustness_service.run_robustness(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/compare")
def post_compare(req: CompareRequest):
    try:
        return robustness_service.compare(req)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- User strategy editor ---------------------------------------------------
# NOTE: /template must be declared before /{name} so it isn't captured by it.

@app.get("/api/user-strategies")
def list_user_strategies():
    return {"files": strategy_editor_service.list_files()}


@app.get("/api/user-strategies/template")
def get_user_strategy_template():
    return {"code": strategy_editor_service.TEMPLATE}


@app.get("/api/user-strategies/{name}")
def get_user_strategy(name: str):
    try:
        return {"name": name, "code": strategy_editor_service.get_code(name)}
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/user-strategies")
def save_user_strategy(req: SaveStrategyRequest):
    try:
        ids = strategy_editor_service.save(req.filename, req.code)
        return {"ok": True, "registered": ids}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/user-strategies/{name}")
def delete_user_strategy(name: str):
    try:
        ids = strategy_editor_service.delete(name)
        return {"ok": True, "registered": ids}
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Market metadata & ticker lookup ---------------------------------------


@app.get("/api/data/intervals")
def get_intervals():
    return {"intervals": market_meta.list_intervals()}


@app.post("/api/data/validate")
def post_data_validate(req: TickerValidateRequest):
    try:
        return market_meta.validate_ticker(req.ticker, req.interval, req.start, req.end)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/data/search")
def get_data_search(q: str, limit: int = 10):
    try:
        return {"results": market_meta.search_tickers(q, limit)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- Options metadata -------------------------------------------------------


@app.get("/api/options/structures")
def get_option_structures():
    from options.structures import CATALOG
    return {"structures": CATALOG}


# --- Replay / manual trading ------------------------------------------------
# NOTE: /orders/undo must be declared before /orders/{order_id} so "undo" isn't
# captured as an order id.


@app.post("/api/replay/sessions")
def post_replay_session(req: CreateReplaySessionRequest):
    try:
        return replay_service.create_session(req)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.SessionTooLarge as e:
        raise HTTPException(status_code=413, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/replay/sessions")
def list_replay_sessions():
    return {"sessions": replay_service.list_sessions()}


@app.get("/api/replay/sessions/{sid}")
def get_replay_session(sid: str):
    try:
        return replay_service.get_state(sid)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.SessionStale as e:
        raise HTTPException(status_code=410, detail=str(e))


@app.get("/api/replay/sessions/{sid}/reference")
def get_replay_reference(sid: str):
    try:
        return replay_service.reference_series(sid)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.SessionStale as e:
        raise HTTPException(status_code=410, detail=str(e))


@app.get("/api/replay/sessions/{sid}/bars")
def get_replay_bars(sid: str, start: int = 0, count: int = replay_service.DEFAULT_BAR_CHUNK):
    try:
        return replay_service.get_bars(sid, start, count)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except IndexError as e:
        raise HTTPException(status_code=416, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/replay/sessions/{sid}/orders")
def post_replay_order(sid: str, req: ReplayOrderRequest):
    try:
        return replay_service.submit_order(sid, req)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.SessionStale as e:
        raise HTTPException(status_code=410, detail=str(e))
    except replay_service.OrderRejected as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/replay/sessions/{sid}/options/preview")
def post_replay_option_preview(sid: str, req: OptionPreviewRequest):
    try:
        return replay_service.preview_option(sid, req)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.SessionStale as e:
        raise HTTPException(status_code=410, detail=str(e))
    except replay_service.OrderRejected as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/replay/sessions/{sid}/options/orders")
def post_replay_option_order(sid: str, req: ReplayOptionOrderRequest):
    try:
        return replay_service.submit_option_order(sid, req)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.SessionStale as e:
        raise HTTPException(status_code=410, detail=str(e))
    except replay_service.OrderRejected as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/replay/sessions/{sid}/orders/undo")
def post_replay_undo(sid: str):
    try:
        return replay_service.undo_last_order(sid)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.OrderRejected as e:
        raise HTTPException(status_code=409, detail=str(e))


@app.delete("/api/replay/sessions/{sid}/orders/{order_id}")
def delete_replay_order(sid: str, order_id: str):
    try:
        return replay_service.delete_order(sid, order_id)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/replay/sessions/{sid}/seek")
def post_replay_seek(sid: str, req: SeekRequest):
    try:
        return replay_service.seek(sid, req.to_index)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.SessionStale as e:
        raise HTTPException(status_code=410, detail=str(e))


@app.post("/api/replay/sessions/{sid}/rewind")
def post_replay_rewind(sid: str, req: RewindRequest):
    try:
        return replay_service.rewind(sid, req.to_index, req.confirm_discard_orders)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.OrderRejected as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/replay/sessions/{sid}/reset")
def post_replay_reset(sid: str):
    try:
        return replay_service.reset(sid)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/replay/sessions/{sid}/score")
def get_replay_score(sid: str, upto: int = None):
    try:
        return replay_service.score(sid, upto)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.SessionStale as e:
        raise HTTPException(status_code=410, detail=str(e))


@app.get("/api/replay/sessions/{sid}/journal")
def get_replay_journal(sid: str, upto: int = None):
    try:
        return replay_service.journal(sid, upto)
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except replay_service.SessionStale as e:
        raise HTTPException(status_code=410, detail=str(e))


@app.delete("/api/replay/sessions/{sid}")
def delete_replay_session(sid: str):
    try:
        replay_service.delete_session(sid)
        return {"ok": True}
    except replay_service.SessionNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))


def main():
    parser = argparse.ArgumentParser(description="BacktestingSuite API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    # Signal readiness on stdout so the Electron launcher can detect the port.
    print(f"BACKTEST_API_LISTENING http://{args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
