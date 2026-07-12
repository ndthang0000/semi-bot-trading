import { BarChart2, BookOpen, LineChart } from "lucide-react";
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
];

export function Sidebar({ reviewLocked = false }: { reviewLocked?: boolean }) {
  const activePage = useNavigationStore((s) => s.activePage);
  const setPage = useNavigationStore((s) => s.setPage);
  const displayedActivePage = reviewLocked ? "journal" : activePage;

  return (
    <aside className="flex h-full w-12 flex-col items-center border-r border-ink-700 bg-ink-900 py-3">
      {/* Logo mark */}
      <div className="mb-4 flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-xs font-bold text-white">
        B
      </div>

      <nav className="flex flex-1 flex-col items-center gap-1">
        {NAV_ITEMS.map(({ page, icon, label }) => {
          const isActive = displayedActivePage === page;
          const disabled = reviewLocked && page !== "journal";
          return (
            <button
              key={page}
              title={disabled ? "Weekly review required" : label}
              disabled={disabled}
              onClick={() => {
                if (!disabled) setPage(page);
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
    </aside>
  );
}
