#!/usr/bin/env bash
set -euo pipefail

source /etc/profile.d/modules.sh
module load ruby/2.5.9 klayout/0.30.5

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export GRB_LICENSE_FILE="${GRB_LICENSE_FILE:-$HOME/pdk/SO3/license/gurobi.lic}"
PYTHON="${PYTHON:-/usr/bin/python3.9}"
RUNNER="$ROOT/bin/run_cell.py"
KLAYOUT="${KLAYOUT:-klayout}"

CDL_ROOT="${CDL_ROOT:-$ROOT/../../Enablement/cdl}"
CDL="${CDL:-$CDL_ROOT/gt2_so3cell_6t_w13_lvt.cdl}"
GDS_OUT="${GDS_OUT:-gds_result}"
D_GDS_OUT="$ROOT/results/gds"
if [ "$GDS_OUT" = "gds_result" ]; then
  GDS_OUT="$D_GDS_OUT"
fi
DUMMY_FOR_IDEAL="${DUMMY_FOR_IDEAL:-0}"
DUMMY_PADDING="${DUMMY_PADDING:-0}"
MISALIGN_COL="${MISALIGN_COL:-0}"
MAX_PLACEMENTS="${MAX_PLACEMENTS:-6}"
GEOMETRY_CONFIG="${GEOMETRY_CONFIG:-$ROOT/config/gt2n_6t_geometry.json}"
SOLVER_CONFIG="${SOLVER_CONFIG:-$ROOT/config/gt2n_solver.json}"

ARCH="${ARCH:-SH}"
MH_ORDER="${MH_ORDER:-N_FIRST}"
FLOW="${FLOW:-SO3}"
PARTITION="${PARTITION:-N}"
NO_TOPOLOGY_OPT="${NO_TOPOLOGY_OPT:-0}"
PHASE="${PHASE:-both}"

ORIG_ARGC=$#
AUTO_CELLS_FROM_CDL=0
CELLS=()
CDL_NAME=""

usage() {
  cat <<'EOF'
Usage: ./run_cell.sh [options] [cells...]

Options:
  --cdl <path>               Explicit CDL file path
  --cdl-name <name>          Use <name>.cdl under Enablement/cdl
  --cells "<c1 c2>"          Space-separated cell list
  --gds-out <dir>            GDS output directory
  --geometry-config <json>   GDS geometry parameter JSON
  --solver-config <json>     ILP runtime parameter JSON
  --dummy-for-ideal N        DUMMY_FOR_IDEAL value
  --dummy-padding N          DUMMY_PADDING value
  --misalign-col N           MISALIGN_COL value
  --arch SH|DH               Cell architecture (default: SH)
  --mh-order N_FIRST|P_FIRST Only used when ARCH=DH
  --flow SO2|SO3             SO2 or SO3 ILP family
  --partition N|LR|H         Partition mode
  --no-topology-opt          Disable circuit topology optimization (SO3 SH only)
  --phase both|placement|routing
                             Split SO3 SH into placement/routing phases
  --python <path>            Python interpreter (default: /usr/bin/python3.9)
  --klayout <path>           KLayout executable (default: klayout)
  -h, --help

Behavior:
  1) --cdl-name gt2_so3cell_6t_w13_lvt   -> Generate every .SUBCKT in that library
  2) --cdl <file> --cells "gt2_6t_inv_x1_w13_lvt" -> Generate only those cells
  3) Run with no args to show this help.

Notes:
  - Most cells use PARTITION=N.
  - Only 2BDFFHQN_X1 is allowed to use partition override:
      SH -> LR
      DH -> H
  - MUX2_X1, LHQ_X1, DFFHQN_X1, 2BDFFHQN_X1 are forced to SO2.

Examples:
  ./run_cell.sh --cdl-name gt2_so3cell_6t_w13_lvt --cells "gt2_6t_inv_x1_w13_lvt"
  ./run_cell.sh --cdl-name gt2_so3cell_7t_w43_lvt --cells "gt2_7t_inv_x1_w43_lvt" \
      --geometry-config config/gt2n_7t_geometry.json
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --cdl)
      CDL="$2"; shift 2 ;;
    --cdl-name)
      CDL_NAME="$2"; shift 2 ;;
    --cells)
      IFS=' ' read -r -a CELLS <<< "$2"; shift 2 ;;
    --gds-out)
      GDS_OUT="$2"; shift 2 ;;
    --geometry-config)
      GEOMETRY_CONFIG="$2"; shift 2 ;;
    --solver-config)
      SOLVER_CONFIG="$2"; shift 2 ;;
    --dummy-for-ideal)
      DUMMY_FOR_IDEAL="$2"; shift 2 ;;
    --dummy-padding)
      DUMMY_PADDING="$2"; shift 2 ;;
    --misalign-col)
      MISALIGN_COL="$2"; shift 2 ;;
    --arch)
      ARCH="$2"; shift 2 ;;
    --mh-order)
      MH_ORDER="$2"; shift 2 ;;
    --flow)
      FLOW="$2"; shift 2 ;;
    --partition)
      PARTITION="$2"; shift 2 ;;
    --no-topology-opt)
      NO_TOPOLOGY_OPT=1; shift ;;
    --phase)
      PHASE="$2"; shift 2 ;;
    --python)
      PYTHON="$2"; shift 2 ;;
    --klayout)
      KLAYOUT="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    --)
      shift
      CELLS+=("$@")
      break ;;
    *)
      if [ -z "$CDL_NAME" ] && [ -f "$CDL_ROOT/${1}.cdl" ]; then
        CDL_NAME="$1"
        shift
      else
        CELLS+=("$1")
        shift
      fi ;;
  esac
