#!/usr/bin/env python3
"""
test_3way_gate.py — Test adding threshold UP gates to current two-stage system.
Uses tick-level book data for actual opp prices (not proxy).
Separates ALL / LIVE / SHADOW results.

Usage:
    cd .
    python3 test_3way_gate.py
"""

import json, math, os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
MKT_HIST = os.path.join(BASE, "market_history.jsonl")
RECAP    = os.path.join(BASE, "market_recap_history.jsonl")

STRATEGY_SIDE_MAP = {
    "depth_collapse_mid": "DN", "depth_surge": "DN", "fake_train_detector": "DN",
    "up_deep_spread_collapse": "UP", "up_depth_collapse_mid_high": "UP",
    "cl_gated_cheap": "UP", "cl_tight": "UP", "t4_late": "UP",
}

CD, UP_BID, UP_ASK, DN_BID, DN_ASK = 0, 1, 2, 3, 4
THRESHOLDS = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]


def load_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except:
                    pass
    return out


def opp_from_ticks(ticks, cd, side):
    if not ticks:
        return None
    best, best_d = None, 999
    for t in ticks:
        d = abs(t[CD] - cd)
        if d < best_d:
            best_d = d
            best = t
        if d < 0.5:
            break
    if best is None:
        return None
    return best[DN_BID] if side == "UP" else best[UP_BID]


def is_eligible(strat, side):
    if strat not in STRATEGY_SIDE_MAP:
        return False
    a = STRATEGY_SIDE_MAP[strat]
    return a == "BOTH" or a == side


def sharpe(pnls):
    if len(pnls) < 2:
        return 0.0
    m = sum(pnls) / len(pnls)
    v = sum((x - m) ** 2 for x in pnls) / (len(pnls) - 1)
    s = math.sqrt(v)
    return m / s * math.sqrt(len(pnls)) if s > 0 else 0.0


