#!/usr/bin/env bash
set -euo pipefail

# repo root
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
RUNNER="$ROOT/bin/run_cell.py"
KLAYOUT="${KLAYOUT:-klayout}"

# Base setting (modify whatever you want)
# e.g, for DFFHQN_X1, if you want to make it with DUMMY_FOR_IDEAL 1, MISALIGN_COL has to be 4.
CDL_ROOT="$ROOT/../../Enablement/cdl"
CDL="${CDL:-$CDL_ROOT/SO3_L1.cdl}"
GDS_OUT="${GDS_OUT:-gds_result}"
D_GDS_OUT="$ROOT/results/gds"
if [ "$GDS_OUT" = "gds_result" ]; then
  GDS_OUT="$D_GDS_OUT"
fi
DUMMY_FOR_IDEAL="${DUMMY_FOR_IDEAL:-0}"
DUMMY_PADDING="${DUMMY_PADDING:-0}"
MISALIGN_COL="${MISALIGN_COL:-0}"

# ARCH: SH (single-height) or DH (double-height)
ARCH="${ARCH:-SH}"                # SH | DH
# MH_ORDER used only when ARCH=DH
MH_ORDER="${MH_ORDER:-N_FIRST}"   # N_FIRST | P_FIRST
FLOW="${FLOW:-SO3}"               # SO2 | SO3
PARTITION="${PARTITION:-N}"       # N | LR | H

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
  --dummy-for-ideal N    DUMMY_FOR_IDEAL value
  --dummy-padding N      DUMMY_PADDING value
  --misalign-col N       MISALIGN_COL value
  --arch SH|DH           Cell architecture (default: SH)
  --mh-order N_FIRST|P_FIRST  Only used when ARCH=DH
  --flow SO2|SO3         SO2 do not touch the circuit
  --partition N|LR|H     Only for 2Bit Flip-Flop
  --python <path>        Python interpreter (default: python3)
  --klayout <path>       KLayout executable (default: klayout)
  -h, --help

Behavior:
  1) --cdl-name SO3_L1   → Generate all .SUBCKT entries in SO3_L1.cdl
  2) --cdl <file> --cells "INV_X1 NAND2_X1" → Generate only those cells
  3) Run with no args to show this help.
Notes:
  - Most cells use PARTITION=N.
  - Only 2BDFFHQN_X1 is allowed to use partition override:
      SH -> LR
      DH -> H
  - MUX2_X1, LHQ_X1, DFFHQN_X1, 2BDFFHQN_X1 are forced to SO2.

Examples:
  ./run_cell.sh --cdl-name SO3_L1 --cells "INV_X1"
  ./run_cell.sh --cdl-name SO3_L1 --cells "2BDFFHQN_X1" --arch SH
  ./run_cell.sh --cdl-name SO3_L1 --cells "MUX2_X1" --arch DH
  ./run_cell.sh --cdl-name SO3_L1 --cells "DFFHQN_X1_SH INV_X1"
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
      # partition is blocked for all non-2BDFFHQN_X1 cells
      local_partition="N"
      ;;
  esac

  echo "$local_flow|$local_misalign|$local_partition"
}

for cell in "${CELLS[@]}"; do
  IFS='|' read -r EFF_FLOW EFF_MISALIGN EFF_PARTITION < <(apply_defaults_for_cell "$cell")

  echo "[RUN]" "$PYTHON" "$RUNNER" \
    --cdl "$CDL" \
    --cell "$cell" \
    --dummy-for-ideal "$DUMMY_FOR_IDEAL" \
    --dummy-padding "$DUMMY_PADDING" \
    --misalign-col "$EFF_MISALIGN" \
    --gds-out "$GDS_OUT" \
    --arch "$ARCH" \
    --mh-order "$MH_ORDER" \
    --flow "$EFF_FLOW" \
    --partition "$EFF_PARTITION" \
    --klayout "$KLAYOUT"

  if ! "$PYTHON" "$RUNNER" \
    --cdl "$CDL" \
    --cell "$cell" \
    --dummy-for-ideal "$DUMMY_FOR_IDEAL" \
    --dummy-padding "$DUMMY_PADDING" \
    --misalign-col "$EFF_MISALIGN" \
    --gds-out "$GDS_OUT" \
    --arch "$ARCH" \
    --mh-order "$MH_ORDER" \
    --flow "$EFF_FLOW" \
    --partition "$EFF_PARTITION" \
    --klayout "$KLAYOUT"
  then
    echo "[WARN] run_cell.py failed for $cell; continue to next cell"
  fi
done
