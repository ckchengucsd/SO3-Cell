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
    ap.add_argument("--ilp-script", default=str(SRC / "ILP_SO3_SH_flex.py"))
    ap.add_argument("--klayout", default="klayout")
    ap.add_argument("--gdsgen-script", default=str(SRC / "gdsgen.py"))

    args = ap.parse_args()

    cells = args.cell

    for cell in cells:
        ilp_cmd = [
            args.python, args.ilp_script,
            "--cdl", args.cdl,
            "--cell", cell,
            "--dummy-for-ideal", str(args.dummy_for_ideal),
            "--dummy-padding",   str(args.dummy_padding),
            "--misalign-col",    str(args.misalign_col),
        ]
        print("[RUN] ", " ".join(ilp_cmd))
        subprocess.run(ilp_cmd, check=True)

    cfg = {
        "output_dir": args.gds_out,
        "cells": cells
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
