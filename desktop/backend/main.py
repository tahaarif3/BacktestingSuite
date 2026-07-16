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
    FetchRequest,
    RobustnessRequest,
    SaveStrategyRequest,
)
from desktop.backend.services import (
    backtest_service,
    data_service,
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
        return data_service.fetch_ticker(req.ticker, req.start, req.end, req.interval)
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
