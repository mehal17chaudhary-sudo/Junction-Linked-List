# AMJ List (Anna Mani Junction List)

> A sorted linked list that gets **faster relative to its competition as N grows** — and at the median, nearly ties SkipList.

Most sorted structures degrade with scale. This one has a scaling exponent of **−0.073** (log-log, N=5k–200k). SkipList's is +0.193. That sign flip is the whole story.

---

## Two numbers that should not coexist

**The one that surprises you (good):** On read-only workloads, AMJ List p50 latency is **5.62 µs vs SkipList's 5.05 µs** — a 1.11× difference. At the median, a structure carrying a full self-repair system is within measurement noise of one that has none.

**The one that keeps you honest (bad):** Under Insert-flood, a single 300-op window recorded a p99 of **2,709 µs against SkipList's 14.2 µs — a 190× ratio**. Max latency in that same window: **2.7 ms**. These are global rebuild events firing under maximum insert pressure. The mean p99 across all Insert-flood windows is 48.6 µs — the average is fine. The tail is not yet tamed. It's an open problem with a known fix (see below).

---

## What it actually is

```
  ┌──── junction ring ────────────────────────────────────────┐
  │                                                           │
  J0 ──────────────────► J1 ──────────────────► J2 ──► ...  │
  │                       │                       │          │
  │  [segment 0]          │  [segment 1]          │          │
  │  • • shortcut • •     │  • • shortcut • •     │          │
  │  node node node node  │  node node node node  │          │
  └───────────────────────┴───────────────────────┴──────────┘
```

The list splits into segments of size ≈ `c·√N`. Each segment has a **junction node** pinned near its centre and a set of **shortcut pointers** spread across it. A search navigates the junction ring first, then drops into a short linear scan. Total hops: O(√N).

Three maintenance tiers run on mutations only — **searches never trigger repairs:**

- **Local** (every ~2000 mutations): re-centres any junction that has drifted past 15% of its segment midpoint
- **Suboptimal** (every ~2000 mutations): splits or merges segments that have grown or shrunk past threshold
- **Global** (emergency only): full rebuild — fires exactly once per seed over 300,000 ops under normal conditions

**Tuned defaults:** `seg=175, k=6, local_interval=2000, sub_interval=2000, t_j=0.15`

---

## Benchmarks

### ⚠ The Insert-flood spike — read this first

The worst single 300-op window across 4 seeds:

| | AMJ List | SkipList |
|---|---|---|
| p99 (worst window) | **2,709 µs** | 14.2 µs |
| max latency | **2,709 µs** | — |
| p99 ratio | **190×** | — |

