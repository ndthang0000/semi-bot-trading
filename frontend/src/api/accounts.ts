import { authFetch } from "./auth";

type AccountsResponse = {
  accounts: Array<{ label: string }>;
};

export async function fetchAccountLabels(): Promise<string[]> {
  const response = await authFetch("/api/accounts");
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail ?? `Accounts API failed with ${response.status}`);
  }
  const payload = await response.json() as AccountsResponse;
  return Array.from(
    new Set(payload.accounts.map((account) => account.label.trim()).filter(Boolean)),
  ).sort((left, right) => left.localeCompare(right));
}
