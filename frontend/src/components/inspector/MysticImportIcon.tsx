import { DatabaseZap, Sparkles } from "lucide-react";

export function MysticImportIcon({ size = 18 }: { size?: number }) {
  return (
    <span className="relative inline-grid shrink-0 place-items-center" style={{ height: size + 4, width: size + 5 }}>
      <DatabaseZap className="drop-shadow-[0_0_7px_rgba(56,189,248,0.8)]" size={size} strokeWidth={1.8} />
      <Sparkles
        className="absolute -right-0.5 -top-0.5 text-cyan-200 drop-shadow-[0_0_6px_rgba(103,232,249,0.95)]"
        size={Math.max(8, Math.round(size * 0.48))}
        strokeWidth={2.2}
      />
    </span>
  );
}
