"""
sym_dn_live_sweep.py — Symmetric dn_live gate sweep.

dn_live blocks DN fires when up_ask >= 0.50 for 2 consecutive ~10s samples.
This tests the symmetric: block UP fires when dn_ask >= threshold for 2 consecutive
~10s samples (sustained DN dominance).

Uses full tick data from market_history.jsonl for accurate signal simulation.
Gate-aware UP fires only (not pre_gate_held, not opp_gate_held).
Full stat battery: Bonferroni, OOS, Bayesian, Kelly, permutation.
"""
import json, os, numpy as np
from scipy import stats as scipy_stats
from scipy.stats import beta as beta_dist

MARKET_HISTORY_PATH = os.path.expanduser('~/polymarket-bot/market_history.jsonl')
RECAP_HISTORY_PATH  = os.path.expanduser('~/polymarket-bot/market_recap_history.jsonl')
IS_SPLIT   = 0.60
N_PERM     = 5000
SAMPLE_GAP = 8      # seconds between samples (dn_live uses ~10s gap)

THRESHOLDS = [0.55, 0.60, 0.65, 0.70]

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

common   = sorted(set(mkt_hist) & set(recap))
split_i  = int(len(common) * IS_SPLIT)
OOS_slugs = set(common[split_i:])
print(f"  {len(common)} markets  IS={split_i}  OOS={len(common)-split_i}")

def get_free_up_fires(fires):
    return [f for f in fires
            if f.get('side') == 'UP'
            and not f.get('pre_gate_held')
            and not f.get('opp_gate_held')
            and f.get('entry_price') is not None]

def gate_fires_at(ticks, cols, threshold, sample_gap=SAMPLE_GAP):
    """
    Simulate symmetric dn_live gate on tick stream.
    Returns cd at which gate fires (2 consecutive samples with dn_ask >= threshold),
    or None if gate never fires.
    """
    ci = {c:i for i,c in enumerate(cols)}
    cd_i = ci.get('cd', 0)
    da_i = ci.get('dn_ask', 4)

    prev_dn = None
    prev_cd = None

    for t in ticks:
        cd = t[cd_i]
        da = t[da_i]
        if cd is None or da is None or cd <= 0 or cd > 295:
            continue

        # Only sample every ~10 seconds
        if prev_cd is not None and (prev_cd - cd) < sample_gap:
            continue

        if da >= threshold and prev_dn is not None and prev_dn >= threshold:
            return cd   # gate fires at this cd

        prev_dn = da
        prev_cd = cd

    return None  # gate never fired

# Baselines
base_fires = [(f, recap[s]['winner'], s in OOS_slugs)
              for s in common for f in get_free_up_fires(recap[s]['fires'])]
base_n    = len(base_fires)
base_wins = sum(1 for f,_,_ in base_fires if f.get('hypo_pnl',0) > 0)
base_prec = base_wins / base_n
print(f"  Baseline free UP fires: {base_wins}/{base_n} = {base_prec*100:.1f}%  "
      f"avg={np.mean([f.get('hypo_pnl',0) for f,_,_ in base_fires]):+.4f}")

N_TESTS    = len(THRESHOLDS)
ALPHA_BONF = 0.05 / N_TESTS
print(f"  {N_TESTS} thresholds  Bonferroni α={ALPHA_BONF:.5f}\n")

# Precompute gate fire CDs
print("Simulating gate on all markets...", flush=True)
gate_cd_cache = {}  # slug -> {thresh: gate_fire_cd or None}
for slug in common:
    mkt = mkt_hist[slug]
    gate_cd_cache[slug] = {}
    for thresh in THRESHOLDS:
        gate_cd_cache[slug][thresh] = gate_fires_at(
            mkt['ticks'], mkt['tick_columns'], thresh)

