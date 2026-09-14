import re

_PARAM = re.compile(r"^[^=\s]+=")
_GLOBAL = {"VDD", "VSS", "GND", "VCC", "VPWR", "VGND"}


def _logical_lines(lines):
    out = []
    for raw in lines:
        s = raw.rstrip("\r\n")
        if s.lstrip().startswith("+") and out:
            out[-1] += " " + s.lstrip()[1:].strip()
        else:
            out.append(s)
    return out


def _subckts(lines):
    table, cur = {}, None
    for s in _logical_lines(lines):
        t = s.split()
        if not t or t[0].startswith("*"):
            continue
        head = t[0].upper()
        if head == ".SUBCKT" and len(t) > 1:
            cur = t[1].upper()
            table[cur] = (s, [p for p in t[2:] if not _PARAM.match(p)], [])
        elif head.startswith(".ENDS"):
            cur = None
        elif cur is not None:
            table[cur][2].append(t)
    return table


def _model_index(t):
    return next((i for i, p in enumerate(t) if i >= 4 and "mos" in p.lower()), None)


def _instance(t):
    rest = t[1:]
    if "/" in rest:
        k = rest.index("/")
        return rest[:k], rest[k + 1], [p for p in rest[k + 2:] if _PARAM.match(p)]
    plain = [p for p in rest if not _PARAM.match(p)]
    return plain[:-1], plain[-1], [p for p in rest if _PARAM.match(p)]


def _scaled(t, mult):
    if mult == 1:
        return t
    for i, p in enumerate(t):
        if p.lower().startswith("m="):
            return t[:i] + ["M=%g" % (float(p[2:]) * mult)] + t[i + 1:]
    return t + ["M=%g" % mult]


def _expand(table, name, conn, path, mult, depth, out):
    if depth > 32:
        raise SystemExit("ERROR: CDL subcircuits nest deeper than 32 levels at %s" % name)
    _line, ports, body = table[name]
    if conn is not None and len(conn) != len(ports):
        raise SystemExit("ERROR: instance %s of %s connects %d nets but the subcircuit has %d ports"
                         % (path, name, len(conn), len(ports)))
    mapping = dict(zip((p.upper() for p in ports), conn)) if conn is not None else {}

    def net(n):
        u = n.upper()
        if conn is None or u in _GLOBAL or n.endswith("!"):
            return mapping.get(u, n)
        return mapping.get(u, "%s_%s" % (path, n))

    for t in body:
        head = t[0].upper()
        if head.startswith("M"):
            k = _model_index(t)
            if k is None:
                raise SystemExit("ERROR: no device model found on CDL line: %s" % " ".join(t))
            dev = t[0] if conn is None else "%s_%s" % (t[0], path)
            out.append(_scaled([dev] + [net(n) for n in t[1:k]] + t[k:], mult))
        elif head.startswith("X"):
            nets, sub, params = _instance(t)
            if sub.upper() not in table:
                raise SystemExit("ERROR: instance %s in %s uses subcircuit %s, which is not defined in the CDL"
                                 % (t[0], name, sub))
            m = mult
            for p in params:
                if p.lower().startswith("m="):
                    m *= float(p[2:])
            child = t[0] if conn is None else "%s_%s" % (path, t[0])
            _expand(table, sub.upper(), [net(n) for n in nets], child, m, depth + 1, out)


def flatten_subckt(lines, top):
    table = _subckts(lines)
    key = top.upper()
    if key not in table or not any(t[0].upper().startswith("X") for t in table[key][2]):
        return lines
    out = []
    _expand(table, key, None, "", 1, 0, out)
    return [table[key][0] + "\n"] + [" ".join(t) + "\n" for t in out] + [".ENDS\n"]
