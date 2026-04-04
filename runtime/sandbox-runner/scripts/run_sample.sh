#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $0 <sample-name> [--stdin-file path] [--workdir path] [--arg value ...]" >&2
    exit 2
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="$ROOT_DIR/config/poc.env"
SAMPLE_NAME="$1"
shift
STDIN_FILE=""
WORKDIR=""
EXEC_ARGS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stdin-file)
            STDIN_FILE="$2"
            shift 2
            ;;
        --workdir)
            WORKDIR="$2"
            shift 2
            ;;
        --arg)
            EXEC_ARGS+=("$2")
            shift 2
            ;;
        *)
            echo "unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

# shellcheck disable=SC1091
source "$CONFIG_FILE"

BIN_PATH="$ROOT_DIR/$BUILD_DIR/$SAMPLE_NAME"
REPORT_DIR="$ROOT_DIR/$REPORTS_DIR/$SAMPLE_NAME"
STDOUT_FILE="$REPORT_DIR/stdout.txt"
STDERR_FILE="$REPORT_DIR/stderr.txt"
META_FILE="$REPORT_DIR/result.env"
RAW_JSON_FILE="$REPORT_DIR/raw-result.json"
MEMORY_KB="$((MEMORY_LIMIT_MB * 1024))"
WALL_TIME_SEC="$(((TIMEOUT_MS + 999) / 1000))"
POLICY_VERSION="official-v1"

if [[ ! -x "$BIN_PATH" ]]; then
    echo "missing built sample: $BIN_PATH" >&2
    echo "run scripts/build_samples.sh first" >&2
    exit 1
fi

mkdir -p "$REPORT_DIR"

if [[ -z "$WORKDIR" ]]; then
    WORKDIR="$ROOT_DIR/$BUILD_DIR"
fi

start_ms="$(date +%s%3N)"
set +e
timeout --signal=TERM "${WALL_TIME_SEC}s" \
    bash -c '
        set -e
        cpu_time_sec="$1"
        memory_kb="$2"
        process_limit="$3"
        workdir="$4"
        stdin_file="$5"
        shift 5

        ulimit -t "$cpu_time_sec" -v "$memory_kb" -u "$process_limit"
        cd "$workdir"

        if [[ -n "$stdin_file" ]]; then
            exec "$@" < "$stdin_file"
        else
            exec "$@"
        fi
    ' _ "$CPU_TIME_SEC" "$MEMORY_KB" "$PROCESS_LIMIT" "$WORKDIR" "$STDIN_FILE" "$BIN_PATH" "${EXEC_ARGS[@]}" \
    >"$STDOUT_FILE" 2>"$STDERR_FILE"
exit_code="$?"
set -e
end_ms="$(date +%s%3N)"
duration_ms="$((end_ms - start_ms))"
cpu_limit_ms="$((CPU_TIME_SEC * 1000))"
wall_limit_ms="$((WALL_TIME_SEC * 1000))"

signal_name=""
status="Success"
runtime_error_reason=""
violation_reason=""
internal_reason_code=""
stderr_text="$(tr '\n' ' ' < "$STDERR_FILE" | tr -s ' ')"
started_at="$(date -u -d "@$((start_ms / 1000))" +"%Y-%m-%dT%H:%M:%SZ")"
finished_at="$(date -u -d "@$((end_ms / 1000))" +"%Y-%m-%dT%H:%M:%SZ")"
cpu_time_ms=0
peak_memory_kb=0
violation_category=""
violation_message=""
violation_resource=""

if [[ "$exit_code" -eq 124 ]]; then
    status="Timeout"
    violation_reason="wall_time_limit_exceeded"
    violation_category="timeout"
    violation_message="wall time limit reached"
    violation_resource="wall_time"
elif [[ "$exit_code" -eq 137 && "$duration_ms" -ge $((cpu_limit_ms - 250)) ]]; then
    status="Timeout"
    violation_reason="cpu_time_limit_exceeded"
    violation_category="timeout"
    violation_message="cpu time limit reached"
    violation_resource="cpu"
    cpu_time_ms="$CPU_TIME_SEC"
elif [[ "$exit_code" -eq 134 || "$exit_code" -eq 143 || "$exit_code" -eq 137 || "$exit_code" -eq 139 ]]; then
    status="RuntimeError"
    if [[ "$exit_code" -eq 134 ]]; then
        signal_name="SIGABRT"
        runtime_error_reason="signal_abrt"
    elif [[ "$exit_code" -eq 143 ]]; then
        signal_name="SIGTERM"
        runtime_error_reason="signal_term"
    elif [[ "$exit_code" -eq 137 ]]; then
        signal_name="SIGKILL"
        runtime_error_reason="signal_kill"
    else
        signal_name="SIGSEGV"
        runtime_error_reason="signal_segv"
    fi
