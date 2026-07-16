// Exposes the backend base URL and app/update bridges to the renderer. The API
// port and app version are injected by the main process via additionalArguments
// so they are known before the page loads; everything else goes over IPC.
const { contextBridge, ipcRenderer } = require("electron");

function argOf(name, fallback) {
  const hit = process.argv.find((a) => a.startsWith(`--${name}=`));
  return hit ? hit.split("=")[1] : fallback;
}

contextBridge.exposeInMainWorld("backtest", {
  baseUrl: `http://127.0.0.1:${argOf("api-port", "8765")}`,
  appVersion: argOf("app-version", "dev"),
  platform: process.platform,
  onUpdateEvent: (cb) => {
    const listener = (_event, data) => cb(data);
    ipcRenderer.on("updater-event", listener);
    return () => ipcRenderer.removeListener("updater-event", listener);
  },
  checkForUpdates: () => ipcRenderer.invoke("check-for-updates"),
  installUpdate: () => ipcRenderer.invoke("install-update"),
  reportBug: () => ipcRenderer.invoke("report-bug"),
});
