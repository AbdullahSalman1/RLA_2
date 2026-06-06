# Delivery Dashboard

A professional Streamlit application for planning, visualizing, and reviewing delivery routes.

The dashboard reads delivery and fleet workbooks, geocodes every address, builds vehicle-specific routes, simulates arrival times, and renders interactive maps and reports for operational review.

## What this project solves

Delivery planning is often messy because the routing problem is not just about distance. In this project, the route planner must also respect:

- delivery priority (`critical`, `high`, `normal`)
- cold-chain handling
- suburban vs city delivery patterns
- vehicle capacity
- driver certification and shift length
- time windows for each stop

The dashboard turns those constraints into a usable delivery plan with a clear map, a terminal trace, and an exportable HTML report.

## Key features

- Upload delivery and fleet workbooks from the sidebar
- Edit warehouse, deliveries, vehicles, and drivers directly in tables
- Reset the app state to empty tables at any time
- Geocode all addresses with OpenRouteService
- Fetch a full distance/duration matrix for route planning
- Assign orders to vehicles using business rules
- Assign drivers to vehicles with refrigerated-driver preference
- Build routes using a priority-first nearest-neighbor heuristic
- Simulate travel time, waiting time, lateness, and shift overruns
- Show an interactive Leaflet/OpenStreetMap map for:
	- all deliveries combined
	- each vehicle route separately
- Print route comparisons in the terminal for debugging and validation
- Generate a full HTML route report in a new tab
- Evaluate emergency deliveries by ranking the best driver for a requested address and time

## How the dashboard works

1. Load a delivery workbook and a fleet workbook in the sidebar.
2. Edit the loaded tables if you want to adjust the scenario.
3. Click **Calculate routes**.
4. The app:
	 - validates the warehouse and orders
	 - geocodes the warehouse and every delivery
	 - requests a distance matrix from OpenRouteService
	 - assigns deliveries to vehicles
	 - assigns drivers to vehicles
	 - builds the final route for each vehicle
	 - simulates the schedule stop by stop
	 - renders the route maps and report
	 - can also score an emergency delivery against the current fleet and route plan

## Routing solution

This project currently uses a **heuristic route builder**, not an exhaustive traveling-salesman search.

The live routing logic is implemented in `main.py` and is the source used by `dashboard.py`.

### 1) Order assignment heuristic

Before route construction, orders are distributed across the fleet with simple operational rules:

- **critical** deliveries are prioritized first
- **cold** deliveries prefer refrigerated vehicles
- **suburban** deliveries prefer larger vehicles
- **city** deliveries prefer smaller vehicles
- if the preferred vehicle type is full, the system falls back to another available vehicle

This is a capacity-and-suitability assignment step, not an optimization solver.

### 2) Route construction heuristic

The active route builder uses a **greedy nearest-neighbor** strategy:

- all **critical** stops are handled first
- then the remaining **high** and **normal** stops are appended
- at each step, the next stop is the **closest unvisited stop** to the current position

This means the route is designed to be simple, stable, and easy to inspect.

Important note: this is often described informally as “brute force,” but technically it is a **nearest-neighbor heuristic**, not an exhaustive brute-force permutation search.

### 3) Route simulation

After the route is built, the app simulates the trip using:

- driver shift start time
- driver maximum hours
- service time per stop
- each stop’s time window

The simulation reports:

- arrival time
- departure time
- lateness, if any
- whether the route exceeds the driver shift
- distance from the previous stop

### 4) Comparison output

For traceability, the app also prints a comparison between:

- the raw stop order before route shaping
- the final priority-first nearest-neighbor route

This output is helpful when checking route decisions in the terminal.

## Algorithms in the codebase

### Geocoding

All addresses are translated into latitude/longitude coordinates using OpenRouteService geocoding.

### Distance matrix retrieval

The app requests a full pairwise matrix of travel distances and durations from OpenRouteService.

This matrix is the basis for route building and schedule simulation.

### Vehicle assignment

Deliveries are sorted by priority and assigned to vehicles according to business constraints:

- refrigerated vans for cold deliveries
- large vans for suburban jobs when possible
- small vans for city jobs when possible

### Driver assignment

Drivers are assigned to vehicles with a refrigerated-driver preference for refrigerated vans.

### Route heuristic

The route builder is greedy and deterministic:

- critical deliveries first
- nearest stop next

This keeps the output readable and avoids the instability that can come from more aggressive optimization methods.

### Time-window simulation

The schedule checker uses the matrix durations and service times to detect:

- late arrivals
- shift overruns
- time-window conflicts

## Project structure

- `dashboard.py` — Streamlit user interface, maps, tables, report generation, and route display
- `main.py` — Core data loading, geocoding, assignment, routing, simulation, and terminal printing
- `geocache.py` — Cached geocoding support
- `routing.py` — Legacy routing module kept for reference only; it is not the active dashboard route source
- `README.md` — Project documentation
- `requirements.txt` — Python dependencies

## Workbook format

### Delivery workbook

Required sheets:

- `warehouse`
	- `id`
	- `name`
	- `address`
- `orders`
	- `id`
	- `name`
	- `address`
	- `priority`
	- `is_cold`
	- `is_suburban`
	- `boxes`
	- `time_window_start`
	- `time_window_end`

### Fleet workbook

Required sheets:

- `vehicles`
	- `id`
	- `type`
	- `label`
	- `max_stops`
- `drivers`
	- `id`
	- `name`
	- `certified_refrigerated`
	- `shift_start`
	- `max_hours`

## Installation

Install the dependencies with:

```bash
pip install -r requirements.txt
```

## Run the app

```bash
streamlit run dashboard.py
```

## Typical workflow

1. Open the app.
2. Upload a delivery workbook.
3. Upload a fleet workbook.
4. Review or edit the tables.
5. Click **Calculate routes**.
6. Inspect:
	 - the combined map
	 - the per-vehicle tabs
	 - the terminal output
	 - the HTML report

## Troubleshooting

### The map is not showing

- Make sure you clicked **Calculate routes**.
- Check that the workbook contains valid addresses.
- Confirm that the machine has internet access for OpenStreetMap tiles and OpenRouteService requests.

### Routes cannot be built

- Ensure the warehouse has a name and address.
- Ensure each delivery has an address.
- Verify that the workbook sheets use the expected column names.

### Geocoding fails

- Some addresses may be incomplete or ambiguous.
- Try adding more specific street, city, and postal-code details.

### Distance matrix request fails

- Check your network connection.
- Check that the OpenRouteService API is reachable.

## Notes

- The app no longer auto-loads sample data at startup.
- Routes are designed for clarity and operational control, not exact mathematical optimality.
- `routing.py` is preserved only as a legacy file; the dashboard uses `main.py`.
- The terminal output is intentionally verbose so route decisions can be audited.

## Example output

When you calculate routes, the app prints information such as:

- vehicle assignment decisions
- the raw stop order
- the final route order
- distance and duration summaries
- late delivery counts

This makes it easier to verify why a particular route was chosen.

## License

No license has been defined for this project yet.
