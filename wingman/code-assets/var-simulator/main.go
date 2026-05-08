// Wingman VaR Simulator — Monte Carlo Value-at-Risk engine in Go.
//
// Reads a JSON envelope on stdin:
//
//   {
//     "rule":          { "corridor_id": "USGC-NWE", "side": "sell_forward",
//                        "size_mt": 10000, "trigger": { "value": 30, ... } },
//     "spot_history":  [ 0.92, 0.94, 0.91, ... ],   // recent weekly EIA spot ($/gal)
//     "horizon_days":  30,
//     "n_simulations": 10000,
//     "freight_usd_mt": 63                         // bunker-derived
//   }
//
// Writes a JSON envelope on stdout:
//
//   {
//     "p50_usd": ..., "p95_usd": ..., "p99_usd": ...,
//     "expected_shortfall_p99_usd": ...,
//     "mean_usd": ..., "std_usd": ...,
//     "histogram": [ { "bin_low": ..., "bin_high": ..., "count": ... }, ... ],
//     "n_simulations": ..., "horizon_days": ...,
//     "narrative": "..."
//   }
//
// Designed for the platform's code-runner sandbox: zero external deps,
// reads stdin, writes stdout, exits 0/1.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"math/rand"
	"os"
	"sort"
	"time"
)

type Trigger struct {
	Metric    string  `json:"metric"`
	Operator  string  `json:"operator"`
	Value     float64 `json:"value"`
}

type Rule struct {
	CorridorID string  `json:"corridor_id"`
	Side       string  `json:"side"`
	SizeMT     float64 `json:"size_mt"`
	Trigger    Trigger `json:"trigger"`
}

type Input struct {
	Rule           Rule      `json:"rule"`
	SpotHistory    []float64 `json:"spot_history"`
	HorizonDays    int       `json:"horizon_days"`
	NSimulations   int       `json:"n_simulations"`
	FreightUSDPerMT float64  `json:"freight_usd_mt"`
}

type HistoBucket struct {
	BinLow  float64 `json:"bin_low"`
	BinHigh float64 `json:"bin_high"`
	Count   int     `json:"count"`
}

type Output struct {
	P50USD                   float64       `json:"p50_usd"`
	P95USD                   float64       `json:"p95_usd"`
	P99USD                   float64       `json:"p99_usd"`
	ExpectedShortfallP99USD  float64       `json:"expected_shortfall_p99_usd"`
	MeanUSD                  float64       `json:"mean_usd"`
	StdUSD                   float64       `json:"std_usd"`
	Histogram                []HistoBucket `json:"histogram"`
	NSimulations             int           `json:"n_simulations"`
	HorizonDays              int           `json:"horizon_days"`
	Narrative                string        `json:"narrative"`
	DataSources              []string      `json:"data_sources"`
}

// estimateVolatility computes annualised stdev of log-returns from a
// price series. Sane fallback (~25% annualised) when too few samples.
func estimateVolatility(prices []float64) float64 {
	if len(prices) < 5 {
		return 0.25
	}
	rets := make([]float64, 0, len(prices)-1)
	for i := 1; i < len(prices); i++ {
		if prices[i-1] <= 0 {
			continue
		}
		rets = append(rets, math.Log(prices[i]/prices[i-1]))
	}
	if len(rets) < 2 {
		return 0.25
	}
	mean := 0.0
	for _, r := range rets {
		mean += r
	}
	mean /= float64(len(rets))
	v := 0.0
	for _, r := range rets {
		v += (r - mean) * (r - mean)
	}
	v /= float64(len(rets) - 1)
	// Series is weekly; scale to annualised — ~52 weekly periods/year.
	return math.Sqrt(v) * math.Sqrt(52.0)
}

// simulatePnL runs one GBM walk over horizon_days and returns total $ P&L
// for the rule. Sell-forward: positive when prices fall below the locked-
// in spot (trader pockets the spread). Buy-forward: opposite.
func simulatePnL(in *Input, vol float64, rng *rand.Rand) float64 {
	if len(in.SpotHistory) == 0 {
		return 0
	}
	startSpot := in.SpotHistory[len(in.SpotHistory)-1]
	// Convert $/gal -> $/MT (propane: 1 MT ≈ 524 gal).
	startUSDPerMT := startSpot * 524.0
	dailyVol := vol / math.Sqrt(252.0)
	dailyDrift := -0.5 * dailyVol * dailyVol // martingale-equivalent

	price := startUSDPerMT
	for d := 0; d < in.HorizonDays; d++ {
		shock := rng.NormFloat64()
		price *= math.Exp(dailyDrift + dailyVol*shock)
	}
	endUSDPerMT := price

	// Net P&L: trader locked in `startUSDPerMT - freight` as the realised
	// $/MT. If the market closes lower (sell-forward win), they keep the
	// spread × size. If higher, they lose.
	freight := in.FreightUSDPerMT
	if freight == 0 {
		freight = 63 // typical USGC->NWE bunker-derived estimate
	}

	switch in.Rule.Side {
	case "sell_forward":
		return (startUSDPerMT - freight - endUSDPerMT) * in.Rule.SizeMT
	case "buy_forward":
		return (endUSDPerMT - startUSDPerMT - freight) * in.Rule.SizeMT
	default:
		// Treat unknown sides as a flat directional bet.
		return (endUSDPerMT - startUSDPerMT) * in.Rule.SizeMT
	}
}

