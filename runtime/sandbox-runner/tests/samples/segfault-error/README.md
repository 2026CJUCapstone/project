# segfault-error

목적:

- `runtime_error` 상태에서 `runtimeErrorReason=signal_segv` 분류를 검증한다.

기대 결과:

- finalStatus: `RuntimeError`
- signal: `SIGSEGV`
- runtimeErrorReason: `signal_segv`
