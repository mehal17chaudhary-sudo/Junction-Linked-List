# ══════════════════════════════════════════════════════════════════════════════
# JLI IMPLEMENTATION
# ══════════════════════════════════════════════════════════════════════════════

class Node:
    __slots__ = ("value", "next", "payload")
    def __init__(self, value, payload=None):
        self.value   = value
        self.next    = None
        self.payload = payload
    def __repr__(self): return "Node(%d)" % self.value


class Junction:
    __slots__ = ("node","segment_start","segment_end","prev_junction",
                 "next_junction","shortcuts","segment_len","runtime_len")
    def __init__(self, node):
        self.node = node; self.segment_start = node; self.segment_end = node
        self.prev_junction = None; self.next_junction = None
        self.shortcuts = []; self.segment_len = 0; self.runtime_len = 0


def _segment_len_hint(actual_len, segment_size, tol=0.02):
    if abs(actual_len - segment_size) <= segment_size * tol:
        return segment_size
    return actual_len


def _plan_shortcuts_offsets(seg_len, K):
    needed = max(0, max(2, int(K)) - 2)
    if seg_len <= 1 or needed <= 0: return []
    mid_idx = (seg_len - 1) // 2
    intervals = [(0, mid_idx), (mid_idx, seg_len - 1)]
    offsets = []
    while needed > 0 and intervals:
        l, r = intervals.pop(0)
        if r - l <= 1: continue
        mid = (l + r) // 2
        if mid not in (0, mid_idx, seg_len - 1):
            offsets.append(mid); needed -= 1
        if needed > 0:
            intervals.append((l, mid)); intervals.append((mid, r))
    return offsets


def _plan_segment(seg_len, K):
    if seg_len <= 1:
        return {"seg_len": seg_len, "junction_offset": 0, "shortcut_offsets": []}
    return {"seg_len": seg_len, "junction_offset": (seg_len - 1) // 2,
            "shortcut_offsets": _plan_shortcuts_offsets(seg_len, K)}


def _compute_segment_ranges(n, segment_size, tol=0.02):
    size = max(1, segment_size); ranges = []; start = 1
    while start <= n:
        end = min(start + size - 1, n); actual = end - start + 1
        ranges.append((start, end, _segment_len_hint(actual, size, tol=tol)))
        start = end + 1
    return ranges


def _is_live(j, jid_set):
    return (j is not None and id(j) in jid_set
            and j.segment_start is not None
            and j.segment_end is not None and j.node is not None)


