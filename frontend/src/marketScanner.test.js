import { describe, expect, it } from "vitest";

import {
  opportunityAgeLabel,
  scannerProgress,
  scannerStatusTone
} from "./marketScanner";

describe("scannerProgress", () => {
  it("uses deep-scanned over prefiltered symbols", () => {
    expect(scannerProgress({
      symbols_prefiltered: 200,
      symbols_deep_scanned: 50
    })).toBe(25);
  });

  it("returns zero when no symbols survived prefilter", () => {
    expect(scannerProgress({
      symbols_prefiltered: 0,
      symbols_deep_scanned: 0
    })).toBe(0);
  });

  it("caps progress at one hundred percent", () => {
    expect(scannerProgress({
      symbols_prefiltered: 10,
      symbols_deep_scanned: 12
    })).toBe(100);
  });
});

describe("scannerStatusTone", () => {
  it("maps partial to amber and failed to red", () => {
    expect(scannerStatusTone("partial")).toBe("amber");
    expect(scannerStatusTone("failed")).toBe("red");
  });

  it("maps complete to green and active states to blue", () => {
    expect(scannerStatusTone("complete")).toBe("green");
    expect(scannerStatusTone("deep_scanning")).toBe("blue");
    expect(scannerStatusTone("discovering")).toBe("blue");
  });
});

describe("opportunityAgeLabel", () => {
  it("reports fresh minute-scale ages", () => {
    const now = new Date("2026-09-19T16:10:00Z");
    expect(
      opportunityAgeLabel("2026-09-19T16:05:00Z", now)
    ).toBe("5m");
  });

  it("returns unavailable for invalid timestamps", () => {
    expect(opportunityAgeLabel("not-a-date")).toBe("—");
  });
});