results = []
for thresh in THRESHOLDS:
    blocked_correct = []  # UP fires blocked in DN markets (saves)
    blocked_wrong   = []  # UP fires blocked in UP markets (costs)

    for slug in common:
        winner = recap[slug]['winner']
        is_oos = slug in OOS_slugs
        gate_cd = gate_cd_cache[slug][thresh]
        if gate_cd is None:
            continue  # gate never fires in this market

        for f in get_free_up_fires(recap[slug]['fires']):
            fire_cd = f.get('cd') or 0
            if fire_cd >= gate_cd:
                continue   # fire happened BEFORE gate checkpoint (gate fires at lower cd)
            # This fire would be blocked
            rec = {'hypo': f.get('hypo_pnl', 0),
                   'won':  f.get('hypo_pnl', 0) > 0,
                   'slug': slug, 'is_oos': is_oos,
                   'winner': winner, 'cd': fire_cd,
                   'gate_cd': gate_cd}
            (blocked_correct if winner == 'DN' else blocked_wrong).append(rec)

    n = len(blocked_correct) + len(blocked_wrong)
    if n < 5:
        continue

    saves  = -sum(b['hypo'] for b in blocked_correct)
    costs  =  sum(b['hypo'] for b in blocked_wrong if b['hypo'] > 0)
    net    = saves - costs
    k_wins = sum(1 for b in (blocked_correct + blocked_wrong) if b['won'])

    p_binom = scipy_stats.binomtest(k_wins, n, base_prec, alternative='less').pvalue
    p_bonf  = min(p_binom * N_TESTS, 1.0)

    # OOS
    oos_c  = [b for b in blocked_correct if b['is_oos']]
    oos_w  = [b for b in blocked_wrong   if b['is_oos']]
    oos_n  = len(oos_c) + len(oos_w)
    oos_sv = -sum(b['hypo'] for b in oos_c)
    oos_ct =  sum(b['hypo'] for b in oos_w if b['hypo'] > 0)
    oos_net= oos_sv - oos_ct
    oos_ev = oos_net / oos_n if oos_n else 0

    # Market-level counts
    mkts_dn = len({b['slug'] for b in blocked_correct})
    mkts_up = len({b['slug'] for b in blocked_wrong})

    # OOS binomial
    oos_k = sum(1 for b in oos_c+oos_w if b['won'])
    oos_p = scipy_stats.binomtest(oos_k, oos_n, base_prec, alternative='less').pvalue \
            if oos_n else 1.0

    # Gate trigger cd distribution
    gate_cds = list({b['slug']: b['gate_cd'] for b in (blocked_correct+blocked_wrong)}.values())

    # Bayesian
    a_p=k_wins+1; b_p=n-k_wins+1
    p_bay = beta_dist.cdf(base_prec, a_p, b_p)
    bf    = 1.0 / beta_dist.pdf(base_prec, a_p, b_p)
    ci_lo, ci_hi = beta_dist.ppf([0.025, 0.975], a_p, b_p)

    # Kelly
    all_b  = blocked_correct + blocked_wrong
    hypos  = [b['hypo'] for b in all_b]
    losses = [abs(h) for h in hypos if h < 0]
    wins_h = [abs(h) for h in hypos if h > 0]
    f_star = None
    if losses and wins_h:
        p_l = 1 - k_wins/n; q_w = k_wins/n
        b_k = np.mean(losses) / np.mean(wins_h)
        f_star = p_l - q_w/b_k

    # Permutation (IS only)
    is_hypos = [b['hypo'] for b in all_b if not b['is_oos']]
    p_perm = None
    if len(is_hypos) >= 5:
        obs = -np.mean(is_hypos)
        np.random.seed(42)
        perm = [-np.mean(np.random.choice(is_hypos, len(is_hypos), replace=True))
                for _ in range(N_PERM)]
        p_perm = np.mean(np.array(perm) >= obs)

    # CD when gate fires: where in the market does this typically trigger?
    gate_cd_med = np.median(gate_cds) if gate_cds else 0

    results.append({
        'thresh': thresh,
        'n': n, 'n_correct': len(blocked_correct), 'n_wrong': len(blocked_wrong),
        'mkts_dn': mkts_dn, 'mkts_up': mkts_up,
        'saves': saves, 'costs': costs, 'net': net,
        'k_wins': k_wins, 'win_rate': k_wins/n,
        'p_binom': p_binom, 'p_bonf': p_bonf, 'p_bay': p_bay, 'bf': bf,
        'ci': (ci_lo, ci_hi), 'kelly': f_star, 'p_perm': p_perm,
        'oos_n': oos_n, 'oos_nc': len(oos_c), 'oos_nw': len(oos_w),
        'oos_ev': oos_ev, 'oos_net': oos_net, 'oos_p': oos_p,
        'gate_cd_med': gate_cd_med,
        'all_blocked': blocked_correct + blocked_wrong,
    })

# ── SUMMARY ───────────────────────────────────────────────────────────────
print(f"{'═'*115}")
print("SYMMETRIC dn_live: block UP if dn_ask >= threshold for 2 consecutive ~10s samples")
print(f"Bonferroni α={ALPHA_BONF:.5f}")
print(f"{'═'*115}")
print(f"  {'thresh':>7} {'n_bl':>6} {'%DN':>5} {'saves':>8} {'costs':>8} "
      f"{'net':>8} {'win%':>6} {'OOS_n':>6} {'OOS_ev':>8} "
      f"{'p_bonf':>10} {'Kelly':>7} {'perm':>7} {'gate@':>7} sig")
