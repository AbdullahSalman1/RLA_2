from __future__ import annotations

import html
import re
import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from routing import build_route, get_distance_matrix, geocode, min_to_time, simulate_route


st.set_page_config(
    page_title="Delivery Operations Dashboard",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
        .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
        .hero {
            padding: 1.25rem 1.4rem;
            border-radius: 1.2rem;
            background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 55%, #7c3aed 100%);
            color: white;
            box-shadow: 0 12px 30px rgba(15, 23, 42, 0.18);
            margin-bottom: 1rem;
        }
        .subtle {
            color: rgba(255,255,255,0.82);
            font-size: 0.95rem;
        }
        .metric-card {
            padding: 1rem;
            border-radius: 1rem;
            background: #ffffff;
            border: 1px solid #e5e7eb;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
        }
        .section-title {
            font-size: 1.08rem;
            font-weight: 700;
            margin: 0.6rem 0 0.4rem 0;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


DELIVERY_COLUMNS = [
    "id",
    "name",
    "address",
    "priority",
    "is_cold",
    "is_suburban",
    "boxes",
    "time_window_start",
    "time_window_end",
]
FLEET_COLUMNS = ["id", "type", "label", "max_stops"]
DRIVER_COLUMNS = ["id", "name", "certified_refrigerated", "shift_start", "max_hours"]


def _empty_warehouse() -> dict[str, str]:
    return {"name": "", "address": ""}


def _empty_orders_df() -> pd.DataFrame:
    return pd.DataFrame(columns=DELIVERY_COLUMNS)


def _empty_vehicles_df() -> pd.DataFrame:
    return pd.DataFrame(columns=FLEET_COLUMNS)


def _empty_drivers_df() -> pd.DataFrame:
    return pd.DataFrame(columns=DRIVER_COLUMNS)


def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "oui", "x"}


def _normalize_bool_series(series: pd.Series) -> pd.Series:
    return series.map(_coerce_bool).astype(bool)


def _split_time_window(value) -> tuple[str, str]:
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return str(value[0]), str(value[1])
    text = str(value or "")
    matches = re.findall(r"\d{1,2}:\d{2}", text)
    if len(matches) >= 2:
        return matches[0], matches[1]
    if "-" in text:
        parts = [p.strip(" ()[]{}'\"") for p in text.split("-") if p.strip()]
        if len(parts) >= 2:
            return parts[0], parts[1]
    return "", ""


def normalize_orders_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_orders_df()

    cleaned = df.copy()
    cleaned.columns = [str(col).strip().lower() for col in cleaned.columns]

    if "time_window" in cleaned.columns and ("time_window_start" not in cleaned.columns or "time_window_end" not in cleaned.columns):
        windows = cleaned["time_window"].apply(_split_time_window)
        cleaned["time_window_start"] = windows.apply(lambda item: item[0])
        cleaned["time_window_end"] = windows.apply(lambda item: item[1])

    defaults = {
        "id": "",
        "name": "",
        "address": "",
        "priority": "normal",
        "is_cold": False,
        "is_suburban": False,
        "boxes": 0,
        "time_window_start": "",
        "time_window_end": "",
    }
    for col, default in defaults.items():
        if col not in cleaned.columns:
            cleaned[col] = default

    cleaned = cleaned[DELIVERY_COLUMNS]
    cleaned["id"] = cleaned["id"].fillna("").astype(str)
    cleaned["name"] = cleaned["name"].fillna("").astype(str)
    cleaned["address"] = cleaned["address"].fillna("").astype(str)
    cleaned["priority"] = cleaned["priority"].fillna("normal").astype(str).str.lower()
    cleaned["is_cold"] = _normalize_bool_series(cleaned["is_cold"])
    cleaned["is_suburban"] = _normalize_bool_series(cleaned["is_suburban"])
    cleaned["boxes"] = pd.to_numeric(cleaned["boxes"], errors="coerce").fillna(0).astype(int)
    cleaned["time_window_start"] = cleaned["time_window_start"].fillna("").astype(str)
    cleaned["time_window_end"] = cleaned["time_window_end"].fillna("").astype(str)
    return cleaned


def normalize_vehicles_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_vehicles_df()

    cleaned = df.copy()
    cleaned.columns = [str(col).strip().lower() for col in cleaned.columns]
    defaults = {"id": "", "type": "", "label": "", "max_stops": 0}
    for col, default in defaults.items():
        if col not in cleaned.columns:
            cleaned[col] = default

    cleaned = cleaned[FLEET_COLUMNS]
    cleaned["id"] = cleaned["id"].fillna("").astype(str)
    cleaned["type"] = cleaned["type"].fillna("").astype(str).str.lower()
    cleaned["label"] = cleaned["label"].fillna("").astype(str)
    cleaned["max_stops"] = pd.to_numeric(cleaned["max_stops"], errors="coerce").fillna(0).astype(int)
    return cleaned


def normalize_drivers_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_drivers_df()

    cleaned = df.copy()
    cleaned.columns = [str(col).strip().lower() for col in cleaned.columns]
    defaults = {
        "id": "",
        "name": "",
        "certified_refrigerated": False,
        "shift_start": "",
        "max_hours": 0,
    }
    for col, default in defaults.items():
        if col not in cleaned.columns:
            cleaned[col] = default

    cleaned = cleaned[DRIVER_COLUMNS]
    cleaned["id"] = cleaned["id"].fillna("").astype(str)
    cleaned["name"] = cleaned["name"].fillna("").astype(str)
    cleaned["certified_refrigerated"] = _normalize_bool_series(cleaned["certified_refrigerated"])
    cleaned["shift_start"] = cleaned["shift_start"].fillna("").astype(str)
    cleaned["max_hours"] = pd.to_numeric(cleaned["max_hours"], errors="coerce").fillna(0).astype(int)
    return cleaned


def parse_delivery_workbook(uploaded_file) -> tuple[dict[str, str], pd.DataFrame]:
    if uploaded_file is None:
        return _empty_warehouse(), _empty_orders_df()

    uploaded_file.seek(0)
    workbook = pd.ExcelFile(uploaded_file)
    warehouse = _empty_warehouse()

    if "warehouse" in workbook.sheet_names:
        warehouse_df = pd.read_excel(workbook, sheet_name="warehouse")
        if not warehouse_df.empty:
            row = warehouse_df.iloc[0].copy()
            row.index = [str(col).strip().lower() for col in row.index]
            warehouse["name"] = str(row.get("name", "") or "")
            warehouse["address"] = str(row.get("address", "") or "")

    orders = _empty_orders_df()
    if "orders" in workbook.sheet_names:
        orders = normalize_orders_df(pd.read_excel(workbook, sheet_name="orders"))

    return warehouse, orders


def parse_fleet_workbook(uploaded_file) -> tuple[pd.DataFrame, pd.DataFrame]:
    if uploaded_file is None:
        return _empty_vehicles_df(), _empty_drivers_df()

    uploaded_file.seek(0)
    workbook = pd.ExcelFile(uploaded_file)
    vehicles = _empty_vehicles_df()
    drivers = _empty_drivers_df()

    if "vehicles" in workbook.sheet_names:
        vehicles = normalize_vehicles_df(pd.read_excel(workbook, sheet_name="vehicles"))

    if "drivers" in workbook.sheet_names:
        drivers = normalize_drivers_df(pd.read_excel(workbook, sheet_name="drivers"))

    return vehicles, drivers


def priority_order(priority: str) -> int:
    return {"critical": 0, "high": 1, "normal": 2}.get(str(priority).lower(), 99)


def apply_filters(orders_df: pd.DataFrame, selected_priorities, selected_cold, selected_area, boxes_range):
    if orders_df.empty:
        return orders_df.copy()

    filtered = orders_df.copy()
    filtered["priority"] = filtered["priority"].astype(str).str.lower()
    filtered = filtered[filtered["priority"].isin(selected_priorities)]
    filtered = filtered[
        filtered["is_cold"].map(lambda x: (bool(x) and "cold" in selected_cold) or (not bool(x) and "regular" in selected_cold))
    ]
    filtered = filtered[
        filtered["is_suburban"].map(lambda x: (bool(x) and "suburban" in selected_area) or (not bool(x) and "city" in selected_area))
    ]
    filtered = filtered[filtered["boxes"].between(boxes_range[0], boxes_range[1])]
    filtered = filtered.copy()
    filtered["priority_rank"] = filtered["priority"].map(priority_order)
    return filtered.sort_values(["priority_rank", "boxes", "name"], ascending=[True, False, True])


def _priority_rank(priority: str) -> int:
    return {"critical": 0, "high": 1, "normal": 2}.get(str(priority).lower(), 99)


def _vehicle_rank(vehicle_type: str) -> int:
    return {"refrigerated": 0, "large": 1, "small": 2}.get(str(vehicle_type).lower(), 99)


def _default_time_window(order_row: dict) -> tuple[str, str]:
    start = str(order_row.get("time_window_start", "") or "").strip()
    end = str(order_row.get("time_window_end", "") or "").strip()
    if start and end:
        return start, end
    return "07:00", "18:00"


def _prepare_route_locations(warehouse: dict[str, str], orders: pd.DataFrame):
    if not warehouse.get("name") or not warehouse.get("address"):
        raise ValueError("Please enter a warehouse name and address before calculating routes.")
    if orders.empty:
        raise ValueError("Please add at least one delivery before calculating routes.")

    locations = []
    warehouse_loc = geocode(warehouse["name"], warehouse["address"])
    if warehouse_loc is None:
        raise ValueError(f"Could not geocode warehouse address: {warehouse['address']}")
    warehouse_loc.update(
        {
            "id": "W0",
            "priority": None,
            "time_window": ("00:00", "23:59"),
            "boxes": 0,
            "is_cold": False,
            "is_suburban": False,
            "source_type": "warehouse",
        }
    )
    locations.append(warehouse_loc)

    geocode_errors = []
    for row in orders.to_dict(orient="records"):
        if not str(row.get("address", "") or "").strip():
            geocode_errors.append(f"{row.get('name', 'Unnamed order')} is missing an address.")
            continue

        loc = geocode(str(row.get("name", "")), str(row.get("address", "")))
        if loc is None:
            geocode_errors.append(f"Could not geocode {row.get('name', 'an order')} ({row.get('address', '')}).")
            continue

        loc.update(
            {
                "id": str(row.get("id", "")),
                "priority": str(row.get("priority", "normal")).lower(),
                "time_window": _default_time_window(row),
                "boxes": int(row.get("boxes", 0) or 0),
                "is_cold": bool(row.get("is_cold", False)),
                "is_suburban": bool(row.get("is_suburban", False)),
                "source_type": "order",
            }
        )
        locations.append(loc)

    if len(locations) == 1:
        raise ValueError("None of the delivery addresses could be geocoded.")

    return locations, geocode_errors


def _assign_orders_to_vehicles(orders: pd.DataFrame, vehicles: pd.DataFrame):
    sorted_orders = orders.copy()
    sorted_orders["priority_rank"] = sorted_orders["priority"].map(_priority_rank)
    sorted_orders = sorted_orders.sort_values(["priority_rank", "boxes", "name"], ascending=[True, False, True])

    vehicle_rows = vehicles.to_dict(orient="records")
    vehicle_rows = sorted(vehicle_rows, key=lambda row: (_vehicle_rank(row.get("type", "")), str(row.get("label", ""))))

    vehicle_stops = {str(v["id"]): 0 for v in vehicle_rows}
    vehicle_orders = {str(v["id"]): [] for v in vehicle_rows}
    order_assignments = {}

    def pick_vehicle(preferred_types):
        for vehicle in vehicle_rows:
            vid = str(vehicle["id"])
            if vehicle_stops[vid] < int(vehicle.get("max_stops", 0) or 0) and str(vehicle.get("type", "")).lower() in preferred_types:
                return vehicle
        for vehicle in vehicle_rows:
            vid = str(vehicle["id"])
            if vehicle_stops[vid] < int(vehicle.get("max_stops", 0) or 0):
                return vehicle
        return None

    for order in sorted_orders.to_dict(orient="records"):
        preferred = ["small", "large", "refrigerated"]
        if bool(order.get("is_cold", False)):
            preferred = ["refrigerated", "large", "small"]
        elif bool(order.get("is_suburban", False)):
            preferred = ["large", "small", "refrigerated"]

        vehicle = pick_vehicle(preferred)
        if vehicle is None:
            order_assignments[str(order.get("id", ""))] = {"vehicle_id": None, "reason": "All vehicles are full"}
            continue

        vid = str(vehicle["id"])
        vehicle_stops[vid] += 1
        vehicle_orders[vid].append(order)
        order_assignments[str(order.get("id", ""))] = {
            "vehicle_id": vid,
            "vehicle_label": str(vehicle.get("label", vid)),
            "reason": "Assigned by capacity and delivery type",
        }

    return vehicle_orders, order_assignments


def _assign_drivers_to_vehicles(vehicle_orders: dict, drivers: pd.DataFrame, vehicles: pd.DataFrame):
    driver_rows = drivers.to_dict(orient="records")
    vehicle_rows = vehicles.to_dict(orient="records")
    assigned_drivers = set()
    vehicle_driver = {}

    def take_driver(predicate):
        for driver in driver_rows:
            did = str(driver.get("id", ""))
            if did and did not in assigned_drivers and predicate(driver):
                assigned_drivers.add(did)
                return driver
        return None

    for vehicle in vehicle_rows:
        vid = str(vehicle.get("id", ""))
        if not vehicle_orders.get(vid):
            continue

        driver = None
        if str(vehicle.get("type", "")).lower() == "refrigerated":
            driver = take_driver(lambda d: bool(d.get("certified_refrigerated", False)))

        if driver is None:
            driver = take_driver(lambda d: True)

        vehicle_driver[vid] = driver

    return vehicle_driver


def _route_total_distance(route, distances):
    if not route:
        return 0.0
    total_km = distances[0][route[0]]
    for idx in range(len(route) - 1):
        total_km += distances[route[idx]][route[idx + 1]]
    total_km += distances[route[-1]][0]
    return float(total_km)


def _route_map_figure(vehicle_label: str, route_results: list[dict], locations: list[dict]):
    if not route_results:
        return None

    route_lats = [locations[0]["lat"]]
    route_lons = [locations[0]["lon"]]
    route_labels = [f"Warehouse: {locations[0]['name']}"]

    for stop in route_results:
        loc = locations[stop["location_index"]]
        route_lats.append(loc["lat"])
        route_lons.append(loc["lon"])
        route_labels.append(
            f"{stop['sequence']}. {stop['name']} | {stop['priority'].title()} | {stop['arrival']} → {stop['departure']}"
        )

    route_lats.append(locations[0]["lat"])
    route_lons.append(locations[0]["lon"])
    route_labels.append(f"Return to {locations[0]['name']}")

    fig = go.Figure()
    fig.add_trace(
        go.Scattermapbox(
            lat=route_lats,
            lon=route_lons,
            mode="lines+markers",
            line=dict(width=4, color="#2563eb"),
            marker=dict(size=10, color="#1d4ed8"),
            hovertext=route_labels,
            hoverinfo="text",
            name=vehicle_label,
        )
    )

    fig.update_layout(
        mapbox=dict(style="open-street-map", zoom=10),
        margin=dict(l=0, r=0, t=0, b=0),
        height=520,
        showlegend=False,
        title=f"Route map — {vehicle_label}",
    )
    return fig


def _build_route_report_html(route_plan: list[dict], warehouse: dict[str, str], geocode_warnings: list[str]):
    sections = []
    total_stops = sum(len(entry["stops"]) for entry in route_plan)
    total_km = sum(entry["total_km"] for entry in route_plan)
    total_late = sum(sum(1 for stop in entry["stops"] if stop["is_late"]) for entry in route_plan)

    warning_html = ""
    if geocode_warnings:
        warning_html = "<div class='warning'><strong>Warnings</strong><ul>" + "".join(
            f"<li>{html.escape(msg)}</li>" for msg in geocode_warnings
        ) + "</ul></div>"

    for entry in route_plan:
        vehicle = entry["vehicle"]
        driver = entry["driver"]
        driver_name = driver["name"] if driver else "No driver assigned"
        map_html = entry["map_html"]
        rows = []
        for stop in entry["stops"]:
            rows.append(
                "<tr>"
                f"<td>{stop['sequence']}</td>"
                f"<td>{html.escape(stop['name'])}</td>"
                f"<td>{html.escape(stop['priority'])}</td>"
                f"<td>{html.escape(stop['window'])}</td>"
                f"<td>{html.escape(stop['arrival'])}</td>"
                f"<td>{html.escape(stop['departure'])}</td>"
                f"<td>{'Late' if stop['is_late'] else 'OK'}</td>"
                f"<td>{stop['late_by_min']}</td>"
                "</tr>"
            )

        sections.append(
            f"""
            <section class='vehicle-card'>
              <h2>{html.escape(vehicle['label'])}</h2>
              <p class='muted'>Driver: {html.escape(driver_name)} · Stops: {len(entry['stops'])} · Distance: {entry['total_km']:.1f} km · Duration: {int(entry['total_duration_min'])} min</p>
              {map_html}
              <table>
                <thead>
                  <tr><th>#</th><th>Client</th><th>Priority</th><th>Window</th><th>Arrival</th><th>Departure</th><th>Status</th><th>Late by</th></tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
              </table>
            </section>
            """
        )

    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset='utf-8'/>
      <meta name='viewport' content='width=device-width, initial-scale=1'/>
      <title>Route report</title>
      <style>
        body {{ font-family: Arial, sans-serif; margin: 24px; background: #f8fafc; color: #0f172a; }}
        h1 {{ margin-bottom: 6px; }}
        .muted {{ color: #64748b; }}
        .summary {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 18px 0 24px; }}
        .summary div, .warning, .vehicle-card {{ background: white; border: 1px solid #e2e8f0; border-radius: 14px; padding: 16px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05); }}
        .summary strong {{ display: block; font-size: 1.6rem; margin-top: 6px; }}
        .vehicle-card {{ margin-bottom: 24px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
        th, td {{ padding: 10px; border-bottom: 1px solid #e2e8f0; text-align: left; font-size: 0.95rem; }}
        th {{ background: #f8fafc; }}
        .warning {{ border-left: 4px solid #f59e0b; margin-bottom: 18px; }}
      </style>
    </head>
    <body>
      <h1>Route report</h1>
      <div class='muted'>Warehouse: {html.escape(warehouse.get('name', ''))} · {html.escape(warehouse.get('address', ''))}</div>
      {warning_html}
      <div class='summary'>
        <div>Total stops<strong>{total_stops}</strong></div>
        <div>Total distance<strong>{total_km:.1f} km</strong></div>
        <div>Late deliveries<strong>{total_late}</strong></div>
        <div>Vehicles used<strong>{len(route_plan)}</strong></div>
      </div>
      {''.join(sections)}
    </body>
    </html>
    """


def calculate_routes_for_dashboard(warehouse: dict[str, str], orders: pd.DataFrame, vehicles: pd.DataFrame, drivers: pd.DataFrame):
    locations, geocode_warnings = _prepare_route_locations(warehouse, orders)
    distances, durations = get_distance_matrix(locations)
    if distances is None or durations is None:
        raise ValueError("The distance matrix request failed. Please check your internet connection or API settings.")

    vehicle_orders, order_assignments = _assign_orders_to_vehicles(orders, vehicles)
    vehicle_drivers = _assign_drivers_to_vehicles(vehicle_orders, drivers, vehicles)
    loc_index = {loc["id"]: i for i, loc in enumerate(locations)}

    route_plan = []
    for vehicle in vehicles.to_dict(orient="records"):
        vid = str(vehicle.get("id", ""))
        assigned_orders = vehicle_orders.get(vid, [])
        if not assigned_orders:
            continue

        stop_indices = [loc_index[str(order.get("id", ""))] for order in assigned_orders if str(order.get("id", "")) in loc_index]
        if not stop_indices:
            continue

        final_route, locked_count = build_route(stop_indices, locations, distances)
        driver = vehicle_drivers.get(vid)
        sim_driver = driver or {"name": "No driver assigned", "shift_start": "07:00", "max_hours": 8}
        sim_stops, total_duration_min = simulate_route(final_route, locations, durations, sim_driver)
        route_total_km = _route_total_distance(final_route, distances)

        route_stops = []
        for seq, stop in enumerate(sim_stops, start=1):
            route_stops.append(
                {
                    "sequence": seq,
                    "location_index": loc_index[stop["id"]],
                    "name": stop["name"],
                    "priority": str(stop["priority"]),
                    "window": stop["window"],
                    "arrival": stop["arrival"],
                    "departure": stop["departure"],
                    "is_late": bool(stop["is_late"]),
                    "late_by_min": int(stop["late_by_min"]),
                }
            )

        map_fig = _route_map_figure(str(vehicle.get("label", vid)), route_stops, locations)
        map_html = map_fig.to_html(include_plotlyjs="cdn", full_html=False) if map_fig is not None else ""

        route_plan.append(
            {
                "vehicle": vehicle,
                "driver": driver,
                "stops": route_stops,
                "total_km": route_total_km,
                "total_duration_min": total_duration_min,
                "locked_count": locked_count,
                "map_fig": map_fig,
                "map_html": map_html,
            }
        )

    report_html = _build_route_report_html(route_plan, warehouse, geocode_warnings)
    return {
        "route_plan": route_plan,
        "order_assignments": order_assignments,
        "geocode_warnings": geocode_warnings,
        "report_html": report_html,
        "locations": locations,
    }


if "warehouse_name" not in st.session_state:
    st.session_state.warehouse_name = ""
if "warehouse_address" not in st.session_state:
    st.session_state.warehouse_address = ""
if "orders_df" not in st.session_state:
    st.session_state.orders_df = _empty_orders_df()
if "vehicles_df" not in st.session_state:
    st.session_state.vehicles_df = _empty_vehicles_df()
if "drivers_df" not in st.session_state:
    st.session_state.drivers_df = _empty_drivers_df()
if "route_result" not in st.session_state:
    st.session_state.route_result = None
if "route_report_path" not in st.session_state:
    st.session_state.route_report_path = None
if "route_error" not in st.session_state:
    st.session_state.route_error = ""


st.sidebar.header("Data sources")
delivery_file = st.sidebar.file_uploader(
    "Delivery workbook",
    type=["xlsx", "xls"],
    help="Upload a workbook with warehouse and orders sheets.",
)
fleet_file = st.sidebar.file_uploader(
    "Fleet workbook",
    type=["xlsx", "xls"],
    help="Upload a workbook with vehicles and drivers sheets.",
)

load_clicked = st.sidebar.button("Load selected files")
reset_clicked = st.sidebar.button("Reset to empty tables")

if reset_clicked:
    st.session_state.warehouse_name = ""
    st.session_state.warehouse_address = ""
    st.session_state.orders_df = _empty_orders_df()
    st.session_state.vehicles_df = _empty_vehicles_df()
    st.session_state.drivers_df = _empty_drivers_df()
    st.session_state.route_result = None
    st.session_state.route_report_path = None
    st.session_state.route_error = ""
    st.sidebar.success("Tables reset. Add or upload new data anytime.")

if load_clicked:
    warehouse, orders = parse_delivery_workbook(delivery_file)
    vehicles, drivers = parse_fleet_workbook(fleet_file)
    st.session_state.warehouse_name = warehouse["name"]
    st.session_state.warehouse_address = warehouse["address"]
    st.session_state.orders_df = orders
    st.session_state.vehicles_df = vehicles
    st.session_state.drivers_df = drivers
    st.session_state.route_result = None
    st.session_state.route_report_path = None
    st.session_state.route_error = ""
    st.sidebar.success("Files loaded into editable tables.")

st.sidebar.header("Warehouse")
st.sidebar.text_input("Name", key="warehouse_name", placeholder="Warehouse name")
st.sidebar.text_input("Address", key="warehouse_address", placeholder="Warehouse address")

st.sidebar.header("Quick tips")
st.sidebar.caption("Upload files first, then use the tables below to add, edit, or remove rows without reloading the app.")

warehouse = {"name": st.session_state.warehouse_name.strip(), "address": st.session_state.warehouse_address.strip()}
orders_df = normalize_orders_df(st.session_state.orders_df)
vehicles_df = normalize_vehicles_df(st.session_state.vehicles_df)
drivers_df = normalize_drivers_df(st.session_state.drivers_df)

st.markdown(
    f"""
    <div class="hero">
        <div style="font-size: 2rem; font-weight: 800;">🚚 Delivery Operations Dashboard</div>
        <div class="subtle">
            Warehouse: {warehouse['name'] or 'not set'} · {warehouse['address'] or 'upload a file or edit the fields in the sidebar'}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.info(
    "Upload a workbook, then edit the tables directly. You can add vehicles, remove deliveries, or change drivers without the dashboard auto-reading a fixed file."
)

st.sidebar.header("Filters")
priority_options = ["critical", "high", "normal"]
selected_priorities = st.sidebar.multiselect(
    "Priority",
    priority_options,
    default=priority_options,
)
selected_cold = st.sidebar.multiselect(
    "Cold chain",
    ["cold", "regular"],
    default=["cold", "regular"],
)
selected_area = st.sidebar.multiselect(
    "Area",
    ["suburban", "city"],
    default=["suburban", "city"],
)

if orders_df.empty:
    boxes_range = (0, 0)
    st.sidebar.caption("Load orders to enable the box filter.")
else:
    min_boxes, max_boxes = int(orders_df["boxes"].min()), int(orders_df["boxes"].max())
    if min_boxes == max_boxes:
        boxes_range = (min_boxes, max_boxes)
        st.sidebar.caption(f"Box filter fixed at {min_boxes} because all orders have the same size.")
    else:
        boxes_range = st.sidebar.slider("Boxes", min_boxes, max_boxes, (min_boxes, max_boxes))

filtered_orders = apply_filters(orders_df, selected_priorities, selected_cold, selected_area, boxes_range)

col1, col2, col3, col4, col5 = st.columns(5)
metrics = [
    ("Orders", len(orders_df)),
    ("Filtered", len(filtered_orders)),
    ("Critical", int((orders_df["priority"].astype(str).str.lower() == "critical").sum())),
    ("Cold chain", int(orders_df["is_cold"].sum() if not orders_df.empty else 0)),
    ("Total boxes", int(orders_df["boxes"].sum() if not orders_df.empty else 0)),
]
for col, (label, value) in zip([col1, col2, col3, col4, col5], metrics):
    col.markdown(
        f'<div class="metric-card"><div style="color:#6b7280;font-size:0.85rem;">{label}</div><div style="font-size:1.7rem;font-weight:800;">{value}</div></div>',
        unsafe_allow_html=True,
    )

st.write("")

left, right = st.columns([1.1, 0.9])
with left:
    st.markdown('<div class="section-title">Priority mix</div>', unsafe_allow_html=True)
    if orders_df.empty:
        st.info("Upload or add orders to see the priority chart.")
    else:
        priority_counts = (
            orders_df["priority"].astype(str).str.lower().value_counts().reindex(priority_options, fill_value=0).reset_index()
        )
        priority_counts.columns = ["priority", "count"]
        fig = px.bar(
            priority_counts,
            x="priority",
            y="count",
            color="priority",
            color_discrete_map={"critical": "#dc2626", "high": "#f59e0b", "normal": "#2563eb"},
            text="count",
        )
        fig.update_layout(height=320, showlegend=False, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, use_container_width=True)

with right:
    st.markdown('<div class="section-title">Delivery types</div>', unsafe_allow_html=True)
    if orders_df.empty:
        st.info("Upload or add orders to see the delivery-type breakdown.")
    else:
        pie_df = pd.DataFrame(
            {
                "type": ["Cold chain", "Regular"],
                "count": [int(orders_df["is_cold"].sum()), int((~orders_df["is_cold"]).sum())],
            }
        )
        fig2 = px.pie(
            pie_df,
            names="type",
            values="count",
            hole=0.55,
            color_discrete_sequence=["#7c3aed", "#22c55e"],
        )
        fig2.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig2, use_container_width=True)

st.subheader("Edit deliveries")
edited_orders = st.data_editor(
    orders_df,
    width="stretch",
    hide_index=True,
    num_rows="dynamic",
    key="orders_editor",
    column_config={
        "id": st.column_config.TextColumn("Order ID"),
        "name": st.column_config.TextColumn("Client"),
        "address": st.column_config.TextColumn("Address"),
        "priority": st.column_config.SelectboxColumn("Priority", options=priority_options, required=True),
        "is_cold": st.column_config.CheckboxColumn("Cold chain"),
        "is_suburban": st.column_config.CheckboxColumn("Suburban"),
        "boxes": st.column_config.NumberColumn("Boxes", min_value=0, step=1),
        "time_window_start": st.column_config.TextColumn("Time window start"),
        "time_window_end": st.column_config.TextColumn("Time window end"),
    },
)
st.session_state.orders_df = normalize_orders_df(edited_orders)

fleet_left, fleet_right = st.columns(2)
with fleet_left:
    st.subheader("Edit vehicles")
    edited_vehicles = st.data_editor(
        vehicles_df,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key="vehicles_editor",
        column_config={
            "id": st.column_config.TextColumn("Vehicle ID"),
            "type": st.column_config.SelectboxColumn(
                "Type",
                options=["small", "large", "refrigerated"],
                required=True,
            ),
            "label": st.column_config.TextColumn("Vehicle"),
            "max_stops": st.column_config.NumberColumn("Max stops", min_value=0, step=1),
        },
    )
    st.session_state.vehicles_df = normalize_vehicles_df(edited_vehicles)

with fleet_right:
    st.subheader("Edit drivers")
    edited_drivers = st.data_editor(
        drivers_df,
        width="stretch",
        hide_index=True,
        num_rows="dynamic",
        key="drivers_editor",
        column_config={
            "id": st.column_config.TextColumn("Driver ID"),
            "name": st.column_config.TextColumn("Driver"),
            "certified_refrigerated": st.column_config.CheckboxColumn("Cold certified"),
            "shift_start": st.column_config.TextColumn("Shift start"),
            "max_hours": st.column_config.NumberColumn("Max hours", min_value=0, step=1),
        },
    )
    st.session_state.drivers_df = normalize_drivers_df(edited_drivers)

st.subheader("Workbook summary")
summary_cols = st.columns(3)
summary_cols[0].metric("Vehicles", len(st.session_state.vehicles_df))
summary_cols[1].metric("Drivers", len(st.session_state.drivers_df))
summary_cols[2].metric("Warehouse", warehouse["name"] or "Not set")

st.subheader("Route planner")
route_actions_left, route_actions_right = st.columns([1, 1])
with route_actions_left:
    calculate_clicked = st.button("Calculate routes", type="primary", use_container_width=True)
with route_actions_right:
    clear_results_clicked = st.button("Clear route results", use_container_width=True)

if clear_results_clicked:
    st.session_state.route_result = None
    st.session_state.route_report_path = None
    st.session_state.route_error = ""
    st.success("Route results cleared.")

if calculate_clicked:
    try:
        with st.spinner("Calculating routes, geocoding addresses, and building the map..."):
            result = calculate_routes_for_dashboard(warehouse, orders_df, vehicles_df, drivers_df)
            report_path = Path(tempfile.gettempdir()) / "distance_route_report.html"
            report_path.write_text(result["report_html"], encoding="utf-8")
            st.session_state.route_result = result
            st.session_state.route_report_path = report_path
            st.session_state.route_error = ""
        st.success("Routes calculated successfully.")
    except Exception as exc:
        st.session_state.route_result = None
        st.session_state.route_report_path = None
        st.session_state.route_error = str(exc)
        st.error(f"Route calculation failed: {exc}")

if st.session_state.route_error:
    st.warning(st.session_state.route_error)

route_result = st.session_state.route_result
if route_result:
    report_path = st.session_state.route_report_path
    if report_path and Path(report_path).exists():
        report_url = Path(report_path).as_uri()
        st.markdown(
            f'<a href="{report_url}" target="_blank" rel="noopener noreferrer">Open detailed route report in a new tab</a>',
            unsafe_allow_html=True,
        )
    st.download_button(
        "Download route report",
        route_result["report_html"],
        file_name="route_report.html",
        mime="text/html",
        use_container_width=True,
    )

    st.subheader("Calculated routes")
    if route_result["geocode_warnings"]:
        for warning in route_result["geocode_warnings"]:
            st.warning(warning)

    if route_result["order_assignments"]:
        assignment_rows = []
        for order_id, info in route_result["order_assignments"].items():
            assignment_rows.append(
                {
                    "Order ID": order_id,
                    "Vehicle": info.get("vehicle_label") or "UNASSIGNED",
                    "Reason": info.get("reason", ""),
                }
            )
        st.caption("Order-to-vehicle assignments")
        st.dataframe(pd.DataFrame(assignment_rows), hide_index=True, use_container_width=True)

    route_plan = route_result["route_plan"]
    if not route_plan:
        st.info("No vehicle routes were generated from the current data.")
    else:
        tabs = st.tabs([entry["vehicle"]["label"] for entry in route_plan])
        for tab, entry in zip(tabs, route_plan):
            with tab:
                driver = entry["driver"]
                driver_name = driver["name"] if driver else "No driver assigned"
                route_cols = st.columns(4)
                route_cols[0].metric("Stops", len(entry["stops"]))
                route_cols[1].metric("Distance (km)", f"{entry['total_km']:.1f}")
                route_cols[2].metric("Duration (min)", int(entry["total_duration_min"]))
                route_cols[3].metric("Driver", driver_name)

                if entry["map_fig"] is not None:
                    st.plotly_chart(entry["map_fig"], use_container_width=True)
                else:
                    st.info("No map available for this vehicle.")

                stop_rows = []
                for stop in entry["stops"]:
                    stop_rows.append(
                        {
                            "#": stop["sequence"],
                            "Client": stop["name"],
                            "Priority": stop["priority"],
                            "Window": stop["window"],
                            "Arrival": stop["arrival"],
                            "Departure": stop["departure"],
                            "Status": "Late" if stop["is_late"] else "OK",
                            "Late by (min)": stop["late_by_min"],
                        }
                    )
                st.dataframe(pd.DataFrame(stop_rows), hide_index=True, use_container_width=True)

st.caption(
    "Tip: upload a different workbook whenever you want to replace the current data, then click \"Load selected files\". The tables remain editable after that."
)
