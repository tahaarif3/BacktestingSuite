declare module "plotly.js-dist-min" {
  interface PlotlyStatic {
    newPlot(el: HTMLElement, data: unknown[], layout?: unknown, config?: unknown): Promise<unknown>;
    react(el: HTMLElement, data: unknown[], layout?: unknown, config?: unknown): Promise<unknown>;
    relayout(el: HTMLElement, update: unknown): Promise<unknown>;
    restyle(el: HTMLElement, update: unknown, traces?: number[]): Promise<unknown>;
    purge(el: HTMLElement): void;
    Plots: { resize(el: HTMLElement): void };
  }
  const Plotly: PlotlyStatic;
  export default Plotly;
}

declare module "react-plotly.js/factory" {
  import type { ComponentType } from "react";
  const createPlotlyComponent: (plotly: unknown) => ComponentType<Record<string, unknown>>;
  export default createPlotlyComponent;
}
