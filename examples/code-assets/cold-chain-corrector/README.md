# cold-chain-corrector

Telemetry cleanup + excursion detection for reefer-container cold chain.

- **Kalman filter** on temperature — smooths sensor noise without lag
- **Excursion detection** — windows where the smoothed temperature is
  out-of-spec for longer than `excursion_minutes` (FSMA / GDP pattern)
- **Door-event extraction** — contiguous door-open windows with total
  duration, compared against the product's `door_open_minutes` budget
- **Dwell-stop inference** — stationary GPS segments (very loose
  haversine threshold — 150m) used to flag loading-dock stops

Pure Go, no external deps. Designed to run as a sandboxed k8s Job
invoked per telemetry window — minutes of data in, structured
findings out.
