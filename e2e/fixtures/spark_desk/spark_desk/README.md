# Spark desk

Prices a gas-fired plant's clean spark spread per delivery month, values the
spread as an option with Kirk's approximation, and stresses each month with P90
gas. The hedge call itself belongs to the desk's hedge policy rules.

Reads JSON on stdin, writes JSON on stdout. Standard library only.
