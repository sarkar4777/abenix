package main

import (
	"encoding/json"
	"io"
	"math"
	"math/cmplx"
	"os"
	"sort"
)

type Input struct {
	Samples      []float64 `json:"samples"`
	SampleRateHz int       `json:"sample_rate_hz"`
	SensorID     string    `json:"sensor_id"`
	ShaftRPM     float64   `json:"shaft_rpm,omitempty"`
}

type FreqBin struct {
	Hz        float64 `json:"hz"`
	Amplitude float64 `json:"amplitude"`
}

type FaultScores struct {
	Bearing      float64 `json:"bearing"`
	Imbalance    float64 `json:"imbalance"`
	Misalignment float64 `json:"misalignment"`
	Cavitation   float64 `json:"cavitation"`
}

type Output struct {
	RMS            float64     `json:"rms"`
	Peak           float64     `json:"peak"`
	CrestFactor    float64     `json:"crest_factor"`
	Kurtosis       float64     `json:"kurtosis"`
	DominantFreqs  []FreqBin   `json:"dominant_freqs"`
	FaultScores    FaultScores `json:"fault_scores"`
	ISO10816Zone   string      `json:"iso_10816_zone,omitempty"`
	SensorID       string      `json:"sensor_id"`
	SampleCount    int         `json:"sample_count"`
}

// ── Helpers ─────────────────────────────────────────────────────────────

func movingAvg(x []float64, window int) []float64 {
	if window <= 1 || window > len(x) {
		return x
	}
	out := make([]float64, len(x))
	var sum float64
	for i := 0; i < window; i++ {
		sum += x[i]
	}
	seed := sum / float64(window)
	for i := 0; i < window; i++ {
		out[i] = x[i] - seed
	}
	for i := window; i < len(x); i++ {
		sum += x[i] - x[i-window]
		out[i] = x[i] - sum/float64(window)
	}
	return out
}

func medianFilter(x []float64, kernel int) []float64 {
	if kernel < 3 || kernel > len(x) {
		return x
	}
	out := make([]float64, len(x))
	half := kernel / 2
	buf := make([]float64, kernel)
	for i := range x {
		lo, hi := i-half, i+half
		if lo < 0 {
			lo = 0
		}
		if hi >= len(x) {
			hi = len(x) - 1
		}
		n := hi - lo + 1
		copy(buf, x[lo:lo+n])
		sub := make([]float64, n)
		copy(sub, buf[:n])
		sort.Float64s(sub)
		out[i] = sub[n/2]
	}
	return out
}

func rms(x []float64) float64 {
	var s float64
	for _, v := range x {
		s += v * v
	}
	return math.Sqrt(s / float64(len(x)))
}

func peak(x []float64) float64 {
	var p float64
	for _, v := range x {
		if math.Abs(v) > p {
			p = math.Abs(v)
		}
	}
	return p
}

func mean(x []float64) float64 {
	var s float64
	for _, v := range x {
		s += v
	}
	return s / float64(len(x))
}

func stddev(x []float64, m float64) float64 {
	var s float64
	for _, v := range x {
		s += (v - m) * (v - m)
	}
	return math.Sqrt(s / float64(len(x)))
}

// Excess kurtosis (normal distribution ≈ 0). Impulsive vibration from
// bearing spalls pushes kurtosis well above 3.
func kurtosis(x []float64) float64 {
	m := mean(x)
	sd := stddev(x, m)
	if sd == 0 {
		return 0
	}
	var s float64
	for _, v := range x {
		z := (v - m) / sd
		s += z * z * z * z
	}
	return s/float64(len(x)) - 3.0
}

// nextPow2 rounds up to the next power of 2 — needed for the
// radix-2 Cooley–Tukey FFT below.
func nextPow2(n int) int {
	p := 1
	for p < n {
		p <<= 1
	}
	return p
}

func fft(x []complex128) {
	n := len(x)
	if n <= 1 {
		return
	}
	// Bit-reversal permutation
	j := 0
	for i := 1; i < n; i++ {
		bit := n >> 1
		for ; j&bit != 0; bit >>= 1 {
			j ^= bit
		}
		j ^= bit
		if i < j {
			x[i], x[j] = x[j], x[i]
		}
	}
	// Cooley–Tukey
	for size := 2; size <= n; size <<= 1 {
		half := size >> 1
		w := complex(math.Cos(-2*math.Pi/float64(size)), math.Sin(-2*math.Pi/float64(size)))
		for start := 0; start < n; start += size {
			ww := complex(1, 0)
			for k := 0; k < half; k++ {
				t := ww * x[start+k+half]
				u := x[start+k]
				x[start+k] = u + t
				x[start+k+half] = u - t
				ww *= w
			}
		}
	}
}

