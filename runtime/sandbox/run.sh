#!/bin/bash
# run.sh – 사용자 코드 실행 래퍼 스크립트
# 사용법: run.sh <language> <source_file>
#   language: python | c | cpp | java | javascript

LANGUAGE=$1
SOURCE_FILE=$2

case "$LANGUAGE" in
  python)
    python3 "$SOURCE_FILE"
    ;;
  c)
    gcc "$SOURCE_FILE" -o /tmp/a.out && /tmp/a.out
    ;;
  cpp)
    g++ "$SOURCE_FILE" -o /tmp/a.out && /tmp/a.out
    ;;
  java)
    javac "$SOURCE_FILE" -d /tmp && java -cp /tmp "$(basename "$SOURCE_FILE" .java)"
    ;;
  javascript)
    node "$SOURCE_FILE"
    ;;
  *)
    echo "Unsupported language: $LANGUAGE" >&2
    exit 1
    ;;
esac
