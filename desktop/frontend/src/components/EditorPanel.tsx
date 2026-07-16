import { useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import "../monaco";
import { api } from "../api";

interface Props {
  // Called after save/delete so the Configure dropdown picks up registry changes.
  onStrategiesChanged: () => void;
}

export default function EditorPanel({ onStrategiesChanged }: Props) {
  const [files, setFiles] = useState<string[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [filename, setFilename] = useState("my_strategy");
  const [code, setCode] = useState("");
  const [template, setTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [names, tpl] = await Promise.all([
          api.listUserStrategies(),
          api.getUserStrategyTemplate(),
        ]);
        setFiles(names);
        setTemplate(tpl);
        if (names.length > 0) {
          await openFile(names[0]);
        } else {
          setCode(tpl);
        }
      } catch (e) {
        setError((e as Error).message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openFile = async (name: string) => {
    setError(null);
    setOk(null);
    if (!name) return;
    try {
      const f = await api.getUserStrategy(name);
      setSelected(name);
      setFilename(name.replace(/\.py$/, ""));
      setCode(f.code);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const newStrategy = () => {
    setSelected("");
    setFilename("my_strategy");
    setCode(template);
    setError(null);
    setOk(null);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      const res = await api.saveUserStrategy(filename, code);
      const names = await api.listUserStrategies();
      setFiles(names);
      setSelected(`${filename}.py`);
      setOk(
        `Saved and registered (${res.registered.join(", ") || "none"}). ` +
          "It now appears in the strategy dropdown — configure and run it from the sidebar."
      );
      onStrategiesChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      await api.deleteUserStrategy(selected);
      const names = await api.listUserStrategies();
      setFiles(names);
      setOk(`Deleted ${selected}.`);
      onStrategiesChanged();
      if (names.length > 0) await openFile(names[0]);
      else newStrategy();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="editor-toolbar">
        <div className="field" style={{ marginBottom: 0, minWidth: 200 }}>
          <label>Saved strategies</label>
          <select value={selected} onChange={(e) => openFile(e.target.value)}>
            <option value="">(new strategy)</option>
            {files.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>
        <div className="field" style={{ marginBottom: 0, minWidth: 180 }}>
          <label>Filename (.py)</label>
          <input
            value={filename}
            onChange={(e) => setFilename(e.target.value)}
            placeholder="my_strategy"
          />
        </div>
        <button className="btn btn-secondary" style={{ width: "auto" }} onClick={newStrategy}>
          New
        </button>
        <button
          className="btn btn-primary"
          style={{ width: "auto" }}
          disabled={busy || !filename.trim()}
          onClick={save}
        >
          {busy && <span className="spinner" />}
          Save &amp; Register
        </button>
        {selected && (
          <button
            className="btn btn-secondary"
            style={{ width: "auto", color: "var(--danger)" }}
            disabled={busy}
            onClick={remove}
          >
            Delete
          </button>
        )}
      </div>

      {error && <div className="error">{error}</div>}
      {ok && <div className="success">{ok}</div>}

      <div className="editor-wrap">
        <Editor
          height="68vh"
          language="python"
          theme="vs-dark"
          value={code}
          onChange={(v) => setCode(v ?? "")}
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 4,
          }}
        />
      </div>
      <div className="hint" style={{ marginTop: 8 }}>
        Subclass <code>strat.base.BaseStrategy</code> and implement{" "}
        <code>generate_signals(bars) → list[float]</code> (1.0 long / 0.0 flat / −1.0 short).
        Numeric <code>__init__</code> defaults become editable fields in the Configure panel;
        a <code>long_only</code> parameter enables the shorting toggle. Code is validated on a
        synthetic price series before it is saved.
      </div>
    </div>
  );
}
