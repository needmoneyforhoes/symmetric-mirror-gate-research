"""
part16_sweep_gateaware.py — Symmetric Part 16: BN < -X% at cd=290 → block UP fires.

Exact mirror of Part 15 (which blocks DN when BN ≥ +4% at cd=290).

Correct fire inclusion:
  - Must be UP side
  - Must fire AFTER gate checkpoint (cd < gate_cd)
  - NOT pre_gate_held (held by ts_drop/ts_rec stage-1)
  - NOT opp_gate_blocked (blocked by live gate: ts_drop, ts_rec, Part 14 etc.)
  - NOT opp_gate_would_block (shadow-tracked as would-block)
  → This is exactly what Part 16 would see in real-time

Winner breakdown:
  DN win triggered → gate CORRECT (UP fires lose in DN market → blocking saves money)
  UP win triggered → gate WRONG  (UP fires win in UP market  → blocking costs money)
"""

import json, os, numpy as np
from scipy import stats as scipy_stats
from scipy.stats import beta as beta_dist

MARKET_HISTORY_PATH = os.path.expanduser('~/polymarket-bot/market_history.jsonl')
RECAP_HISTORY_PATH  = os.path.expanduser('~/polymarket-bot/market_recap_history.jsonl')

CD_RANGE      = list(range(290, 140, -10))   # 290, 280, ... 150
BN_THRESHOLDS = [-0.02, -0.04, -0.06, -0.08]  # NEGATIVE thresholds (BN falling)
IS_SPLIT      = 0.60

def get_bn_at_cd(ticks, cols, target_cd):
    ci = {c:i for i,c in enumerate(cols)}
    cd_i = ci.get('cd',0); bn_i = ci.get('bn_delta_pct',12)
    for t in ticks:
        cd = t[cd_i]
        if cd is not None and cd <= target_cd:
            v = t[bn_i]; return v if v is not None else None
    return None

def get_gate_aware_up_fires(fires, gate_cd):
    """
    UP fires that Part 16 would see and block:
      - UP side
      - fire_cd < gate_cd (fires AFTER the gate triggers)
      - passed ALL existing gates (not pre_gate_held, not blocked, not would_block)
    """
    passed = []
    for f in fires:
        if f.get('side') != 'UP': continue
        fire_cd = f.get('cd') or 0
        if fire_cd >= gate_cd: continue
        if (f.get('pre_gate_held') or
                f.get('opp_gate_blocked') or
                f.get('opp_gate_would_block')):
            continue
        passed.append(f.get('hypo_pnl', 0))
    return passed

print("Loading...", flush=True)
mkt_hist = {}
with open(MARKET_HISTORY_PATH) as f:
    for line in f:
        try:
            d = json.loads(line)
            if d.get('slug') and d.get('ticks') and d.get('tick_columns'):
                mkt_hist[d['slug']] = d
        except: pass

recap = {}
with open(RECAP_HISTORY_PATH) as f:
    for line in f:
        try:
            d = json.loads(line)
            if d.get('slug') and d.get('fires') and d.get('winner') in ('UP','DN'):
                recap[d['slug']] = d
        except: pass

common = sorted(set(mkt_hist) & set(recap))
markets = []
for slug in common:
    mkt = mkt_hist[slug]; rec = recap[slug]
    markets.append({'slug':slug,'winner':rec['winner'],'mkt':mkt,'fires':rec['fires']})

split_i   = int(len(markets) * IS_SPLIT)
OOS_slugs = {m['slug'] for m in markets[split_i:]}
print(f"  {len(markets)} markets  IS={split_i}  OOS={len(markets)-split_i}")

# Baseline: all gate-aware UP fires
baseline_fires = [p for m in markets
                  for p in get_gate_aware_up_fires(m['fires'], 999)]
baseline_n     = len(baseline_fires)
baseline_wins  = sum(1 for p in baseline_fires if p > 0)
baseline_prec  = baseline_wins / baseline_n if baseline_n else 0
print(f"  Baseline UP fires: {baseline_wins}/{baseline_n} = {baseline_prec*100:.1f}%  "
      f"avg={np.mean(baseline_fires):+.4f}")

