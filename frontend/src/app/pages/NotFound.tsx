import { ArrowLeft, Home } from 'lucide-react';
import { Link, useRouteError } from 'react-router';

export function NotFound() {
  return (
    <main className="flex min-h-full items-center justify-center bg-gray-50 px-6 py-16 text-gray-900 dark:bg-[#121212] dark:text-white">
      <section className="w-full max-w-lg rounded-xl border border-gray-200 bg-white p-8 text-center shadow-sm dark:border-[#333] dark:bg-[#1a1a1a]">
        <p className="text-sm font-semibold text-blue-600 dark:text-blue-400">404</p>
        <h1 className="mt-2 text-2xl font-bold">페이지를 찾을 수 없습니다</h1>
        <p className="mt-3 text-sm leading-6 text-gray-600 dark:text-gray-400">
          주소가 바뀌었거나 더 이상 제공하지 않는 페이지입니다.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <button type="button" onClick={() => window.history.back()} className="inline-flex items-center gap-2 rounded-md border border-gray-200 px-4 py-2 text-sm font-semibold dark:border-[#444]">
            <ArrowLeft size={16} /> 이전 페이지
          </button>
          <Link to="/" className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500">
            <Home size={16} /> 홈으로
          </Link>
        </div>
      </section>
    </main>
  );
}

export function RouteErrorPage() {
  const error = useRouteError();
  const message = error instanceof Error ? error.message : '페이지를 불러오는 중 오류가 발생했습니다.';
  return (
    <main className="flex min-h-screen items-center justify-center bg-gray-50 px-6 py-16 text-gray-900 dark:bg-[#121212] dark:text-white">
      <section className="w-full max-w-lg rounded-xl border border-red-500/30 bg-white p-8 text-center dark:bg-[#1a1a1a]">
        <p className="text-sm font-semibold text-red-600 dark:text-red-400">오류</p>
        <h1 className="mt-2 text-2xl font-bold">페이지를 표시하지 못했습니다</h1>
        <p className="mt-3 break-words text-sm leading-6 text-gray-600 dark:text-gray-400">{message}</p>
        <Link to="/" className="mt-6 inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500">
          <Home size={16} /> 홈으로
        </Link>
      </section>
    </main>
  );
}
