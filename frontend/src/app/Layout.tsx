import { Link, Outlet } from "react-router";
import { Header } from "./components/Header";

export function Layout() {
  return (
    <div className="flex flex-col h-screen w-screen bg-gray-50 dark:bg-[#0d0d0d] text-gray-900 dark:text-gray-100 overflow-hidden font-sans transition-colors duration-200">
      <Header />
      <main className="flex-1 flex overflow-hidden relative">
        <Outlet />
      </main>
      <footer className="flex shrink-0 items-center justify-end border-t border-gray-200 bg-white px-4 py-1.5 text-xs dark:border-[#333] dark:bg-[#1e1e1e]">
        <nav aria-label="도움말"><Link to="/help/judging" className="text-gray-500 hover:text-blue-600 hover:underline focus-visible:outline-2 focus-visible:outline-blue-500 dark:text-gray-400 dark:hover:text-blue-400">도움말·FAQ</Link></nav>
      </footer>
    </div>
  );
}
