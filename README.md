# symmetric-mirror-gate-research

Symmetric-mirror gate research (Part-16): UP-block mirrors, inverted UP gate, and 3-way threshold-gate tests.

## Why it exists

The 5-minute crypto bot already runs *DN-suppression* gates (e.g. Part 15 blocks DN fires when BN ≥ +4% at cd=290; `dn_live` blocks DN when `up_ask` stays high). This repo answers the obvious follow-up: **do the symmetric mirrors hold for the UP side?** Each script backtests a candidate UP-blocking gate against historical fires, measures saves-vs-costs, and runs the full statistical battery (OOS split, binomial, Bayesian, Kelly, permutation) before anything is considered for the live bot.

## What's inside

| Script | Gate hypothesis tested |
| --- | --- |
| `part16_sweep_gateaware.py` | Part-16 mirror of Part-15: block UP fires when `BN ≤ -X%` at a `cd` checkpoint (sweeps cd 290→150 × thresholds -2…-8%). Gate-aware (excludes already-held/blocked fires). Full OOS + Bayesian + Kelly + binomial. |
| `sym_dn_live_sweep.py` | Symmetric `dn_live`: block UP when `dn_ask ≥ threshold` for 2 consecutive ~10s samples (sustained DN dominance). Sweeps 0.55–0.70 with Bonferroni correction, permutation test, and gate-trigger-cd distribution. |
| `inverted_up_gate.py` | Investigates a gate that blocked 7 UP fires — all winners. Tests current vs **inverted** (DN-dominant → *allow* UP as a reversal) vs double-inverted logic, plus early/late timing splits. Pure stdlib. |
| `test_3way_gate.py` | Layers threshold UP gates on top of the existing two-stage system using real opp-side book prices from ticks. Reports ALL / LIVE-ELIGIBLE / SHADOW splits, per-strategy deltas, and market-level trigger accuracy. Pure stdlib. |

All four are standalone, read-only backtests — they print tables to stdout and write nothing.

## Requirements

- Python 3.9+
- `numpy`, `scipy` — required by `part16_sweep_gateaware.py` and `sym_dn_live_sweep.py` only. `inverted_up_gate.py` and `test_3way_gate.py` use the standard library only.
- No wallet, key, or network access — these scripts do not trade or touch funds.

```bash
pip install numpy scipy
```

## Usage

Run from the bot directory so the default data paths resolve (`part16_*` and `sym_dn_*` expect the files at `~/polymarket-bot/`):

```bash
# Part-16 BN mirror sweep (cd × BN-threshold grid, OOS + stat battery)
python3 part16_sweep_gateaware.py

# Symmetric dn_live: sustained-dn_ask UP block, Bonferroni-corrected
python3 sym_dn_live_sweep.py

# 3-way threshold gate on tick-level book data, ALL/LIVE/SHADOW split
python3 test_3way_gate.py

# Inverted UP-gate study (takes the history file as an arg)
python3 inverted_up_gate.py market_history.jsonl
```

## Data

These scripts load `market_history.jsonl` (tick + book columns) and `market_recap_history.jsonl` (fires + winner) from the **private `polymarket-data` repo**. `part16_sweep_gateaware.py` and `sym_dn_live_sweep.py` hardcode `~/polymarket-bot/`; `test_3way_gate.py` reads from its own directory; `inverted_up_gate.py` takes the path as `argv[1]`. Place or symlink the data files accordingly. Per `.gitignore`, no `*.jsonl` data is committed.

> Private research software. No warranty; trades/handles real funds at your own risk.
