package main

import (
	"encoding/json"
	"io"
	"math"
	"os"
	"time"
)

type Reading struct {
	Timestamp string  `json:"timestamp"`
	TempC     float64 `json:"temp_c"`
	DoorOpen  bool    `json:"door_open,omitempty"`
	Lat       float64 `json:"lat,omitempty"`
	Lon       float64 `json:"lon,omitempty"`
}

type ProductSpec struct {
	SKU              string  `json:"sku"`
	Name             string  `json:"name"`
	MinC             float64 `json:"min_c"`
	MaxC             float64 `json:"max_c"`
	ExcursionMin     int     `json:"excursion_minutes"`
	DoorOpenMin      int     `json:"door_open_minutes"`
}

type Input struct {
	Readings    []Reading   `json:"readings"`
	ProductSpec ProductSpec `json:"product_spec"`
}

type SmoothedPoint struct {
	Timestamp string  `json:"timestamp"`
	TempC     float64 `json:"temp_c"`
}

type Excursion struct {
	Start       string  `json:"start"`
	End         string  `json:"end"`
	DurationMin float64 `json:"duration_min"`
	PeakTempC   float64 `json:"peak_temp_c"`
	Direction   string  `json:"direction"`
}

type DoorEvent struct {
	Start       string  `json:"start"`
	End         string  `json:"end"`
	DurationMin float64 `json:"duration_min"`
}

type Summary struct {
	MinSmoothedC       float64 `json:"min_smoothed_c"`
	MaxSmoothedC       float64 `json:"max_smoothed_c"`
	MeanSmoothedC      float64 `json:"mean_smoothed_c"`
	TotalExcursionMin  float64 `json:"total_excursion_min"`
	TotalDoorOpenMin   float64 `json:"total_door_open_min"`
	DwellStops         int     `json:"dwell_stops"`
	SpoilageRiskFlag   bool    `json:"spoilage_risk_flag"`
}

type Output struct {
	Smoothed    []SmoothedPoint `json:"smoothed"`
	Excursions  []Excursion     `json:"excursions"`
	DoorEvents  []DoorEvent     `json:"door_events"`
	Summary     Summary         `json:"summary"`
	ProductSKU  string          `json:"product_sku"`
	ReadingCount int            `json:"reading_count"`
}

// ── 1-D Kalman filter ────────────────────────────────────────────────────
//
// State = measured temperature; we don't model the derivative (reefer
// thermal inertia makes a constant-velocity model marginally better but
// substantially more brittle to sparse sampling). Constant-level model
// with process + measurement noise tuned for reefer telemetry (readings
// every 1–5 minutes, sensor accuracy ±0.3 °C).
func kalman(zs []float64) []float64 {
	n := len(zs)
	if n == 0 {
		return zs
	}
	// Process noise — how much we believe the true temp can drift
	// between two consecutive readings. Set modest.
	Q := 0.05
	// Measurement noise — sensor variance.
	R := 0.25

	x := zs[0]
	P := 1.0
	out := make([]float64, n)
	for i := 0; i < n; i++ {
		// Predict
		P = P + Q
		// Update
		K := P / (P + R)
		x = x + K*(zs[i]-x)
		P = (1 - K) * P
		out[i] = x
	}
	return out
}

func parseTS(s string) time.Time {
	// Accept both Z and +00:00
	if t, err := time.Parse(time.RFC3339Nano, s); err == nil {
		return t
	}
	if t, err := time.Parse(time.RFC3339, s); err == nil {
		return t
	}
	return time.Time{}
}

func haversineMeters(lat1, lon1, lat2, lon2 float64) float64 {
	const R = 6371000.0
	rad := math.Pi / 180.0
	dLat := (lat2 - lat1) * rad
	dLon := (lon2 - lon1) * rad
	a := math.Sin(dLat/2)*math.Sin(dLat/2) +
		math.Cos(lat1*rad)*math.Cos(lat2*rad)*
			math.Sin(dLon/2)*math.Sin(dLon/2)
	return 2 * R * math.Asin(math.Min(1.0, math.Sqrt(a)))
}

func must(err error) {
	if err != nil {
		_, _ = os.Stderr.WriteString("cold-chain error: " + err.Error() + "\n")
		os.Exit(1)
	}
}

