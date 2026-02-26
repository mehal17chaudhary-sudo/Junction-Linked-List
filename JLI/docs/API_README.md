# JLI API Reference

**JLI / AMJ List — Python API Documentation**

This document covers every user-facing parameter, method, and observable property in the JLI library.

---

## Table of Contents

1. [Installation](#1-installation)
2. [Initialization & Configuration](#2-initialization--configuration)
3. [Core Operations](#3-core-operations)
4. [Observability: get_metrics()](#4-observability-get_metrics)
5. [Complete Examples](#5-complete-examples)
6. [Parameter Reference](#6-parameter-reference)

---

## 1. Installation

```bash
pip install jli
```

The class is available under two equivalent names:

```python
from JLI import JunctionLinkedList   # full name
from JLI import JLI                  # short alias
```

---

## 2. Initialization & Configuration

All configuration is set at initialization time. Parameters cannot be changed after the instance is created — structural invariants are defined once and held for the lifetime of the index.

> **Library defaults vs. tuned defaults.** The constructor signature below shows the library's built-in defaults. These are not the empirically tuned values. For production use at N≈30k, use the tuned configuration shown here:

```python
from JLI import JLI

jli = JLI(
    segment_size=175,
    shortcuts_per_junction=6,
    local_interval=2000,
    sub_interval=2000,
    soft_pct=0.10,
    hard_pct=0.25,
    flagged_ratio_limit=0.20,
    max_suboptimal_segments=0.70,
    emergency_hard_segment_ratio=0.90,
)
```

For other dataset sizes, scale `segment_size ≈ sqrt(N)` and set `shortcuts_per_junction = max(4, int(sqrt(segment_size)))`.

### Constructor Signature

```python
JLI(
    segment_size=100,
    shortcuts_per_junction=3,
    *,
    enable_rebuild=True,
    local_interval=1000,
    t_j=0.15,
    sub_interval=5000,      # ⚠ outside recommended range — see sub_interval section
    soft_pct=0.25,
    hard_pct=0.50,
    flagged_ratio_limit=0.30,
    min_seg_len_pct=0.25,
    max_suboptimal_segments=0.3,   # ⚠ in danger zone — see max_suboptimal_segments section
    min_suboptimal_events_before_global=5,
    emergency_hard_segment_ratio=0.95,
    stop_crash_local_sub=0.08,
)
```

All parameters after `*` are keyword-only.

---

### Parameter Details

---

#### `segment_size` — `int`, default `100`

The number of nodes per segment. This is the single most impactful parameter. Traversal cost is `O(N/S + S)`, minimized when `S ≈ sqrt(N)`.

**Recommended by N:**

| N | Recommended `segment_size` |
|---|---|
| 5,000 | 70 |
| 10,000 | 100 |
| 25,000 | 150 |
| 50,000 | 225 |
| 100,000 | 300 |
| 200,000 | 450 |

---

#### `shortcuts_per_junction` — `int`, default `3`

Number of shortcut nodes per segment. Shortcuts accelerate intra-segment traversal without adding a separate structural tier.

Minimum effective value is 2 (permanent start/end shortcuts). Additional shortcuts are placed at computed midpoints. The engine internally enforces `K = max(2, shortcuts_per_junction)`.

**Auto-scale formula:** `k = max(4, int(sqrt(segment_size)))`

---

#### `enable_rebuild` — `bool`, default `True`

Master switch for all periodic maintenance. Setting to `False` disables local, suboptimal, and global rebuilds entirely. Leave `True` in production.

---

#### `local_interval` — `int`, default `1000`

How many mutating operations (insert + delete) between local maintenance scans. A local scan checks each junction for positional drift and triggers a local rebuild on any segment where the junction has drifted more than `t_j` from center.

**Hard limit:** values below ~500 cause a measurable thrashing cliff — p99 degrades significantly. Stay above 500.

**Lower values** → more frequent checks, smaller drift accumulation.
**Higher values** → fewer interruptions, more drift allowed before correction.

---

#### `t_j` — `float`, default `0.15`

Junction drift tolerance. Controls how far a junction node may drift from the center of its segment before triggering a local rebuild, measured as a fraction of segment length.

Triggers when `abs(position - 0.5) > t_j`. At `t_j=0.15`, the junction must move more than 15% off-center. Values ≥ 0.08 eliminate spurious events.

---

#### `sub_interval` — `int`, default `5000`

How many mutating operations between suboptimal (segment-level) scans. A suboptimal scan checks all segments against fragmentation thresholds and rebuilds degraded regions.

**⚠ The library default of 5000 is outside the empirically recommended range.** For datasets in the tens-of-thousands, keep this between 1,000 and 3,000. The tuned default is 2,000.

**Hard limits:**
- **Too high** (e.g. 40,000+): deferred maintenance eventually fires as a catastrophic latency spike. A benchmark run with `sub_interval=40k` produced mean p99 of 2,395 µs — 51× worse than the tuned default. This is the single most dangerous misconfiguration.
- **Too low** (e.g. 200): frequent small scans add overhead. Measured at 1.17× worse than tuned.

Setting `sub_interval` to tens-of-thousands is the fastest way to recreate the Insert-flood tail spike problem on every workload, permanently.

---

#### `soft_pct` — `float`, default `0.25`

Soft fragmentation threshold. A segment whose length differs from `segment_size` by more than `soft_pct × segment_size` is soft-flagged. Soft-flagged segments are rebuilt when the overall soft-flagged ratio exceeds `flagged_ratio_limit`.

Lower values make the sub-level system more responsive to drift.

---

#### `hard_pct` — `float`, default `0.50`

Hard fragmentation threshold. A segment that differs from `segment_size` by more than `hard_pct × segment_size` is hard-flagged and bypasses the ratio check — rebuilt immediately.

Lower hard threshold means the bypass fires sooner on genuine structural bloat.

---

#### `flagged_ratio_limit` — `float`, default `0.30`

If the fraction of soft-flagged segments across the list exceeds this limit, a suboptimal rebuild pass runs. Lowering catches fragmentation earlier.

---

#### `min_seg_len_pct` — `float`, default `0.25`

Minimum rebuilt-segment length as a fraction of `segment_size`. Regions shorter than `min_seg_len_pct × segment_size` are absorbed into a neighboring segment rather than rebuilt standalone. Prevents over-segmentation after heavy deletes.

---

#### `max_suboptimal_segments` — `float`, default `0.3`

A **fraction** of total segments. If the flagged-segment ratio exceeds this value AND `min_suboptimal_events_before_global` has been reached, a global rebuild is triggered.

**⚠ The library default of 0.3 is inside the danger zone.** This parameter functions as a **guard, not a trigger** — it must be large enough to not fire prematurely under normal load. Setting below 0.35 risks unintended global escalation under normal operation. **The tuned value is 0.70.**

Combined gate: `(sub_events ≥ min_suboptimal_events_before_global) AND (flagged_ratio ≥ max_suboptimal_segments)` → global rebuild.

---

#### `min_suboptimal_events_before_global` — `int`, default `5`

How many suboptimal rebuild events must occur before the system may escalate to a global rebuild. Together with `max_suboptimal_segments`, this forms the escalation gate.

---

#### `emergency_hard_segment_ratio` — `float`, default `0.95`

Emergency global rebuild threshold. If the fraction of hard-flagged segments reaches this value, an unconditional global rebuild fires regardless of event count. This is the structural safety floor of last resort.

---

#### `stop_crash_local_sub` — `float`, default `0.08`

Backoff fraction to prevent local and suboptimal maintenance from colliding. When a suboptimal scan is within `stop_crash_local_sub × sub_interval` operations of firing, local maintenance is deferred rather than running.

This is a float, not a bool. At `0.08` with `sub_interval=2000`: local maintenance backs off when fewer than 160 operations remain before the next suboptimal scan.

---

## 3. Core Operations

---

### `build_from_values(values, key=lambda x: x)` → `None`

Build the JLI index from a **pre-sorted** iterable. Most efficient path for initial data — builds the full junction structure in a single pass, bypassing per-insert maintenance hooks.

```python
# Simple sorted integers
jli.build_from_values([1, 4, 7, 12, 25, 50])

# Objects with a key function (must be pre-sorted by that key)
records = [{"id": 1, "name": "Alice"}, {"id": 5, "name": "Bob"}]
jli.build_from_values(records, key=lambda r: r["id"])
```

**Parameters:**
- `values` — any iterable; must already be sorted according to `key`
- `key` — function that extracts the sortable value. Default is identity

Each item is stored as a `Node` with `node.value = key(item)` and `node.payload = item`.

---

### `insert(value, payload=None, allow_duplicate=False)` → `bool`

Insert a value into the ordered index. Returns `True` if inserted, `False` if the key already exists and `allow_duplicate=False`.

```python
jli.insert(42)
jli.insert(42, payload={"user": "alice"})   # with attached data
jli.insert(42, allow_duplicate=True)         # allow repeated keys
```

**Parameters:**
- `value` — integer key
- `payload` — any Python object; retrieved via `node.payload` from `search()`
- `allow_duplicate` — if `False` (default), duplicate keys are silently rejected

**Cost:** O(1) best case, O(N/S + S) average and worst case.
**Side effect:** triggers the maintenance hook on every call (unless `enable_rebuild=False`).

---

### `delete(value)` → `bool`

Remove a value from the index. Returns `True` if found and removed, `False` if not found.

```python
removed = jli.delete(42)
```

**Cost:** O(N/S + S) average and worst case.

---

### `search(value)` → `Node | None`

Search for a value. Returns the **`Node` object** if found, `None` if not found.

```python
node = jli.search(42)
if node is not None:
    print(node.value)    # the key
    print(node.payload)  # attached data if any
```

The returned `Node` has:
- `node.value` — the key
- `node.payload` — payload attached at insert time, or the original item from `build_from_values`
- `node.next` — next node in sorted order (internal linkage; treat as read-only)

**Cost:** O(1) best case, O(N/S + S) average and worst case.

---

### `insert_many(values, allow_duplicate=False, rebuild=False)` → `None`

Batch insert from an iterable.

```python
jli.insert_many(range(100_000))
jli.insert_many(data, rebuild=True)   # force full junction rebuild after batch
```

**Parameters:**
- `values` — iterable of integer keys
- `allow_duplicate` — passed to each `insert()` call
- `rebuild` — if `True`, forces a full `_build_junctions()` after all inserts

Maintenance hooks still fire normally during the batch.

---

### `delete_many(values, rebuild=False)` → `None`

Batch delete from an iterable.

```python
jli.delete_many([1, 5, 7, 23])
jli.delete_many(stale_keys, rebuild=True)
```

---

### `size()` → `int`

Returns the current number of nodes in the list.

```python
n = jli.size()
```

---

## 4. Observability: get_metrics()

### `get_metrics()` → `dict`

Returns a snapshot of all maintenance counters since the instance was created. All values are cumulative totals — subtract two snapshots to get deltas over a window.

```python
m = jli.get_metrics()
```

**Return value:**

| Key | Type | Description |
|---|---|---|
| `local_scan` | int | Total local scan events (full drift checks) |
| `sub_scan` | int | Total suboptimal scan events (fragmentation checks) |
| `local_event` | int | Total local rebuild events |
| `sub_event` | int | Total suboptimal rebuild events |
| `global_event` | int | Total global rebuild events |
| `local_cost` | int | Nodes processed in local rebuilds |
| `sub_cost` | int | Segments rebuilt in suboptimal passes |
| `global_cost` | int | Nodes processed in global rebuilds |

**Useful derived signals:**

```python
m = jli.get_metrics()
total_ops = jli._e.search_count + jli._e.insert_count + jli._e.delete_count

# Maintenance rate: sub-level scan frequency per operation
sub_scan_rate = m["sub_scan"] / max(total_ops, 1)

# Amortized rebuild cost per operation
amortized_cost = (m["local_cost"] + m["sub_cost"] + m["global_cost"]) / max(total_ops, 1)
```

**Windowed monitoring pattern** — subtract consecutive snapshots to get per-window deltas:

```python
prev = {k: 0 for k in ["local_scan","sub_scan","local_event","sub_event",
                        "global_event","local_cost","sub_cost","global_cost"]}

def get_window_deltas(jli):
    global prev
    m = jli.get_metrics()
    delta = {k: m[k] - prev[k] for k in prev}
    prev = dict(m)
    return delta

# In your monitoring loop:
delta = get_window_deltas(jli)
if delta["global_event"] > 0:
    print(f"WARNING: {delta['global_event']} global rebuild(s) in last window")
```

---

## 5. Complete Examples

### Example 1: Basic Usage

```python
from JLI import JLI
import random

jli = JLI(
    segment_size=175,
    shortcuts_per_junction=6,
    local_interval=2000,
    sub_interval=2000,
    soft_pct=0.10,
    hard_pct=0.25,
    flagged_ratio_limit=0.20,
    max_suboptimal_segments=0.70,
    emergency_hard_segment_ratio=0.90,
)

keys = sorted(random.sample(range(1_000_000), 30_000))
jli.build_from_values(keys)

for _ in range(25_000):
    key = random.randint(0, 1_000_000)
    r = random.random()
    if r < 0.34:
        jli.search(key)
    elif r < 0.67:
        jli.insert(key)
    else:
        jli.delete(key)

print(f"Size: {jli.size()}")
m = jli.get_metrics()
print(f"Local events:    {m['local_event']}")
print(f"Sub events:      {m['sub_event']}")
print(f"Global events:   {m['global_event']}")
```

---

### Example 2: Insert with Payload

```python
from JLI import JLI

jli = JLI(segment_size=100)

jli.insert(1001, payload={"name": "Alice", "score": 95.5})
jli.insert(1002, payload={"name": "Bob",   "score": 88.0})
jli.insert(1003, payload={"name": "Carol", "score": 91.2})

node = jli.search(1002)
if node:
    print(node.value)           # 1002
    print(node.payload["name"]) # "Bob"
```

---

### Example 3: Build from Objects

```python
from JLI import JLI

records = [
    {"id": 10, "name": "Alice"},
    {"id": 25, "name": "Bob"},
    {"id": 47, "name": "Carol"},
]
records.sort(key=lambda r: r["id"])   # must be pre-sorted

jli = JLI(segment_size=100)
jli.build_from_values(records, key=lambda r: r["id"])

node = jli.search(25)
if node:
    print(node.payload["name"])  # "Bob"
```

---

### Example 4: Auto-scaled Configuration for Any N

```python
from JLI import JLI
import math

def make_jli_for_n(N, **overrides):
    seg = max(25, int(round(math.sqrt(N))))
    k   = max(4, min(10, int(math.sqrt(seg))))
    params = dict(
        segment_size=seg,
        shortcuts_per_junction=k,
        enable_rebuild=True,
        local_interval=2000,
        t_j=0.15,
        sub_interval=2000,
        soft_pct=0.10,
        hard_pct=0.25,
        flagged_ratio_limit=0.20,
        min_seg_len_pct=0.25,
        max_suboptimal_segments=0.70,
        min_suboptimal_events_before_global=5,
        emergency_hard_segment_ratio=0.90,
        stop_crash_local_sub=0.08,
    )
    params.update(overrides)
    return JLI(**params)
```

---

### Example 5: Windowed Monitoring

```python
from JLI import JLI
import random

jli = make_jli_for_n(30_000)
jli.build_from_values(sorted(random.sample(range(1_000_000), 30_000)))

WINDOW = 5_000
prev = {k: 0 for k in ["local_scan","sub_scan","local_event",
                        "sub_event","global_event","local_cost",
                        "sub_cost","global_cost"]}

for window_num in range(1, 7):
    for _ in range(WINDOW):
        key = random.randint(0, 1_000_000)
        r = random.random()
        if r < 0.34:   jli.search(key)
        elif r < 0.67: jli.insert(key)
        else:          jli.delete(key)

    m = jli.get_metrics()
    delta = {k: m[k] - prev[k] for k in prev}
    prev = dict(m)

    print(f"Window {window_num}")
    print(f"  local={delta['local_event']}  sub={delta['sub_event']}  "
          f"global={delta['global_event']}  sub_cost={delta['sub_cost']}")
    if delta["global_event"] > 0:
        print("  ⚠ Global rebuild fired")
```

---

### Example 6: Workload Shift

```python
from JLI import JLI
import random

jli = make_jli_for_n(30_000)
jli.build_from_values(sorted(random.sample(range(1_000_000), 30_000)))

phases = [
    ("Balanced",     0.34, 0.33),
    ("Read-heavy",   0.80, 0.15),
    ("Insert-flood", 0.05, 0.90),
    ("Delete-flood", 0.05, 0.05),
    ("Recovery",     0.34, 0.33),
]

prev = {k: 0 for k in ["local_event","sub_event","global_event"]}

for label, sp, ip in phases:
    for _ in range(10_000):
        key = random.randint(0, 1_000_000)
        r = random.random()
        if r < sp:       jli.search(key)
        elif r < sp+ip:  jli.insert(key)
        else:            jli.delete(key)

    m = jli.get_metrics()
    d = {k: m[k] - prev[k] for k in prev}
    prev = {k: m[k] for k in prev}
    print(f"{label:16s}  local={d['local_event']:3d}  "
          f"sub={d['sub_event']:3d}  global={d['global_event']}")
```

---

## 6. Parameter Reference

| Parameter | Type | Library Default | Tuned Default | Description |
|---|---|---|---|---|
| `segment_size` | int | 100 | 175 (N≈30k) | Nodes per segment. Scale with √N. |
| `shortcuts_per_junction` | int | 3 | 6 | Shortcut nodes per segment. Min effective = 2. |
| `enable_rebuild` | bool | True | True | Master maintenance switch. |
| `local_interval` | int | 1000 | 2000 | Mutating ops between local drift scans. Stay above 500. |
| `t_j` | float | 0.15 | 0.15 | Junction drift tolerance (fraction of segment length). |
| `sub_interval` | int | **5000 ⚠** | **2000** | Mutating ops between suboptimal scans. **Keep 1,000–3,000. Library default is outside this range.** |
| `soft_pct` | float | 0.25 | 0.10 | Soft fragmentation flag threshold. |
| `hard_pct` | float | 0.50 | 0.25 | Hard fragmentation flag threshold. |
| `flagged_ratio_limit` | float | 0.30 | 0.20 | Soft-flagged fraction to trigger suboptimal rebuild. |
| `min_seg_len_pct` | float | 0.25 | 0.25 | Min rebuilt region size as fraction of segment_size. |
| `max_suboptimal_segments` | float | **0.30 ⚠** | **0.70** | Flagged fraction (with event count) to allow global escalation. **Library default is in danger zone — must be ≥ 0.35.** |
| `min_suboptimal_events_before_global` | int | 5 | 5 | Min sub events before global escalation is possible. |
| `emergency_hard_segment_ratio` | float | 0.95 | 0.90 | Hard-segment fraction for emergency global rebuild. |
| `stop_crash_local_sub` | float | 0.08 | 0.08 | Backoff fraction to avoid local/sub maintenance collision. |

---

### Hard Limits

| Parameter | Danger Zone | Effect |
|---|---|---|
| `local_interval` | < 500 | Thrashing — p99 degrades severely |
| `sub_interval` | > ~5,000 (library default) or > 20,000+ | Deferred maintenance fires as a large latency spike. At 40,000: measured 51× p99 degradation. |
| `max_suboptimal_segments` | < 0.35 | Premature global escalation under normal operation. Library default of 0.30 is inside this zone. |
| `segment_size` | < 50 or > 1,500 | Traversal imbalance at both extremes — measured 2.56× worse p99 at seg=1,500 |
