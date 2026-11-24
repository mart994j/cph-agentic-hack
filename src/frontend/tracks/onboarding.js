// Passenger onboarding track. Guide: docs/track-1-passenger-onboarding.md
import { api, chartPalette, cssVar, renderPlaceholder } from "../app.js";

let kpiRefreshStarted = false;

function localTime(iso) {
  return new Date(iso).toLocaleTimeString("en-GB", {
    timeZone: "Europe/Copenhagen",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function waitStatus(minutes) {
  if (minutes > 20) return { className: "heatmap-cell--critical", label: "critical" };
  if (minutes >= 10) return { className: "heatmap-cell--warn", label: "warn" };
  return { className: "heatmap-cell--ok", label: "ok" };
}

function renderHeatmap(container, rows) {
  const slots = [...new Set(rows.map((row) => row.slot_start))].sort();
  const keys = [];
  for (const terminal of ["T2", "T3"]) {
    for (const checkpoint of ["CHECKIN", "SECURITY", "PASSPORT"]) {
      keys.push({ terminal, checkpoint });
    }
  }

  const table = document.createElement("table");
  table.className = "heatmap";
  table.caption = null;
  const caption = document.createElement("caption");
  caption.className = "visually-hidden";
  caption.textContent = "Passenger wait minutes by terminal, checkpoint, and 15-minute slot";
  table.append(caption);

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const label of ["Terminal · checkpoint", ...slots.map(localTime)]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = label;
    headerRow.append(th);
  }
  thead.append(headerRow);
  table.append(thead);

  const tbody = document.createElement("tbody");
  for (const key of keys) {
    const row = document.createElement("tr");
    const heading = document.createElement("th");
    heading.scope = "row";
    heading.textContent = `${key.terminal} · ${key.checkpoint}`;
    row.append(heading);

    for (const slot of slots) {
      const data = rows.find((item) =>
        item.terminal === key.terminal &&
        item.checkpoint === key.checkpoint &&
        item.slot_start === slot
      );
      const cell = document.createElement("td");
      if (data) {
        const minutes = Math.round(data.avg_wait_min);
        const status = waitStatus(minutes);
        cell.className = `heatmap-cell ${status.className}`;
        cell.textContent = String(minutes);
        cell.setAttribute("aria-label", `${key.terminal} ${key.checkpoint}, ${localTime(slot)}, ${minutes} minutes, ${status.label}`);
        cell.title = `${minutes} min · ${status.label}`;
      } else {
        cell.textContent = "—";
        cell.setAttribute("aria-label", `${key.terminal} ${key.checkpoint}, ${localTime(slot)}, no data`);
      }
      row.append(cell);
    }
    tbody.append(row);
  }
  table.append(tbody);

  const wrap = document.createElement("div");
  wrap.className = "heatmap-wrap";
  wrap.setAttribute("role", "region");
  wrap.setAttribute("aria-label", "Queue wait heatmap");
  wrap.tabIndex = 0;
  wrap.append(table);
  container.append(wrap);
}

function renderForecast(container, forecasts) {
  const security = forecasts.filter((row) => row.checkpoint === "SECURITY");
  const labels = [...new Set(security
    .filter((row) => row.terminal === "T2")
    .map((row) => row.slot_start))]
    .sort()
    .map(localTime);
  const palette = chartPalette();

  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-label", "Security wait forecast for terminals T2 and T3 over the next three hours");
  canvas.setAttribute("role", "img");

  const caption = document.createElement("p");
  caption.className = "chip chip--info";
  caption.textContent = "Now → next 3 hours";

  const wrap = document.createElement("div");
  wrap.className = "forecast-chart-wrap";
  const chartContainer = document.createElement("div");
  chartContainer.className = "forecast-chart-container";
  chartContainer.append(canvas);
  wrap.append(chartContainer, caption);
  container.append(wrap);

  if (!window.Chart) return;
  const nowMarker = {
    id: "nowMarker",
    beforeDraw(chart) {
      if (!chart.scales.x) return;
      const context = chart.ctx;
      const x = chart.scales.x.getPixelForValue(0);
      context.save();
      context.strokeStyle = cssVar("--status-warn");
      context.lineWidth = 2;
      context.setLineDash([6, 4]);
      context.beginPath();
      context.moveTo(x, chart.chartArea.top);
      context.lineTo(x, chart.chartArea.bottom);
      context.stroke();
      context.setLineDash([]);
      context.fillStyle = cssVar("--cph-midnight-blue");
      context.font = `700 ${cssVar("--font-size-small")} ${cssVar("--font-sans")}`;
      context.fillText("Now", x + 6, chart.chartArea.top + 14);
      context.restore();
    },
  };

  canvas.chart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: ["T2", "T3"].map((terminal, index) => ({
        label: `Security wait ${terminal}`,
        data: security
          .filter((row) => row.terminal === terminal)
          .sort((a, b) => a.slot_start.localeCompare(b.slot_start))
          .map((row) => row.predicted_wait_min),
        borderColor: palette[index],
        backgroundColor: palette[index],
        tension: 0.25,
        pointRadius: 3,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { align: "start" },
        tooltip: {
          callbacks: {
            label(context) {
              return `${context.dataset.label}: ${context.parsed.y} min`;
            },
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          title: { display: true, text: "Wait (minutes)" },
        },
      },
    },
    plugins: [nowMarker],
  });
}

export async function refreshSecurityKpis() {
  try {
    const forecasts = await api("/api/onboarding/forecast");
    for (const terminal of ["T2", "T3"]) {
      const current = forecasts
        .filter((row) => row.terminal === terminal && row.checkpoint === "SECURITY")
        .sort((a, b) => a.slot_start.localeCompare(b.slot_start))[0];
      const tile = document.querySelector(`[data-kpi="security-wait-${terminal.toLowerCase()}"]`);
      if (tile) {
        tile.querySelector(".kpi__value").textContent =
          current ? String(Math.round(current.predicted_wait_min)) : "--";
      }
    }
  } catch {
    for (const terminal of ["T2", "T3"]) {
      const tile = document.querySelector(`[data-kpi="security-wait-${terminal.toLowerCase()}"]`);
      if (tile) tile.querySelector(".kpi__value").textContent = "--";
    }
  }

  if (!kpiRefreshStarted) {
    kpiRefreshStarted = true;
    setInterval(refreshSecurityKpis, 60_000);
  }
}

/** Called every time the "Passenger onboarding" tab is shown. */
export async function render(panel) {
  panel.replaceChildren();
  await refreshSecurityKpis();

  const grid = document.createElement("div");
  grid.className = "onboarding-grid";

  const heatmapSection = document.createElement("section");
  heatmapSection.className = "onboarding-section";
  heatmapSection.setAttribute("aria-labelledby", "queue-heatmap-heading");
  const heatmapHeading = document.createElement("h3");
  heatmapHeading.id = "queue-heatmap-heading";
  heatmapHeading.className = "section-title";
  heatmapHeading.textContent = "Passenger queue wait";

  const legend = document.createElement("p");
  legend.textContent = "Minutes: ok < 10 · warn 10–20 · critical > 20";
  legend.className = "chip chip--info";
  heatmapSection.append(heatmapHeading, legend);

  const forecastSection = document.createElement("section");
  forecastSection.className = "onboarding-section";
  forecastSection.setAttribute("aria-labelledby", "queue-forecast-heading");
  const forecastHeading = document.createElement("h3");
  forecastHeading.id = "queue-forecast-heading";
  forecastHeading.className = "section-title";
  forecastHeading.textContent = "Security wait forecast";
  forecastSection.append(forecastHeading);

  grid.append(heatmapSection, forecastSection);
  panel.append(grid);

  try {
    const [queues, forecasts] = await Promise.all([
      api("/api/onboarding/queues"),
      api("/api/onboarding/forecast"),
    ]);
    renderHeatmap(heatmapSection, queues);
    renderForecast(forecastSection, forecasts);
  } catch (error) {
    if (error.status === 501) {
      renderPlaceholder(panel, "onboarding", {
        title: "build the queue heatmap and wait-time forecast here",
        text: "Implement the onboarding queues and forecast endpoints, then refresh this tab.",
      });
      return;
    }
    const message = document.createElement("p");
    message.setAttribute("role", "alert");
    message.textContent = "Could not load passenger queue data.";
    panel.append(message);
  }
}