# Precompute BN
print("Precomputing BN snapshots...", flush=True)
bn_cache = {}
for m in markets:
    slug = m['slug']
    bn_cache[slug] = {}
    for cd in CD_RANGE:
        bn_cache[slug][cd] = get_bn_at_cd(m['mkt']['ticks'], m['mkt']['tick_columns'], cd)

# Sweep
results = []
for gate_cd in CD_RANGE:
    for bn_thresh in BN_THRESHOLDS:   # NEGATIVE: trigger when BN ≤ threshold

        trig_dn = []; trig_up = []; not_trig = []
        for m in markets:
            bn = bn_cache[m['slug']].get(gate_cd)
            fires = get_gate_aware_up_fires(m['fires'], gate_cd)
            if not fires: continue
            rec = {'slug':m['slug'],'winner':m['winner'],
                   'fires':fires,'pnl':sum(fires),
                   'n':len(fires),'wins':sum(1 for p in fires if p>0),
                   'is_oos':m['slug'] in OOS_slugs}
            if bn is not None and bn <= bn_thresh:   # BN below (more negative than) threshold
                (trig_dn if m['winner']=='DN' else trig_up).append(rec)
            else:
                not_trig.append(rec)

        n_trig = len(trig_dn) + len(trig_up)
        if n_trig < 5: continue

        prec_mkt = len(trig_dn) / n_trig   # DN win = gate correct

        dn_fires_all = [p for r in trig_dn for p in r['fires']]  # UP fires lose (correct block)
        up_fires_all = [p for r in trig_up for p in r['fires']]  # UP fires win  (wrong block)
        all_trig_fires = dn_fires_all + up_fires_all

        saves = -sum(dn_fires_all)   # blocking DN-win markets: saves UP losses
        costs =  sum(up_fires_all)   # blocking UP-win markets: misses UP wins
        net   = saves - costs
        ev_mkt = net / n_trig

        oos_dn = [r for r in trig_dn if r['is_oos']]
        oos_up = [r for r in trig_up if r['is_oos']]
        oos_n  = len(oos_dn) + len(oos_up)
        oos_saves = -sum(p for r in oos_dn for p in r['fires'])
        oos_costs =  sum(p for r in oos_up for p in r['fires'])
        oos_net   = oos_saves - oos_costs
        oos_ev    = oos_net / oos_n if oos_n else 0

        n_f = len(all_trig_fires); k_f = sum(1 for p in all_trig_fires if p > 0)
        p_binom = scipy_stats.binomtest(k_f, n_f, baseline_prec, alternative='less').pvalue \
            if n_f > 0 else 1.0

        saves_pm = np.mean([-r['pnl'] for r in trig_dn]) if trig_dn else 0
        costs_pm = np.mean([r['pnl']  for r in trig_up]) if trig_up else 0
        bkev = costs_pm / (saves_pm + costs_pm) if (saves_pm+costs_pm) > 0 else 0.5

        results.append({
            'cd':gate_cd,'thresh':bn_thresh,
            'n_trig':n_trig,'n_dn':len(trig_dn),'n_up':len(trig_up),
            'prec_mkt':prec_mkt,'ev_mkt':ev_mkt,
            'saves':saves,'costs':costs,'net':net,
            'oos_n':oos_n,'oos_dn':len(oos_dn),'oos_up':len(oos_up),
            'oos_ev':oos_ev,'oos_net':oos_net,
            'n_fires':n_f,'k_wins':k_f,
            'p_binom':p_binom,
            'breakeven':bkev,'margin':prec_mkt-bkev,
        })

# Summary table
print(f"\n{'═'*100}")
print("PART 16 GATE-AWARE SWEEP: BN < threshold at cd=290→150  (UP fire suppression)")
print(f"{'═'*100}")

