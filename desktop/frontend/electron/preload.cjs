// Exposes the backend base URL to the renderer. The port is injected by the
// main process via additionalArguments so it is known before the page loads.
const { contextBridge } = require("electron");

const portArg = process.argv.find((a) => a.startsWith("--api-port="));
const port = portArg ? portArg.split("=")[1] : "8765";

contextBridge.exposeInMainWorld("backtest", {
  baseUrl: `http://127.0.0.1:${port}`,
});
