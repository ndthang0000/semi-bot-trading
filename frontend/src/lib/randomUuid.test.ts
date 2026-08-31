import { describe, expect, it, vi } from "vitest";
import { createRandomUuid } from "./randomUuid";

describe("createRandomUuid", () => {
  it("uses the native implementation when available", () => {
    const randomUUID = vi.fn(() => "12345678-1234-4123-8123-123456789abc" as `${string}-${string}-${string}-${string}-${string}`);
    const source = {
      getRandomValues: vi.fn(),
      randomUUID,
    } as unknown as Crypto;

    expect(createRandomUuid(source)).toBe("12345678-1234-4123-8123-123456789abc");
    expect(randomUUID).toHaveBeenCalledOnce();
    expect(source.getRandomValues).not.toHaveBeenCalled();
  });

  it("creates a v4 UUID with getRandomValues when randomUUID is unavailable", () => {
    const source = {
      getRandomValues: vi.fn((bytes: Uint8Array) => {
        bytes.fill(0);
        return bytes;
      }),
    } as unknown as Crypto;

    expect(createRandomUuid(source)).toBe("00000000-0000-4000-8000-000000000000");
    expect(source.getRandomValues).toHaveBeenCalledOnce();
  });
});
