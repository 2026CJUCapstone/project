import { Outlet } from "react-router";
import { Header } from "./components/Header";

export function Layout() {
  return (
    <div className="flex flex-col h-screen w-screen bg-[#0d0d0d] text-gray-100 overflow-hidden font-sans">
      <Header />
      <main className="flex-1 flex overflow-hidden relative">
        <Outlet />
      </main>
    </div>
  );
}