func percentile(sorted []float64, p float64) float64 {
	if len(sorted) == 0 {
		return 0
	}
	if p <= 0 {
		return sorted[0]
	}
	if p >= 100 {
		return sorted[len(sorted)-1]
	}
	idx := int(math.Round(p / 100.0 * float64(len(sorted)-1)))
	if idx < 0 {
		idx = 0
	}
	if idx >= len(sorted) {
		idx = len(sorted) - 1
	}
	return sorted[idx]
}

func histogram(values []float64, bins int) []HistoBucket {
	if len(values) == 0 || bins <= 0 {
		return nil
	}
	lo, hi := values[0], values[0]
	for _, v := range values {
		if v < lo {
			lo = v
		}
		if v > hi {
			hi = v
		}
	}
	if hi == lo {
		hi = lo + 1
	}
	width := (hi - lo) / float64(bins)
	out := make([]HistoBucket, bins)
	for i := 0; i < bins; i++ {
		out[i].BinLow = lo + float64(i)*width
		out[i].BinHigh = lo + float64(i+1)*width
	}
	for _, v := range values {
		idx := int((v - lo) / width)
		if idx >= bins {
			idx = bins - 1
		}
		if idx < 0 {
			idx = 0
		}
		out[idx].Count++
	}
	return out
}

func main() {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintln(os.Stderr, "stdin read:", err)
		os.Exit(1)
	}
	var in Input
	if err := json.Unmarshal(raw, &in); err != nil {
		fmt.Fprintln(os.Stderr, "JSON parse:", err)
		os.Exit(1)
	}
	if in.NSimulations == 0 {
		in.NSimulations = 10000
	}
	if in.HorizonDays == 0 {
		in.HorizonDays = 30
	}

	vol := estimateVolatility(in.SpotHistory)
	rng := rand.New(rand.NewSource(time.Now().UnixNano()))

	pnls := make([]float64, in.NSimulations)
	sum := 0.0
	for i := 0; i < in.NSimulations; i++ {
		v := simulatePnL(&in, vol, rng)
		pnls[i] = v
		sum += v
	}
	mean := sum / float64(in.NSimulations)
	var ssq float64
	for _, v := range pnls {
		ssq += (v - mean) * (v - mean)
	}
	std := math.Sqrt(ssq / float64(in.NSimulations))

	sort.Float64s(pnls)

	p50 := percentile(pnls, 50)
	p95 := percentile(pnls, 5)
	p99 := percentile(pnls, 1)

	// Expected shortfall at 99%: average of the worst 1%.
	cutoff := int(math.Max(1, math.Floor(float64(in.NSimulations)*0.01)))
	tailSum := 0.0
	for i := 0; i < cutoff; i++ {
		tailSum += pnls[i]
	}
	es99 := tailSum / float64(cutoff)

	out := Output{
		P50USD:                  p50,
		P95USD:                  p95,
		P99USD:                  p99,
		ExpectedShortfallP99USD: es99,
		MeanUSD:                 mean,
		StdUSD:                  std,
		Histogram:               histogram(pnls, 30),
		NSimulations:            in.NSimulations,
		HorizonDays:             in.HorizonDays,
		Narrative: fmt.Sprintf(
			"Monte Carlo VaR over %d days, %d sims. Median P&L $%.0f; 95%% VaR $%.0f; 99%% VaR $%.0f; expected shortfall (99%%) $%.0f. Annualised vol from history: %.1f%%.",
			in.HorizonDays, in.NSimulations, p50, p95, p99, es99, vol*100,
		),
		DataSources: []string{"EIA: PROPANE_USGC_MB", "GBM Monte Carlo (Go)"},
	}

	if err := json.NewEncoder(os.Stdout).Encode(out); err != nil {
		fmt.Fprintln(os.Stderr, "encode:", err)
		os.Exit(1)
	}
}
