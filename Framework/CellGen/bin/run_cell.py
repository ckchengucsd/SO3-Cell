#!/usr/bin/env python3
import argparse, json, subprocess, os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC  = ROOT / "src"

def main():
    ap = argparse.ArgumentParser(description="Run ILP + KLayout GDS generation")

    ap.add_argument("--cell", nargs="+", required=True,
                help="One or more cell/subckt names (e.g., INV_X1 NAND2_X1)")

    # ILP args
    ap.add_argument("--cdl", required=True)
    ap.add_argument("--dummy-for-ideal", type=int, default=0)
    ap.add_argument("--dummy-padding", type=int, default=0)
    ap.add_argument("--misalign-col", type=int, default=0)

    # GDS args
    ap.add_argument("--gds-out", default="gds_result", help="Output directory for GDS")
    ap.add_argument("--cells", nargs="+", default=None, help="Optional override list of cell names")

    # Tool paths
    ap.add_argument("--python", default=sys.executable)
    # New CLI knobs
    ap.add_argument("--arch", choices=["SH", "DH"], default="SH",
                    help="Cell architecture: SH (single-height) or DH (double-height)")
    ap.add_argument("--mh-order", choices=["N_FIRST", "P_FIRST"], default="N_FIRST",
                    help="When --arch=DH, choose transistor row order (N_FIRST or P_FIRST)")

    # Make ilp-script optional; choose by arch if not provided
    ap.add_argument("--ilp-script", default=None,
                    help="Override ILP script path. If omitted, picks SH/DH script automatically.")
    ap.add_argument("--klayout", default="klayout")
    ap.add_argument("--gdsgen-script", default=str(SRC / "gdsgen.py"))

    args = ap.parse_args()

    # Decide ILP script if user didn't override
    if not args.ilp_script:  # None or empty string
        ilp_script = str(SRC / ("ILP_SO3_DH_flex.py" if args.arch == "DH" else "ILP_SO3_SH_flex.py"))
    else:
        ilp_script = args.ilp_script  # honor explicit override

    def derive_out_name(base_name: str, arch: str, mh_order: str) -> str:
        if arch == "DH":
            return f"{base_name}_DH_{'N' if mh_order == 'N_FIRST' else 'P'}"
        return base_name
    cells = args.cell
    cells_out = []

    for cell in cells:
        base_name = cell
        out_name  = derive_out_name(base_name, args.arch, args.mh_order)
        cells_out.append(out_name)

        ilp_cmd = [
            args.python, ilp_script,
            "--cdl", args.cdl,
            "--cell", cell,
            "--dummy-for-ideal", str(args.dummy_for_ideal),
            "--dummy-padding",   str(args.dummy_padding),
            "--misalign-col",    str(args.misalign_col),
            "--out-cell-name",   out_name,
        ]
        # Only DH needs mh-order
        if args.arch == "DH":
            ilp_cmd += ["--mh-order", args.mh_order]
        print("[RUN] ", " ".join(ilp_cmd))
        subprocess.run(ilp_cmd, check=True)

    cfg = {
        "output_dir": args.gds_out,
        #"cells": cells,
        "cells": cells_out,
        # new: forward arch/mh_order to the GDS generator
        "arch": args.arch,
        "mh_order": args.mh_order if args.arch == "DH" else "N_FIRST",
    }
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tf:
        json.dump(cfg, tf, ensure_ascii=False, indent=2)
        cfg_path = tf.name

    env = os.environ.copy()
    env["GDSGEN_CONFIG"] = cfg_path

    kl_cmd = [args.klayout, "-b", "-r", args.gdsgen_script]
    print("[RUN] ", " ".join(kl_cmd))
    try:
        subprocess.run(kl_cmd, check=True, env=env)
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass

if __name__ == "__main__":
    main()
