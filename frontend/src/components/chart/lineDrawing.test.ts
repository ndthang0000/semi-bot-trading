import { expect, it } from "vitest";
import { lineDraftFromPoints } from "./lineDrawing";
it("leftward second click keeps first click price and normalizes visual times", () => {
  expect(lineDraftFromPoints({x:300,price:3000,time:"2026-09-06T12:00:00Z"},
    {x:100,time:"2026-09-06T10:00:00Z"},"short")).toMatchObject({
      price:3000,direction:"short",visual_start:"2026-09-06T10:00:00Z",visual_end:"2026-09-06T12:00:00Z",
    });
});
it("ignores accidental double click with no span", () => {
  expect(lineDraftFromPoints({x:300,price:3000,time:"2026-09-06T12:00:00Z"},
    {x:301,time:"2026-09-06T12:00:00Z"},"long")).toBeNull();
});
