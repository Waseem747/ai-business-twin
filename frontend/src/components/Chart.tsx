import { useEffect, useMemo, useRef } from "react";
import Plotly from "plotly.js-basic-dist-min";
import { useTheme } from "../lib/theme";

interface ChartProps {
  data: any[];
  layout?: Record<string, any>;
  height?: number;
  className?: string;
  config?: Record<string, any>;
}

export function Chart({ data, layout = {}, height = 300, className = "", config = {} }: ChartProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const { theme } = useTheme();

  const resolvedLayout = useMemo(() => {
    const dark = theme === "dark";
    return {
      height,
      autosize: true,
      margin: { l: 52, r: 20, t: 16, b: 42 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: "DM Sans, sans-serif", size: 11, color: dark ? "#9FB0C7" : "#68778C" },
      hoverlabel: {
        bgcolor: dark ? "#142338" : "#0E1B2E",
        bordercolor: "transparent",
        font: { family: "DM Sans, sans-serif", size: 12, color: "#F5F8FC" },
      },
      xaxis: {
        gridcolor: dark ? "#1B2B40" : "#EDF1F6",
        zerolinecolor: dark ? "#29405C" : "#DCE3EC",
        linecolor: dark ? "#29405C" : "#DCE3EC",
        tickfont: { size: 10 },
        ...(layout.xaxis || {}),
      },
      yaxis: {
        gridcolor: dark ? "#1B2B40" : "#EDF1F6",
        zerolinecolor: dark ? "#29405C" : "#DCE3EC",
        linecolor: dark ? "#29405C" : "#DCE3EC",
        tickfont: { size: 10 },
        ...(layout.yaxis || {}),
      },
      legend: {
        orientation: "h",
        y: 1.12,
        x: 0,
        font: { size: 10 },
        bgcolor: "rgba(0,0,0,0)",
        ...(layout.legend || {}),
      },
      ...layout,
    };
  }, [layout, theme, height]);

  useEffect(() => {
    if (!ref.current) return;
    const node = ref.current;
    Plotly.newPlot(node, data, resolvedLayout, {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d", "toggleSpikelines"],
      ...config,
    });
    const resize = () => Plotly.Plots.resize(node);
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      Plotly.purge(node);
    };
  }, [data, resolvedLayout, config]);

  return <div ref={ref} className={`chart ${className}`} style={{ minHeight: height }} />;
}
