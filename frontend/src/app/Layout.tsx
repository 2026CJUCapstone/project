import { Outlet } from "react-router";
import { Header } from "./components/Header";

export function Layout() {
  return (
    <div className="flex flex-col h-screen w-screen bg-gray-50 dark:bg-[#0d0d0d] text-gray-900 dark:text-gray-100 overflow-hidden font-sans transition-colors duration-200">
      <Header />
      <main className="flex-1 flex overflow-hidden relative">
        <Outlet />
      </main>
    </div>
  );
}