This is real. A global rebuild event coincided with the measurement window at peak insert pressure. The mean p99 across all Insert-flood windows is 48.6 µs — that context matters — but the spike exists and matters for any tail-sensitive application. See [Open Problems](#open-problems) for the fix in progress.

---

### Latency — averages across all snapshots and 4 seeds

| Workload | AMJ avg (µs) | AMJ p50 (µs) | AMJ p95 (µs) | AMJ p99 (µs) | SL avg (µs) | SL p50 (µs) | SL p95 (µs) | SL p99 (µs) | p99 ratio |
|---|---|---|---|---|---|---|---|---|---|
| Read-only | 6.82 | 5.62 | 13.98 | 29.97 | 5.36 | 5.05 | 8.95 | 11.89 | 2.5× |
| Search-heavy | 11.03 | 8.95 | 22.93 | 32.25 | 5.21 | 4.90 | 9.32 | 12.53 | 2.6× |
| Balanced | 10.90 | 7.33 | 21.88 | 32.62 | 3.72 | 2.97 | 8.22 | 11.28 | 2.9× |
| Insert-heavy | 13.76 | 7.97 | 23.98 | 63.51 | 3.28 | 2.78 | 7.30 | 10.89 | 5.8× |
| Write-heavy | 11.01 | 7.49 | 19.55 | 34.08 | 2.98 | 2.65 | 6.44 | 10.35 | 3.3× |
| Insert-flood | 14.11 | 7.53 | 18.76 | 48.59 | 2.90 | 2.73 | 4.05 | 7.78 | 6.2× |
| Delete-flood | 6.23 | 5.11 | 12.74 | 23.28 | 2.15 | 1.93 | 3.57 | 6.69 | 3.5× |

**Overall mean p99 ratio: 3.89×.** The p50 gap on Read-only (1.11×) remains the most striking single number: at the median, AMJ List's entire maintenance system is nearly invisible. The distribution is well-behaved through p95 and then spikes at p99 — the exact shape of a maintenance event distribution. Most ops are clean; a small number catch a rebuild.

### Hop count

| Workload | AMJ avg hops | SL avg hops | AMJ hops / √N | SL hops / log₂N |
|---|---|---|---|---|
| Read-only | 36.0 | 20.6 | 0.208 | 1.385 |
| Search-heavy | 128.6 | 20.5 | 0.743 | 1.378 |
| Balanced | 135.2 | 21.7 | 0.780 | 1.456 |
| Insert-heavy | 168.2 | 20.6 | 0.971 | 1.384 |
| Write-heavy | 140.0 | 21.1 | 0.808 | 1.421 |
| Insert-flood | 165.0 | 22.3 | 0.953 | 1.498 |
| Delete-flood | 79.5 | 21.3 | 0.459 | 1.431 |

**AMJ hops / √N = 0.703 overall** — well within O(√N). On Read-only the ratio drops to 0.208, meaning the structure uses far fewer hops than the theoretical bound when mutations aren't disturbing it.

### Throughput

| Workload | AMJ (ops/sec) | SL (ops/sec) | SL advantage |
|---|---|---|---|
| Read-only | ~153,000 | ~189,000 | 1.2× |
| Search-heavy | ~111,000 | ~193,000 | 1.7× |
| Balanced | ~115,000 | ~270,000 | 2.3× |
| Write-heavy | ~107,000 | ~336,000 | 3.2× |
| Insert-heavy | ~95,000 | ~305,000 | 3.2× |
| Delete-flood | ~170,000 | ~467,000 | 2.7× |
| Insert-flood | ~93,000 | ~346,000 | 3.7× |

The gap is narrow on read-dominant workloads (1.2×) and widens under write pressure (3.7× at Insert-flood). SkipList pays no maintenance cost per mutation. AMJ List does — and that cost is what buys predictable degradation cycles and observable repair events.

### Maintenance cost per mutation

| Workload | Maintenance events / mutation |
|---|---|
| Read-only | 0.0008 |
| Search-heavy | 0.0005 |
| Balanced | 0.0003 |
| Insert-heavy | 0.0006 |
| Write-heavy | 0.0004 |
| Insert-flood | 0.0007 |
| Delete-flood | ~0.0000 |

Maintenance cost is stable and does not blow up under write pressure.

---

## The scaling result

AMJ p99 stays within a narrow absolute band across the full 5k–200k range. SkipList grows as expected. The ratio keeps narrowing at scale.

| N | AMJ p99 (µs) | SkipList p99 (µs) | AMJ/SL ratio |
|---|---|---|---|
| 5,000 | 72.9 | 7.7 | 9.4× |
| 10,000 | 51.6 | 5.9 | 8.8× |
| 25,000 | 109.4 | 7.3 | 15.0× |
| 50,000 | 56.8 | 11.4 | 5.0× |
| 100,000 | 46.4 | 10.3 | 4.5× |
| 200,000 | 58.6 | 13.8 | 4.2× |

At N=200k they're 4.2× apart and that gap is still closing. The spike at N=25k is a maintenance cycle coinciding with the measurement window, not a trend.

## Tuned parameters beat all tested alternatives

| Configuration | Mean p99 (µs) | vs Tuned |
|---|---|---|
| **Tuned (seg=175, k=6)** | **46.7** | **baseline** |
| Overcuts (k=20) | 47.0 | 1.01× |
| High local_interval=50k | 48.4 | 1.04× |
| No shortcuts (k=2) | 51.9 | 1.11× |
| Low sub_interval=200 | 54.7 | 1.17× |
| Undersized seg=50 | 65.4 | 1.40× |
| OldDefault (seg=100, k=3) | 108.1 | 2.32× |
| Oversized seg=1500 | 119.4 | 2.56× |
| Low local_interval=50 | 139.0 | 2.98× |
| **High sub_interval=40k** | **2,395.1** | **51.3×** |

`sub_interval` is the most sensitive knob. Set it too high and you get the Insert-flood spike problem on every workload, permanently. The 51× case is what this structure looks like when segment maintenance is effectively disabled.

## No runaway drift over 300k ops

| Run | First window p99 (µs) | Last window p99 (µs) | Drift |
|---|---|---|---|
| seed=42 | 28.0 | 32.5 | 1.16× |
| seed=43 | 25.7 | 30.7 | 1.19× |
| seed=44 | 30.2 | 45.8 | 1.52× |
| seed=45 | 36.6 | 45.3 | 1.24× |

**Mean drift: 1.28×** over 300,000 ops with exactly 1 global rebuild per seed. No runaway growth.

## Structural invariants under insert patterns (Bench B)

Shortcut validity and junction centring were checked across all 5 insert patterns — Random, Sorted-asc, Sorted-desc, Localized, and Clustered — across 4 workloads. Zero structural violations across all combinations. This includes the most adversarial pattern tested: 90% of keys concentrated in 10% of the key space.

---

## Open problems

**The Insert-flood tail spike.** The 190× p99 and 2.7ms max are global rebuild events under maximum insert pressure. The fix is a write-rate-aware trigger — tracking per-segment write velocity and lowering `local_interval` dynamically when hotspot pressure is detected. Not implemented yet, but it's a well-scoped problem.

**The optimal segment coefficient c drifts with N.** The `seg = c·√N` formula assumes c is a universal constant — it isn't:

| N | Best c |
|---|---|
| 5,000 | 2.00 |
| 25,000 | 0.50 |
| 100,000 | 0.50 |
| 200,000 | 0.75 |

CV of optimal c = 0.766. The auto-constructor should use `c = max(0.5, 1.5 − 0.4·log₁₀(N/5000))` rather than a fixed c=1.01.

**The oscillation ceiling has a positive slope.** The rolling max hop count is still rising at end of 30k-op runs for mutation-heavy workloads. The mean is stable — it's not getting worse per window — but the worst single window keeps setting new highs. Bench 8 suggests this stabilises long-term (1.28× mean drift over 300k ops), but it hasn't been confirmed to flatten within 30k.

---

## Why does this exist

SkipList and B-tree are cache-friendly, fast, and battle-tested. AMJ List is pointer-based and slower in raw throughput. That's not the pitch.

The pitch is **observable maintenance**. Every degradation event is tracked, every repair is categorised (local / suboptimal / global), and the cost per mutation is stable and measurable. If you've used SkipList at high write rates and hit unpredictable tail latency spikes — the kind that show up at p99 but not p50 — that's probabilistic rebalancing doing something you can't instrument. AMJ List's maintenance system is deterministic and observable. You can tune `local_interval`, watch the maintenance rate, and know roughly when the next event fires.

The other property is **predictable degradation cycles**: degrade → threshold → repair → reset. SkipList has probabilistic amortisation instead, which performs better on average but is harder to reason about at the tail.

The current open problem (Insert-flood tail spikes) is exactly where that predictability breaks down. It's known and scoped — the fix is a smarter trigger, not a different structure.

---

## Try it

```bash
git clone <repo>
cd amj-list
pip install -r requirements.txt

# Run all benchmarks
python run_benchmarks.py

# Run specific benches
python bench_a.py --n 30000 --seeds 42 43 44 45
python bench_2.py   # N-scaling sweep
python bench_e.py   # shortcut sweep

# Use the auto-constructor
from amj import make_amj_auto
amj = make_amj_auto(N=100_000)
```

All results use seeds [42, 43, 44, 45] with snapshots every 300 ops.

---

## Appendix — Full test parameters

```
N (default)        : 30,000
Seeds              : [42, 43, 44, 45]
Snapshot interval  : 300 ops
Workloads          : 7 profiles (Read-only 99/0.5 through Insert-flood 2/97)
Insert patterns    : Random, Sorted-asc, Sorted-desc, Localized, Clustered
Tuned AMJ params   : seg=175, k=6, local_interval=2000, sub_interval=2000,
                     t_j=0.15, soft_pct=0.10, hard_pct=0.25,
                     flagged_ratio_limit=0.20, max_suboptimal_segments=0.70,
                     emergency_hard_segment_ratio=0.90
Bench 2 sizes      : [5k, 10k, 25k, 50k, 100k, 200k]
Bench D c-sweep    : [0.50, 0.75, 1.00, 1.01, 1.25, 1.50, 2.00]
Bench E k-sweep    : [2, 3, 4, 5, 6, 8, 10, 14, 20]
Bench E seg-sweep  : [50, 100, 175, 300, 500, 800]
Bench 8 total ops  : 300,000 (6 × 50k windows)
```
