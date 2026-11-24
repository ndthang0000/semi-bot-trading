export const DEFAULT_LIMIT_EXPIRY_MINUTES = 8 * 60;

export function quickOrderAccountLabels(labels: string[]): string[] {
  return labels.filter((label) => !label.toLocaleLowerCase().includes("ftmo"));
}