func dominantFreqs(samples []float64, sampleRate int, topK int) []FreqBin {
	n := nextPow2(len(samples))
	cs := make([]complex128, n)
	// Hann window + zero-pad
	for i, v := range samples {
		w := 0.5 * (1.0 - math.Cos(2*math.Pi*float64(i)/float64(len(samples)-1)))
		cs[i] = complex(v*w, 0)
	}
	fft(cs)
	// Only first N/2 bins are meaningful (Nyquist)
	half := n / 2
	bins := make([]FreqBin, 0, half)
	for k := 0; k < half; k++ {
		amp := cmplx.Abs(cs[k]) / float64(n/2)
		hz := float64(k) * float64(sampleRate) / float64(n)
		bins = append(bins, FreqBin{Hz: hz, Amplitude: amp})
	}
	sort.Slice(bins, func(i, j int) bool { return bins[i].Amplitude > bins[j].Amplitude })
	if topK > len(bins) {
		topK = len(bins)
	}
	// Exclude DC bin if it snuck to the top.
	filtered := make([]FreqBin, 0, topK)
	for _, b := range bins {
		if b.Hz < 0.5 {
			continue
		}
		filtered = append(filtered, b)
		if len(filtered) >= topK {
			break
		}
	}
	return filtered
}

// amplitudeAt returns the FFT amplitude near a target frequency ±tol Hz.
func amplitudeAt(bins []FreqBin, targetHz, tolHz float64) float64 {
	var best float64
	for _, b := range bins {
		if math.Abs(b.Hz-targetHz) <= tolHz && b.Amplitude > best {
			best = b.Amplitude
		}
	}
	return best
}

func highFreqEnergy(samples []float64, sampleRate int, cutoffHz float64) float64 {
	n := nextPow2(len(samples))
	cs := make([]complex128, n)
	for i, v := range samples {
		cs[i] = complex(v, 0)
	}
	fft(cs)
	half := n / 2
	cutBin := int(cutoffHz * float64(n) / float64(sampleRate))
	if cutBin < 0 {
		cutBin = 0
	}
	if cutBin > half {
		cutBin = half
	}
	var energy float64
	for k := cutBin; k < half; k++ {
		a := cmplx.Abs(cs[k]) / float64(n/2)
		energy += a * a
	}
	return math.Sqrt(energy)
}

// iso10816Zone maps velocity-RMS (mm/s) to ISO 10816-3 zones for
// medium-size pumps on rigid foundations. We approximate velocity
// from acceleration RMS assuming sinusoid at shaft rpm.
func iso10816Zone(accelRMS, shaftRPM float64) string {
	if shaftRPM <= 0 {
		return ""
	}
	freq := shaftRPM / 60.0
	// v = a / (2*pi*f), convert g to mm/s² (1 g ≈ 9806.65 mm/s²)
	velMMS := (accelRMS * 9806.65) / (2 * math.Pi * freq)
	switch {
	case velMMS <= 1.8:
		return "A"
	case velMMS <= 4.5:
		return "B"
	case velMMS <= 11.2:
		return "C"
	default:
		return "D"
	}
}

// clamp01 squashes any real number into [0, 1] using a soft logistic.
func clamp01(x float64) float64 {
	if x < 0 {
		x = 0
	}
	return 1.0 - math.Exp(-x)
}

// ── Main ────────────────────────────────────────────────────────────────

func must(err error) {
	if err != nil {
		_, _ = os.Stderr.WriteString("pump-dsp error: " + err.Error() + "\n")
		os.Exit(1)
	}
}

func main() {
	raw, err := io.ReadAll(os.Stdin)
	must(err)
	var in Input
	must(json.Unmarshal(raw, &in))

	if len(in.Samples) < 32 {
		must(json.NewEncoder(os.Stdout).Encode(map[string]any{
			"error": "need at least 32 samples",
		}))
		os.Exit(1)
	}

	// Pipeline: detrend → denoise → metrics → fft → scores
	window := len(in.Samples) / 8
	if window < 3 {
		window = 3
	}
	detrended := movingAvg(in.Samples, window)
	cleaned := medianFilter(detrended, 5)

	r := rms(cleaned)
	p := peak(cleaned)
	cf := 0.0
	if r > 0 {
		cf = p / r
	}
	k := kurtosis(cleaned)

	bins := dominantFreqs(cleaned, in.SampleRateHz, 5)

	scores := FaultScores{}
	if in.ShaftRPM > 0 {
		shaftHz := in.ShaftRPM / 60.0
		tol := math.Max(0.5, shaftHz*0.05)
		a1x := amplitudeAt(bins, shaftHz, tol)
		a2x := amplitudeAt(bins, 2*shaftHz, tol)
		scores.Imbalance = clamp01(a1x / (r + 1e-9) * 2.0)
		scores.Misalignment = clamp01(a2x / (r + 1e-9) * 2.0)
	}
	hfe := highFreqEnergy(cleaned, in.SampleRateHz, float64(in.SampleRateHz)/4.0)
	// bearing: impulsive (kurtosis) + high-freq
	scores.Bearing = clamp01((math.Max(0, k)/5.0)*0.6 + (hfe/(r+1e-9))*0.4)
	// cavitation: broadband high-freq without strong line content
	maxLine := 0.0
	for _, b := range bins {
		if b.Amplitude > maxLine {
			maxLine = b.Amplitude
		}
	}
	scores.Cavitation = clamp01((hfe / (r + 1e-9)) * (1.0 - math.Min(1.0, maxLine/(r+1e-9))))

	out := Output{
		RMS:           r,
		Peak:          p,
		CrestFactor:   cf,
		Kurtosis:      k,
		DominantFreqs: bins,
		FaultScores:   scores,
		ISO10816Zone:  iso10816Zone(r, in.ShaftRPM),
		SensorID:      in.SensorID,
		SampleCount:   len(in.Samples),
	}

	enc := json.NewEncoder(os.Stdout)
	must(enc.Encode(out))
}