for thresh in BN_THRESHOLDS:
    sub = [r for r in results if abs(r['thresh']-thresh)<0.001]
    if not sub: continue
    print(f"\n  BN≤{thresh*100:.0f}%")
    print(f"  {'CD':>4} {'n_trig':>6} {'DN%':>5} {'UP%':>5} "
          f"{'saves':>8} {'costs':>8} {'net':>8} {'ev/mkt':>8} "
          f"{'breakevn':>9} {'margin':>7} "
          f"{'OOS_n':>6} {'OOS_DN%':>8} {'OOS_ev':>8} {'sig'}")
    print("  " + "-"*98)
    for r in sub:
        sig = '✅' if r['oos_ev']>0 and r['p_binom']<1e-4 else '⚠️' if r['oos_ev']>0 else '❌'
        print(f"  {r['cd']:>4} {r['n_trig']:>6} "
              f"{r['prec_mkt']*100:>4.0f}% {(1-r['prec_mkt'])*100:>4.0f}% "
              f"{r['saves']:>+8.1f} {r['costs']:>+8.1f} {r['net']:>+8.1f} "
              f"{r['ev_mkt']:>+8.2f} "
              f"{r['breakeven']*100:>8.1f}% {r['margin']*100:>+6.1f}pp "
              f"{r['oos_n']:>6} "
              f"{r['oos_dn']/r['oos_n']*100 if r['oos_n'] else 0:>7.0f}% "
              f"{r['oos_ev']:>+8.2f} {sig}")

# Optimal
print(f"\n{'═'*100}")
print("OPTIMAL: max OOS EV — prec_mkt > breakeven, OOS consistent, p_binom < 0.001")
print(f"{'═'*100}")
valid = [r for r in results
         if r['oos_ev']>0 and r['prec_mkt']>r['breakeven']
         and r['p_binom']<0.001 and r['oos_n']>=5 and r['net']>0]

