// @vitest-environment node

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";

import { describe, expect, it, afterEach } from "vitest";

import { readMonacoDistribution } from "./localMonacoAssets";


const WORKER_KINDS = ["editor", "css", "html", "json", "ts"] as const;
const fixtureRoots: string[] = [];


function makeFixture(writeInReverse = false) {
  const packageRoot = mkdtempSync(path.join(os.tmpdir(), "local-monaco-assets-test-"));
  fixtureRoots.push(packageRoot);
  const files = new Map<string, Buffer>([
    ["loader.js", Buffer.from("loader-v1\n")],
    ["editor/editor.main.js", Buffer.from("editor-main-v1\n")],
    ["editor/editor.main.css", Buffer.from(".editor { color: red; }\n")],
    ["assets/editor.worker-test.js", Buffer.from("editor-worker-v1\n")],
    ["assets/css.worker-test.js", Buffer.from("css-worker-v1\n")],
    ["assets/html.worker-test.js", Buffer.from("html-worker-v1\n")],
    ["assets/json.worker-test.js", Buffer.from("json-worker-v1\n")],
    ["assets/ts.worker-test.js", Buffer.from("ts-worker-v1\n")],
    ["assets/font.ttf", Buffer.from([0, 255, 17, 128, 42])],
  ]);
  const entries = [...files.entries()];
  if (writeInReverse) entries.reverse();
  for (const [relative, contents] of entries) {
    const target = path.join(packageRoot, "min", "vs", relative);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, contents);
  }
  writeFileSync(path.join(packageRoot, "LICENSE"), Buffer.from("Monaco license\n\x00\xff"));
  return { packageRoot, files };
}


afterEach(() => {
  for (const fixtureRoot of fixtureRoots.splice(0)) {
    rmSync(fixtureRoot, { recursive: true, force: true });
  }
});


describe("readMonacoDistribution", () => {
  it("snapshots every file byte-for-byte, including binary assets and LICENSE", () => {
    const { packageRoot, files } = makeFixture();
    files.set("LICENSE.txt", Buffer.from("Monaco license\n\x00\xff"));

    const distribution = readMonacoDistribution(packageRoot);

    expect([...distribution.files.keys()].sort()).toEqual([...files.keys()].sort());
    for (const [name, expected] of files) {
      const actual = distribution.files.get(name);
      expect(actual).toBeDefined();
      expect(Buffer.compare(actual!, expected)).toBe(0);
    }
    expect(distribution.workers).toEqual(
      Object.fromEntries(WORKER_KINDS.map(kind => [`${kind}`, `assets/${kind}.worker-test.js`])),
    );
    expect(distribution.directory).toMatch(/^assets\/monaco-[0-9a-f]{64}\/vs$/);
  });

  it("produces the same content-addressed directory for identical bytes", () => {
    const first = makeFixture();
    const second = makeFixture(true);

    expect(readMonacoDistribution(first.packageRoot).directory).toBe(
      readMonacoDistribution(second.packageRoot).directory,
    );
  });

  it("changes the content-addressed directory when a file changes", () => {
    const { packageRoot } = makeFixture();
    const before = readMonacoDistribution(packageRoot).directory;
    writeFileSync(
      path.join(packageRoot, "min", "vs", "assets", "json.worker-test.js"),
      Buffer.from("json-worker-v2\n"),
    );

    expect(readMonacoDistribution(packageRoot).directory).not.toBe(before);
  });

  it.each([
    ["min/vs/loader.js", "loader.js"],
    ["min/vs/editor/editor.main.css", "editor/editor.main.css"],
    ["LICENSE", "LICENSE"],
  ])("rejects a distribution missing %s", (relative, expectedName) => {
    const { packageRoot } = makeFixture();
    rmSync(path.join(packageRoot, relative));

    if (expectedName === "LICENSE") {
      expect(() => readMonacoDistribution(packageRoot)).toThrow();
    } else {
      expect(() => readMonacoDistribution(packageRoot)).toThrow(
        `Missing Monaco distribution file: ${expectedName}`,
      );
    }
  });

  it("rejects a package distribution with a missing worker", () => {
    const { packageRoot } = makeFixture();
    rmSync(path.join(packageRoot, "min", "vs", "assets", "ts.worker-test.js"));

    expect(() => readMonacoDistribution(packageRoot)).toThrow(
      "Expected exactly one local Monaco ts worker asset",
    );
  });
});
