# symmetric-mirror-gate-research

Part-16 backtests for UP-side fire-suppression gates: mirrors of the existing DN-suppression gates, plus an inverted-gate study and a 3-way threshold-gate test.

The 5-minute crypto bot runs DN-suppression gates (Part 15 blocks DN when BN >= +4% at cd=290; `dn_live` blocks DN when `up_ask` stays high). These scripts test whether the symmetric UP-blocking versions hold up. Each one backtests a candidate UP gate against historical fires, measures saves vs costs, and runs an OOS split plus binomial, Bayesian, Kelly, and permutation tests.

## Scripts

| Script | What it tests |
| --- | --- |
| `part16_sweep_gateaware.py` | Block UP fires when `BN <= -X%` at a `cd` checkpoint. Sweeps cd 290..150 x thresholds -2..-8%. Excludes already-held/blocked fires. OOS + Bayesian + Kelly + binomial. |
| `sym_dn_live_sweep.py` | Block UP when `dn_ask >= threshold` for 2 consecutive ~10s samples. Sweeps 0.55..0.70 with Bonferroni correction, permutation test, gate-trigger-cd distribution. |
| `inverted_up_gate.py` | A gate blocked 7 UP fires, all winners. Tests current vs inverted (DN-dominant allows UP as a reversal) vs double-inverted logic, with early/late timing splits. Stdlib only. |
| `test_3way_gate.py` | Layers threshold UP gates on the two-stage system using real opp-side book prices from ticks. Reports ALL / LIVE-ELIGIBLE / SHADOW splits, per-strategy deltas, market-level trigger accuracy. Stdlib only. |

All four are read-only. They print tables to stdout and write nothing. Read-only; no credentials, network, or funds involved.

## Requirements

Python 3.9+. `numpy` and `scipy` for `part16_sweep_gateaware.py` and `sym_dn_live_sweep.py`. The other two use stdlib only.

```bash
pip install numpy scipy
```

## Usage

```bash
python3 part16_sweep_gateaware.py
python3 sym_dn_live_sweep.py
python3 test_3way_gate.py
python3 inverted_up_gate.py market_history.jsonl
```

## Data

Loads `market_history.jsonl` (tick + book columns) and `market_recap_history.jsonl` (fires + winner) from the private `polymarket-data` repo. `part16_sweep_gateaware.py` and `sym_dn_live_sweep.py` read `$DATA_DIR`; `test_3way_gate.py` reads its own directory; `inverted_up_gate.py` takes the path as `argv[1]`. Place or symlink the files accordingly. No `*.jsonl` is committed (see `.gitignore`).
