// Flight plans track. Guide: docs/track-2-flight-plans.md
import { addLayer, api, cssVar, escapeHtml, renderPlaceholder } from "../app.js";

const STATUS_COLOURS = {
  ON_TIME: "--status-ok",
  DELAYED: "--status-warn",
  CANCELLED: "--status-critical",
};
const STATUS_LABELS = {
  ON_TIME: "On time",
  SCHEDULED: "Scheduled",
  BOARDING: "Boarding",
  DEPARTED: "Departed",
  LANDED: "Landed",
  DELAYED: "Delayed",
  CANCELLED: "Cancelled",
};

let flights = [];
let routeFeatures = [];
let airportsByIata = new Map();
let activeDirection = "DEP";
let boardContainer = null;
let resultStatus = null;
let searchTimer = null;
let searchBound = false;
let kpiRefreshStarted = false;

function statusColour(status) {
  const variable = STATUS_COLOURS[status] || "--status-info";
  return cssVar(variable);
}

function statusChip(status) {
  const chip = document.createElement("span");
  const className = status === "CANCELLED"
    ? "chip--critical"
    : status === "DELAYED"
      ? "chip--warn"
      : status === "ON_TIME" || status === "BOARDING" || status === "DEPARTED" || status === "LANDED"
        ? "chip--ok"
        : "chip--info";
  chip.className = `chip ${className}`;
  chip.textContent = STATUS_LABELS[status] || status;
  return chip;
}

