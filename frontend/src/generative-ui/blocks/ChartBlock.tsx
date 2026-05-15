import {
  ArcElement,
  BarElement,
  CategoryScale,
  Chart as ChartJS,
  Legend,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
} from "chart.js";
import { memo } from "react";
import { Bar, Line, Pie } from "react-chartjs-2";
import type { PresentationBlock } from "../../types";
import { isRecord } from "../presentationData";

type Chart = Extract<PresentationBlock, { type: "chart" }>;

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  ArcElement,
  Tooltip,
  Legend,
);

const COLORS = ["#059669", "#2563eb", "#7c3aed", "#d97706", "#0f766e", "#e11d48"];

export const ChartBlock = memo(function ChartBlock({ block, mode }: {
  block: Chart;
  mode: "inline" | "workspace";
}) {
  const labels = Array.isArray(block.labels) ? block.labels.map(display) : [];
  const series = Array.isArray(block.series)
    ? block.series.filter(isRecord).map((item) => ({
        name: display(item.name),
        values: Array.isArray(item.values)
          ? item.values.map((value) => typeof value === "number" && Number.isFinite(value) ? value : null)
          : [],
      }))
    : [];

  const horizontal = block.kind === "bar";
  const options: any = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    indexAxis: horizontal ? "y" : "x",
    plugins: {
      legend: {
        display: block.kind === "pie" || series.length > 1,
        position: "bottom",
        labels: {
          boxWidth: 8,
          boxHeight: 8,
          color: "#6b7280",
          padding: 18,
          usePointStyle: true,
        },
      },
    },
  };
  const height = block.kind === "bar"
    ? mode === "inline"
      ? Math.min(340, Math.max(190, labels.length * 28 + 50))
      : Math.min(900, Math.max(280, labels.length * 34 + 70))
    : mode === "inline"
      ? 208
      : 320;

  return (
    <section className={mode === "inline" ? "min-w-0 py-1" : "min-w-0 rounded-2xl border border-emerald-100 bg-white p-5 shadow-[0_8px_24px_rgba(15,23,42,0.04)] sm:p-6"}>
      {block.title && <h3 className={mode === "inline" ? "mb-3 text-sm font-semibold text-slate-800" : "mb-5 text-lg font-semibold tracking-[-0.01em] text-slate-950"}>{block.title}</h3>}
      <div style={{ height }} role="img" aria-label={block.title || `${block.kind} chart`}>
        {block.kind === "pie" ? (
          <Pie
            data={{
              labels,
              datasets: [{
                data: labels.map((_, index) => series[0]?.values[index] ?? 0),
                backgroundColor: labels.map((_, index) => COLORS[index % COLORS.length]),
                borderColor: "#ffffff",
                borderWidth: 2,
              }],
            }}
            options={options}
          />
        ) : block.kind === "line" ? (
          <Line data={chartData(labels, series)} options={{ ...options, scales: verticalScales() }} />
        ) : (
          <Bar data={chartData(labels, series)} options={{ ...options, scales: horizontalScales() }} />
        )}
      </div>
    </section>
  );
});

function verticalScales() {
  return {
    x: { grid: { display: false }, ticks: { color: "#6b7280" } },
    y: { beginAtZero: true, grid: { color: "#eef0f2" }, ticks: { color: "#6b7280" } },
  };
}

function horizontalScales() {
  return {
    x: { beginAtZero: true, grid: { color: "#eef0f2" }, ticks: { color: "#6b7280" } },
    y: { grid: { display: false }, ticks: { color: "#4b5563" } },
  };
}

function chartData(labels: string[], series: { name: string; values: (number | null)[] }[]) {
  return {
    labels,
    datasets: series.map((item, index) => ({
      label: item.name,
      data: item.values,
      backgroundColor: COLORS[index % COLORS.length],
      borderColor: COLORS[index % COLORS.length],
      borderRadius: 3,
      borderWidth: 1.5,
      tension: 0.3,
      pointRadius: 2,
    })),
  };
}

function display(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}
