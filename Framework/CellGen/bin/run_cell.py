#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def parse_cdl_ports(cdl_file: str, cell_name: str):
    with open(cdl_file, encoding="utf-8") as f:
        for line in f:
            m = re.match(
                r"\.SUBCKT\s+" + re.escape(cell_name) + r"\s+(.+)",
                line,
                re.IGNORECASE,
            )
            if m:
                return [p.upper() for p in m.group(1).split()]
    return []


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
        raise SystemExit(
            f"ERROR: unsupported flow/arch combination: {flow}/{arch}"
        ) from e


def derive_out_name(base_name: str, arch: str, mh_order: str) -> str:
    if arch == "DH":
        suffix = "N" if mh_order == "N_FIRST" else "P"
        if not base_name.endswith(f"_DH_{suffix}"):
            return f"{base_name}_DH_{suffix}"
    return base_name


def load_solver_config(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"ERROR: solver config not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: invalid solver JSON {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise SystemExit("ERROR: solver config schema_version must be integer 1")
    solver = raw.get("solver")
    if not isinstance(solver, dict):
        raise SystemExit("ERROR: solver config must contain a solver JSON object")
    time_limit = solver.get("time_limit_seconds")
    threads = solver.get("threads")
    if isinstance(time_limit, bool) or not isinstance(time_limit, int) or time_limit <= 0:
        raise SystemExit("ERROR: solver.time_limit_seconds must be a positive integer")
    if isinstance(threads, bool) or not isinstance(threads, int) or threads < 0:
        raise SystemExit("ERROR: solver.threads must be a non-negative integer")
    topology_optimization = solver.get("topology_optimization")
    if not isinstance(topology_optimization, bool):
        raise SystemExit("ERROR: solver.topology_optimization must be a boolean")

    retry = raw.get("retry")
    if not isinstance(retry, dict):
        raise SystemExit("ERROR: solver config must contain a retry JSON object")
    attempts = retry.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise SystemExit("ERROR: retry.attempts must be a non-empty JSON array")
    offset_keys = (
        "dummy_for_ideal_offset",
        "dummy_padding_offset",
        "misalign_col_offset",
    )
    parsed_attempts = []
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            raise SystemExit(f"ERROR: retry.attempts[{index}] must be a JSON object")
        parsed = {}
        for key in offset_keys:
            value = attempt.get(key)
            if isinstance(value, bool) or not isinstance(value, int):
                raise SystemExit(
                    f"ERROR: retry.attempts[{index}].{key} must be an integer"
                )
            parsed[key] = value
        parsed_attempts.append(parsed)
    return {
        "time_limit_seconds": time_limit,
        "threads": threads,
        "topology_optimization": topology_optimization,
        "retry_attempts": parsed_attempts,
    }


def main():
    ap = argparse.ArgumentParser(description="Run ILP + KLayout GDS generation")

    ap.add_argument(
        "--cell",
        nargs="+",
        required=True,
        help="One or more cell/subckt names (e.g., INV_X1 NAND2_X1)",
    )

    ap.add_argument("--cdl", required=True)
    ap.add_argument("--dummy-for-ideal", type=int, default=0)
    ap.add_argument("--dummy-padding", type=int, default=0)
    ap.add_argument("--misalign-col", type=int, default=0)
    ap.add_argument("--flow", choices=["SO2", "SO3"], default="SO3")
    ap.add_argument("--partition", choices=["N", "LR", "H"], default="N")
    ap.add_argument(
        "--no-topology-opt",
        action="store_true",
        help="Disable circuit topology optimization (SO3 SH only)",
    )
    ap.add_argument(
        "--phase",
        choices=["both", "placement", "routing", "sequential"],
        default="both",
        help="ILP phase: both (joint), placement only, routing only, or sequential (placement→routing with dummy escalation, SO3 SH only)",
    )
    ap.add_argument(
        "--max-placements",
        type=int,
        default=3,
        help="Sequential mode: max placement candidates to try routing on (default: 3)",
    )
    ap.add_argument(
        "--max-dummy",
        type=int,
        default=2,
        help="Sequential mode: max dummy-for-ideal level to try (tries 0..N, default: 2)",
    )

    ap.add_argument("--gds-out", default="gds_result", help="Output directory for GDS")
    ap.add_argument(
        "--geometry-config",
        default=str(ROOT / "config" / "gt2n_6t_geometry.json"),
        help="JSON geometry parameters passed to gdsgen.py",
    )
    ap.add_argument(
        "--solver-config",
        default=str(ROOT / "config" / "gt2n_solver.json"),
        help="JSON solver runtime parameters passed to ILP subprocesses",
    )
    ap.add_argument(
        "--cells",
        nargs="+",
        default=None,
        help="Optional override list of cell names for GDS generation",
    )

    ap.add_argument("--python", default=sys.executable)
    ap.add_argument(
        "--arch",
        choices=["SH", "DH"],
        default="SH",
        help="Cell architecture: SH (single-height) or DH (double-height)",
    )
    ap.add_argument(
        "--mh-order",
        choices=["N_FIRST", "P_FIRST"],
        default="N_FIRST",
        help="When --arch=DH, choose transistor row order",
    )
    ap.add_argument(
        "--ilp-script",
        default=None,
        help="Override ILP script path. If omitted, choose automatically from --flow and --arch.",
    )
    ap.add_argument(
        "--out-cell-name",
        default=None,
        help="Override the output cell name. Only valid when one input cell is provided.",
    )
    ap.add_argument("--klayout", default="klayout")
    ap.add_argument("--gdsgen-script", default=str(SRC / "gdsgen.py"))

    args = ap.parse_args()

    if args.out_cell_name and len(args.cell) != 1:
        raise SystemExit("ERROR: --out-cell-name can only be used with a single --cell.")

    geometry_path = Path(args.geometry_config)
    if not geometry_path.is_file():
        raise SystemExit(f"ERROR: geometry config not found: {geometry_path}")
    try:
        geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"ERROR: invalid geometry JSON {geometry_path}: {exc}") from exc
    if not isinstance(geometry, dict):
        raise SystemExit(f"ERROR: geometry config root must be a JSON object: {geometry_path}")

    solver_path = Path(args.solver_config)
    solver_config = load_solver_config(solver_path)
    os.environ["CELLGEN_TIMELIMIT"] = str(solver_config["time_limit_seconds"])
    os.environ["CELLGEN_THREADS"] = str(solver_config["threads"])
    print(
        "[SOLVER-CONFIG]"
        f" path={solver_path}"
        f" time_limit_seconds={solver_config['time_limit_seconds']}"
        f" threads={solver_config['threads']}"
        f" topology_optimization={solver_config['topology_optimization']}",
        flush=True,
    )
    disable_topology_optimization = (
        args.no_topology_opt or not solver_config["topology_optimization"]
    )

    if args.ilp_script:
        ilp_script = Path(args.ilp_script)
    else:
        ilp_script = pick_ilp_script(args.flow, args.arch)

    if not ilp_script.exists():
        raise SystemExit(f"ERROR: ILP script not found: {ilp_script}")

    successful_cells = []
    port_nets_map = {}

    for cell in args.cell:
        out_name = (
            args.out_cell_name
            if args.out_cell_name
            else derive_out_name(cell, args.arch, args.mh_order)
        )
        port_nets_map[out_name] = parse_cdl_ports(args.cdl, cell)

        ilp_cmd = [
            args.python,
            str(ilp_script),
            "--cdl",
            args.cdl,
            "--cell",
            cell,
            "--dummy-for-ideal",
            str(args.dummy_for_ideal),
            "--dummy-padding",
            str(args.dummy_padding),
            "--misalign-col",
            str(args.misalign_col),
            "--out-cell-name",
            out_name,
            "--partition",
            args.partition,
        ]

        if args.arch == "DH":
            ilp_cmd += ["--mh-order", args.mh_order]
        if disable_topology_optimization and args.flow == "SO3" and args.arch != "DH":
            ilp_cmd += ["--no-topology-opt"]

        use_sequential = args.phase in ("placement", "routing", "sequential") and args.flow == "SO3" and args.arch != "DH"
        max_pl = args.max_placements if use_sequential else 1

        if use_sequential:
            if args.phase == "placement":
                ilp_cmd += ["--phase", "placement"]
                if max_pl > 1:
                    ilp_cmd += ["--pool-size", str(max_pl)]
                print("[RUN]", " ".join(ilp_cmd))
                try:
                    subprocess.run(ilp_cmd, check=True, cwd=str(ROOT))
                    successful_cells.append(out_name)
                except subprocess.CalledProcessError:
                    print(f"[ERROR] Placement ILP failed for cell: {cell}")
                    continue

            elif args.phase == "routing":
                routed = False
                for k in range(max_pl):
                    pl_file = (
                        f"{out_name}.placement.json" if k == 0
                        else f"{out_name}.placement_{k}.json"
                    )
                    pl_path = Path(ROOT) / pl_file
                    if not pl_path.exists():
                        print(f"[SKIP] Placement candidate {k} not found: {pl_path}")
                        break
                    route_cmd = ilp_cmd + ["--phase", "routing", "--placement-file", pl_file]
                    print(f"[RUN] Routing attempt {k}/{max_pl-1}:", " ".join(route_cmd))
                    result = subprocess.run(route_cmd, cwd=str(ROOT))
                    if result.returncode == 0:
                        print(f"[OK] Routing succeeded with placement candidate {k}")
                        routed = True
                        successful_cells.append(out_name)
                        break
                    else:
                        print(f"[FAIL] Routing failed for placement candidate {k}, trying next...")
                if not routed:
                    print(f"[ERROR] All {max_pl} placement candidates failed routing for cell: {cell}")
                    continue

            elif args.phase == "sequential":
                SH_POOL = 3

                def _try_sequential(ilp_scr, arch_str, mh_order_str, misalign_str, partition_str):
                    for dummy_val in range(args.max_dummy + 1):
                        place_cmd = [
                            args.python, str(ilp_scr),
                            "--cdl", args.cdl,
                            "--cell", cell,
                            "--dummy-for-ideal", str(dummy_val),
                            "--dummy-padding", str(args.dummy_padding),
                            "--misalign-col", misalign_str,
                            "--out-cell-name", out_name,
                            "--partition", partition_str,
                            "--phase", "placement",
                            "--pool-size", str(SH_POOL),
                        ]
                        if arch_str == "DH":
                            place_cmd += ["--mh-order", mh_order_str]
                        if disable_topology_optimization and args.flow == "SO3" and arch_str != "DH":
                            place_cmd += ["--no-topology-opt"]
                        print(f"[SEQ/{arch_str}] dummy={dummy_val} placement:", " ".join(place_cmd), flush=True)
                        pl_result = subprocess.run(place_cmd, cwd=str(ROOT))
                        if pl_result.returncode != 0:
                            print(f"[SEQ/{arch_str}-FAIL] dummy={dummy_val} placement failed, trying next dummy level...")
                            continue
                        for k in range(SH_POOL):
                            pl_file = (
                                f"{out_name}.placement.json" if k == 0
                                else f"{out_name}.placement_{k}.json"
                            )
                            pl_path = Path(ROOT) / pl_file
                            if not pl_path.exists():
                                print(f"[SKIP] dummy={dummy_val} candidate {k} not found: {pl_path}")
                                break
                            route_cmd = [
                                args.python, str(ilp_scr),
                                "--cdl", args.cdl,
                                "--cell", cell,
                                "--dummy-for-ideal", str(dummy_val),
                                "--dummy-padding", str(args.dummy_padding),
                                "--misalign-col", misalign_str,
                                "--out-cell-name", out_name,
                                "--partition", partition_str,
                                "--phase", "routing",
                                "--placement-file", pl_file,
                            ]
                            if arch_str == "DH":
                                route_cmd += ["--mh-order", mh_order_str]
                            if disable_topology_optimization and args.flow == "SO3" and arch_str != "DH":
                                route_cmd += ["--no-topology-opt"]
                            print(f"[SEQ/{arch_str}] dummy={dummy_val} routing candidate {k}/{SH_POOL-1}:", " ".join(route_cmd), flush=True)
                            result = subprocess.run(route_cmd, cwd=str(ROOT))
                            if result.returncode == 0:
                                print(f"[SEQ/{arch_str}-OK] {cell} dummy={dummy_val} candidate {k} succeeded")
                                return out_name
                            else:
                                print(f"[SEQ/{arch_str}-FAIL] dummy={dummy_val} routing candidate {k} failed, trying next...")
                    return None

                def _try_dh_once(ilp_scr, mh_order_str, misalign_str, partition_str):
                    cmd = [
                        args.python, str(ilp_scr),
                        "--cdl", args.cdl,
                        "--cell", cell,
                        "--dummy-for-ideal", "0",
                        "--dummy-padding", str(args.dummy_padding),
                        "--misalign-col", misalign_str,
                        "--out-cell-name", out_name,
                        "--partition", partition_str,
                        "--mh-order", mh_order_str,
                    ]
                    print(f"[DH-ONCE]", " ".join(cmd), flush=True)
                    if subprocess.run(cmd, cwd=str(ROOT)).returncode == 0:
                        print(f"[DH-ONCE-OK] {cell} DH succeeded", flush=True)
                        return out_name
                    print(f"[DH-ONCE-FAIL] DH failed", flush=True)
                    return None

                solved_name = _try_sequential(
                    ilp_script, args.arch, args.mh_order,
                    str(args.misalign_col), args.partition,
                )

                if solved_name is None and args.arch != "DH":
                    print(f"[SEQ-DH] SH exhausted for {cell} — trying DH once", flush=True)
                    dh_ilp = pick_ilp_script(args.flow, "DH")
                    if dh_ilp.exists():
                        solved_name = _try_dh_once(
                            dh_ilp, args.mh_order,
                            str(args.misalign_col), args.partition,
                        )
                    else:
                        print(f"[SEQ-DH-SKIP] DH ILP script not found: {dh_ilp}", flush=True)

                if solved_name is not None:
                    successful_cells.append(solved_name)
                else:
                    raise SystemExit(
                        f"[SEQ-FAILED] {cell}: SH (dummy 0-{args.max_dummy}) and DH both failed — no solution found"
                    )
        else:
            base_cmd = ilp_cmd + (["--phase", args.phase] if args.phase not in ("both", "sequential") else [])
            retry_flags = (
                ("--dummy-for-ideal", args.dummy_for_ideal, "dummy_for_ideal_offset"),
                ("--dummy-padding", args.dummy_padding, "dummy_padding_offset"),
                ("--misalign-col", args.misalign_col, "misalign_col_offset"),
            )
            solved = False
            for attempt_index, offsets in enumerate(solver_config["retry_attempts"]):
                cmd = list(base_cmd)
                effective = {}
                for flag, base_value, offset_key in retry_flags:
                    value = base_value + offsets[offset_key]
                    if value < 0:
                        raise SystemExit(
                            f"ERROR: retry attempt {attempt_index} makes {flag} negative "
                            f"({base_value} + {offsets[offset_key]})"
                        )
                    cmd[cmd.index(flag) + 1] = str(value)
                    effective[flag] = value
                print(
                    "[RUN]",
                    " ".join(cmd),
                    "(retry="
                    f"{attempt_index}; dummy-for-ideal={effective['--dummy-for-ideal']}; "
                    f"dummy-padding={effective['--dummy-padding']}; "
                    f"misalign-col={effective['--misalign-col']})",
                )
                try:
                    subprocess.run(cmd, check=True, cwd=str(ROOT))
                    successful_cells.append(out_name)
                    if attempt_index > 0:
                        print(f"[OK] {cell} solved with configured retry={attempt_index}")
                    solved = True
                    break
                except subprocess.CalledProcessError:
                    print(
                        f"[RETRY] {cell}: ILP failed at configured retry={attempt_index} "
                        f"(dummy-for-ideal={effective['--dummy-for-ideal']}; "
                        f"dummy-padding={effective['--dummy-padding']}; "
                        f"misalign-col={effective['--misalign-col']})",
                        flush=True,
                    )
            if not solved:
                print()
                print(
                    f"[ERROR] ILP failed for cell: {cell} "
                    f"(tried {len(solver_config['retry_attempts'])} configured retry attempts)"
                )
                print("[INFO] GDS generation is skipped for this cell.")
                continue

    if not successful_cells:
        print("[ERROR] No cells were solved successfully.")
        print("[INFO] GDS generation is skipped.")
        raise SystemExit(1)

    if args.phase == "placement":
        print("[SKIP] GDS generation (placement phase only)")
        return

    gds_cells = args.cells or successful_cells
    cfg = {
        "output_dir": args.gds_out,
        "cells": gds_cells,
        "arch": args.arch,
        "mh_order": args.mh_order if args.arch == "DH" else "N_FIRST",
        "port_nets": port_nets_map,
        "geometry": geometry,
    }

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as tf:
        json.dump(cfg, tf, ensure_ascii=False, indent=2)
        cfg_path = tf.name

    env = os.environ.copy()
    env["GDSGEN_CONFIG"] = cfg_path

    kl_cmd = [args.klayout, "-b", "-r", args.gdsgen_script]
    print("[RUN]", " ".join(kl_cmd))
    try:
        subprocess.run(kl_cmd, check=True, env=env, cwd=str(ROOT))
    finally:
        try:
            os.unlink(cfg_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
