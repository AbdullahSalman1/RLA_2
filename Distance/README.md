# Delivery Dashboard

A Streamlit dashboard for the delivery routing project.

## Run

```bash
streamlit run dashboard.py
```

## Dashboard workflow

- Upload a delivery workbook in the sidebar, then click **Load selected files**.
- Upload a fleet workbook in the sidebar, then click **Load selected files**.
- Edit rows directly in the tables to add, remove, or change deliveries, vehicles, and drivers.
- Use **Reset to empty tables** if you want to start over.

## Expected workbook sheets

- Delivery workbook:
	- `warehouse` sheet with `id`, `name`, `address`
	- `orders` sheet with `id`, `name`, `address`, `priority`, `is_cold`, `is_suburban`, `boxes`, `time_window_start`, `time_window_end`
- Fleet workbook:
	- `vehicles` sheet with `id`, `type`, `label`, `max_stops`
	- `drivers` sheet with `id`, `name`, `certified_refrigerated`, `shift_start`, `max_hours`

## Notes

- The dashboard no longer auto-loads the local sample data at startup.
- You can upload a different workbook at any time and replace the current tables.
- Click **Calculate routes** to build the route plan, see the map, and open the full route report in a new tab.
