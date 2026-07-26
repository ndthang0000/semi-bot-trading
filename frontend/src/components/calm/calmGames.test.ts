import { describe, expect, it } from "vitest";
import { generateMaze, type MazeDirection } from "./MindfulMazeGame";
import { CALM_GAMES, randomCalmGame } from "./gameTypes";

describe("Calm game selection", () => {
  it("contains the three intended games", () => {
    expect(CALM_GAMES.map((game) => game.id)).toEqual(["rhythm", "maze", "pixel"]);
  });

  it("does not select the excluded game", () => {
    for (let index = 0; index < 20; index += 1) {
      expect(randomCalmGame("maze")).not.toBe("maze");
    }
  });
});

describe("Mindful Maze", () => {
  it("generates a connected maze with a reachable goal", () => {
    const maze = generateMaze(8);
    const visited = new Set(["0:0"]);
    const queue = [{ row: 0, col: 0 }];
    const moves: Record<MazeDirection, { row: number; col: number }> = {
      up: { row: -1, col: 0 },
      right: { row: 0, col: 1 },
      down: { row: 1, col: 0 },
      left: { row: 0, col: -1 },
    };

    while (queue.length > 0) {
      const current = queue.shift()!;
      const cell = maze[current.row][current.col];
      for (const direction of Object.keys(moves) as MazeDirection[]) {
        if (cell.walls[direction]) continue;
        const next = {
          row: current.row + moves[direction].row,
          col: current.col + moves[direction].col,
        };
        const key = `${next.row}:${next.col}`;
        if (visited.has(key)) continue;
        visited.add(key);
        queue.push(next);
      }
    }

    expect(visited.size).toBe(64);
    expect(visited.has("7:7")).toBe(true);
  });
});
