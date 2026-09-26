# disproportionality

PRR, ROR and EBGM for one drug-event pair, from its 2x2 contingency counts.

```bash
echo '{"a": 12, "b": 3400, "c": 480, "d": 295000}' | python main.py
```

| Measure | What it answers |
|---|---|
| PRR | How much more often this event is reported for this drug than for the rest of the database |
| ROR | The same question as an odds ratio, which behaves better on rare events |
| EBGM | Observed over expected, shrunk toward the null in proportion to how little data supports it |

Each comes with its lower bound, and the bound is what matters. A PRR of 8
whose 95% lower bound is 0.9 is not a finding.

## The a < 3 rule

No pair is called a signal on fewer than three reports, however large the
ratio. Two reports against an expectation of 0.01 gives a PRR in the hundreds
and means nothing. The rule is applied before any other, and `rule` says so
explicitly rather than leaving a caller to wonder why a huge ratio returned
`crosses_threshold: false`.

## Why this is code and not a model

These are closed-form expressions. An earlier cut of this app trained a
gradient-boosted classifier to predict the same threshold and it scored level
with the arithmetic, which is what should happen when you ask a model to
approximate a formula it has been handed the inputs to. The model was dropped
and the formula kept.

What did survive as a model is the part that is genuinely not arithmetic:
which cases a medical reviewer escalates. That lives in `aimodels/` and beats
a hand-written rule by a measurable margin.

## Reading the output

`caveat` is returned on every call for a reason. Disproportionality measures
**reporting**, not risk. A high ratio means the pair turns up more often than
expected given everything else in the database — reporting bias, media
attention and indication all produce that too.