function localTime(iso) {
  return new Date(iso).toLocaleTimeString("en-GB", {
    timeZone: "Europe/Copenhagen",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function greatCircle([lat1, lon1], [lat2, lon2], steps = 64) {
  const radians = (degrees) => degrees * Math.PI / 180;
  const degrees = (radiansValue) => radiansValue * 180 / Math.PI;
  const phi1 = radians(lat1);
  const lambda1 = radians(lon1);
  const phi2 = radians(lat2);
  const lambda2 = radians(lon2);
  const delta = 2 * Math.asin(Math.sqrt(
    Math.sin((phi2 - phi1) / 2) ** 2 +
    Math.cos(phi1) * Math.cos(phi2) * Math.sin((lambda2 - lambda1) / 2) ** 2
  ));
  if (delta === 0) return [[lat1, lon1]];

  const points = [];
  for (let index = 0; index <= steps; index++) {
    const fraction = index / steps;
    const a = Math.sin((1 - fraction) * delta) / Math.sin(delta);
    const b = Math.sin(fraction * delta) / Math.sin(delta);
    const x = a * Math.cos(phi1) * Math.cos(lambda1) + b * Math.cos(phi2) * Math.cos(lambda2);
    const y = a * Math.cos(phi1) * Math.sin(lambda1) + b * Math.cos(phi2) * Math.sin(lambda2);
    const z = a * Math.sin(phi1) + b * Math.sin(phi2);
    points.push([
      degrees(Math.atan2(z, Math.sqrt(x * x + y * y))),
      degrees(Math.atan2(y, x)),
    ]);
  }
  return points;
}

function splitAtAntimeridian(points) {
  const segments = [[points[0]]];
  for (let index = 1; index < points.length; index++) {
    if (Math.abs(points[index][1] - points[index - 1][1]) > 180) segments.push([]);
    segments.at(-1).push(points[index]);
  }
  return segments;
}

function drawRoutes() {
  const lines = routeFeatures.flatMap((feature) => {
    const properties = feature.properties;
    const [start, end] = feature.geometry.coordinates;
    const points = greatCircle([start[1], start[0]], [end[1], end[0]]);
    return splitAtAntimeridian(points).map((segment) => {
      const tooltip = `${escapeHtml(properties.dest_iata)} · ${escapeHtml(properties.city)} · ` +
        `${properties.flights} flights · ${escapeHtml(STATUS_LABELS[properties.status] || properties.status)}`;
      return L.polyline(segment, {
        color: statusColour(properties.status),
        weight: 2,
        opacity: 0.8,
      }).bindTooltip(tooltip);
    });
  });
  addLayer("flights:routes", L.layerGroup(lines));

  const legend = L.control({ position: "bottomright" });
  legend.onAdd = () => {
    const container = L.DomUtil.create("div", "legend");
    for (const [status, label] of [["ON_TIME", "On time"], ["DELAYED", "Delayed"], ["CANCELLED", "Cancelled"]]) {
      const row = document.createElement("div");
      const swatch = document.createElement("span");
      swatch.setAttribute("aria-hidden", "true");
      swatch.style.cssText = `display:inline-block;width:0.8em;height:0.8em;margin-right:0.4em;border-radius:50%;background:${statusColour(status)}`;
      row.append(swatch, document.createTextNode(label));
      container.append(row);
    }
    return container;
  };
  addLayer("flights:legend", legend);
}

function renderRouteTable(container) {
  const section = document.createElement("section");
  section.setAttribute("aria-labelledby", "flight-routes-heading");
  const heading = document.createElement("h3");
  heading.id = "flight-routes-heading";
  heading.className = "section-title";
  heading.textContent = "Route summary";
  section.append(heading);

  if (!routeFeatures.length) {
    const empty = document.createElement("p");
    empty.textContent = "No route data available.";
    section.append(empty);
    container.append(section);
    return;
  }

  const table = document.createElement("table");
  table.className = "board";
  const caption = document.createElement("caption");
  caption.className = "visually-hidden";
  caption.textContent = "Flight routes, flight counts, delays, cancellations, and summary status";
  table.append(caption);

  const thead = document.createElement("thead");
  const header = document.createElement("tr");
  for (const label of ["Destination", "Flights", "Delayed", "Cancelled", "Status"]) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    header.append(cell);
  }
  thead.append(header);
  table.append(thead);

  const tbody = document.createElement("tbody");
  for (const feature of routeFeatures) {
    const properties = feature.properties;
    const row = document.createElement("tr");
    const destination = document.createElement("th");
    destination.scope = "row";
    destination.textContent = `${properties.dest_iata} · ${properties.city}`;
    row.append(destination);
    for (const value of [properties.flights, properties.delayed, properties.cancelled]) {
      const cell = document.createElement("td");
      cell.textContent = String(value);
      row.append(cell);
    }
    const status = document.createElement("td");
    status.append(statusChip(properties.status));
    row.append(status);
    tbody.append(row);
  }
  table.append(tbody);

  const wrap = document.createElement("div");
  wrap.className = "flight-table-wrap";
  wrap.append(table);
  section.append(wrap);
  container.append(section);
}

function appendFlightTime(cell, flight) {
  if (flight.status === "DELAYED" && flight.est_time) {
    const scheduled = document.createElement("del");
    scheduled.textContent = localTime(flight.sched_time);
    const estimated = document.createElement("time");
    estimated.dateTime = flight.est_time;
    estimated.textContent = ` ${localTime(flight.est_time)} est.`;
    cell.append(scheduled, estimated);
    return;
  }
  const time = document.createElement("time");
  time.dateTime = flight.sched_time;
  time.textContent = localTime(flight.sched_time);
  cell.append(time);
}

function renderBoard() {
  if (!boardContainer || !resultStatus) return;
  boardContainer.replaceChildren();

  const query = document.getElementById("flight-search-input")?.value.trim().toLocaleLowerCase() || "";
  const matches = flights.filter((flight) => {
    if (flight.direction !== activeDirection) return false;
    const otherIata = activeDirection === "DEP" ? flight.dest_iata : flight.origin_iata;
    const airport = airportsByIata.get(otherIata);
    const searchable = `${flight.flight_no} ${otherIata} ${airport?.city || ""}`.toLocaleLowerCase();
    return searchable.includes(query);
  });

  resultStatus.textContent = `${matches.length} ${activeDirection === "DEP" ? "departures" : "arrivals"}`;
  if (!matches.length) {
    const empty = document.createElement("p");
    empty.textContent = query ? "No flights match this search." : "No flights available.";
    boardContainer.append(empty);
    return;
  }

  const table = document.createElement("table");
  table.className = "board";
  const caption = document.createElement("caption");
  caption.className = "visually-hidden";
  caption.textContent = activeDirection === "DEP" ? "Departures from Copenhagen" : "Arrivals to Copenhagen";
  table.append(caption);

  const thead = document.createElement("thead");
  const header = document.createElement("tr");
  for (const label of ["Time", "Flight", activeDirection === "DEP" ? "Destination" : "Origin", "Terminal", "Gate", "Status"]) {
    const cell = document.createElement("th");
    cell.scope = "col";
    cell.textContent = label;
    header.append(cell);
  }
  thead.append(header);
  table.append(thead);

  const tbody = document.createElement("tbody");
  for (const flight of matches) {
    const row = document.createElement("tr");
    const time = document.createElement("td");
    appendFlightTime(time, flight);
    row.append(time);

    const number = document.createElement("th");
    number.scope = "row";
    number.textContent = flight.flight_no;
    row.append(number);

    const otherIata = activeDirection === "DEP" ? flight.dest_iata : flight.origin_iata;
    const airport = airportsByIata.get(otherIata);
    const route = document.createElement("td");
    route.textContent = `${otherIata} · ${airport?.city || "City unavailable"}`;
    row.append(route);

    const terminal = document.createElement("td");
    terminal.textContent = flight.terminal;
    row.append(terminal);

    const gate = document.createElement("td");
    gate.textContent = flight.gate || "—";
    row.append(gate);

    const status = document.createElement("td");
    status.append(statusChip(flight.status));
    row.append(status);
    tbody.append(row);
  }
  table.append(tbody);

  const wrap = document.createElement("div");
  wrap.className = "flight-table-wrap";
  wrap.append(table);
  boardContainer.append(wrap);
}

function bindSearch() {
  if (searchBound) return;
  const form = document.querySelector(".flight-search");
  const input = document.getElementById("flight-search-input");
  if (!form || !input) return;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    clearTimeout(searchTimer);
    renderBoard();
  });
  input.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderBoard, 200);
  });
  searchBound = true;
}

