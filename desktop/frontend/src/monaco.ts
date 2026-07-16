// Bundle Monaco locally (no CDN) so the editor works offline inside Electron.
// @monaco-editor/react loads from a CDN by default, which would fail in a
// packaged app without internet access.
import * as monaco from "monaco-editor";
import editorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import { loader } from "@monaco-editor/react";

// Python editing only needs the base editor worker (no TS/CSS/HTML services).
(self as unknown as { MonacoEnvironment: unknown }).MonacoEnvironment = {
  getWorker: () => new editorWorker(),
};

loader.config({ monaco });
