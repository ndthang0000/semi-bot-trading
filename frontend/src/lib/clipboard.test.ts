// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";
import { copyTextToClipboard } from "./clipboard";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("copyTextToClipboard", () => {
  it("uses the Clipboard API in a secure context", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });

    await copyTextToClipboard("4383.58");

    expect(writeText).toHaveBeenCalledWith("4383.58");
  });

  it("falls back to execCommand for an HTTP deployment", async () => {
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: false });
    Object.defineProperty(document, "execCommand", { configurable: true, value: execCommand });

    await copyTextToClipboard("4375.03");

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(document.querySelector("textarea")).toBeNull();
  });

  it("falls back when Clipboard API permission is denied", async () => {
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(window, "isSecureContext", { configurable: true, value: true });
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    Object.defineProperty(document, "execCommand", { configurable: true, value: execCommand });

    await copyTextToClipboard("4360.25");

    expect(execCommand).toHaveBeenCalledWith("copy");
  });
});
