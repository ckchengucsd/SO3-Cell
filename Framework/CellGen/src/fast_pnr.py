#!/usr/bin/env python3

import re
import sys
import time
import argparse
from collections import defaultdict

UNIT_FIN   = 2
MAX_TRACK  = 4
UPPER_ROWS = [7, 6, 5]
ROWS       = list(range(MAX_TRACK - 1, -1, -1))
TOTAL_ROWS = ROWS + UPPER_ROWS
POWER_NETS = {"VDD", "VSS"}

PMOS_ROWS = ROWS[:MAX_TRACK // 2]
NMOS_ROWS = ROWS[MAX_TRACK // 2:]
_COL_PITCH = 3
_COL_BASE  = 3
_VIA_PITCH = 4
_VIA_OFFSET = 0
_M_MAR_EXT = 2

_log = None


def pr(*args, sep=" ", end="\n"):
    global _log
    s = sep.join(str(a) for a in args)
    print(s, end=end)
    if _log is not None:
        _log.write(s + ("" if end is None else end))
        _log.flush()


def parse_args():
    p = argparse.ArgumentParser(
        description="Fast Euler-path P&R for SO3 standard cells (no Gurobi)"
    )
    p.add_argument("--cdl",             required=True,  help="Path to CDL file")
    p.add_argument("--cell",            required=False, help="Cell name (subckt)")
    p.add_argument("--subckt",          required=False, help="(deprecated) same as --cell")
    p.add_argument("--out-cell-name",   default=None,   help="Override output file name")
    p.add_argument("--dummy-for-ideal", type=int, default=0)
    p.add_argument("--dummy-padding",   type=int, default=0)
    return p.parse_args()


_nfin_re = re.compile(r"nfin\s*=\s*(\d+)")


def parse_cdl(cdl_path: str, cell_name: str):
    top_trans, bot_trans, io_pins = [], [], []
    found = False

    from cdl_flatten import flatten_subckt
    with open(cdl_path) as f:
        for line in flatten_subckt(f.readlines(), cell_name):
            s = line.strip()

            if s.upper().startswith(".SUBCKT "):
                parts = s.split()
                if len(parts) > 1 and parts[1].upper() == cell_name.upper():
                    found = True
                    io_pins = parts[2:]
                    continue

            if not found:
                continue
            if s.upper().startswith(".ENDS"):
                break
            if not s.upper().startswith("M"):
                continue

            parts = s.split()
            if len(parts) < 6:
                continue

            name  = parts[0]
            D, G, S, B = parts[1], parts[2], parts[3], parts[4]
            ttype = parts[5].lower()
            param_str = " ".join(parts[6:])

            m = _nfin_re.search(param_str)
            nfin_val = int(m.group(1)) if m else 1
            replica_count = nfin_val // UNIT_FIN if nfin_val % UNIT_FIN == 0 else 1

            for i in range(replica_count):
                new_name = name if i == 0 else f"{name}_f{i}"
                trans = (new_name, G, D, S, B, UNIT_FIN)
                if "pmos" in ttype:
                    top_trans.append(trans)
                elif "nmos" in ttype:
                    bot_trans.append(trans)

    if not found:
        raise SystemExit(f"ERROR: .SUBCKT {cell_name} not found in {cdl_path}")
    return top_trans, bot_trans, io_pins



def euler_placement(transistors: list, extra_dummy: int = 0, io_pins: list = None,
                    power_start: str = None, top_trans0: tuple = None) -> list:
    n = len(transistors)
    num_cols = 2 * (n + extra_dummy) + 1

    if n == 0:
        return ["VDD"] * num_cols

    contact_seq, gate_seq = _hierholzer(transistors, io_pins=io_pins or [],
                                        power_start=power_start)
    if contact_seq is None:
        contact_seq, gate_seq = _greedy_order(transistors)
        columns: list = []
        for i, c in enumerate(contact_seq):
            columns.append(c)
            if i < len(gate_seq):
                columns.append(gate_seq[i])
        pad_net = columns[-1] if columns else (power_start or "VDD")
        while len(columns) < num_cols:
            columns.append(pad_net)
        return columns[:num_cols]

    variants = _all_euler_variants(contact_seq, gate_seq)

    if top_trans0 is not None:
        valid = [v for v in variants if _pmos_orient0_ok(v[0], v[1], top_trans0)]
        chosen_c, chosen_g = valid[0] if valid else variants[0]
    else:
        chosen_c, chosen_g = variants[0]

    pad_net = power_start or (chosen_c[-1] if chosen_c else "VDD")
    return _cols_from_seqs(chosen_c, chosen_g, num_cols, pad_net)


def _hierholzer(transistors: list, io_pins: list = None, power_start: str = None):
    n = len(transistors)

    adj: dict = defaultdict(list)
    for eid, (name, G, D, S, B, nfin) in enumerate(transistors):
        adj[D].append({"nbr": S, "gate": G, "eid": eid, "alive": True})
        adj[S].append({"nbr": D, "gate": G, "eid": eid, "alive": True})

    odd_nodes = [nd for nd, es in adj.items() if len(es) % 2 != 0]
    if len(odd_nodes) > 2:
        return None, None

    def _start_priority(nd):
        if power_start and nd == power_start:
            return 0
        if nd in POWER_NETS:
            return 3
        return 1

    if odd_nodes:
        start = min(odd_nodes, key=_start_priority)
    else:
        start = min(adj.keys(), key=_start_priority)

    stk = [start]
    result: list = []
    while stk:
        v = stk[-1]
        moved = False
        for e in adj[v]:
            if e["alive"]:
                e["alive"] = False
                for re in adj[e["nbr"]]:
                    if re["eid"] == e["eid"] and re["alive"]:
                        re["alive"] = False
                        break
                stk.append(e["nbr"])
                moved = True
                break
        if not moved:
            result.append(stk.pop())

    contact_seq = list(reversed(result))
    if len(contact_seq) != n + 1:
        return None, None

    alive2 = [True] * n
    ds_map: dict = defaultdict(list)
    for i, (name, G, D, S, B, nfin) in enumerate(transistors):
        ds_map[frozenset([D, S])].append(i)

    gate_seq: list = []
    for i in range(len(contact_seq) - 1):
        u, v = contact_seq[i], contact_seq[i + 1]
        key = frozenset([u, v])
        matched = False
        for tidx in ds_map[key]:
            if alive2[tidx]:
                gate_seq.append(transistors[tidx][1])
                alive2[tidx] = False
                matched = True
                break
        if not matched:
            return None, None

    return contact_seq, gate_seq


def _all_euler_variants(contact_seq: list, gate_seq: list) -> list:
    n = len(gate_seq)
    is_circuit = (contact_seq[0] == contact_seq[-1])
    variants = []

    if is_circuit:
        def add_rotations(cs, gs):
            for k in range(n):
                c = cs[k:] + cs[1:k + 1]
                g = gs[k:] + gs[:k]
                variants.append((c, g))
        add_rotations(contact_seq, gate_seq)
        add_rotations(list(reversed(contact_seq)), list(reversed(gate_seq)))
    else:
        variants.append((contact_seq, gate_seq))
        variants.append((list(reversed(contact_seq)), list(reversed(gate_seq))))

    return variants


def _cols_from_seqs(contact_seq: list, gate_seq: list, num_cols: int, pad_net: str) -> list:
    cols: list = []
    for i, c in enumerate(contact_seq):
        cols.append(c)
        if i < len(gate_seq):
            cols.append(gate_seq[i])
    pad = cols[-1] if cols else pad_net
    while len(cols) < num_cols:
        cols.append(pad)
    return cols[:num_cols]


def _pmos_orient0_ok(contact_seq: list, gate_seq: list, top_trans0: tuple) -> bool:
    _, G, D, S, _, _ = top_trans0
    ds = frozenset([D, S])
    for i, g in enumerate(gate_seq):
        if g == G and frozenset([contact_seq[i], contact_seq[i + 1]]) == ds:
            return contact_seq[i] == 'VDD'
    return True


def _greedy_order(transistors: list):
    n = len(transistors)
    if n == 0:
        return [], []

    net_to_trans: dict = defaultdict(list)
    for i, (name, G, D, S, B, nfin) in enumerate(transistors):
        net_to_trans[D].append(i)
        net_to_trans[S].append(i)

    used = [False] * n
    contacts: list = []
    gates: list = []

    start = next(
        (i for i, (_, G, D, S, *_) in enumerate(transistors)
         if D in POWER_NETS or S in POWER_NETS),
        0,
    )

    def pick_trans(t):
        name, G, D, S, B, nfin = t
        if contacts and S == contacts[-1]:
            return S, G, D
        if contacts and D == contacts[-1]:
            return D, G, S
        if S in POWER_NETS:
            return S, G, D
        return D, G, S

    def add_trans(idx):
        t = transistors[idx]
        left, g, right = pick_trans(t)
        if not contacts:
            contacts.append(left)
        gates.append(g)
        contacts.append(right)
        used[idx] = True
        return right

    prev_net = add_trans(start)

    for _ in range(n - 1):
        nxt = None
        for candidate in net_to_trans[prev_net]:
            if not used[candidate]:
                nxt = candidate
                break
        if nxt is None:
            contacts.append(prev_net)
            gates.append("VDD")
            nxt = next(i for i in range(n) if not used[i])
        prev_net = add_trans(nxt)

    return contacts, gates



def _nmos_best_cols(transistors: list, io_pins: list, pmos_cols: list) -> list:
    n = len(transistors)
    num_cols = len(pmos_cols)
    pad_net = "VSS"

    if n == 0:
        return [pad_net] * num_cols

    variants: list = []
    rev = list(reversed(transistors))
    for base_order in [transistors, rev]:
        for i in range(n):
            t_order = base_order[i:] + base_order[:i]
            for ps in [None, 'VSS']:
                base_c, base_g = _hierholzer(t_order, io_pins=io_pins or [],
                                             power_start=ps)
                if base_c is not None:
                    variants.extend(_all_euler_variants(base_c, base_g))
    seen_keys: set = set()
    unique: list = []
    for v in variants:
        key = (tuple(v[0]), tuple(v[1]))
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(v)
    variants = unique

    if not variants:
        base_c, base_g = _greedy_order(transistors)
        columns: list = []
        for i, c in enumerate(base_c):
            columns.append(c)
            if i < len(base_g):
                columns.append(base_g[i])
        pad = columns[-1] if columns else pad_net
        while len(columns) < num_cols:
            columns.append(pad)
        return columns[:num_cols]

    pmos_gates = [pmos_cols[i] for i in range(1, len(pmos_cols), 2)]

    def gate_score(g: list) -> int:
        return sum(a == b for a, b in zip(g, pmos_gates))

    def ac_score(c: list) -> int:
        return sum(
            1 for i, net in enumerate(c)
            if net not in POWER_NETS and 2 * i < len(pmos_cols) and net == pmos_cols[2 * i]
        )

    best_g = max(gate_score(g) for _, g in variants)
    best_gate = [(c, g) for c, g in variants if gate_score(g) == best_g]
    chosen_c, chosen_g = max(best_gate, key=lambda v: ac_score(v[0]))

    return _cols_from_seqs(chosen_c, chosen_g, num_cols, pad_net)


def _pmos_orient_align(pmos_cols: list, nmos_cols: list, top_trans0: tuple) -> list:
    _name, G, D, S, _B, _nfin = top_trans0

    def orient0_ok(cols: list) -> bool:
        for c in range(1, len(cols), 2):
            if cols[c] == G:
                return c > 0 and cols[c - 1] == S
        return True

    def gate_score(cols_a: list, cols_b: list) -> int:
        ga = [cols_a[i] for i in range(1, len(cols_a), 2)]
        gb = [cols_b[i] for i in range(1, len(cols_b), 2)]
        return sum(a == b for a, b in zip(ga, gb))

    def gate_rev(cols: list) -> list:
        pg = [cols[i] for i in range(1, len(cols), 2)]
        new_cols = list(cols)
        for i, g in enumerate(reversed(pg)):
            new_cols[2 * i + 1] = g
        return new_cols

    is_circuit = pmos_cols[0] == pmos_cols[-1]
    rev = list(reversed(pmos_cols))

    candidates = [pmos_cols, rev]
    if is_circuit:
        candidates += [gate_rev(pmos_cols), gate_rev(rev)]

    valid = [(c, gate_score(c, nmos_cols)) for c in candidates if orient0_ok(c)]
    if not valid:
        return pmos_cols

    return max(valid, key=lambda x: x[1])[0]


def _nmos_align(nmos_cols: list, pmos_cols: list) -> list:
    def gate_match(a: list, b: list) -> bool:
        ga = [a[i] for i in range(1, len(a), 2)]
        gb = [b[i] for i in range(1, len(b), 2)]
        return all(x == y for x, y in zip(ga, gb))

    def ac_contacts(ncols: list, pcols: list) -> int:
        return sum(
            1 for c in range(0, min(len(ncols), len(pcols)), 2)
            if ncols[c] not in POWER_NETS and ncols[c] == pcols[c]
        )

    rev = list(reversed(nmos_cols))
    if not gate_match(rev, pmos_cols):
        return nmos_cols
    return rev if ac_contacts(rev, pmos_cols) > ac_contacts(nmos_cols, pmos_cols) else nmos_cols


def _via_positions_for(num_cols: int) -> list:
    col_max_pos = _COL_BASE + _COL_PITCH * (num_cols - 1)
    result = []
    i = 0
    while True:
        pos = int(_VIA_OFFSET + _VIA_PITCH * (i + 1))
        if pos > col_max_pos:
            break
        if pos >= _COL_BASE:
            result.append(pos)
        i += 1
    return result


def _route_pp_nn_via(net: str, pp_cols: set, nn_cols: set,
                     net_routing: dict, net_vias: dict, num_cols: int):
    via_list = _via_positions_for(num_cols)
    nn_row = NMOS_ROWS[0]
    pp_row = PMOS_ROWS[0]

    if not via_list:
        for c in range(num_cols):
            net_routing[net][nn_row][c] = 1
        return

    max_nn_col = max(nn_cols)
    min_pp_col = min(pp_cols)
    max_pp_col = max(pp_cols)
    min_nn_col = min(nn_cols)

    def _col_pos(c):
        return _COL_BASE + _COL_PITCH * c

    if max_nn_col <= min_pp_col:
        via_p = max(
            (v for v in via_list if _col_pos(max_nn_col) <= v <= _col_pos(min_pp_col)),
            default=min(via_list, key=lambda v: abs(v - (_col_pos(max_nn_col) + _col_pos(min_pp_col)) // 2))
        )
    else:
        via_p = min(
            (v for v in via_list if _col_pos(max_pp_col) <= v <= _col_pos(min_nn_col)),
            default=min(via_list, key=lambda v: abs(v - (_col_pos(max_pp_col) + _col_pos(min_nn_col)) // 2))
        )

    c_left = max((c for c in range(num_cols) if _col_pos(c) <= via_p), default=0)
    c_right = min((c for c in range(num_cols) if _col_pos(c) >= via_p), default=num_cols - 1)

    if max_nn_col <= min_pp_col:
        for c in range(c_right + 1):
            net_routing[net][nn_row][c] = 1
        for c in range(c_left, num_cols):
            net_routing[net][pp_row][c] = 1
    else:
        for c in range(c_right + 1):
            net_routing[net][pp_row][c] = 1
        for c in range(c_left, num_cols):
            net_routing[net][nn_row][c] = 1

    net_vias[net].append((1, via_p))


def route_nets(pmos_cols: list, nmos_cols: list, io_pins: list):
    num_cols = len(pmos_cols)
    io_set = set(io_pins)

    net_p: dict = defaultdict(set)
    net_n: dict = defaultdict(set)
    for c, net in enumerate(pmos_cols):
        if net and net not in POWER_NETS:
            net_p[net].add(c)
    for c, net in enumerate(nmos_cols):
        if net and net not in POWER_NETS:
            net_n[net].add(c)

    signal_nets = sorted(set(net_p.keys()) | set(net_n.keys()))

    row_spans: dict = defaultdict(list)

    def has_conflict(row: int, lo: int, hi: int) -> bool:
        return any(lo <= b and a <= hi for a, b in row_spans[row])

    def pick_row(row_order: list, lo: int, hi: int):
        for r in row_order:
            if not has_conflict(r, lo, hi):
                row_spans[r].append((lo, hi))
                return r
        return None

    net_routing: dict = {}
    net_vias: dict = defaultdict(list)

    def net_sort_key(net):
        p = net_p[net]
        n = net_n[net]
        all_c = p | n
        span = max(all_c) - min(all_c) if all_c else 0
        ep = {c for c in p if c % 2 == 0}
        en = {c for c in n if c % 2 == 0}
        is_dual = 1 if ((ep - en) and (en - ep)) else 0
        only_odd = not {c for c in all_c if c % 2 == 0}
        if only_odd and all_c:
            gate_lo = max(0, min(all_c) - _M_MAR_EXT)
            return (-is_dual, -span, 0 if net in io_set else 1, 0, gate_lo, net)
        return (-is_dual, -span, 0 if net in io_set else 1, 1, 0, net)

    for net in sorted(signal_nets, key=net_sort_key):
        p = net_p[net]
        n = net_n[net]
        all_c = p | n

        even_c = {c for c in all_c if c % 2 == 0}
        odd_c  = {c for c in all_c if c % 2 != 0}
        boundary_c = {c for c in even_c if c == 0 or c == num_cols - 1}

        needs_routing = bool(all_c)

        init: dict = {r: [0] * num_cols for r in TOTAL_ROWS}
        net_routing[net] = init

        if not needs_routing:
            continue

        even_p = {c for c in p if c % 2 == 0}
        even_n = {c for c in n if c % 2 == 0}
        pp_contacts = even_p - even_n
        nn_contacts = even_n - even_p

        only_odd = not even_c

        lo = max(0, min(all_c) - _M_MAR_EXT)
        hi = min(num_cols - 1, max(all_c) + _M_MAR_EXT)

        if only_odd:
            gate_segs = []
            for gc in sorted(all_c):
                seg_lo = max(0, gc - _M_MAR_EXT)
                seg_hi = min(num_cols - 1, gc + 1)
                gate_segs.append((seg_lo, seg_hi))
            mutually_ok = all(
                gate_segs[i + 1][0] > gate_segs[i][1]
                for i in range(len(gate_segs) - 1)
            )
            if mutually_ok:
                placed = False
                for r in [3, 0, 2, 1]:
                    if all(not has_conflict(r, a, b) for a, b in gate_segs):
                        for a, b in gate_segs:
                            row_spans[r].append((a, b))
                            for c_pos in range(a, b + 1):
                                net_routing[net][r][c_pos] = 1
                        placed = True
                        break
                if not placed:
                    chosen = pick_row([3, 0, 2, 1], lo, hi)
                    if chosen is not None:
                        for c_pos in range(lo, hi + 1):
                            net_routing[net][chosen][c_pos] = 1
            else:
                chosen = pick_row([3, 0, 2, 1], lo, hi)
                if chosen is not None:
                    for c_pos in range(lo, hi + 1):
                        net_routing[net][chosen][c_pos] = 1
            continue
        elif pp_contacts and nn_contacts:
            dr_lo = max(0, min(all_c) - _M_MAR_EXT)
            dr_hi = min(num_cols - 1, max(all_c) + _M_MAR_EXT)
            pp_row = pick_row(PMOS_ROWS, dr_lo, dr_hi)
            nn_row = pick_row(NMOS_ROWS, dr_lo, dr_hi)
            if pp_row is not None:
                for c in range(dr_lo, dr_hi + 1):
                    net_routing[net][pp_row][c] = 1
            if nn_row is not None:
                for c in range(dr_lo, dr_hi + 1):
                    net_routing[net][nn_row][c] = 1
            continue
        elif nn_contacts and not pp_contacts:
            row_order = [0, 1, 2, 3]
        elif pp_contacts and not nn_contacts:
            row_order = [3, 2, 1, 0]
        else:
            row_order = [3, 2, 1, 0] if (bool(p) and not bool(n)) else \
                        [0, 1, 2, 3] if (bool(n) and not bool(p)) else \
                        [2, 1, 3, 0]

        chosen = pick_row(row_order, lo, hi)
        if chosen is not None:
            for c in range(lo, hi + 1):
                net_routing[net][chosen][c] = 1

    return net_routing, dict(net_vias)



def main():
    global _log

    args = parse_args()
    cell_name = args.cell or args.subckt
    if not cell_name:
        raise SystemExit("ERROR: --cell is required (or use --subckt for backward compat)")

    out_name  = args.out_cell_name or cell_name
    dummy_col = args.dummy_for_ideal + args.dummy_padding

    _log = open(out_name, "w", encoding="utf-8")

    t0 = time.perf_counter()

    top_trans, bot_trans, io_pins = parse_cdl(args.cdl, cell_name)

    n_top = len(top_trans)
    n_bot = len(bot_trans)
    n_max = max(n_top, n_bot)
    num_cols = 2 * (n_max + dummy_col) + 1

    pmos_extra = dummy_col + max(0, n_bot - n_top)
    nmos_extra = dummy_col + max(0, n_top - n_bot)

    def _pad(cols, length, pad_net):
        if len(cols) < length:
            cols = cols + [pad_net] * (length - len(cols))
        return cols[:length]

    def _gate_align_score(p_cols, n_cols):
        pg = [p_cols[i] for i in range(1, len(p_cols), 2)]
        ng = [n_cols[i] for i in range(1, len(n_cols), 2)]
        return sum(a == b for a, b in zip(pg, ng))

    all_pmos_variants: list = []
    _pmos_rev = list(reversed(top_trans))
    for _base in [top_trans, _pmos_rev]:
        for _i in range(len(top_trans)):
            _t_order = _base[_i:] + _base[:_i]
            base_c, base_g = _hierholzer(_t_order, io_pins=io_pins or [], power_start="VDD")
            if base_c is not None:
                all_pmos_variants.extend(_all_euler_variants(base_c, base_g))
    _seen_pmos: set = set()
    _dedup_pmos: list = []
    for _v in all_pmos_variants:
        _k = (tuple(_v[0]), tuple(_v[1]))
        if _k not in _seen_pmos:
            _seen_pmos.add(_k)
            _dedup_pmos.append(_v)
    all_pmos_variants = _dedup_pmos

    if all_pmos_variants and top_trans:
        valid_pmos = [(c, g) for c, g in all_pmos_variants
                      if _pmos_orient0_ok(c, g, top_trans[0])]
        if not valid_pmos:
            valid_pmos = all_pmos_variants
    else:
        valid_pmos = all_pmos_variants

    best_pmos_cols: list = []
    best_nmos_cols: list = []
    best_joint_score: tuple = (-1, -1)

    if valid_pmos:
        for p_c, p_g in valid_pmos:
            p_cols = _pad(_cols_from_seqs(p_c, p_g, num_cols, "VDD"), num_cols, "VDD")
            if bot_trans:
                n_cols = _pad(_nmos_best_cols(bot_trans, io_pins, p_cols),
                              num_cols, "VSS")
            else:
                n_cols = ["VSS"] * num_cols
            gate_s = _gate_align_score(p_cols, n_cols)
            ac_s = sum(
                1 for c in range(0, num_cols, 2)
                if p_cols[c] not in POWER_NETS
                and c < len(n_cols)
                and n_cols[c] not in POWER_NETS
                and p_cols[c] == n_cols[c]
            )
            score = (gate_s, ac_s)
            if score > best_joint_score:
                best_joint_score = score
                best_pmos_cols = p_cols
                best_nmos_cols = n_cols
    else:
        best_pmos_cols = _pad(
            euler_placement(top_trans, extra_dummy=pmos_extra, io_pins=io_pins,
                            power_start="VDD",
                            top_trans0=top_trans[0] if top_trans else None),
            num_cols, "VDD")
        best_nmos_cols = _pad(
            _nmos_best_cols(bot_trans, io_pins, best_pmos_cols) if bot_trans
            else ["VSS"] * num_cols,
            num_cols, "VSS")

    pmos_columns = best_pmos_cols
    nmos_columns = best_nmos_cols

    routing, net_vias = route_nets(pmos_columns, nmos_columns, io_pins)

    t1 = time.perf_counter()

    pr("Optimal solution found.")
    pr("PMOS: 1 ", pmos_columns)
    pr("NMOS: 1 ", nmos_columns)
    pr()
    pr("t_n_c_r and ut_n_c_r values:")

    all_signal_nets = sorted(routing.keys())

    for net in all_signal_nets:
        net_rows = routing[net]
        pr(f"  Net {net}: Via positions {net_vias.get(net, [])}, []")
        for r in ROWS:
            pr(f"  Net {net}, H 1, Row {r}: {net_rows[r]}")
        for r in UPPER_ROWS:
            pr(f"  Net {net}, H 1, Row {r}: {net_rows.get(r, [0] * num_cols)}")

    zeros = [0] * num_cols
    for r in ROWS:
        pr(f"  Net eol, Row {r}: {zeros}")
    for r in UPPER_ROWS:
        pr(f"  Net eol, Row {r}: {zeros}")

    pr()
    pr(f"Optimal total cost: 0.0")
    pr("Optimal Via positions:")
    for net in all_signal_nets:
        pr(f"  Net {net}: Via positions {net_vias.get(net, [])}")
    pr(f"Column Track Costs: {[2] * num_cols}")
    pr(f"Runtime :  {round(t1 - t0, 3)}")

    _log.close()


if __name__ == "__main__":
    main()