class _JLIEngine:
    def __init__(self, segment_size=100, shortcuts_per_junction=3,
                 enable_rebuild=True, local_interval=1000, t_j=0.15,
                 sub_interval=5000, soft_pct=0.25, hard_pct=0.50,
                 flagged_ratio_limit=0.30, min_seg_len_pct=0.25,
                 max_suboptimal_segments=0.3,
                 min_suboptimal_events_before_global=5,
                 emergency_hard_segment_ratio=0.95, stop_crash_local_sub=0.08):
        self.head = None; self.length = 0
        self.junctions = []; self._jid_set = set()
        self.segment_size = max(1, segment_size)
        self.K = max(2, shortcuts_per_junction)
        self.enable_rebuild = enable_rebuild
        self.local_interval = local_interval; self.t_j = t_j
        self.sub_interval = sub_interval; self.soft_pct = soft_pct
        self.hard_pct = hard_pct; self.flagged_ratio_limit = flagged_ratio_limit
        self.min_seg_len_pct = min_seg_len_pct
        self.max_suboptimal_segments = max_suboptimal_segments
        self.min_suboptimal_events_before_global = min_suboptimal_events_before_global
        self.emergency_hard_segment_ratio = emergency_hard_segment_ratio
        self.stop_crash_local_sub = stop_crash_local_sub
        self._last_junction = None; self._last_prev_junction = None
        self.local_scan_counter = 0; self.suboptimal_scan_count = 0
        self.local_rebuild_events = 0; self.suboptimal_rebuild_events = 0
        self.global_rebuild_events = 0; self.local_rebuild_cost = 0
        self.suboptimal_segments_cost = 0; self.global_rebuild_cost = 0
        self.local_ops_counter = 0; self.sub_ops_counter = 0
        self.sub_event_before_global_rebuild = 0
        self.search_count = 0; self.insert_count = 0; self.delete_count = 0

    def _refresh_jid(self):
        self._jid_set = {id(j) for j in self.junctions if j is not None}
    def _live(self, j): return _is_live(j, self._jid_set)
    def _ps(self, seg_len): return _plan_segment(seg_len, self.K)
    def _dist(self, a, b):
        d = 1; cur = a
        while cur and cur is not b: cur = cur.next; d += 1
        return d
    def size(self): return self.length
    def get_metrics(self):
        return {"local_scan": self.local_scan_counter,
                "sub_scan":   self.suboptimal_scan_count,
                "local_event":  self.local_rebuild_events,
                "sub_event":    self.suboptimal_rebuild_events,
                "global_event": self.global_rebuild_events,
                "local_cost":   self.local_rebuild_cost,
                "sub_cost":     self.suboptimal_segments_cost,
                "global_cost":  self.global_rebuild_cost}

    def _build_junctions(self):
        self.junctions = []
        if not self.head: self._refresh_jid(); return
        ranges = _compute_segment_ranges(self.length, self.segment_size, tol=0.02)
        plans  = [_plan_segment(sl, self.K) for _, _, sl in ranges]
        cur    = self.head; seg_i = seg_offset = 0
        seg_start = jn = None; shortcuts = []; sc_set = set()
        while cur and seg_i < len(plans):
            plan = plans[seg_i]; sl = plan["seg_len"]
            if seg_offset == 0:
                seg_start = cur; jn = None; shortcuts = [cur]
                sc_set = set(plan["shortcut_offsets"])
            if seg_offset == plan["junction_offset"]: jn = cur
            if seg_offset in sc_set: shortcuts.append(cur)
            if seg_offset == sl - 1:
                seg_end = cur; shortcuts.append(cur)
                if len(shortcuts) < self.K:
                    shortcuts.extend([seg_start] * (self.K - len(shortcuts)))
                if jn is None: jn = seg_start
                j = Junction(jn); j.segment_start = seg_start
                j.segment_end = seg_end; j.segment_len = sl; j.shortcuts = shortcuts
                self.junctions.append(j)
                seg_i += 1; seg_offset = -1; shortcuts = []; jn = None; sc_set = set()
            cur = cur.next; seg_offset += 1
        n = len(self.junctions)
        for i in range(n):
            self.junctions[i].prev_junction = self.junctions[i - 1]
            self.junctions[i].next_junction = self.junctions[(i + 1) % n]
        self._refresh_jid()

    def build_from_values(self, values, key=lambda x: x):
        self.head = None; prev = None; self.length = 0
        for item in values:
            v = key(item); node = Node(v, payload=item)
            if self.head is None: self.head = node
            else: prev.next = node
            prev = node; self.length += 1
        self._build_junctions()

    def _choose_start(self, target):
        if not self.junctions: return None
        cands = []
        f = self.junctions[0]; la = self.junctions[-1]
        if self._live(f): cands.append(f)
        if self._live(la) and la is not f: cands.append(la)
        if self._live(self._last_junction): cands.append(self._last_junction)
        if self._live(self._last_prev_junction): cands.append(self._last_prev_junction)
        if not cands: return None
        for j in cands:
            if j.segment_start.value <= target <= j.segment_end.value: return j
        return min(cands, key=lambda j: min(abs(target - j.segment_start.value),
                                             abs(target - j.segment_end.value)))

    def search(self, target):
        self.search_count += 1
        if not self.junctions: return None
        cj = self._choose_start(target); visited = set()
        while cj not in visited:
            if not self._live(cj): return None
            visited.add(cj)
            ss = cj.segment_start.value; se = cj.segment_end.value
            if not (ss <= target <= se):
                cj = cj.prev_junction if target < ss else cj.next_junction; continue
            sn = (cj.segment_start if (cj.node and target < cj.node.value)
                  else (cj.node or cj.segment_start))
            valid = [sc for sc in cj.shortcuts if sn.value < sc.value <= target]
            if valid:
                best = max(valid, key=lambda n: n.value)
                if best.value > sn.value: sn = best
            cur = sn
            while cur and cur.value <= se:
                if cur.value == target: self._last_junction = cj; return cur
                if cur.value > target: return None
                cur = cur.next
            return None
        return None

    def _linear_scan(self, target):
        prev = None; cur = self.head
        while cur and cur.value < target: prev = cur; cur = cur.next
        return prev, cur, None

    def mutation_search(self, target):
        if not self.junctions: return self._linear_scan(target)
        cj = self._choose_start(target)
        if not cj or not self._live(cj): return self._linear_scan(target)
        prev_junc = None; visited = set(); direction = None
        while cj not in visited:
            if not self._live(cj): return self._linear_scan(target)
            visited.add(cj)
            ss = cj.segment_start.value; se = cj.segment_end.value
            if ss <= target <= se: break
            prev_junc = cj
            if target < ss: direction = "r2l"; cj = cj.prev_junction
            else:           direction = "l2r"; cj = cj.next_junction
        else:
            if target < self.junctions[0].segment_start.value:
                self._last_prev_junction = None
                self._last_junction = self.junctions[0]
                return None, self.junctions[0].segment_start, self.junctions[0]
            else:
                self._last_prev_junction = (self.junctions[-2]
                                            if len(self.junctions) > 1 else None)
                self._last_junction = self.junctions[-1]
                return self.junctions[-1].segment_end, None, self.junctions[-1]
        self._last_prev_junction = prev_junc; self._last_junction = cj
        if target == cj.segment_start.value:
            if cj.segment_start is self.head:
                self._last_junction = cj; return None, self.head, cj
            fb = (cj.prev_junction if direction in ("l2r", None) else cj.next_junction)
            if fb and self._live(fb):
                anchor = fb.shortcuts[-1] if fb.shortcuts else fb.segment_end
                sp = anchor; sn = anchor.next
            else: sp = None; sn = self.head
            prev = sp; cur = sn
            while cur and cur.value < target: prev = cur; cur = cur.next
            self._last_junction = cj; return prev, cur, cj
        sn = cj.segment_start; sp = None
        if cj.node and target > cj.node.value: sn = cj.node
        psc = None
        for sc in cj.shortcuts:
            if sc.value < target: psc = sc
            else: break
        if psc: sn = psc
        if (self._last_prev_junction and self._live(self._last_prev_junction)
                and cj.segment_start is not self.head
                and target != cj.segment_start.value):
            cp = self._last_prev_junction.segment_end
            cn = cp.next if cp else None
            if cn and cn.value <= target: sp = cp; sn = cn
        prev = sp; cur = sn
        while cur and cur.value < target: prev = cur; cur = cur.next
        self._last_junction = cj; return prev, cur, cj

    def insert(self, value, payload=None, allow_duplicate=False):
        nn = Node(value, payload)
        if not self.head:
            self.head = nn; self.length = 1; self._build_junctions()
            self.insert_count += 1; return True
        prev, cur, j = self.mutation_search(value)
        if cur and cur.value == value and not allow_duplicate: return False
        nn.next = cur
        if prev: prev.next = nn
        else: self.head = nn
        self.length += 1
        if j is not None:
            if prev is None or value < j.segment_start.value:
                j.segment_start = nn
                if j.shortcuts and j.shortcuts[0] is cur: j.shortcuts[0] = nn
            elif prev is j.segment_end:
                j.segment_end = nn
                if j.shortcuts: j.shortcuts[-1] = nn
        self.local_ops_counter += 1; self.sub_ops_counter += 1
        if self.enable_rebuild: self._maintenance_hook()
        self.insert_count += 1; return True

    def delete(self, value):
        prev, cur, j = self.mutation_search(value)
        if not cur or cur.value != value: return False
        nxt = cur.next
        if prev: prev.next = nxt
        else: self.head = nxt
        self.length -= 1
        if self.length == 0:
            self.junctions = []; self._refresh_jid()
            self._last_junction = self._last_prev_junction = None
            self.delete_count += 1; return True
        if j is not None:
            nd = cur
            if nd is j.segment_start:
                j.segment_start = nxt
                for i in range(len(j.shortcuts)):
                    if j.shortcuts[i] is nd: j.shortcuts[i] = nxt
            elif nd is j.segment_end:
                j.segment_end = prev
                if j.shortcuts: j.shortcuts[-1] = prev
            elif nd is j.node:
                slow = fast = j.segment_start
                while (fast and fast.next and fast is not j.segment_end
                       and fast.next is not j.segment_end):
                    fast = fast.next.next; slow = slow.next
                j.node = slow
            elif nd in j.shortcuts:
                idx   = j.shortcuts.index(nd)
                left  = j.shortcuts[idx - 1] if idx > 0 else j.segment_start
                right = (j.shortcuts[idx + 1] if idx + 1 < len(j.shortcuts)
                         else j.segment_end)
                if left and right and left is not right:
                    slow = fast = left
                    while (fast and fast.next and fast is not right
                           and fast.next is not right):
                        fast = fast.next.next; slow = slow.next
                    j.shortcuts[idx] = slow
                else: j.shortcuts[idx] = left or right or j.segment_start
            sl = self._dist(j.segment_start, j.segment_end)
            if sl <= 2:
                vals = []; c2 = j.segment_start
                for _ in range(sl):
                    if c2 is None: break
                    vals.append(c2.value); c2 = c2.next
                if j in self.junctions: self.junctions.remove(j)
                n2 = len(self.junctions)
                for i in range(n2):
                    self.junctions[i].prev_junction = self.junctions[i - 1]
                    self.junctions[i].next_junction = self.junctions[(i + 1) % n2]
                self._refresh_jid()
                self._last_junction = self._last_prev_junction = None
                old_l = self.local_ops_counter; old_s = self.sub_ops_counter
                old_en = self.enable_rebuild; self.enable_rebuild = False
                for v in vals: self.insert(v)
                self.enable_rebuild = old_en
                self.local_ops_counter = old_l; self.sub_ops_counter = old_s
                self._last_junction = self._last_prev_junction = None
                self.delete_count += 1; return True
        self.local_ops_counter += 1; self.sub_ops_counter += 1
        if self.enable_rebuild: self._maintenance_hook()
        self.delete_count += 1; return True

    def insert_many(self, values, allow_duplicate=False, rebuild=False):
        for v in values: self.insert(v, allow_duplicate=allow_duplicate)
        if rebuild: self._build_junctions()

    def delete_many(self, values, rebuild=False):
        for v in values: self.delete(v)
        if rebuild: self._build_junctions()

    def _maintenance_hook(self):
        if self.local_ops_counter >= self.local_interval:
            bw = int(self.sub_interval * self.stop_crash_local_sub)
            if self.sub_interval > 0 and (self.sub_interval - self.sub_ops_counter) <= bw:
                self.local_ops_counter = max(self.local_interval // 2, 1)
            else:
                self.local_ops_counter = 0
                self.maintenance_step(self.local_interval, self.t_j)
        if self.sub_ops_counter >= self.sub_interval:
            self.sub_ops_counter = 0; self.suboptimal_scan_count += 1
            flagged, hard, seg_ratio = self._scan_suboptimal_segments()
            total = len(self.junctions)
            hard_ratio = len(hard) / max(1, total)
            if hard_ratio >= self.emergency_hard_segment_ratio:
                self.sub_event_before_global_rebuild = 0
                self._perform_global_rebuild(); return
            if (self.sub_event_before_global_rebuild
                    >= self.min_suboptimal_events_before_global
                    and seg_ratio >= self.max_suboptimal_segments):
                self.sub_event_before_global_rebuild = 0
                self._perform_global_rebuild(); return
            fr = len(flagged) / max(1, total)
            if fr >= self.flagged_ratio_limit: self.suboptimal_rebuild_step(flagged)
            elif hard: self.suboptimal_rebuild_step(hard)

    def maintenance_step(self, interval, t_j):
        if not self.junctions: return False
        rebuilt_any = False
        for j in list(self.junctions):
            if not self._live(j): continue
            rebuilt = self.maybe_local_rebuild(j, t_j)
            rebuilt_any = rebuilt_any or rebuilt
        self.local_scan_counter += 1; return rebuilt_any

    def _should_rebuild_and_measure(self, j, t_j):
        left = right = 0; seen = False; cur = j.segment_start
        while cur:
            if cur is j.node: seen = True; right = 1
            elif not seen: left += 1
            else: right += 1
            if cur is j.segment_end: break
            cur = cur.next
        if not seen: return False, 0
        total = left + right
        if total <= 1: return False, total
        return abs(left / total - 0.5) > t_j, total

    def _local_rebuild(self, j, seg_len):
        if seg_len <= 1: return
        plan = self._ps(seg_len); sc_set = set(plan["shortcut_offsets"])
        cur = j.segment_start; idx = 0; new_sc = []; jn = None
        while cur:
            if idx == plan["junction_offset"]: jn = cur
            if idx in sc_set: new_sc.append(cur)
            if cur is j.segment_end: break
            cur = cur.next; idx += 1
        if jn is None: jn = j.segment_start
        sc = [j.segment_start] + new_sc + [j.segment_end]
        if len(sc) < self.K: sc.extend([j.segment_start] * (self.K - len(sc)))
        j.node = jn; j.shortcuts = sc; j.segment_len = seg_len
        self.local_rebuild_events += 1; self.local_rebuild_cost += seg_len

    def maybe_local_rebuild(self, j, t_j):
        should, sl = self._should_rebuild_and_measure(j, t_j)
        if not should: return False
        self._local_rebuild(j, sl); self._last_junction = j; return True

    def _scan_suboptimal_segments(self):
        if not self.junctions: return [], [], 0.0
        soft = []; hard = []
        for i, j in enumerate(self.junctions):
            sl = self._dist(j.segment_start, j.segment_end); j.runtime_len = sl
            drift = abs(sl - self.segment_size) / self.segment_size
            if drift >= self.hard_pct: hard.append(i)
            elif drift >= self.soft_pct: soft.append(i)
        flagged = sorted(set(soft + hard))
        return flagged, hard, len(flagged) / max(1, len(self.junctions))

    def suboptimal_rebuild_step(self, flagged):
        if not self.junctions or not flagged: return 0
        min_seg_len_pct = self.min_seg_len_pct
        seg_size = self.segment_size
        min_region_len = int(seg_size * min_seg_len_pct)
        regions = []; start = prev2 = flagged[0]
        for idx in flagged[1:]:
            if idx == prev2 + 1: prev2 = idx
            else: regions.append((start, prev2)); start = prev2 = idx
        regions.append((start, prev2))
        rebuilt_any = False; aff = 0
        for si, ei in reversed(regions):
            region_start = self.junctions[si].segment_start
            region_end   = self.junctions[ei].segment_end
            L = sum(self.junctions[i].runtime_len for i in range(si, ei + 1))
            if L == 0: continue
            if L < min_region_len:
                if si > 0: si -= 1
                elif ei + 1 < len(self.junctions): ei += 1
                else: continue
                region_start = self.junctions[si].segment_start
                region_end   = self.junctions[ei].segment_end
                _nodes = []; _cur = region_start
                while _cur:
                    _nodes.append(_cur)
                    if _cur is region_end: break
                    _cur = _cur.next
                L = sum(self.junctions[i].runtime_len for i in range(si, ei + 1))
            rem = L; ranges = []
            while rem > 0: sz = min(seg_size, rem); ranges.append(sz); rem -= sz
            plans = [self._ps(s) for s in ranges]
            new_js = []; cur = region_start; re = region_end
            s_i = s_o = 0; ss2 = jn2 = None; sc2 = []; scs2 = set()
            while cur and s_i < len(plans):
                plan = plans[s_i]; sl = plan["seg_len"]
                if s_o == 0: ss2 = cur; jn2 = None; sc2 = [cur]; scs2 = set(plan["shortcut_offsets"])
                if s_o == plan["junction_offset"]: jn2 = cur
                if s_o in scs2: sc2.append(cur)
                if s_o == sl - 1:
                    se2 = cur; sc2.append(cur)
                    if len(sc2) < self.K: sc2.extend([ss2] * (self.K - len(sc2)))
                    if jn2 is None: jn2 = ss2
                    j2 = Junction(jn2); j2.segment_start = ss2; j2.segment_end = se2
                    j2.segment_len = sl; j2.shortcuts = sc2; new_js.append(j2)
                    s_i += 1; s_o = -1; sc2 = []; jn2 = None; scs2 = set()
                if cur is re: break
                cur = cur.next; s_o += 1
            self.junctions[si:ei + 1] = new_js; rebuilt_any = True; aff += len(new_js)
        n = len(self.junctions)
        for i in range(n):
            self.junctions[i].prev_junction = self.junctions[i - 1]
            self.junctions[i].next_junction = self.junctions[(i + 1) % n]
        self._refresh_jid(); self._last_junction = self._last_prev_junction = None
        if rebuilt_any:
            self.suboptimal_rebuild_events += 1
            self.sub_event_before_global_rebuild += 1
            self.suboptimal_segments_cost += aff
        return aff

    def _perform_global_rebuild(self):
        self._build_junctions(); self._last_junction = self._last_prev_junction = None
        self.local_ops_counter = self.sub_ops_counter = 0
        self.global_rebuild_events += 1; self.global_rebuild_cost += self.length


class JunctionLinkedList:
    def __init__(self, segment_size=100, shortcuts_per_junction=3,
                 enable_rebuild=True, local_interval=1000, t_j=0.15,
                 sub_interval=5000, soft_pct=0.25, hard_pct=0.50,
                 flagged_ratio_limit=0.30, min_seg_len_pct=0.25,
                 max_suboptimal_segments=0.3,
                 min_suboptimal_events_before_global=5,
                 emergency_hard_segment_ratio=0.95, stop_crash_local_sub=0.08):
        self._e = _JLIEngine(
            segment_size=segment_size,
            shortcuts_per_junction=shortcuts_per_junction,
            enable_rebuild=enable_rebuild, local_interval=local_interval,
            t_j=t_j, sub_interval=sub_interval, soft_pct=soft_pct,
            hard_pct=hard_pct, flagged_ratio_limit=flagged_ratio_limit,
            min_seg_len_pct=min_seg_len_pct,
            max_suboptimal_segments=max_suboptimal_segments,
            min_suboptimal_events_before_global=min_suboptimal_events_before_global,
            emergency_hard_segment_ratio=emergency_hard_segment_ratio,
            stop_crash_local_sub=stop_crash_local_sub)
    def insert(self, value, payload=None, allow_duplicate=False):
        return self._e.insert(value, payload=payload, allow_duplicate=allow_duplicate)
    def delete(self, value): return self._e.delete(value)
    def search(self, target):
       return self._e.search(target)
      
    def insert_many(self, values, allow_duplicate=False, rebuild=False):
        return self._e.insert_many(values, allow_duplicate=allow_duplicate, rebuild=rebuild)
    def delete_many(self, values, rebuild=False): return self._e.delete_many(values, rebuild=rebuild)
    def build_from_values(self, values, key=lambda x: x):
        return self._e.build_from_values(values, key=key)
    def size(self): return self._e.size()
    def get_metrics(self): return self._e.get_metrics()

JLI = JunctionLinkedList
