#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SAMPLES_DIR="$ROOT_DIR/tests/samples"
CONFIG_FILE="$ROOT_DIR/config/poc.env"

# shellcheck disable=SC1091
source "$CONFIG_FILE"

mkdir -p "$ROOT_DIR/$BUILD_DIR"

for sample_dir in "$SAMPLES_DIR"/*; do
    sample_name="$(basename "$sample_dir")"
    source_file="$sample_dir/main.c"
    output_file="$ROOT_DIR/$BUILD_DIR/$sample_name"

    if [[ ! -d "$sample_dir" || "$sample_name" == "_template" || ! -f "$source_file" ]]; then
        continue
    fi

    "$CC" $CFLAGS "$source_file" -o "$output_file"
    echo "built: $sample_name -> $output_file"
done