if valid:
    best = max(valid, key=lambda x: x['oos_ev'])
    print(f"\n  Top candidates:")
    print(f"  {'CD':>4} {'BN≤':>6} {'n_trig':>6} {'DN%':>6} {'breakevn':>9} "
          f"{'OOS_n':>6} {'OOS_ev':>8} {'OOS_DN%':>8}")
    for r in sorted(valid, key=lambda x: -x['oos_ev'])[:10]:
        print(f"  {r['cd']:>4} {r['thresh']:>6.2f} {r['n_trig']:>6} "
              f"{r['prec_mkt']*100:>5.1f}% {r['breakeven']*100:>8.1f}% "
              f"{r['oos_n']:>6} {r['oos_ev']:>+8.2f} "
              f"{r['oos_dn']/r['oos_n']*100 if r['oos_n'] else 0:>7.1f}%")

    print(f"\n  ★  BEST: cd={best['cd']}  BN≤{best['thresh']*100:.0f}%")
    print(f"     Market precision: {best['prec_mkt']*100:.1f}% DN win  "
          f"(breakeven {best['breakeven']*100:.1f}%, margin {best['margin']*100:+.1f}pp)")
    print(f"     Full:  {best['n_trig']} mkts  net={best['net']:+.2f}  per_mkt={best['ev_mkt']:+.2f}")
    print(f"     OOS:   {best['oos_n']} mkts  net={best['oos_net']:+.2f}  per_mkt={best['oos_ev']:+.2f}")
    print(f"     Fires: {best['k_wins']}/{best['n_fires']} UP wins = "
          f"{best['k_wins']/best['n_fires']*100:.1f}%  p_binom={best['p_binom']:.2e}")

    # Binomial + Bayesian + Kelly
    print(f"\n  Statistical tests on best candidate:")
    n_f = best['n_fires']; k_f = best['k_wins']
    r_b = scipy_stats.binomtest(k_f, n_f, baseline_prec, alternative='less')
    a_p = k_f+1; b_p = n_f-k_f+1
    p_bayes = beta_dist.cdf(baseline_prec, a_p, b_p)
    bf = 1.0 / beta_dist.pdf(baseline_prec, a_p, b_p)
    ci_lo, ci_hi = beta_dist.ppf([0.025, 0.975], a_p, b_p)
    print(f"  Binomial p:  {r_b.pvalue:.2e}")
    print(f"  Bayesian:    P(rate<baseline)={p_bayes:.6f}  BF={bf:.0f}  "
          f"CI=[{ci_lo*100:.1f}%,{ci_hi*100:.1f}%]")

    # OOS binomial
    n_f_oos = sum(r['n'] for r in ([r for r in
        [{'slug':m['slug'],'winner':m['winner'],
          'fires':get_gate_aware_up_fires(m['fires'],best['cd']),
          'n':len(get_gate_aware_up_fires(m['fires'],best['cd'])),
          'wins':sum(1 for p in get_gate_aware_up_fires(m['fires'],best['cd']) if p>0)}
         for m in markets if m['slug'] in OOS_slugs
         and (bn_cache[m['slug']].get(best['cd']) or 0) <= best['thresh']]
        if r['n']>0]))
    k_f_oos = sum(r['wins'] for r in ([r for r in
        [{'slug':m['slug'],'winner':m['winner'],
          'fires':get_gate_aware_up_fires(m['fires'],best['cd']),
          'n':len(get_gate_aware_up_fires(m['fires'],best['cd'])),
          'wins':sum(1 for p in get_gate_aware_up_fires(m['fires'],best['cd']) if p>0)}
         for m in markets if m['slug'] in OOS_slugs
         and (bn_cache[m['slug']].get(best['cd']) or 0) <= best['thresh']]
        if r['n']>0]))
    if n_f_oos > 0:
        r_oos = scipy_stats.binomtest(k_f_oos, n_f_oos, baseline_prec, alternative='less')
        print(f"  OOS binomial: {k_f_oos}/{n_f_oos} wins = {k_f_oos/n_f_oos*100:.1f}%  "
              f"p={r_oos.pvalue:.2e}")

    # Kelly
    best_cd = best['cd']; best_t = best['thresh']
    all_trig_fires_k = [p for m in markets
                        for p in get_gate_aware_up_fires(m['fires'], best_cd)
                        if (bn_cache[m['slug']].get(best_cd) or 0) <= best_t]
    losses_k = [abs(p) for p in all_trig_fires_k if p < 0]
    wins_k   = [abs(p) for p in all_trig_fires_k if p > 0]
    if losses_k and wins_k:
        p_l = 1 - best['k_wins']/best['n_fires']
        q_w = best['k_wins']/best['n_fires']
        b_k = np.mean(losses_k)/np.mean(wins_k)
        f_star = p_l - q_w/b_k
        print(f"  Kelly f*:    {f_star:.4f}  {'✅ block EV+' if f_star>0 else '❌ block EV-'}")

    # Impact on market 1777556700
    print(f"\n  Impact on market 1777556700 (DN win, -$10.88):")
    for m in markets:
        if '1777556700' in m['slug']:
            bn_v = bn_cache[m['slug']].get(best_cd)
            fires = get_gate_aware_up_fires(m['fires'], best_cd)
            trig  = bn_v is not None and bn_v <= best_t
            print(f"    BN at cd={best_cd}: {bn_v}  trigger={'YES' if trig else 'NO'}")
            if trig:
                print(f"    UP fires blocked: {len(fires)}  pnl_saved={-sum(fires):+.2f}")
            break
else:
    print("  No valid candidates found.")
    best_raw = min(results, key=lambda r: r['p_binom']) if results else None
    if best_raw:
        print(f"  Best raw: cd={best_raw['cd']} BN≤{best_raw['thresh']*100:.0f}%  "
              f"p_binom={best_raw['p_binom']:.2e}  OOS_ev={best_raw['oos_ev']:+.3f}")

# BN≤-4% across CDs summary
print(f"\n{'═'*100}")
print("BN≤-4% across CDs for quick comparison:")
print(f"{'═'*100}")
print(f"  {'CD':>4} {'n':>5} {'DN%':>6} {'EV/mkt':>8} {'OOS_n':>6} {'OOS_ev':>8}")
for r in [x for x in results if abs(x['thresh']+0.04)<0.001]:
    print(f"  {r['cd']:>4} {r['n_trig']:>5} {r['prec_mkt']*100:>5.0f}% "
          f"{r['ev_mkt']:>+8.2f} {r['oos_n']:>6} {r['oos_ev']:>+8.2f} "
          f"{'✅' if r['oos_ev']>0 and r['p_binom']<1e-4 else ''}")
