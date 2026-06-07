#!/usr/bin/env python3
"""
Inverted UP Gate Scanner
==========================
The UP gate (DN≥$0.65 p40%) blocked 7 fires — ALL winners.
If we INVERT: when DN shows dominance → UP is likely to WIN (reversal).

Tests:
  1. Current: DN dominant → block UP (proven -$21 in 7 live markets)
  2. Inverted: DN dominant → ALLOW UP, block DN
  3. Double-inverted: DN dominant → block DN (boost DN gate)
  4. Timing: early DN dominance vs late DN dominance
  5. Also test what happens when we just disable UP gate entirely

Run: python3 inverted_up_gate.py market_history.jsonl
"""
import json, sys

CD,UP_BID,UP_ASK,DN_BID,DN_ASK = 0,1,2,3,4

def load(fp):
    mkts = []
    with open(fp) as f:
        for line in f:
            if not line.strip(): continue
            m = json.loads(line)
            if m.get('ticks') and m.get('winner') in ('UP','DN'):
                mkts.append(m)
    mkts.sort(key=lambda m: m.get('ts',''))
    return mkts

def sample_Ns(ticks, idx, interval):
    s = []; prev = 999
    for t in ticks:
        if t[CD] < prev - (interval - 0.5):
            s.append((t[CD], t[idx] or 0))
            prev = t[CD]
    return s

def check_dn_dominance(ticks, thresh=0.65, pct=40, interval=3):
    """Check if DN≥thresh for pct% of samples. Returns (triggered, trigger_cd)."""
    dn_s = sample_Ns(ticks, DN_ASK, interval)
    n = len(dn_s)
    for i in range(3, n+1):
        subset = dn_s[:i]
        cd = subset[-1][0]
        above = sum(1 for _, p in subset if p >= thresh)
        if (above / i * 100) >= pct:
            return True, cd
    return False, None

def compute_side_pnl(ticks, winner, side, after_cd=None):
    """Compute total PnL for one side's fires."""
    idx = UP_ASK if side == 'UP' else DN_ASK
    s = sample_Ns(ticks, idx, 10)
    total = 0; count = 0
    fired = set()
    for cd, price in s:
        if cd < 30 or price <= 0: continue
        if after_cd is not None and cd > after_cd: continue
        zone = round(price * 20) / 20
        if zone in fired: continue
        fired.add(zone)
        won = (winner == side)
        pnl = ((1.0 - price) * 5) if won else (-price * 5)
        total += pnl
        count += 1
    return total, count

def main():
    fp = sys.argv[1] if len(sys.argv) > 1 else "market_history.jsonl"
    print(f"Loading {fp}...")
    raw = load(fp)
    n = len(raw)
    split = int(n * 0.68)
    train = raw[:split]
    test = raw[split:]
    print(f"Loaded {n} markets (Train={len(train)} Test={len(test)})")

    for thresh, pct in [(0.65, 40), (0.60, 50), (0.55, 60), (0.70, 40)]:
        for ds_name, dataset in [("OOS", test), ("TRAIN", train)]:
            trig_up_wins = 0; trig_dn_wins = 0; trig_count = 0
            no_trig_up_wins = 0; no_trig_dn_wins = 0; no_trig_count = 0

            # PnL scenarios
            pnl_no_gate_up = 0; pnl_no_gate_dn = 0
            pnl_current_up = 0  # block UP when triggered
            pnl_inverted_up = 0  # allow UP when triggered, block when NOT
            pnl_block_dn_when_trig = 0  # block DN when DN dominant (inverted for DN)
            pnl_allow_dn_when_trig = 0  # normal DN behavior

            early_trig = 0; late_trig = 0
            early_up_wins = 0; late_up_wins = 0

            for m in dataset:
                ticks = m['ticks']
                winner = m['winner']
                triggered, trig_cd = check_dn_dominance(ticks, thresh, pct)

                up_pnl, up_n = compute_side_pnl(ticks, winner, 'UP')
                dn_pnl, dn_n = compute_side_pnl(ticks, winner, 'DN')

                pnl_no_gate_up += up_pnl
                pnl_no_gate_dn += dn_pnl

                if triggered:
                    trig_count += 1
                    if winner == 'UP': trig_up_wins += 1
                    else: trig_dn_wins += 1

                    # Current: block UP when triggered
                    pnl_current_up += 0  # UP blocked, no PnL
                    # Inverted: ALLOW UP when triggered
                    pnl_inverted_up += up_pnl
                    # Block DN when DN dominant (inverted DN logic)
                    pnl_block_dn_when_trig += 0  # DN blocked

                    # Timing
                    if trig_cd and trig_cd > 150:
                        early_trig += 1
                        if winner == 'UP': early_up_wins += 1
                    else:
                        late_trig += 1
                        if winner == 'UP': late_up_wins += 1
                else:
                    no_trig_count += 1
                    if winner == 'UP': no_trig_up_wins += 1
                    else: no_trig_dn_wins += 1

                    # Current: allow UP (no gate)
                    pnl_current_up += up_pnl
                    # Inverted: block UP when NOT triggered
                    pnl_inverted_up += 0  # UP blocked
                    # Normal DN
                    pnl_block_dn_when_trig += dn_pnl

            print(f"\n{'='*90}")
            print(f"DN≥${thresh:.2f} p{pct}% — {ds_name} ({len(dataset)} markets)")
            print(f"{'='*90}")

            print(f"\n  WHEN DN DOMINANT (triggered): {trig_count} markets")
            print(f"    UP wins: {trig_up_wins} ({trig_up_wins/max(trig_count,1)*100:.0f}%)")
            print(f"    DN wins: {trig_dn_wins} ({trig_dn_wins/max(trig_count,1)*100:.0f}%)")
            if early_trig:
                print(f"    Early (cd>150): {early_trig} → UP wins {early_up_wins} ({early_up_wins/max(early_trig,1)*100:.0f}%)")
            if late_trig:
                print(f"    Late  (cd≤150): {late_trig} → UP wins {late_up_wins} ({late_up_wins/max(late_trig,1)*100:.0f}%)")

            print(f"\n  WHEN NOT TRIGGERED: {no_trig_count} markets")
            print(f"    UP wins: {no_trig_up_wins} ({no_trig_up_wins/max(no_trig_count,1)*100:.0f}%)")
            print(f"    DN wins: {no_trig_dn_wins} ({no_trig_dn_wins/max(no_trig_count,1)*100:.0f}%)")

            no_gate_total = pnl_no_gate_up + pnl_no_gate_dn
            print(f"\n  PnL COMPARISON:")
            print(f"    No gate (baseline UP):          ${pnl_no_gate_up:+.0f}")
            print(f"    Current (block UP on trigger):   ${pnl_current_up:+.0f} (${pnl_current_up - pnl_no_gate_up:+.0f} vs baseline)")
            print(f"    Inverted (allow UP on trigger):  ${pnl_inverted_up:+.0f} (${pnl_inverted_up - pnl_no_gate_up:+.0f} vs baseline)")
            print(f"    Block DN when DN dominant:       ${pnl_block_dn_when_trig:+.0f} vs ${pnl_no_gate_dn:+.0f} baseline DN")

if __name__ == "__main__":
    main()
