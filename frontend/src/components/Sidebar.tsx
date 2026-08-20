import { useState } from "react";
import { BarChart2, BookHeart, BookOpen, LineChart, PanelLeftClose, PanelLeftOpen, Wind } from "lucide-react";
import { AppPage, useNavigationStore } from "../store/navigationStore";

interface NavItem {
  page: AppPage;
  icon: React.ReactNode;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { page: "chart", icon: <LineChart size={18} />, label: "Chart" },
  { page: "dashboard", icon: <BarChart2 size={18} />, label: "Dashboard" },
  { page: "journal", icon: <BookOpen size={18} />, label: "Journal" },
  { page: "weekly-journal", icon: <BookHeart size={18} />, label: "Weekly Journal" },
  { page: "calm", icon: <Wind size={18} />, label: "Calm" },
];

export function Sidebar({ reviewLocked = false }: { reviewLocked?: boolean }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const activePage = useNavigationStore((s) => s.activePage);
  const setPage = useNavigationStore((s) => s.setPage);
  const reflectionPage = activePage === "calm" || activePage === "weekly-journal";
  const displayedActivePage = reviewLocked && !reflectionPage ? "journal" : activePage;

  return (
    <>
      {!mobileOpen ? (
        <button
          aria-label="Mở menu điều hướng"
          className={`fixed left-3 z-[60] grid h-10 w-10 place-items-center rounded-xl border border-blue-400/35 bg-ink-900/95 text-blue-300 shadow-[0_8px_30px_rgba(0,0,0,0.45)] backdrop-blur transition hover:border-cyan-300/50 hover:text-cyan-200 md:hidden ${
            activePage === "chart"
              ? "bottom-[calc(4.5rem+env(safe-area-inset-bottom))]"
              : "bottom-[max(1rem,env(safe-area-inset-bottom))]"
          }`}
          title="Mở menu"
          type="button"
          onClick={() => setMobileOpen(true)}
        >
          <PanelLeftOpen size={19} />
        </button>
      ) : null}

      <aside
        className={[
          "absolute inset-y-0 left-0 z-[70] flex h-full w-16 flex-col items-center border-r border-ink-700 bg-ink-900/95 pt-3 shadow-2xl shadow-black/35 backdrop-blur transition-transform duration-200",
          activePage === "chart"
            ? "pb-[calc(4.75rem+env(safe-area-inset-bottom))]"
            : "pb-[max(1rem,env(safe-area-inset-bottom))]",
          mobileOpen ? "translate-x-0" : "-translate-x-full",
          "md:static md:z-auto md:w-12 md:translate-x-0 md:bg-ink-900 md:py-3 md:shadow-none md:backdrop-blur-none",
        ].join(" ")}
      >
        {/* Logo mark */}
        <div className="mb-4 flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-xs font-bold text-white">
          B
        </div>

        <nav className="flex flex-1 flex-col items-center gap-1">
          {NAV_ITEMS.map(({ page, icon, label }) => {
            const isActive = displayedActivePage === page;
            const disabled = reviewLocked && page !== "journal" && page !== "weekly-journal" && page !== "calm";
            return (
              <button
                key={page}
                aria-label={label}
                title={disabled ? "Weekly review required" : label}
                disabled={disabled}
                onClick={() => {
                  if (!disabled) {
                    setPage(page);
                    setMobileOpen(false);
                  }
                }}
                className={[
                  "group relative flex h-9 w-9 items-center justify-center rounded-md transition-colors",
                  disabled ? "cursor-not-allowed opacity-35" : "",
                  isActive
                    ? "bg-blue-600/20 text-blue-400"
                    : "text-slate-500 hover:bg-ink-700 hover:text-slate-300",
                ].join(" ")}
              >
                {icon}
                {/* Tooltip */}
                <span className="pointer-events-none absolute left-full ml-2 whitespace-nowrap rounded bg-ink-700 px-2 py-1 text-xs text-slate-200 opacity-0 shadow-lg transition-opacity group-hover:opacity-100">
                  {label}
                </span>
              </button>
            );
          })}
        </nav>

        <button
          aria-label="Đóng menu điều hướng"
          className="grid h-12 w-12 flex-shrink-0 place-items-center rounded-xl border border-blue-400/35 bg-ink-800 text-blue-300 shadow-[0_8px_24px_rgba(0,0,0,0.4)] transition hover:border-cyan-300/50 hover:bg-ink-700 hover:text-cyan-200 md:hidden"
          title="Đóng menu"
          type="button"
          onClick={() => setMobileOpen(false)}
        >
          <PanelLeftClose size={24} />
        </button>
      </aside>
    </>
  );
}