async function refreshDeparturesKpi() {
  const tile = document.querySelector('[data-kpi="departures-next-hour"]');
  if (!tile) return;
  const value = tile.querySelector(".kpi__value");
  try {
    const now = new Date();
    const nextHour = new Date(now.getTime() + 60 * 60 * 1000);
    const url = `/api/flights?direction=DEP&from=${encodeURIComponent(now.toISOString())}` +
      `&to=${encodeURIComponent(nextHour.toISOString())}`;
    const upcoming = await api(url);
    value.textContent = String(upcoming.length);
  } catch (error) {
    console.error("Could not load departures KPI", error);
    value.textContent = "--";
  }

  if (!kpiRefreshStarted) {
    kpiRefreshStarted = true;
    setInterval(refreshDeparturesKpi, 60_000);
  }
}

document.addEventListener("DOMContentLoaded", refreshDeparturesKpi, { once: true });

/** Render routes, an accessible route summary, and the departures/arrivals board. */
export async function render(panel) {
  panel.replaceChildren();
  const toolbar = document.createElement("div");
  toolbar.className = "flight-direction-toggle";
  toolbar.setAttribute("role", "group");
  toolbar.setAttribute("aria-label", "Choose departures or arrivals");
  const directionButtons = [];
  for (const [direction, label] of [["DEP", "Departures"], ["ARR", "Arrivals"]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn--secondary";
    button.textContent = label;
    button.setAttribute("aria-pressed", String(direction === activeDirection));
    button.addEventListener("click", () => {
      activeDirection = direction;
      for (const item of directionButtons) {
        item.setAttribute("aria-pressed", String(item.dataset.direction === activeDirection));
      }
      renderBoard();
    });
    button.dataset.direction = direction;
    directionButtons.push(button);
    toolbar.append(button);
  }

  const boardHeading = document.createElement("h3");
  boardHeading.className = "section-title";
  boardHeading.textContent = "Departures and arrivals";
  resultStatus = document.createElement("p");
  resultStatus.setAttribute("role", "status");
  resultStatus.setAttribute("aria-live", "polite");
  boardContainer = document.createElement("div");
  boardContainer.className = "flight-board";
  const boardSection = document.createElement("section");
  boardSection.setAttribute("aria-labelledby", "flight-board-heading");
  boardHeading.id = "flight-board-heading";
  boardSection.append(boardHeading, toolbar, resultStatus, boardContainer);

  const routesContainer = document.createElement("div");
  renderRouteTable(routesContainer);
  panel.append(boardSection, routesContainer);
  bindSearch();

  try {
    const [flightData, routes, airports] = await Promise.all([
      api("/api/flights"),
      api("/api/flights/routes"),
      api("/api/airports"),
    ]);
    flights = flightData;
    routeFeatures = routes.features;
    airportsByIata = new Map(airports.map((airport) => [airport.iata, airport]));
    drawRoutes();
    routesContainer.replaceChildren();
    renderRouteTable(routesContainer);
    renderBoard();
  } catch (error) {
    if (error.status === 501) {
      renderPlaceholder(panel, "flights", {
        title: "build the world route map here",
        text: "Implement GET /api/flights and GET /api/flights/routes, then refresh this tab.",
      });
      return;
    }
    const message = document.createElement("p");
    message.setAttribute("role", "alert");
    message.textContent = "Could not load flight plan data.";
    panel.append(message);
  }
}
