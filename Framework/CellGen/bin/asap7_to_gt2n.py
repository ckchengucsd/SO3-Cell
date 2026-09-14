#!/usr/bin/env python3
import argparse
import os
import re

DEFAULT_TRACKS = 6
DEFAULT_WIDTH_NM = 13
DEFAULT_VT = "lvt"
GT2N_L = "0.014u"
UNIT_FIN = 2


def target_names(tracks, width_nm, vt):
    return f"gt2_{tracks}t_", f"w{width_nm}_{vt}", f"{width_nm / 1000:.3f}u"


def device_M(dev_tokens):
    for tok in dev_tokens:
        m = re.fullmatch(r"nfin=(\d+)", tok, re.IGNORECASE)
        if m:
            return max(1, round(int(m.group(1)) / UNIT_FIN))
    return 1


def parse_subckts(path):
    cells, cur = [], None
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s.upper().startswith(".SUBCKT"):
                p = s.split()
                cur = {"name": p[1], "pins": p[2:], "devs": []}
            elif s.upper().startswith(".ENDS"):
                if cur:
                    cells.append(cur); cur = None
            elif cur is not None and s[:1].upper() == "M" and "mos" in s.lower():
                cur["devs"].append(s.split())
    return cells


def convert(cell, prefix, flavor, gt2n_w, vt):
    base = cell["name"].split("_ASAP7")[0]
    dm = re.fullmatch(r"(.+?)(x[p\d]+)", base)
    func, drive = (dm.group(1), dm.group(2)) if dm else (base, "x1")
    gname = f"{prefix}{func.lower()}_{drive.lower()}_{flavor}"

    power = {"VDD", "VSS"}
    gates, driven = set(), set()
    for d in cell["devs"]:
        mi = next((i for i, t in enumerate(d) if i >= 4 and "mos" in t.lower()), None)
        if mi is None or mi < 3:
            continue
        gates.add(d[2]); driven.add(d[1]); driven.add(d[3])

    pins = cell["pins"]
    ins = [p for p in pins if p not in power and p in gates and p not in driven]
    outs = [p for p in pins if p not in power and p in driven]
    seen = set()
    outs = [p for p in outs if not (p in seen or seen.add(p))]
    if not outs:
        outs = [p for p in pins if p not in power and p not in ins]

    def low(n):
        return n.lower() if n.upper() in ("VDD", "VSS") else n

    dlines = []
    max_M = 1
    for d in cell["devs"]:
        mi = next((i for i, t in enumerate(d) if i >= 4 and "mos" in t.lower()), None)
        nm, D, G, S = d[0], low(d[1]), low(d[2]), low(d[3])
        model = f"nmos_{vt}" if "nmos" in d[mi].lower() else f"pmos_{vt}"
        rail = "vss" if model.startswith("nmos") else "vdd"
        M = device_M(d)
        max_M = max(max_M, M)
        dlines.append(f"{nm} {D} {G} {S} {rail} {model} W={gt2n_w} L={GT2N_L} M={M}")

    order = ins + outs + ["vdd", "vss"]
    pininfo = "*.PININFO " + " ".join([f"{p}:I" for p in ins] + [f"{p}:O" for p in outs] + ["vdd:B", "vss:B"])
    body = "\n".join([f".subckt {gname} " + " ".join(order), pininfo] + dlines + [f".ends {gname}"])
    return gname, func, drive, max_M, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_cdl", help="ASAP7 CDL (e.g. asap7sc7p5t_28_R.cdl)")
    ap.add_argument("-o", "--out", default="gt2n_from_asap7.cdl")
    ap.add_argument("--tracks", type=int, default=DEFAULT_TRACKS,
                    help="track height of the target library, sets the gt2_<n>t_ name prefix")
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH_NM, metavar="NM",
                    help="nanosheet width of the target library in nm, sets both the w<nm> name token and the device W")
    ap.add_argument("--vt", default=DEFAULT_VT, help="threshold flavor, sets the name token and the device model")
    args = ap.parse_args()
    if args.tracks <= 0 or args.width <= 0:
        ap.error("tracks and width must be positive")

    prefix, flavor, gt2n_w = target_names(args.tracks, args.width, args.vt)
    cells = parse_subckts(args.input_cdl)
    out, funcs, names = [], {}, set()
    for c in cells:
        gname, func, drive, M, body = convert(c, prefix, flavor, gt2n_w, args.vt)
        if gname in names:
            continue
        names.add(gname); funcs.setdefault(func.lower(), []).append(drive)
        out.append(body)
    header = ("* GT2N cells converted from ASAP7 (" + os.path.basename(args.input_cdl) + ")\n"
              "* NOTE: first line is a comment (SPICE readers skip line 1).\n")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(out) + "\n")
    print(f"converted {len(names)} cells, {len(funcs)} unique functions -> {args.out}")
    print(f"target {prefix}<func>_<drive>_{flavor}, device W={gt2n_w}")
    print("functions:", " ".join(sorted(funcs)))


if __name__ == "__main__":
    main()
