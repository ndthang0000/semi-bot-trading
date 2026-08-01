// @vitest-environment jsdom

import { act, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RichTextEditor } from "./RichTextEditor";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("RichTextEditor", () => {
  let root: ReturnType<typeof createRoot> | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    root = null;
    container = null;
  });

  it("does not call a destroyed Tiptap instance during StrictMode remounts", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const onChange = vi.fn();

    await act(async () => {
      root?.render(
        <StrictMode>
          <RichTextEditor value="<p>Tuần cũ vẫn an toàn.</p>" onChange={onChange} />
        </StrictMode>,
      );
    });

    await act(async () => {
      root?.render(
        <StrictMode>
          <RichTextEditor value="<p>Tuần khác.</p>" onChange={onChange} />
        </StrictMode>,
      );
    });

    expect(container.querySelector(".ProseMirror")).not.toBeNull();
    expect(container.textContent).toContain("Tuần khác.");
  });

  it("renders an embedded journal image after content is loaded", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const source = "data:image/webp;base64,UklGRg==";

    await act(async () => {
      root?.render(<RichTextEditor value={`<p>Kế hoạch</p><img src="${source}" alt="chart.webp">`} onChange={() => undefined} />);
    });

    const image = container.querySelector<HTMLImageElement>(".ProseMirror img");
    expect(image?.getAttribute("src")).toBe(source);
    expect(image?.getAttribute("alt")).toBe("chart.webp");
  });
});