elif [[ "$exit_code" -ne 0 ]]; then
    if [[ "$stderr_text" == *"Cannot allocate memory"* || "$stderr_text" == *"allocation failed"* ]]; then
        status="OOM"
        violation_reason="memory_limit_exceeded"
        violation_category="memory"
        violation_message="memory limit reached"
        violation_resource="memory"
        peak_memory_kb="$MEMORY_KB"
    elif [[ "$stderr_text" == *"fork:"* || "$stderr_text" == *"Resource temporarily unavailable"* ]]; then
        status="SecurityViolation"
        violation_reason="process_limit_exceeded"
        violation_category="process"
        violation_message="process limit reached"
        violation_resource="process"
    elif [[ "$stderr_text" == *"Operation not permitted"* || "$stderr_text" == *"Permission denied"* ]]; then
        status="SecurityViolation"
        violation_reason="forbidden_file_access"
        if [[ "$SAMPLE_NAME" == "forbidden-network-access" ]]; then
            violation_category="network"
            violation_message="network access denied"
            violation_resource="network"
            violation_reason="forbidden_network_access"
        else
            violation_category="filesystem"
            violation_message="filesystem access denied"
            violation_resource="filesystem"
        fi
    else
        status="RuntimeError"
        runtime_error_reason="nonzero_exit"
    fi
fi

if [[ "$signal_name" == "SIGABRT" ]]; then
    runtime_error_reason="signal_abrt"
elif [[ "$signal_name" == "SIGTERM" ]]; then
    runtime_error_reason="signal_term"
elif [[ -n "$signal_name" && -z "$runtime_error_reason" ]]; then
    runtime_error_reason="unknown_signal"
fi

stdout_bytes="$(wc -c < "$STDOUT_FILE")"
stderr_bytes="$(wc -c < "$STDERR_FILE")"
stdout_total_bytes="$stdout_bytes"
stderr_total_bytes="$stderr_bytes"
truncated="false"

apply_ring_buffer() {
    local file_path="$1"
    local keep_bytes="$2"
    local current_bytes="$3"

    if [[ "$current_bytes" -le "$keep_bytes" ]]; then
        RING_BUFFER_RESULT="$current_bytes"
        return
    fi

    tail -c "$keep_bytes" "$file_path" > "$file_path.tmp"
    mv "$file_path.tmp" "$file_path"
    truncated="true"
    RING_BUFFER_RESULT="$keep_bytes"
}

if [[ "$stdout_bytes" -gt "$MAX_STDOUT_BYTES" ]]; then
    apply_ring_buffer "$STDOUT_FILE" "$MAX_STDOUT_BYTES" "$stdout_bytes"
    stdout_bytes="$RING_BUFFER_RESULT"
fi

if [[ "$stderr_bytes" -gt "$MAX_STDERR_BYTES" ]]; then
    apply_ring_buffer "$STDERR_FILE" "$MAX_STDERR_BYTES" "$stderr_bytes"
    stderr_bytes="$RING_BUFFER_RESULT"
fi

if [[ "${WRITE_DEBUG_ENV:-false}" == "true" ]]; then
    cat >"$META_FILE" <<EOF
sample_name=$SAMPLE_NAME
exit_code=$exit_code
final_status=$status
signal=$signal_name
duration_ms=$duration_ms
stdout_bytes=$stdout_bytes
stderr_bytes=$stderr_bytes
truncated=$truncated
violation_reason=$violation_reason
internal_reason_code=$internal_reason_code
EOF
fi

if [[ -n "$violation_reason" ]]; then
    violation_json=$(cat <<EOF
{
  "category": "$violation_category",
  "reason": "$violation_reason",
  "message": "$violation_message",
  "resource": "$violation_resource"
}
EOF
)
else
    violation_json="null"
fi

cat >"$RAW_JSON_FILE" <<EOF
{
  "requestId": "poc-$SAMPLE_NAME",
  "sampleName": "$SAMPLE_NAME",
  "finalStatus": "$status",
  "exitCode": $exit_code,
  "runtimeErrorReason": "$runtime_error_reason",
  "signal": "$signal_name",
  "startedAt": "$started_at",
  "finishedAt": "$finished_at",
  "metrics": {
    "durationMs": $duration_ms,
    "cpuTimeMs": $cpu_time_ms,
    "peakMemoryKb": $peak_memory_kb,
    "stdoutBytes": $stdout_bytes,
    "stderrBytes": $stderr_bytes
  },
  "violation": $violation_json,
  "stdoutMeta": {
    "bytes": $stdout_bytes,
    "truncated": $truncated,
    "encoding": "utf-8"
  },
  "stderrMeta": {
    "bytes": $stderr_bytes,
    "truncated": $truncated,
    "encoding": "utf-8"
  },
  "internalReasonCode": "$internal_reason_code",
  "notes": "generated by poc driver",
  "metadata": {
    "executionMode": "poc-local",
    "engine": "local",
    "policyVersion": "$POLICY_VERSION",
    "timeoutMs": $TIMEOUT_MS,
    "cpuQuotaCores": $CPU_QUOTA_CORES,
    "cpuQuotaMode": "best-effort",
    "memoryLimitMB": $MEMORY_LIMIT_MB,
    "processLimit": $PROCESS_LIMIT,
    "networkMode": "no-network",
    "filesystemMode": "isolated",
    "syscallProfile": "minimal-runtime",
    "workingDirectory": "$WORKDIR",
    "argsCount": ${#EXEC_ARGS[@]},
    "stdoutTotalBytes": $stdout_total_bytes,
    "stderrTotalBytes": $stderr_total_bytes
  }
}
EOF

printf 'sample=%s\nstatus=%s\nexit_code=%s\nduration_ms=%s\nstdout_bytes=%s\nstderr_bytes=%s\ntruncated=%s\n' \
    "$SAMPLE_NAME" "$status" "$exit_code" "$duration_ms" "$stdout_bytes" "$stderr_bytes" "$truncated"
if [[ -n "$violation_reason" ]]; then
    printf 'violation_reason=%s\n' "$violation_reason"
fi