func main() {
	raw, err := io.ReadAll(os.Stdin)
	must(err)
	var in Input
	must(json.Unmarshal(raw, &in))

	if len(in.Readings) < 4 {
		must(json.NewEncoder(os.Stdout).Encode(map[string]any{
			"error": "need at least 4 readings",
		}))
		os.Exit(1)
	}
	spec := in.ProductSpec
	if spec.ExcursionMin <= 0 {
		spec.ExcursionMin = 10
	}
	if spec.DoorOpenMin <= 0 {
		spec.DoorOpenMin = 5
	}

	// ── Extract raw temps & timestamps ───────────────────────────
	temps := make([]float64, len(in.Readings))
	times := make([]time.Time, len(in.Readings))
	for i, r := range in.Readings {
		temps[i] = r.TempC
		times[i] = parseTS(r.Timestamp)
	}
	smoothed := kalman(temps)
	outSmoothed := make([]SmoothedPoint, len(smoothed))
	for i, v := range smoothed {
		outSmoothed[i] = SmoothedPoint{Timestamp: in.Readings[i].Timestamp, TempC: math.Round(v*100) / 100}
	}

	// ── Excursion detection ──────────────────────────────────────
	// Build contiguous runs where smoothed temp is out-of-spec.
	var excursions []Excursion
	var runStart int = -1
	var runDir string
	var runPeak float64
	closeRun := func(endIdx int) {
		if runStart < 0 {
			return
		}
		startT := times[runStart]
		endT := times[endIdx]
		dur := endT.Sub(startT).Minutes()
		if dur >= float64(spec.ExcursionMin) {
			excursions = append(excursions, Excursion{
				Start:       in.Readings[runStart].Timestamp,
				End:         in.Readings[endIdx].Timestamp,
				DurationMin: math.Round(dur*10) / 10,
				PeakTempC:   math.Round(runPeak*100) / 100,
				Direction:   runDir,
			})
		}
		runStart = -1
		runDir = ""
		runPeak = 0
	}
	for i, t := range smoothed {
		var dir string
		if t > spec.MaxC {
			dir = "above"
		} else if t < spec.MinC {
			dir = "below"
		}
		if dir != "" {
			if runStart < 0 {
				runStart = i
				runDir = dir
				runPeak = t
			} else if dir != runDir {
				// Direction flipped — close the current run, open new one.
				closeRun(i - 1)
				runStart = i
				runDir = dir
				runPeak = t
			} else {
				if (dir == "above" && t > runPeak) ||
					(dir == "below" && t < runPeak) {
					runPeak = t
				}
			}
		} else if runStart >= 0 {
			closeRun(i - 1)
		}
	}
	if runStart >= 0 {
		closeRun(len(smoothed) - 1)
	}

	// ── Door events ──────────────────────────────────────────────
	var doors []DoorEvent
	doorStart := -1
	for i, r := range in.Readings {
		if r.DoorOpen {
			if doorStart < 0 {
				doorStart = i
			}
		} else {
			if doorStart >= 0 {
				dur := times[i].Sub(times[doorStart]).Minutes()
				doors = append(doors, DoorEvent{
					Start:       in.Readings[doorStart].Timestamp,
					End:         in.Readings[i].Timestamp,
					DurationMin: math.Round(dur*10) / 10,
				})
				doorStart = -1
			}
		}
	}
	if doorStart >= 0 {
		last := len(in.Readings) - 1
		dur := times[last].Sub(times[doorStart]).Minutes()
		doors = append(doors, DoorEvent{
			Start:       in.Readings[doorStart].Timestamp,
			End:         in.Readings[last].Timestamp,
			DurationMin: math.Round(dur*10) / 10,
		})
	}

	// ── Dwell stops from GPS ─────────────────────────────────────
	// Stationary segments where movement < 150m from the previous point
	// for at least 3 consecutive readings.
	dwellStops := 0
	staticRun := 0
	for i := 1; i < len(in.Readings); i++ {
		prev := in.Readings[i-1]
		curr := in.Readings[i]
		if prev.Lat == 0 && prev.Lon == 0 {
			staticRun = 0
			continue
		}
		if haversineMeters(prev.Lat, prev.Lon, curr.Lat, curr.Lon) < 150.0 {
			staticRun++
			if staticRun == 3 {
				dwellStops++
			}
		} else {
			staticRun = 0
		}
	}

	// ── Summary ──────────────────────────────────────────────────
	minT, maxT := smoothed[0], smoothed[0]
	var sumT float64
	for _, v := range smoothed {
		if v < minT {
			minT = v
		}
		if v > maxT {
			maxT = v
		}
		sumT += v
	}
	var totalExcursion float64
	for _, e := range excursions {
		totalExcursion += e.DurationMin
	}
	var totalDoor float64
	for _, d := range doors {
		totalDoor += d.DurationMin
	}
	risk := totalExcursion > 0 || totalDoor > float64(spec.DoorOpenMin)

	out := Output{
		Smoothed:   outSmoothed,
		Excursions: excursions,
		DoorEvents: doors,
		Summary: Summary{
			MinSmoothedC:      math.Round(minT*100) / 100,
			MaxSmoothedC:      math.Round(maxT*100) / 100,
			MeanSmoothedC:     math.Round((sumT/float64(len(smoothed)))*100) / 100,
			TotalExcursionMin: math.Round(totalExcursion*10) / 10,
			TotalDoorOpenMin:  math.Round(totalDoor*10) / 10,
			DwellStops:        dwellStops,
			SpoilageRiskFlag:  risk,
		},
		ProductSKU:   spec.SKU,
		ReadingCount: len(in.Readings),
	}

	enc := json.NewEncoder(os.Stdout)
	must(enc.Encode(out))
}
