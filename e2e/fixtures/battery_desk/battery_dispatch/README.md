# Battery dispatch

Decides one hour of battery dispatch from a price forecast. Discharges when the
price is at or above `discharge_above`, charges when it is at or below
`charge_below`, holds in between. State of charge stays between 10 and 90 percent.

Reads JSON on stdin, writes JSON on stdout:
`{action, mw, expected_revenue_eur, revenue_low_eur, revenue_high_eur, reason}`.
Standard library only.
