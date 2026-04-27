#!/bin/bash

set -euo pipefail

MODE="${1:-}"
LANGUAGE="${2:-}"
SOURCE_FILE="${3:-}"
STDIN_FILE="${4:-}"
OPTIMIZE="${COMPILER_OPTIMIZE:-0}"

if [[ -z "$MODE" || -z "$LANGUAGE" || -z "$SOURCE_FILE" ]]; then
  echo "usage: run.sh <compile|run|dump-ir|dump-ssa|asm> <language> <source_file> [stdin_file]" >&2
  exit 2
fi

if [[ ! -f "$SOURCE_FILE" ]]; then
  echo "source file not found: $SOURCE_FILE" >&2
  exit 1
fi

if [[ -n "$STDIN_FILE" && ! -f "$STDIN_FILE" ]]; then
  echo "stdin file not found: $STDIN_FILE" >&2
  exit 1
fi

C_FLAGS=(-Wall -Wextra -std=c11)
CPP_FLAGS=(-Wall -Wextra -std=c++17)

if [[ "$OPTIMIZE" == "1" ]]; then
  C_FLAGS+=(-O2)
  CPP_FLAGS+=(-O2)
else
  C_FLAGS+=(-O0 -g)
  CPP_FLAGS+=(-O0 -g)
fi

compile_python() {
  python3 - "$SOURCE_FILE" <<'PY'
import py_compile
import sys

py_compile.compile(sys.argv[1], cfile="/tmp/program.pyc", doraise=True)
PY
}

run_python() {
  if [[ -n "$STDIN_FILE" ]]; then
    python3 "$SOURCE_FILE" < "$STDIN_FILE"
  else
    python3 "$SOURCE_FILE"
  fi
}

compile_c() {
  gcc "${C_FLAGS[@]}" "$SOURCE_FILE" -o /tmp/program
}

run_c() {
  if [[ -n "$STDIN_FILE" ]]; then
    /tmp/program < "$STDIN_FILE"
  else
    /tmp/program
  fi
}

compile_cpp() {
  g++ "${CPP_FLAGS[@]}" "$SOURCE_FILE" -o /tmp/program
}

run_cpp() {
  if [[ -n "$STDIN_FILE" ]]; then
    /tmp/program < "$STDIN_FILE"
  else
    /tmp/program
  fi
}

compile_java() {
  javac -encoding UTF-8 "$SOURCE_FILE" -d /tmp/java-classes
}

run_java() {
  local class_name
  class_name="$(basename "$SOURCE_FILE" .java)"
  if [[ -n "$STDIN_FILE" ]]; then
    java -cp /tmp/java-classes "$class_name" < "$STDIN_FILE"
  else
    java -cp /tmp/java-classes "$class_name"
  fi
}

compile_javascript() {
  node --check "$SOURCE_FILE"
}

run_javascript() {
  if [[ -n "$STDIN_FILE" ]]; then
    node "$SOURCE_FILE" < "$STDIN_FILE"
  else
    node "$SOURCE_FILE"
  fi
}

compile_bpp() {
  local bpp_flags=()
  if [[ "$OPTIMIZE" == "1" ]]; then
    bpp_flags+=(-O1)
  else
    bpp_flags+=(-O0)
  fi

  bpp "${bpp_flags[@]}" -asm "$SOURCE_FILE" > /tmp/program.asm
  nasm -f elf64 -O1 /tmp/program.asm -o /tmp/program.o
  ld /tmp/program.o -o /tmp/program
}

dump_bpp_ir() {
  local bpp_flags=()
  if [[ "$OPTIMIZE" == "1" ]]; then
    bpp_flags+=(-O1)
  else
    bpp_flags+=(-O0)
  fi
  bpp "${bpp_flags[@]}" -dump-ir "$SOURCE_FILE"
}

dump_bpp_ssa() {
  local bpp_flags=()
  if [[ "$OPTIMIZE" == "1" ]]; then
    bpp_flags+=(-O1)
  else
    bpp_flags+=(-O0)
  fi
  bpp "${bpp_flags[@]}" -dump-ssa "$SOURCE_FILE"
}

emit_bpp_asm() {
  local bpp_flags=()
  if [[ "$OPTIMIZE" == "1" ]]; then
    bpp_flags+=(-O1)
  else
    bpp_flags+=(-O0)
  fi
  bpp "${bpp_flags[@]}" -asm "$SOURCE_FILE"
}

run_bpp() {
  if [[ -n "$STDIN_FILE" ]]; then
    /tmp/program < "$STDIN_FILE"
  else
    /tmp/program
  fi
}

case "$LANGUAGE" in
  bpp)
    case "$MODE" in
      compile)
        compile_bpp
        ;;
      run)
        compile_bpp
        run_bpp
        ;;
      dump-ir)
        dump_bpp_ir
        ;;
      dump-ssa)
        dump_bpp_ssa
        ;;
      asm)
        emit_bpp_asm
        ;;
      *)
        echo "Unsupported mode for B++: $MODE" >&2
        exit 1
        ;;
    esac
    ;;
  python)
    if [[ "$MODE" != "compile" && "$MODE" != "run" ]]; then
      echo "Unsupported mode for Python: $MODE" >&2
      exit 1
    fi
    compile_python
    if [[ "$MODE" == "run" ]]; then
      run_python
    fi
    ;;
  c)
    if [[ "$MODE" != "compile" && "$MODE" != "run" ]]; then
      echo "Unsupported mode for C: $MODE" >&2
      exit 1
    fi
    compile_c
    if [[ "$MODE" == "run" ]]; then
      run_c
    fi
    ;;
  cpp)
    if [[ "$MODE" != "compile" && "$MODE" != "run" ]]; then
      echo "Unsupported mode for C++: $MODE" >&2
      exit 1
    fi
    compile_cpp
    if [[ "$MODE" == "run" ]]; then
      run_cpp
    fi
    ;;
  java)
    if [[ "$MODE" != "compile" && "$MODE" != "run" ]]; then
      echo "Unsupported mode for Java: $MODE" >&2
      exit 1
    fi
    mkdir -p /tmp/java-classes
    compile_java
    if [[ "$MODE" == "run" ]]; then
      run_java
    fi
    ;;
  javascript)
    if [[ "$MODE" != "compile" && "$MODE" != "run" ]]; then
      echo "Unsupported mode for JavaScript: $MODE" >&2
      exit 1
    fi
    compile_javascript
    if [[ "$MODE" == "run" ]]; then
      run_javascript
    fi
    ;;
  *)
    echo "Unsupported language: $LANGUAGE" >&2
    exit 1
    ;;
esac
