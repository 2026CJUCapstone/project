# Functional history runtime verification — 2026-09-10

`frontend/e2e/history-runtime.local.spec.ts` is a single-worker, actual-browser
test for the isolated fixture at `http://127.0.0.1:15181/webcompiler/`.  Its
configuration rejects every other protocol, host, port, path, query, and hash;
it starts no web server and writes only under
`.deploy/test-results/history-runtime/`.

The test reads the disposable admin account only in the Node process, without
printing or attaching its credentials.  It creates one uniquely named public
problem through the live API, registers one unique disposable participant in
the real UI, and intentionally leaves those owned fixture records for the
fixture owner to remove.

The intended browser contract is:

1. Search the created challenge and enter it through challenge detail into the
   IDE.
2. Select Python, replace the Monaco source with `print(42)`, and submit using
   the visible judge panel.
3. Verify the live submission receipt carries `language: "python"`, then that
   the visible verdict is accepted.
4. Filter the live queue by grading kind, the created problem ID, the new
   username, and accepted verdict; verify the matching rendered row.
5. Filter submissions by verdict/problem/user, enable **내 제출**, and follow
   the rendered problem link back to challenge detail.
6. Verify the live leaderboard row contains the new username and the problem's
   137-point score.  It also checks body/document horizontal overflow at both
   desktop and 390 px widths and captures only post-authenticated, non-secret
   desktop/mobile screenshots.

Run it from the repository root with the bundled Node runtime:

```powershell
& .deploy/node24-audit-20260910/node-v24.21.0-win-x64/node.exe frontend/node_modules/@playwright/test/cli.js test --config frontend/playwright.history-runtime.config.ts
```

## Recorded fixture result

After the fixture frontend was refreshed to
`sha256:0c2bf9cfd47e60d9ad55628245308d7863355797ffee7570db0fbbddb3085bf3`, the
command above passed one complete browser test in 14.6 seconds.  The live POST
receipt carried `language: "python"`, the judge UI showed **정답**, and the
rendered queue, submission-history, mine-filter, challenge navigation, and
leaderboard assertions all passed.  Both desktop and 390 px body/document
overflow checks passed; post-authenticated screenshots are in
`.deploy/test-results/history-runtime/artifacts/`.

The old-image attempts stopped at harness locators before a submission payload
was captured, so they are not represented as actual evidence that the old
image emitted B++.  The final test remains deliberately strict on Python and
its sanitized `submission-language-contract` attachment records only the
problem ID and expected/observed language.  No server, container, existing
account, or product mutation was performed by this verification suite.

The test runs left uniquely prefixed disposable fixture records (`history_`
users and `History runtime` problems) for the fixture owner to clean up.
