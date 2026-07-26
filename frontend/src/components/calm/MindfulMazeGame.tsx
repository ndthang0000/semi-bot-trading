import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Sparkles } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { CalmGameProps } from "./gameTypes";

const SIZE = 8;
const CELL = 46;

export type MazeDirection = "up" | "right" | "down" | "left";
export type MazeCell = { row: number; col: number; walls: Record<MazeDirection, boolean> };
type Position = { row: number; col: number };

const MOVES: Record<MazeDirection, { row: number; col: number; opposite: MazeDirection }> = {
  up: { row: -1, col: 0, opposite: "down" },
  right: { row: 0, col: 1, opposite: "left" },
  down: { row: 1, col: 0, opposite: "up" },
  left: { row: 0, col: -1, opposite: "right" },
};

export function MindfulMazeGame({ onComplete }: CalmGameProps) {
  const maze = useMemo(() => generateMaze(SIZE), []);
  const [position, setPosition] = useState<Position>({ row: 0, col: 0 });
  const [trail, setTrail] = useState<Position[]>([{ row: 0, col: 0 }]);
  const completedRef = useRef(false);

  const move = (direction: MazeDirection) => {
    const cell = maze[position.row][position.col];
    if (cell.walls[direction]) return;
    const delta = MOVES[direction];
    const next = { row: position.row + delta.row, col: position.col + delta.col };
    setPosition(next);
    setTrail((current) => [...current, next]);
  };

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const direction = {
        ArrowUp: "up",
        ArrowRight: "right",
        ArrowDown: "down",
        ArrowLeft: "left",
      }[event.key] as MazeDirection | undefined;
      if (!direction) return;
      event.preventDefault();
      move(direction);
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  });

  useEffect(() => {
    if (
      completedRef.current
      || position.row !== SIZE - 1
      || position.col !== SIZE - 1
    ) return;
    completedRef.current = true;
    const timer = window.setTimeout(onComplete, 450);
    return () => window.clearTimeout(timer);
  }, [onComplete, position]);

  const trailPoints = trail
    .map(({ row, col }) => `${col * CELL + CELL / 2},${row * CELL + CELL / 2}`)
    .join(" ");

  return (
    <div className="flex h-full min-h-[500px] flex-col items-center justify-center">
      <div className="mb-4 text-center">
        <div className="text-xs font-bold uppercase tracking-[0.22em] text-violet-300">Tìm đường thật chậm</div>
        <div className="mt-1 text-xs text-slate-600">Dùng phím mũi tên hoặc các nút bên dưới · không có tính điểm</div>
      </div>

      <svg
        viewBox={`0 0 ${SIZE * CELL} ${SIZE * CELL}`}
        className="h-[368px] w-[368px] rounded-xl bg-ink-950 shadow-[0_0_60px_rgba(167,139,250,0.10)]"
        aria-label="Mindful maze"
      >
        <polyline
          points={trailPoints}
          fill="none"
          stroke="rgba(34,211,238,0.22)"
          strokeWidth="6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        {maze.flat().map((cell) => (
          <g key={`${cell.row}-${cell.col}`} stroke="rgba(148,163,184,0.45)" strokeWidth="2">
            {cell.walls.up ? <line x1={cell.col * CELL} y1={cell.row * CELL} x2={(cell.col + 1) * CELL} y2={cell.row * CELL} /> : null}
            {cell.walls.right ? <line x1={(cell.col + 1) * CELL} y1={cell.row * CELL} x2={(cell.col + 1) * CELL} y2={(cell.row + 1) * CELL} /> : null}
            {cell.walls.down ? <line x1={cell.col * CELL} y1={(cell.row + 1) * CELL} x2={(cell.col + 1) * CELL} y2={(cell.row + 1) * CELL} /> : null}
            {cell.walls.left ? <line x1={cell.col * CELL} y1={cell.row * CELL} x2={cell.col * CELL} y2={(cell.row + 1) * CELL} /> : null}
          </g>
        ))}
        <circle
          cx={(SIZE - 1) * CELL + CELL / 2}
          cy={(SIZE - 1) * CELL + CELL / 2}
          r="11"
          fill="rgba(167,139,250,0.22)"
          stroke="rgb(196,181,253)"
          strokeWidth="2"
        />
        <circle
          cx={position.col * CELL + CELL / 2}
          cy={position.row * CELL + CELL / 2}
          r="9"
          fill="rgb(34,211,238)"
        />
      </svg>

      <div className="mt-4 grid grid-cols-3 gap-1.5">
        <span />
        <MoveButton label="Lên" onClick={() => move("up")}><ArrowUp size={16} /></MoveButton>
        <span />
        <MoveButton label="Trái" onClick={() => move("left")}><ArrowLeft size={16} /></MoveButton>
        <div className="grid h-9 w-9 place-items-center text-violet-300"><Sparkles size={15} /></div>
        <MoveButton label="Phải" onClick={() => move("right")}><ArrowRight size={16} /></MoveButton>
        <span />
        <MoveButton label="Xuống" onClick={() => move("down")}><ArrowDown size={16} /></MoveButton>
        <span />
      </div>
    </div>
  );
}

function MoveButton({ label, onClick, children }: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="grid h-9 w-9 place-items-center rounded-lg border border-ink-700 bg-ink-950 text-slate-400 hover:border-violet-400/40 hover:text-violet-200"
    >
      {children}
    </button>
  );
}

export function generateMaze(size: number): MazeCell[][] {
  const cells = Array.from({ length: size }, (_, row) =>
    Array.from({ length: size }, (_, col) => ({
      row,
      col,
      walls: { up: true, right: true, down: true, left: true },
    })),
  );
  const visited = new Set(["0:0"]);
  const stack: Position[] = [{ row: 0, col: 0 }];

  while (stack.length > 0) {
    const current = stack[stack.length - 1];
    const options = (Object.keys(MOVES) as MazeDirection[])
      .map((direction) => ({
        direction,
        row: current.row + MOVES[direction].row,
        col: current.col + MOVES[direction].col,
      }))
      .filter(({ row, col }) => (
        row >= 0
        && row < size
        && col >= 0
        && col < size
        && !visited.has(`${row}:${col}`)
      ));
    if (options.length === 0) {
      stack.pop();
      continue;
    }
    const next = options[Math.floor(Math.random() * options.length)];
    const opposite = MOVES[next.direction].opposite;
    cells[current.row][current.col].walls[next.direction] = false;
    cells[next.row][next.col].walls[opposite] = false;
    visited.add(`${next.row}:${next.col}`);
    stack.push({ row: next.row, col: next.col });
  }
  return cells;
}
