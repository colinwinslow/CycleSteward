# Charge session fixtures

Fixtures should be small CSV files used by the pure-core analyzer before real
Home Assistant entities exist.

Proposed columns for the first slice:

```csv
timestamp,power_w,temperature_c
2026-06-08T18:00:00-07:00,1.8,21.0
2026-06-08T18:01:00-07:00,69.2,21.0
```

`power_w` is wall power from the metering smart plug. The analyzer subtracts the
learned idle watts before integrating active Wh.
