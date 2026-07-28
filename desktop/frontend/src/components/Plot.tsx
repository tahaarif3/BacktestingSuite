import Plotly from "plotly.js-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";

const RawPlot = createPlotlyComponent(Plotly);

// Shared dark theme applied to every chart so the dashboard reads as one system.
const BASE_LAYOUT: Record<string, unknown> = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#cbd5e1", family: "Inter, Segoe UI, system-ui, sans-serif", size: 12 },
  margin: { l: 56, r: 24, t: 32, b: 40 },
  xaxis: { gridcolor: "#1e293b", zerolinecolor: "#1e293b" },
  yaxis: { gridcolor: "#1e293b", zerolinecolor: "#1e293b" },
  legend: { orientation: "h", y: 1.12, x: 0 },
  hovermode: "x unified",
};

export const PALETTE = {
  primary: "#38bdf8",
  benchmark: "#94a3b8",
  danger: "#f87171",
  success: "#34d399",
  accent: "#a78bfa",
  up: "#34d399",
  down: "#f87171",
};

interface PlotProps {
  data: Record<string, unknown>[];
  layout?: Record<string, unknown>;
  height?: number;
}

export default function Plot({ data, layout = {}, height = 320 }: PlotProps) {
  const merged = {
    ...BASE_LAYOUT,
    ...layout,
    xaxis: { ...(BASE_LAYOUT.xaxis as object), ...((layout.xaxis as object) ?? {}) },
    yaxis: { ...(BASE_LAYOUT.yaxis as object), ...((layout.yaxis as object) ?? {}) },
    autosize: true,
    height,
  };
  return (
    <RawPlot
      data={data}
      layout={merged}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: "100%", height }}
      useResizeHandler
    />
  );
}
