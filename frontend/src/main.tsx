import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import * as echarts from "echarts";
import "./styles.css";
import { formatUkTime } from "./lib/time";

type Slot = {
  startTime: string;
  forecast_mw: number;
  actual_mw?: number;
  p10_error_mw?: number;
  p90_error_mw?: number;
  band_sample_count?: number;
  horizon_hours: number;
};
type Decision = {
  delivery_day: string;
  cutoff: string;
  slots: Slot[];
  metrics: Record<string, number | null>;
  buffer_mw: number | null;
  buffer_slot_start: string | null;
  method: string;
};
type Accuracy = {
  metrics: Record<string, number | null>;
  errors: any[];
  by_hour: any[];
  by_horizon: any[];
  by_wind: any[];
};
type Evolution = { points: any[] };
// Vite proxies `/api` in local development; the production container serves
// FastAPI and the static site from the same origin.
const API = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "/api" : "");

function Chart({ option }: { option: any }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [option]);
  return <div className="chart" ref={ref} />;
}
const fmt = (value?: number | null) =>
  value == null ? "n/a" : `${Math.round(value).toLocaleString()} MW`;
const day = (offset = 0) => {
  const d = new Date("2026-01-16T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + offset);
  return d.toISOString().slice(0, 10);
};
async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function App() {
  const [view, setView] = useState<
    "decision" | "accuracy" | "evolution" | "method"
  >("decision");
  const [deliveryDay, setDeliveryDay] = useState(day());
  const [cutoff, setCutoff] = useState("09:30");
  const [reveal, setReveal] = useState(false);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [accuracy, setAccuracy] = useState<Accuracy | null>(null);
  const [evolution, setEvolution] = useState<Evolution | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [demand, setDemand] = useState("");
  const demandMw = Number(demand) > 0 ? Number(demand) : null;
  const [hour, minute] = cutoff.split(":");
  useEffect(() => {
    setLoading(true);
    setError("");
    Promise.all([
      get<Decision>(
        `/decision?delivery_day=${deliveryDay}&cutoff_hour=${hour}&cutoff_minute=${minute}`,
      ),
      get<Accuracy>(`/accuracy?cutoff_hour=${hour}&cutoff_minute=${minute}`),
      get<Evolution>(`/evolution?delivery_day=${deliveryDay}`),
    ])
      .then(([d, a, e]) => {
        setDecision(d);
        setAccuracy(a);
        setEvolution(e);
      })
      .catch(() =>
        setError("Unable to load the snapshot. Start the API and try again."),
      )
      .finally(() => setLoading(false));
  }, [deliveryDay, cutoff]);
  const decisionOption = useMemo(
    () => ({
      tooltip: {
        trigger: "axis",
        formatter: (params: any[]) => {
          const slot = decision?.slots[params[0]?.dataIndex];
          if (!slot) return "";
          const p10 = slot.p10_error_mw == null ? null : slot.forecast_mw + slot.p10_error_mw;
          const p90 = slot.p90_error_mw == null ? null : slot.forecast_mw + slot.p90_error_mw;
          const buffer = slot.p10_error_mw == null ? null : Math.max(0, -slot.p10_error_mw);
          return [
            `<strong>Time (UK): ${formatUkTime(slot.startTime)}</strong>`,
            `Forecast: ${fmt(slot.forecast_mw)}`,
            ...(reveal ? [`Actual: ${fmt(slot.actual_mw)}`] : []),
            `P10: ${fmt(p10)}`,
            `P90: ${fmt(p90)}`,
            `Buffer: ${fmt(buffer)}`,
          ].join("<br/>");
        },
      },
      legend: {
        data: ["Forecast", "P10–P90 band", ...(reveal ? ["Actual"] : [])],
      },
      grid: { left: 55, right: 24, top: 48, bottom: 72 },
      dataZoom: [{ type: "inside" }, { type: "slider" }],
      xAxis: {
        type: "category",
        data: decision?.slots.map((s) =>
          formatUkTime(s.startTime),
        ),
      },
      yAxis: { type: "value", name: "MW" },
      series: [
        {
          name: "P10–P90 band",
          type: "line",
          stack: "band",
          symbol: "none",
          tooltip: { show: false },
          lineStyle: { opacity: 0 },
          data: decision?.slots.map((s) =>
            s.p10_error_mw == null ? 0 : s.forecast_mw + s.p10_error_mw,
          ),
        },
        {
          name: "P10–P90 band",
          type: "line",
          stack: "band",
          symbol: "none",
          areaStyle: { color: "#8b5cf6", opacity: 0.16 },
          lineStyle: { opacity: 0 },
          itemStyle: { color: "#8b5cf6" },
          tooltip: { show: false },
          data: decision?.slots.map((s) =>
            s.p90_error_mw == null || s.p10_error_mw == null
              ? 0
              : s.p90_error_mw - s.p10_error_mw,
          ),
        },
        {
          name: "Forecast",
          type: "line",
          step: "start",
          smooth: false,
          data: decision?.slots.map((s) => s.forecast_mw),
          lineStyle: { color: "#2563eb", width: 3 },
          itemStyle: { color: "#2563eb" },
        },
        ...(reveal
          ? [
              {
                name: "Actual",
                type: "line",
                smooth: false,
                data: decision?.slots.map((s) => s.actual_mw),
                lineStyle: { color: "#1f2937", width: 2 },
                itemStyle: { color: "#1f2937" },
              },
            ]
          : []),
        ...(demandMw
          ? [{ name: "Demand input", type: "line", symbol: "none", data: decision?.slots.map(() => demandMw), lineStyle: { color: "#d97706", type: "dashed", width: 2 }, tooltip: { show: false } }]
          : []),
      ],
    }),
    [decision, demandMw, reveal],
  );
  const accuracyOption = useMemo(
    () => ({
      tooltip: {},
      grid: { left: 55, right: 20, top: 25, bottom: 40 },
      xAxis: {
        type: "category",
        data: accuracy?.by_hour.map((x) => `${x.hour}:00`),
      },
      yAxis: { type: "value", name: "MAE (MW)" },
      series: [
        {
          type: "bar",
          data: accuracy?.by_hour.map((x) => Math.round(x.mae_mw)),
          itemStyle: { color: "#6d5dfc", borderRadius: [5, 5, 0, 0] },
        },
      ],
    }),
    [accuracy],
  );
  const evolutionOption = useMemo(
    () => ({
      tooltip: { trigger: "axis" },
      grid: { left: 55, right: 20, top: 30, bottom: 48 },
      xAxis: {
        type: "category",
        data: evolution?.points.map(
          (x) => formatUkTime(x.startTime),
        ),
      },
      yAxis: { type: "value", name: "MW" },
      series: [
        {
          name: "Forecast publications",
          type: "scatter",
          data: evolution?.points.map((x) => [
            formatUkTime(x.startTime),
            x.forecast_mw,
          ]),
          symbolSize: 5,
          itemStyle: { color: "#6d5dfc", opacity: 0.32 },
        },
        {
          name: "Actual",
          type: "line",
          data: evolution?.points
            .filter(
              (x: any, i: number, a: any[]) =>
                a.findIndex((y) => y.startTime === x.startTime) === i,
            )
            .map((x) => x.actual_mw),
          lineStyle: { color: "#19b38a", width: 3 },
        },
      ],
    }),
    [evolution],
  );
  const buffer = decision?.buffer_mw;
  const bufferTime = formatUkTime(decision?.buffer_slot_start);
  const bandSampleCount =
    decision?.slots.find((slot) => slot.band_sample_count)?.band_sample_count ?? 0;
  const hasBand = buffer != null;
  const slotGaps =
    decision?.slots.map((slot) => Math.max(0, (demandMw ?? 0) - slot.forecast_mw)) ?? [];
  const riskAdjustedGaps =
    decision?.slots.map((slot) =>
      slot.p10_error_mw == null || demandMw == null
        ? null
        : Math.max(0, demandMw - (slot.forecast_mw + slot.p10_error_mw)),
    ) ?? [];
  return (
    <main>
      <aside>
        <div className="brand">
          grid<span>bricks</span>
          <small>WIND FORECAST DECISION DESK</small>
        </div>
        {[
          ["decision", "Decision desk"],
          ["accuracy", "Accuracy"],
          ["evolution", "Forecast evolution"],
          ["method", "Methodology"],
        ].map(([id, label]) => (
          <button
            className={view === id ? "active" : ""}
            onClick={() => setView(id as any)}
            key={id}
          >
            {label}
          </button>
        ))}
        <div className="side-note">
          January 2026
          <br />
          Elexon-only snapshot
        </div>
      </aside>
      <section className="content">
        <header>
          <div>
            <p className="eyebrow">DAY-AHEAD PROCUREMENT</p>
            <h1>
              {view === "decision"
                ? "Wind you could count on"
                : view === "accuracy"
                  ? "How wrong is it, usually?"
                  : view === "evolution"
                    ? "How the forecast moved"
                    : "Methodology & limits"}
            </h1>
          </div>
          <div className="controls">
            <label>
              Delivery day
              <input
                type="date"
                min="2026-01-01"
                max="2026-01-31"
                value={deliveryDay}
                onChange={(e) => setDeliveryDay(e.target.value)}
              />
            </label>
            <label>
              Decision cutoff
              <input
                type="time"
                value={cutoff}
                onChange={(e) => setCutoff(e.target.value)}
              />
            </label>
          </div>
        </header>
        {loading && <p className="status">Loading decision snapshot…</p>}
        {error && <p className="error">{error}</p>}
        {view === "decision" && decision && (
          <>
            <div className="kpis">
              <div>
                <small>FORECAST MAE</small>
                <strong>{fmt(decision.metrics.mae_mw)}</strong>
              </div>
              <div>
                <small>BIAS</small>
                <strong>{fmt(decision.metrics.bias_mw)}</strong>
              </div>
              <div>
                <small>90% BUFFER (WORST SLOT)</small>
                <strong>{hasBand ? fmt(buffer) : "n/a – insufficient history"}</strong>
                {hasBand && <em>at {bufferTime} UK</em>}
              </div>
              <div>
                <small>HEADLINE HORIZON</small>
                <strong>
                  {Math.round(decision.slots[0]?.horizon_hours || 0)} h
                </strong>
              </div>
            </div>
            <div className="card">
              <div className="card-head">
                <div>
                  <h2>{deliveryDay} availability</h2>
                  <p>Latest forecast published by {cutoff} UK time on D-1.</p>
                </div>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={reveal}
                    onChange={(e) => setReveal(e.target.checked)}
                  />{" "}
                  Reveal actuals
                </label>
              </div>
              <Chart option={decisionOption} />
              <p className="chart-note">
                Forecast is hourly and held across two half-hours; not interpolated.
              </p>
              <p className="chart-note">
                {hasBand
                  ? `Uncertainty band sample count: ${bandSampleCount}`
                  : "Insufficient history for uncertainty band"}
              </p>
            </div>
            <div className="action">
              <b>Purchasing action</b>
              <span>
                {hasBand ? (
                  <>
                    To be 90% covered, hold up to <strong>{fmt(buffer)}</strong> of extra thermal
                    cover (worst slot, {bufferTime}) on top of the forecast thermal gap.
                  </>
                ) : (
                  "n/a – insufficient history for a 90% thermal-cover buffer."
                )}
              </span>
            </div>
            <div className="card demand">
              <div>
                <h2>Optional demand what-if</h2>
                <p>
                  Enter a total demand MW profile to see the forecast thermal
                  gap. No demand data is invented.
                </p>
              </div>
              <input
                placeholder="35000"
                value={demand}
                onChange={(e) => setDemand(e.target.value)}
              />
              {demandMw && (
                <div className="demand-results">
                  <strong>
                    Average thermal gap: {fmt(slotGaps.reduce((sum, gap) => sum + gap, 0) / slotGaps.length)}
                  </strong>
                  <strong>Peak thermal gap: {fmt(Math.max(...slotGaps))}</strong>
                  <strong>
                    Risk-adjusted peak gap:{" "}
                    {riskAdjustedGaps.some((gap) => gap != null)
                      ? fmt(Math.max(...riskAdjustedGaps.filter((gap): gap is number => gap != null)))
                      : "n/a – insufficient history"}
                  </strong>
                </div>
              )}
            </div>
          </>
        )}
        {view === "accuracy" && accuracy && (
          <>
            <div className="kpis">
              <div>
                <small>MAE</small>
                <strong>{fmt(accuracy.metrics.mae_mw)}</strong>
              </div>
              <div>
                <small>RMSE</small>
                <strong>{fmt(accuracy.metrics.rmse_mw)}</strong>
              </div>
              <div>
                <small>BIAS</small>
                <strong>{fmt(accuracy.metrics.bias_mw)}</strong>
              </div>
              <div>
                <small>NORMALIZED MAE</small>
                <strong>
                  {((accuracy.metrics.nmae || 0) * 100).toFixed(1)}%
                </strong>
              </div>
            </div>
            <div className="card">
              <h2>Error by hour of day</h2>
              <Chart option={accuracyOption} />
            </div>
          </>
        )}
        {view === "evolution" && evolution && (
          <div className="card">
            <h2>Successive publications vs actual</h2>
            <p>
              Each violet point is a forecast publication for a target hour; the
              green line is realised wind.
            </p>
            <Chart option={evolutionOption} />
          </div>
        )}
        {view === "method" && (
          <div className="method">
            <h2>Leakage-safe by design</h2>
            <p>
              For each target time, the desk chooses the latest WINDFOR
              publication at or before the D-1 decision cutoff. It never uses a
              later forecast in metrics or bands.
            </p>
            <h3>Uncertainty</h3>
            <p>
              P10–P90 bands use fully observed delivery days through D−2 only:
              D−1 is incomplete at the decision time. A negative error is a wind
              shortfall, so the procurement buffer is max(0, −P10 error).
            </p>
            <h3>Data limits</h3>
            <p>
              FUELHH is half-hourly while WINDFOR targets are hourly. The source
              forecast is carried across the two matching half-hours. The app
              uses no demand, capacity, weather, or market-price data.
            </p>
          </div>
        )}
      </section>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
