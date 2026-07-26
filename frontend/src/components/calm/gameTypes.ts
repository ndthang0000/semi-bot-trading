export type CalmGameId = "rhythm" | "maze" | "pixel";

export type CalmGameProps = {
  onComplete: () => void;
};

export const CALM_GAMES: Array<{ id: CalmGameId; label: string; duration: string }> = [
  { id: "rhythm", label: "Rhythm Reset", duration: "48 giây" },
  { id: "maze", label: "Mindful Maze", duration: "30–60 giây" },
  { id: "pixel", label: "Pixel Calm", duration: "30–60 giây" },
];

export function randomCalmGame(exclude?: CalmGameId): CalmGameId {
  const choices = CALM_GAMES.map((game) => game.id).filter((id) => id !== exclude);
  return choices[Math.floor(Math.random() * choices.length)] ?? "rhythm";
}