done

if [ -n "$CDL_NAME" ]; then
  CDL="$CDL_ROOT/${CDL_NAME}.cdl"
  AUTO_CELLS_FROM_CDL=1
fi

if [ $ORIG_ARGC -eq 0 ]; then
  usage
  exit 0
fi

if [ ! -f "$CDL" ]; then
  echo "ERROR: CDL file not found: $CDL" >&2
  echo "  (CDL_ROOT='$CDL_ROOT', --cdl-name='$CDL_NAME')" >&2
  echo "  Provide a valid path via --cdl <path>, --cdl-name <name>, or CDL/CDL_ROOT env vars." >&2
  exit 1
fi

if [ ${#CELLS[@]} -eq 0 ]; then
  if [ "$AUTO_CELLS_FROM_CDL" -eq 1 ]; then
    mapfile -t CELLS < <("$PYTHON" - "$CDL" <<'PY'
import sys
path = sys.argv[1]
names = []
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("*"):
            continue
        if line.upper().startswith(".SUBCKT "):
            parts = line.split()
            if len(parts) > 1 and parts[1] not in names:
                names.append(parts[1])
for n in names:
    print(n)
PY
)
    if [ ${#CELLS[@]} -eq 0 ]; then
      echo "[WARN] No .SUBCKT entries found in $CDL; defaulting to INV_X1" >&2
      CELLS=(INV_X1)
    fi
  else
    CELLS=(INV_X1)
  fi
fi

apply_defaults_for_cell() {
  local cell="$1"
  local local_flow="$FLOW"
  local local_misalign="$MISALIGN_COL"
  local local_partition="$PARTITION"

  case "$cell" in
    MUX2_X1|LHQ_X1)
      local_flow="SO2"
      local_misalign=2
      local_partition="N"
      ;;
    DFFHQN_X1_SH|DFFRNQ_X1_SH|DFFHQN_X1_DH|DFFRNQ_X1_DH)
      local_flow="SO2"
      local_misalign=4
      local_partition="N"
      ;;
    2BDFFHQN_X1_SH)
      local_flow="SO2"
      local_misalign=8
      local_partition="LR"
      ;;
    2BDFFHQN_X1_DH)
      local_flow="SO2"
      local_misalign=8
      local_partition="H"
      ;;
    *)
      local_partition="N"
      ;;
  esac

  echo "$local_flow|$local_misalign|$local_partition"
}

for cell in "${CELLS[@]}"; do
  IFS='|' read -r EFF_FLOW EFF_MISALIGN EFF_PARTITION < <(apply_defaults_for_cell "$cell")

  cmd=(
    "$PYTHON" "$RUNNER"
    --cdl "$CDL"
    --cell "$cell"
    --dummy-for-ideal "$DUMMY_FOR_IDEAL"
    --dummy-padding "$DUMMY_PADDING"
    --misalign-col "$EFF_MISALIGN"
    --gds-out "$GDS_OUT"
    --geometry-config "$GEOMETRY_CONFIG"
    --solver-config "$SOLVER_CONFIG"
    --arch "$ARCH"
    --mh-order "$MH_ORDER"
    --flow "$EFF_FLOW"
    --partition "$EFF_PARTITION"
    --klayout "$KLAYOUT"
    --max-placements "$MAX_PLACEMENTS"
  )

  if [ "$NO_TOPOLOGY_OPT" = "1" ] && [ "$EFF_FLOW" = "SO3" ] && [ "$ARCH" != "DH" ]; then
    cmd+=(--no-topology-opt)
  fi
  if [ "$PHASE" != "both" ] && [ "$EFF_FLOW" = "SO3" ] && [ "$ARCH" != "DH" ]; then
    cmd+=(--phase "$PHASE")
  fi

  echo "[RUN]" "${cmd[@]}"
  if ! "${cmd[@]}"; then
    echo "[WARN] run_cell.py failed for $cell; continue to next cell"
  fi
done
