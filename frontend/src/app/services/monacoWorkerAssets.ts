const workerKinds = ["editor", "css", "html", "json", "ts"] as const;
type WorkerKind = typeof workerKinds[number];

/** Fail early if a package update changes the prebuilt-worker layout. */
export function resolveMonacoWorkerAssets(assets: Record<string, string>): Record<WorkerKind, string> {
  return Object.fromEntries(workerKinds.map(kind => {
    const matches = Object.entries(assets).filter(([name]) =>
      new RegExp(`/${kind}\\.worker-[^/]+\\.js$`).test(name));
    if (matches.length !== 1 || !matches[0][1]) {
      throw new Error(`Expected exactly one local Monaco ${kind} worker asset`);
    }
    return [kind, matches[0][1]];
  })) as Record<WorkerKind, string>;
}
