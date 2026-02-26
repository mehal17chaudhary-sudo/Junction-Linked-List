# Junction Linked List (JLI) — AMJ List

**Stability. Structural Intelligence. Transparent Cost.**

---

## What Is JLI?

Junction Linked List (JLI), also known as the **Anna Mani Junction List (AMJ List)**, is an in-memory, structurally driven ordered index built around a single guiding principle: **the structure should carry all the information needed to stay efficient — not the workload.**

JLI does not tune itself to access patterns. It does not rely on probabilistic balancing. Instead, it maintains explicit structural invariants that govern traversal, bound maintenance costs, and give you direct, real-time visibility into what the structure is doing and why.

---

## About the Name

JLI is also referred to as the **Anna Mani Junction List (AMJ List)**, named in tribute to **Anna Mani** (1918–2001), a pioneering Indian physicist and meteorologist.

In a newly independent India that depended on foreign meteorological instruments, Anna Mani took a harder path: she built reliable scientific instruments domestically, capable of operating under India's demanding and diverse conditions. Through her work at the India Meteorological Department, she standardized weather instruments for the entire country, later making foundational contributions to solar radiation measurement before renewable energy was a global concern.

Her legacy is one of **structural self-reliance over dependence on external conditions** — the same design ethos that defines this data structure.

---

## Why JLI Exists

Most fast in-memory structures hide their true costs. Probabilistic structures promise strong averages but offer no structural guarantee on tail behavior, maintenance timing, or what happens when access patterns shift. Structures that rely on workload-specific tuning degrade when assumptions no longer hold.

These problems don't show up in microbenchmarks. They show up at scale, over time, under mixed or shifting workloads — precisely when reliability matters most.

JLI was built to address this directly.

---

## Structural Design

JLI is built from three components:

**Segments** divide the list into fixed-size regions, bounding traversal and maintenance cost to local areas. Optimal segment size scales with `sqrt(N)`.

**Junctions** sit at segment midpoints. Each junction stores segment metadata and participates in traversal as a normal node, providing O(N/S) coarse navigation without a separate index layer.

**Shortcuts** are regular nodes within a segment that additionally accelerate fine-grained traversal. They are placed at computed offsets — not randomly — and reduce the linear scan within a segment without adding a new structural tier.

---

## Maintenance Model

JLI uses three levels of explicit, rate-limited maintenance:

| Level | Scope | Trigger | Purpose |
|---|---|---|---|
| Local | Single segment | Junction drifts > `t_j` from center | Corrects drift in individual segments |
| Suboptimal | Flagged segments | Segment deviation exceeds `soft_pct` / `hard_pct` | Targets structurally degraded regions |
| Global | Full list | Last resort: escalation gate or emergency ratio | Emergency structural recovery |

None of these run on every operation. They are triggered by structural conditions — not probabilistic thresholds — and their costs are fully exposed through the `get_metrics()` API. If a global rebuild fires, you will see it in the counter.

---

## What JLI Actually Guarantees

These are the properties JLI is designed and empirically validated to provide:

### 1. Structural Invariants Are Maintained

JLI's invariants — segment size bounds, junction positioning, shortcut validity — are maintained continuously by the maintenance system. The structure does not silently degrade over time or under unusual key distributions. Maintenance is structural: it triggers on measurable drift, not on probability.

### 2. Maintenance Behavior Is Workload-Independent

The *decision* to maintain is driven by structural state, not by what operations are running. Across workloads from pure-delete to extreme insert floods, the maintenance scan rate stays within a narrow band. The structure maintains itself at roughly the same rhythm whether you're reading, writing, or doing both.

This does not mean **latency** is workload-independent — it is not. Latency is coupled to operation mix because search traversal and insert pressure have different raw costs. The invariant is about maintenance behavior, not about raw speed.

### 3. Long-Run Stability

p99 latency over a 300k-operation continuous run drifts by a mean of **1.28×** — roughly 28% from first window to last, with exactly 1 global rebuild per seed. Worst-case observed drift across 4 seeds: 1.52×. The structure does not compound degradation over time and no runaway growth has been observed, but drift is real and should not be reported as zero.

### 4. Near-Flat Latency Scaling With N

p99 stays within a narrow absolute band as N grows. The log-log scaling exponent is **−0.073** across N=5k–200k — meaning p99 actually decreases relative to N as the dataset grows. A 40× increase in dataset size produces p99 values that are lower at large N than small N. Most sorted structures degrade with N. This one does not.

### 5. Works Correctly Across All Dataset Sizes

