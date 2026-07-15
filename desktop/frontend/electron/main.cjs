// Electron main process: spawns the Python FastAPI backend as a sidecar,
// waits for it to become healthy, then opens the React UI.
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");
const net = require("net");

const isDev = !app.isPackaged;
let backendProc = null;
let apiPort = 8765;

// Repo root relative to this file (desktop/frontend/electron -> repo root).
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");

function findFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => resolve(port));
    });
  });
}

function backendCommand(port) {
  if (isDev) {
    // Use the project virtualenv's Python to run the backend module.
    const py = process.platform === "win32"
      ? path.join(REPO_ROOT, ".venv", "Scripts", "python.exe")
      : path.join(REPO_ROOT, ".venv", "bin", "python");
    return {
      cmd: py,
      args: ["-m", "desktop.backend.main", "--port", String(port)],
      cwd: REPO_ROOT,
      env: process.env,
    };
  }
  // Production: bundled PyInstaller binary under resources/backend.
  const exe = process.platform === "win32" ? "BacktestApiServer.exe" : "BacktestApiServer";
  const binDir = path.join(process.resourcesPath, "backend");
  return {
    cmd: path.join(binDir, exe),
    args: ["--port", String(port)],
    cwd: binDir,
    env: { ...process.env, BACKTEST_REPO_ROOT: binDir },
  };
}

function startBackend(port) {
  const { cmd, args, cwd, env } = backendCommand(port);
  backendProc = spawn(cmd, args, { cwd, env });
  backendProc.stdout.on("data", (d) => process.stdout.write(`[backend] ${d}`));
  backendProc.stderr.on("data", (d) => process.stderr.write(`[backend] ${d}`));
  backendProc.on("exit", (code) => console.log(`[backend] exited with code ${code}`));
}

function waitForHealth(port, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get({ host: "127.0.0.1", port, path: "/health", timeout: 1500 }, (res) => {
        if (res.statusCode === 200) {
          res.resume();
          resolve();
        } else {
          res.resume();
          retry();
        }
      });
      req.on("error", retry);
      req.on("timeout", () => { req.destroy(); retry(); });
    };
    const retry = () => {
      if (Date.now() > deadline) reject(new Error("Backend health check timed out"));
      else setTimeout(attempt, 400);
    };
    attempt();
  });
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 960,
    minHeight: 640,
    backgroundColor: "#0f172a",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [`--api-port=${apiPort}`],
    },
  });

  if (isDev) {
    win.loadURL("http://127.0.0.1:5173");
    win.webContents.openDevTools({ mode: "detach" });
  } else {
    win.loadFile(path.join(__dirname, "..", "dist", "index.html"));
  }
}

app.whenReady().then(async () => {
  apiPort = await findFreePort();
  startBackend(apiPort);
  try {
    await waitForHealth(apiPort);
  } catch (e) {
    console.error(e);
  }
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

function shutdownBackend() {
  if (backendProc && !backendProc.killed) {
    backendProc.kill();
    backendProc = null;
  }
}

app.on("window-all-closed", () => {
  shutdownBackend();
  if (process.platform !== "darwin") app.quit();
});
app.on("before-quit", shutdownBackend);
process.on("exit", shutdownBackend);
