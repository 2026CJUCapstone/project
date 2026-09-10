import { describe, expect, it } from "vitest";

import { resolveMonacoWorkerAssets } from "./monacoWorkerAssets";


const WORKER_KINDS = ["editor", "css", "html", "json", "ts"] as const;
const ASSET_ROOT = "/node_modules/monaco-editor/min/vs/assets";
const URL_ROOT = "/webcompiler/assets";


function assetPath(kind: string) {
  return `${ASSET_ROOT}/${kind}.worker-test-hash.js`;
}


function assetUrl(kind: string) {
  return `${URL_ROOT}/${kind}.worker-test-hash.js`;
}


function validAssets(): Record<string, string> {
  return Object.fromEntries(WORKER_KINDS.map(kind => [assetPath(kind), assetUrl(kind)]));
}


describe("resolveMonacoWorkerAssets", () => {
  it("returns all five worker URLs unchanged under the application asset subpath", () => {
    expect(resolveMonacoWorkerAssets(validAssets())).toEqual(
      Object.fromEntries(WORKER_KINDS.map(kind => [kind, assetUrl(kind)])),
    );
  });

  it.each(WORKER_KINDS)("rejects when the %s worker is missing", kind => {
    const assets = validAssets();
    delete assets[assetPath(kind)];

    expect(() => resolveMonacoWorkerAssets(assets)).toThrow(
      `Expected exactly one local Monaco ${kind} worker asset`,
    );
  });

  it("rejects duplicate assets for the same worker kind", () => {
    const assets = validAssets();
    assets[`${ASSET_ROOT}/editor.worker-another-hash.js`] = `${URL_ROOT}/editor.worker-another-hash.js`;

    expect(() => resolveMonacoWorkerAssets(assets)).toThrow(
      "Expected exactly one local Monaco editor worker asset",
    );
  });

  it("rejects an empty URL for an otherwise valid worker asset", () => {
    const assets = validAssets();
    assets[assetPath("json")] = "";

    expect(() => resolveMonacoWorkerAssets(assets)).toThrow(
      "Expected exactly one local Monaco json worker asset",
    );
  });

  it("ignores unrelated files while resolving the five worker assets", () => {
    const assets = {
      ...validAssets(),
      [`${ASSET_ROOT}/editor.worker-test-hash.js.map`]: `${URL_ROOT}/editor.worker-test-hash.js.map`,
      [`${ASSET_ROOT}/typescript.worker-test-hash.js`]: `${URL_ROOT}/typescript.worker-test-hash.js`,
      [`${ASSET_ROOT}/worker.js`]: `${URL_ROOT}/worker.js`,
    };

    expect(resolveMonacoWorkerAssets(assets)).toEqual(
      Object.fromEntries(WORKER_KINDS.map(kind => [kind, assetUrl(kind)])),
    );
  });
});
