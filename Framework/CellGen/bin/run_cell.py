#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def pick_ilp_script(flow: str, arch: str) -> Path:
    table = {
        ("SO2", "SH"): SRC / "ILP_SO2_SH_flex.py",
        ("SO2", "DH"): SRC / "ILP_SO2_DH_flex.py",
        ("SO3", "SH"): SRC / "ILP_SO3_SH_flex.py",
        ("SO3", "DH"): SRC / "ILP_SO3_DH_flex.py",
    }
    try:
        return table[(flow, arch)]
    except KeyError as e:
        raise SystemExit(f"ERROR: unsupported flow/arch combination: {flow}/{arch}") from e


def derive_out_name(base_name: str, arch: str, mh_order: str) -> str:
    if arch == "DH":
        suffix = "N" if mh_order == "N_FIRST" else "P"
        return f"{base_name}_DH_{suffix}"
    return base_name


def main():
    ap = argparse.ArgumentParser(description="Run ILP + KLayout GDS generation")

    ap.add_argument(
        "--cell",
        nargs="+",
        required=True,
        help="One or more cell/subckt names (e.g., INV_X1 NAND2_X1)",
    )

    # ILP args
    ap.add_argument("--cdl", required=True)
    ap.add_argument("--dummy-for-ideal", type=int, default=0)
    ap.add_argument("--dummy-padding", type=int, default=0)
    ap.add_argument("--misalign-col", type=int, default=0)
    ap.add_argument("--flow", choices=["SO2", "SO3"], default="SO3")
    ap.add_argument("--partition", choices=["N", "LR", "H"], default="N")

    # GDS args
    ap.add_argument("--gds-out", default="gds_result", help="Output directory for GDS")
    ap.add_argument(
        "--cells",
        nargs="+",
        default=None,
        help="Optional override list of cell names for GDS generation",
    )

    # Tool paths
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--arch", choices=["SH", "DH"], default="SH",
                    help="Cell architecture: SH (single-height) or DH (double-height)")
    ap.add_argument("--mh-order", choices=["N_FIRST", "P_FIRST"], default="N_FIRST",
                    help="When --arch=DH, choose transistor row order")

    ap.add_argument(
        "--ilp-script",
        default=None,
        help="Override ILP script path. If omitted, choose automatically from --flow and --arch.",
    )
    ap.add_argument("--klayout", default="klayout")
    ap.add_argument("--gdsgen-script", default=str(SRC / "gdsgen.py"))

    args = ap.parse_args()

    # Decide ILP script
    if args.ilp_script:
        ilp_script = Path(args.ilp_script)
    else:
        ilp_script = pick_ilp_script(args.flow, args.arch)

    if not ilp_script.exists():
        raise SystemExit(f"ERROR: ILP script not found: {ilp_script}")

    input_cells = args.cell
    cells_out = []

    successful_cells = []

    for cell in input_cells:
        out_name = derive_out_name(cell, args.arch, args.mh_order)
        cells_out.append(out_name)

        ilp_cmd = [
            args.python,
            str(ilp_script),
            "--cdl", args.cdl,
            "--cell", cell,
            "--dummy-for-ideal", str(args.dummy_for_ideal),
            "--dummy-padding", str(args.dummy_padding),
            "--misalign-col", str(args.misalign_col),
            "--out-cell-name", out_name,
            "--partition", args.partition,
        ]

        if args.arch == "DH":
            ilp_cmd += ["--mh-order", args.mh_order]

        print("[RUN]", " ".join(ilp_cmd))
        try:
            subprocess.run(ilp_cmd, check=True)
            successful_cells.append(out_name)
        except subprocess.CalledProcessError:
            print()
            print(f"[ERROR] ILP failed for cell: {cell}")
            print("[INFO] GDS generation is skipped because no valid ILP solution was produced.")
            print("[GUIDE] Please try one or more of the following:")
            print("        - increase --dummy-for-ideal")
            print("        - check whether --misalign-col is appropriate for this cell")
            print("        - verify that the selected flow/architecture is valid for this cell")
            continue
    
    if not successful_cells:
        print("[ERROR] No cells were solved successfully.")
        print("[INFO] GDS generation is skipped.")
        raise SystemExit(1)

    # Which names should GDS use?
    gds_cells = successful_cells

    cfg = {
        "output_dir": args.gds_out,
        "cells": gds_cells,
        "arch": args.arch,
        "mh_order": args.mh_order if args.arch == "DH" else "N_FIRST",
    }

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tf:
        json.dump(cfg, tf, ensure_ascii=False, indent=2)
        cfg_path = tf.name

    env = os.environ.copy()
    env["GDSGEN_CONFIG"] = cfg_path

    kl_cmd = [args.klayout, "-b", "-r", args.gdsgen_script]
    print("[RUN]", " ".join(kl_cmd))
    try:
        subprocess.run(kl_cmd, check=True, env=env)
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