JLI operates correctly and maintains its structural invariants across the full range of practical in-memory dataset sizes. Parameters scale with `sqrt(N)` and the structure adapts automatically. The practical lower bound is approximately N=5,000, below which constant overhead dominates.

---

## Cost Model

**Core Operations:**

| Operation | Best Case | Average / Worst Case |
|---|---|---|
| Search | O(1) | O(N/S + S) |
| Insert | O(1) | O(N/S + S) |
| Delete | O(1) | O(N/S + S) |

`S` = segment size. At `S ≈ sqrt(N)`, this reduces to O(sqrt(N)). **Average and worst-case bounds are identical** — traversal follows structural logic, not distributional assumptions.

**Maintenance:**

| Level | Cost |
|---|---|
| Local Rebuild | O(r · S) per pass, r = rebuilt segments |
| Suboptimal Rebuild | O(r · S) per pass, r = affected regions |
| Global Rebuild | O(N) — last resort only |

All maintenance costs are directly measurable via `get_metrics()`.

---

## Observability

JLI exposes a full set of read-only counters via `get_metrics()`:

```python
m = jli.get_metrics()
# {
#   "local_scan":   int,   # local drift scan events
#   "sub_scan":     int,   # suboptimal fragmentation scan events
#   "local_event":  int,   # local rebuild events
#   "sub_event":    int,   # suboptimal rebuild events
#   "global_event": int,   # global rebuild events
#   "local_cost":   int,   # nodes processed in local rebuilds
#   "sub_cost":     int,   # segments rebuilt in suboptimal passes
#   "global_cost":  int,   # nodes processed in global rebuilds
# }
```

These are direct counts of what the structure has done — not estimates or approximations.

---

## Key Observed Properties

**Latency scaling with N** — p99 scales with a log-log exponent of **−0.073** over the N=5k–200k range. A 40× dataset size increase produces p99 values that are lower at large N than small N. The structure gets proportionally cheaper as it grows — the opposite of most sorted structures.

**Long-run p99 stability** — over a 300k-operation continuous mixed workload, mean first-to-last window p99 drift is **1.28×** (range: 1.16× to 1.52× across 4 seeds), with exactly 1 global rebuild per seed. No runaway growth observed.

**Maintenance rate stability across workloads** — the maintenance scan rate stays within a narrow absolute range across workload profiles spanning pure-delete to extreme insert floods. The maintenance decision is structural, not workload-driven.

**Configuration robustness** — the empirically tuned parameter set consistently outperforms alternative configurations by significant margins. Two hard limits are worth knowing: `sub_interval` set excessively high causes deferred maintenance to eventually fire as a large latency spike; `local_interval` below ~500 causes thrashing. Both are documented in the API reference.

---

## Latency vs. Throughput

JLI carries an explicit maintenance overhead — this is by design and fully measurable. If your primary metric is peak raw throughput on a single operation type, a simpler structure will outperform it. If your primary metric is **stable, predictable, observable behavior over long runtimes under mixed workloads**, JLI is built for exactly that.

---

## When to Use JLI

**JLI is a strong fit when:**
- Workloads are mixed, unknown, or shift over time
- Systems run continuously at high operation counts
- Maintenance cost must be measurable and bounded, not hidden
- Long-term latency stability is a correctness requirement
- Dataset size changes over the lifetime of the system

**JLI is not designed for:**
- Very small datasets (N < ~5,000) where constant overhead dominates
- Random-access semantics — JLI is an ordered index, not a hash map or array
- Single-operation benchmarks optimized for one workload type
- Workloads that are overwhelmingly search-dominant

---

## API Quick Reference

```python
from JLI import JLI

# Initialize
jli = JLI(segment_size=175, shortcuts_per_junction=6)

# Load (most efficient path for initial data)
jli.build_from_values(sorted_keys)
jli.build_from_values(objects, key=lambda o: o["id"])

# Core operations
jli.insert(key)
jli.insert(key, payload=obj)
jli.delete(key)
node = jli.search(key)      # returns Node or None
jli.insert_many(keys)
jli.delete_many(keys)
jli.size()

# Observability
m = jli.get_metrics()       # full maintenance counter dict
```

Full API documentation: `API_README.md`

---

## Who Built This

**Mehal Chaudhary** — computer science engineering student and independent researcher, 18. Interested in systems design where structure, performance, and long-term behavior intersect.

JLI reflects a focus on structural invariants, maintenance-aware systems, and predictable performance over time rather than short-lived optimizations.

Open to internships, research collaborations, and engineering roles where systems thinking and scalability reasoning are valued.

---

*"If the ideas behind JLI resonate with you, the best way to evaluate it is to observe its behavior in your own workload."*