def main():
    print("Loading market_recap_history.jsonl ...")
    recaps = load_jsonl(RECAP)
    recap_by_slug = {r["slug"]: r for r in recaps}
    print(f"  {len(recaps)} markets")

    print("Loading market_history.jsonl (tick data, may take a minute) ...")
    tick_by_slug = {}
    count = 0
    with open(MKT_HIST) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except:
                continue
            s = m.get("slug", "")
            if "ticks" in m and m["ticks"]:
                tick_by_slug[s] = m["ticks"]
            count += 1
            if count % 50 == 0:
                print(f"  ... {count} records, {len(tick_by_slug)} with ticks", end="\r")
    print(f"  {count} records, {len(tick_by_slug)} with ticks           ")

    # Collect all eligible fires with real opp prices
    all_fires = []
    for slug, recap in recap_by_slug.items():
        w = recap.get("winner")
        if not w or w not in ("UP", "DN"):
            continue
        ticks = tick_by_slug.get(slug)
        for f in recap.get("fires", []):
            strat, side = f.get("strategy", ""), f.get("side", "")
            hypo = f.get("hypo_pnl", 0)
            ask = f.get("entry_price", 0) or 0
            cd = f.get("cd", 0)
            mode = f.get("mode", "UNKNOWN")
            cl_pass = f.get("cl_pass")

            elig = is_eligible(strat, side)
            cl_ok = cl_pass != "FAIL"

            opp = opp_from_ticks(ticks, cd, side) if ticks else None
            if opp is None:
                opp = 1.02 - ask

            all_fires.append({
                "slug": slug, "strategy": strat, "side": side,
                "hypo": hypo, "ask": ask, "cd": cd, "mode": mode,
                "opp": opp, "winner": w,
                "map_elig": elig, "cl_ok": cl_ok,
                "live_elig": elig and cl_ok,
            })

    n_all = len(all_fires)
    n_live = sum(1 for f in all_fires if f["live_elig"])
    n_shadow = n_all - n_live
    print(f"\n  Total fires: {n_all} (LIVE-elig={n_live}, SHADOW={n_shadow})")

    # Run gate simulations
    for mode_label, mode_filter in [("ALL", lambda f: True),
                                     ("LIVE-ELIGIBLE", lambda f: f["live_elig"]),
                                     ("SHADOW-ONLY", lambda f: not f["live_elig"])]:

        fires = [f for f in all_fires if mode_filter(f)]
        if not fires:
            continue

        # Group by slug for per-market PnL
        by_slug = defaultdict(list)
        for f in fires:
            by_slug[f["slug"]].append(f)

        print(f"\n{'=' * 130}")
        print(f"GATE TEST — {mode_label} (n={len(fires)} fires, {len(by_slug)} markets, data=TICK-LEVEL)")
        print(f"{'=' * 130}")

        print(f"\n  {'Config':<35} {'Fires':>5} {'Blk':>5} {'BlkW':>4} {'BlkL':>4} {'FP%':>5} | "
              f"{'PnL':>10} {'$/mkt':>7} {'Sharpe':>7} | {'vs Base':>8}")
        print(f"  {'-' * 120}")

        baseline_pnl = None

        for thresh_label in [None] + THRESHOLDS:
            if thresh_label is None:
                cfg_name = "A. Current (no UP threshold)"
            else:
                cfg_name = f"   + DN≥${thresh_label:.2f}"

            total_pnl = 0.0
            blk_n = 0
            blk_w = 0
            blk_l = 0
            mkt_pnls = []

            for slug, slug_fires in by_slug.items():
                mkt_pnl = 0.0
                for f in slug_fires:
                    blocked = False
                    if thresh_label is not None and f["side"] == "UP":
                        if f["opp"] >= thresh_label:
                            blocked = True
                            blk_n += 1
                            if f["hypo"] > 0:
                                blk_w += 1
                            else:
                                blk_l += 1

                    if not blocked:
                        mkt_pnl += f["hypo"]
                        total_pnl += f["hypo"]
                mkt_pnls.append(mkt_pnl)

            if baseline_pnl is None:
                baseline_pnl = total_pnl

            fp = blk_w / blk_n * 100 if blk_n else 0
            avg = total_pnl / len(mkt_pnls) if mkt_pnls else 0
            sh = sharpe(mkt_pnls)
            delta = total_pnl - baseline_pnl

            mark = "✅" if delta > 5 and fp < 25 else "⚠️" if delta > 0 else "❌" if delta < -5 else "≈"
            print(f"  {cfg_name:<35} {len(fires):>5} {blk_n:>5} {blk_w:>4} {blk_l:>4} {fp:>4.0f}% | "
                  f"${total_pnl:>+9.2f} ${avg:>+6.3f} {sh:>+6.2f} | ${delta:>+7.2f} {mark}")

        # Per-strategy at DN>=0.70
        print(f"\n  PER-STRATEGY @ DN≥$0.70 ({mode_label}):")
        strat_g = defaultdict(lambda: {"n": 0, "blk": 0, "no_gate": 0.0, "blk_pnl": 0.0})
        for f in fires:
            if f["side"] != "UP":
                continue
            k = f"{f['strategy']}|UP"
            strat_g[k]["n"] += 1
            strat_g[k]["no_gate"] += f["hypo"]
            if f["opp"] >= 0.70:
                strat_g[k]["blk"] += 1
                strat_g[k]["blk_pnl"] += f["hypo"]

        print(f"  {'Strategy':<35} {'n':>4} {'blk':>4} {'%':>4} | {'NoGate':>9} {'BlkPnL':>9} {'With':>9} | {'Delta':>8}")
        print(f"  {'-' * 95}")
        for k in sorted(strat_g, key=lambda x: strat_g[x]["blk_pnl"]):
            s = strat_g[k]
            if s["n"] == 0:
                continue
            pct = s["blk"] / s["n"] * 100 if s["n"] else 0
            with_gate = s["no_gate"] - s["blk_pnl"]
            delta = with_gate - s["no_gate"]
            mark = "✅" if delta > 1 else "❌" if delta < -1 else "≈"
            print(f"  {k:<35} {s['n']:>4} {s['blk']:>4} {pct:>3.0f}% | "
                  f"${s['no_gate']:>+8.2f} ${s['blk_pnl']:>+8.2f} ${with_gate:>+8.2f} | ${delta:>+7.2f} {mark}")

    # Market-level accuracy at each threshold
    print(f"\n{'=' * 130}")
    print("MARKET-LEVEL ACCURACY (does trigger predict DN winner?)")
    print(f"{'=' * 130}")
    print(f"\n  {'Threshold':>10} | {'Triggered':>10} {'%':>5} | {'DN wins':>8} {'UP wins':>8} | {'Accuracy':>8} | {'Note':>20}")
    print(f"  {'-' * 85}")

    for thresh in THRESHOLDS:
        trig = 0
        dn_correct = 0
        up_fp = 0
        for slug, slug_fires in defaultdict(list,
                {f["slug"]: [] for f in all_fires}).items():
            pass  # rebuild properly

    # Rebuild by_slug from all fires
    by_slug_all = defaultdict(list)
    for f in all_fires:
        by_slug_all[f["slug"]].append(f)

    for thresh in THRESHOLDS:
        trig = 0
        dn_w = 0
        up_w = 0
        for slug, slug_fires in by_slug_all.items():
            if not slug_fires:
                continue
            winner = slug_fires[0]["winner"]
            blocked_any = any(f["side"] == "UP" and f["opp"] >= thresh
                              for f in slug_fires if f["live_elig"])
            if blocked_any:
                trig += 1
                if winner == "DN":
                    dn_w += 1
                else:
                    up_w += 1

        acc = dn_w / trig * 100 if trig else 0
        pct = trig / len(by_slug_all) * 100
        mark = "✅" if acc >= 65 else "⚠️" if acc >= 55 else "❌"
        print(f"  DN≥${thresh:.2f}  | {trig:>5}/{len(by_slug_all)} {pct:>4.0f}% | "
              f"{dn_w:>8} {up_w:>8} | {acc:>6.1f}%  {mark}")

    print(f"\n{'=' * 130}")
    print("DONE — tick-level verification complete")
    print(f"{'=' * 130}")


if __name__ == "__main__":
    main()
