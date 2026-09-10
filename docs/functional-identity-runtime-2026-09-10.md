# Current-image identity runtime check — 2026-09-10

## Result

Root follow-up on the F13+F14 frontend (`sha256:0c2bf9cfd47e60d9ad55628245308d7863355797ffee7570db0fbbddb3085bf3`): **3/3 PASS, 19.5 seconds**. The same result JSON now contains this final run. The long-email fixture was tightened to a valid <=64-character local part while keeping the whole address longer than64. The first 14.3-second result below is historical; no duplicate case count is added. Runtime image/archive evidence, not the inherited health response's deployment SHA setting, identifies the tested build.

**PASS — 3/3, 0 skipped, 0 unexpected, 0 flaky, 14.3 seconds.** The authoritative artifact is [`results.json`](../.deploy/test-results/identity-runtime/results.json); it reports a UTC start of `2026-09-10T11:09:00.489Z` and 14,260 ms total duration.

Command, run from `frontend/`, using the requested Node 24 runtime and no Playwright `webServer`:

```text
F:\01_Programming\01_Project\03_Study\Capstone\project\.deploy\node24-audit-20260910\node-v24.21.0-win-x64\node.exe F:\01_Programming\01_Project\03_Study\Capstone\project\frontend\node_modules\@playwright\test\cli.js test --config=playwright.identity-runtime.config.ts
```

Target health was HTTP 200 immediately before the run at `http://127.0.0.1:15181/webcompiler/health`, with deployment SHA prefix `63badb96` and runtime instance prefix `40a4dd8b`. The test used the isolated image at `http://127.0.0.1:15181/webcompiler/`, generated unique disposable accounts via the real API, and did not mutate existing contest accounts or perform cleanup/server operations.

Passed scenarios in [`identity-runtime.local.spec.ts`](../frontend/e2e/identity-runtime.local.spec.ts):

1. Two-character nickname login and an email longer than 64 characters; both nickname and email login payloads were accepted by the real image.
2. Real cross-tab A → B switch: an unsaved A profile draft was invalidated, the first tab observed B, and the subsequent real PATCH body contained B’s email/nickname rather than the stale A draft. Both server profiles were read back with their original ownership.
3. Profile persistence: omitted-field PATCH retention, explicit UI clearing to JSON `null`, server readback, cache removal, reload and empty profile fields.

No product defect was observed. An initial one-test harness attempt expected uppercase `tabB` email spelling, while the API correctly canonicalized it to lowercase; the test was narrowed to lowercase generated prefixes and the full authoritative run then passed. This was a test expectation issue, not a product failure.

No usernames, passwords, access tokens, or response secrets are recorded. Fixture/resource cleanup remains owned by the root agent.