print("  " + "-"*112)
for r in results:
    sig   = '✅***' if r['p_bonf'] < ALPHA_BONF else ('⚠️' if r['p_binom'] < 0.05 else '')
    kelly = f"{r['kelly']:.3f}" if r['kelly'] else '-'
    perm  = f"{r['p_perm']:.3f}" if r['p_perm'] is not None else '-'
    oos_dn = f"{r['oos_nc']/r['oos_n']*100:.0f}%DN" if r['oos_n'] else '-'
    print(f"  {r['thresh']:>7.2f} {r['n']:>6} "
          f"{r['n_correct']/r['n']*100:>4.0f}% {r['saves']:>+8.1f} {r['costs']:>+8.1f} "
          f"{r['net']:>+8.1f} {r['win_rate']*100:>5.0f}% "
          f"{r['oos_n']:>4}({oos_dn}) {r['oos_ev']:>+8.2f} "
          f"{r['p_bonf']:>10.5f} {kelly:>7} {perm:>7} "
          f"cd≈{r['gate_cd_med']:.0f} {sig}")

# ── DEEP DIVE ─────────────────────────────────────────────────────────────
print(f"\n{'═'*115}")
print("DEEP DIVE — ALL CANDIDATES")
print(f"{'═'*115}")
for r in results:
    sig = '✅ CONFIRMED' if r['p_bonf'] < ALPHA_BONF else '⚠️ marginal'
    print(f"\n  ★ dn_ask >= {r['thresh']:.2f} for 2 consecutive 10s samples  ({sig})")
    print(f"    {r['n']} fires blocked: {r['n_correct']} DN-win (saves ${r['saves']:.1f})  "
          f"{r['n_wrong']} UP-win (costs ${r['costs']:.1f})")
    print(f"    Markets affected: {r['mkts_dn']} DN win  {r['mkts_up']} UP win")
    print(f"    Net: {r['net']:+.1f}  Fire win rate: {r['k_wins']}/{r['n']} = {r['win_rate']*100:.1f}%")
    print(f"    Gate fires at cd≈{r['gate_cd_med']:.0f} (median)")
    print(f"    Binomial  p={r['p_binom']:.2e}  Bonf p={r['p_bonf']:.5f}")
    print(f"    Bayesian  P(rate<base)={r['p_bay']:.6f}  BF={r['bf']:.0f}  "
          f"CI=[{r['ci'][0]*100:.1f}%,{r['ci'][1]*100:.1f}%]")
    print(f"    OOS       n={r['oos_n']}  ev={r['oos_ev']:+.3f}  net={r['oos_net']:+.1f}  "
          f"p={r['oos_p']:.2e}")
    if r['kelly']:
        print(f"    Kelly     f*={r['kelly']:.4f}  {'✅ EV+' if r['kelly']>0 else '❌ EV-'}")
    if r['p_perm'] is not None:
        print(f"    Permutation p={r['p_perm']:.4f}  {'✅' if r['p_perm']<0.05 else '❌'}")

    # Gate fire CD distribution
    gate_cds = sorted({b['slug']: b['gate_cd'] for b in r['all_blocked']}.values(), reverse=True)
    print(f"    Gate fire CD distribution ({len(gate_cds)} markets):")
    for lo,hi in [(290,260),(259,220),(219,180),(179,150),(149,0)]:
        n_in = sum(1 for c in gate_cds if hi < c <= lo)
        pct  = n_in/len(gate_cds)*100 if gate_cds else 0
        bar  = '█' * int(pct/5)
        print(f"      cd {lo:>3}→{hi:>3}: {n_in:>3} ({pct:>4.0f}%)  {bar}")

    # Specific market checks
    for chk_slug, chk_label, chk_gc in [
        ('1777556700', 'DN win target', -10.88),
        ('1777551300', 'UP win control', -19.53),
    ]:
        gate_cd = gate_cd_cache.get(chk_slug, {}).get(r['thresh'])
        if gate_cd:
            fires_blocked = [b for b in r['all_blocked'] if b['slug'] == chk_slug]
            saved = -sum(b['hypo'] for b in fires_blocked)
            winner = recap.get(chk_slug, {}).get('winner', '?')
            print(f"    {chk_label} ({chk_slug}): gate fires cd={gate_cd:.0f}  "
                  f"blocks {len(fires_blocked)} fires  saved={saved:+.2f}  "
                  f"new_gc={chk_gc+saved:+.2f}  winner={winner}")
        else:
            print(f"    {chk_label} ({chk_slug}): gate SILENT at thresh={r['thresh']:.2f}")

print()
EOF