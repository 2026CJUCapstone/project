import { lazy, Suspense, type ComponentType } from "react";

function RouteLoading() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex min-h-48 items-center justify-center px-4 text-sm text-gray-500 dark:text-gray-400"
    >
      페이지를 불러오는 중...
    </div>
  );
}

export function lazyRoute<Module extends Record<string, unknown>, Key extends keyof Module>(
  load: () => Promise<Module>,
  exportName: Key,
) {
  const Page = lazy(async () => ({
    default: (await load())[exportName] as ComponentType,
  }));

  return function LazyRoute() {
    return (
      <Suspense fallback={<RouteLoading />}>
        <Page />
      </Suspense>
    );
  };
}
