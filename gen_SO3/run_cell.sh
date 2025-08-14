#!/usr/bin/env bash
set -euo pipefail

# repo root
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON="${PYTHON:-python3}"
RUNNER="$ROOT/bin/run_cell.py"

# Base setting (modify whaever you want)
CDL="${CDL:-$ROOT/../cdl/SO3_L1.cdl}"
GDS_OUT="${GDS_OUT:-gds_result}"
DUMMY_FOR_IDEAL="${DUMMY_FOR_IDEAL:-0}"
DUMMY_PADDING="${DUMMY_PADDING:-0}"
MISALIGN_COL="${MISALIGN_COL:-0}"

# cell list you want
CELLS=("$@")
if [ ${#CELLS[@]} -eq 0 ]; then
  #CELLS=(INV_X1 NAND2_X1)
  CELLS=(INV_X1)
fi

echo "[RUN]" "$PYTHON" "$RUNNER" \
  --cdl "$CDL" \
  --cell "${CELLS[@]}" \
  --dummy-for-ideal "$DUMMY_FOR_IDEAL" \
  --dummy-padding "$DUMMY_PADDING" \
  --misalign-col "$MISALIGN_COL" \
  --gds-out "$GDS_OUT"

exec "$PYTHON" "$RUNNER" \
  --cdl "$CDL" \
  --cell "${CELLS[@]}" \
  --dummy-for-ideal "$DUMMY_FOR_IDEAL" \
  --dummy-padding "$DUMMY_PADDING" \
  --misalign-col "$MISALIGN_COL" \
  --gds-out "$GDS_OUT"
