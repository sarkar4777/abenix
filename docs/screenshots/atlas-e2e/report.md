# Atlas E2E results

**28 passed · 2 failed**

Run against `http://localhost:3000` on 2026-04-29T15:57:01.570Z.

| # | Step | Result | ms | Detail |
|---|------|--------|----|--------|
| 1 | login | ✅ | 6047 |  |
| 2 | navigate to /atlas | ✅ | 2141 |  |
| 3 | create new graph via PromptModal | ✅ | 2858 |  |
| 4 | verify onboarding cards | ✅ | 7 |  |
| 5 | add concept manually | ✅ | 2320 |  |
| 6 | add instance manually | ✅ | 2206 |  |
| 7 | NL parse — review ribbon | ✅ | 18746 |  |
| 8 | apply NL ops | ✅ | 2539 |  |
| 9 | open Starters modal | ✅ | 838 |  |
| 10 | import FIBO Core starter | ✅ | 4111 |  |
| 11 | relayout — circle | ✅ | 2546 |  |
| 12 | relayout — grid | ✅ | 2542 |  |
| 13 | relayout — semantic | ✅ | 2553 |  |
| 14 | open Visual Query panel | ✅ | 854 |  |
| 15 | run visual query | ✅ | 1559 |  |
| 16 | select first node | ✅ | 663 |  |
| 17 | inspector tab — relations | ✅ | 460 |  |
| 18 | inspector tab — properties | ✅ | 460 |  |
| 19 | inspector tab — instances | ✅ | 458 |  |
| 20 | inspector tab — lineage | ✅ | 449 |  |
| 21 | inspector tab — schema | ✅ | 454 |  |
| 22 | capture snapshot | ✅ | 2355 |  |
| 23 | open History panel | ✅ | 1047 |  |
| 24 | JSON-LD export download | ✅ | 411 |  |
| 25 | drop-to-extract — file upload | ✅ | 27365 |  |
| 26 | apply extracted ops | ✅ | 3049 |  |
| 27 | ConfirmModal — cancel deletes nothing | ✅ | 2400 |  |
| 28 | open KB picker | ✅ | 1577 |  |
| 29 | bind first KB | ❌ | 6 | no KBs in tenant — cannot test KB binding |
| 30 | delete the test graph | ❌ | 30019 | locator.hover: Timeout 30000ms exceeded. |