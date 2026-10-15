import { describe, expect, test } from "vitest";
import type { BackendStats, NodeStats } from "../api/types";
import { statsReport } from "../test/fakeApi";
import {
  agreementText,
  comparedLine,
  costLabel,
  offsetText,
  pct,
  shadowOf,
  primaryOf,
  sinceToIso,
  timeoutRate,
  wilson,
} from "./summary";

const understand = statsReport.nodes.find(
  (n) => n.node === "understand",
) as NodeStats;
const nimble = understand.backends.find(
  (b) => b.backend === "nimble",
) as BackendStats;
const jev = understand.backends.find(
  (b) => b.backend === "jev",
) as BackendStats;

describe("wilson", () => {
  test("a small sample gives a wide interval, a large one a narrow one", () => {
    const [lo, hi] = wilson(16, 18);
    expect(lo).toBeCloseTo(0.672, 2);
    expect(hi).toBeCloseTo(0.969, 2);
    const [lo2, hi2] = wilson(118, 165);
    expect(hi2 - lo2).toBeLessThan(hi - lo);
  });

  test("no samples has no interval, and a perfect score still has a lower bound below one", () => {
    expect(wilson(0, 0)).toEqual([0, 1]);
    expect(wilson(18, 18)[0]).toBeLessThan(1);
    expect(wilson(18, 18)[1]).toBeCloseTo(1, 5);
  });
});

describe("text helpers", () => {
  test("the compared line gives both denominators and what was left out", () => {
    expect(comparedLine(understand)).toBe(
      "165 of 228 decisions compared · 63 nimble errors · 0 fallbacks",
    );
  });

  test("a clean node says so", () => {
    const clean = statsReport.nodes.find(
      (n) => n.node === "post_check",
    ) as NodeStats;
    expect(comparedLine(clean)).toBe(
      "68 of 68 decisions compared · 0 nimble errors · 0 fallbacks",
    );
  });

  test("the primary and the shadow come from the roles, not from names", () => {
    expect(primaryOf(understand)?.backend).toBe("jev");
    expect(shadowOf(understand)?.backend).toBe("nimble");
    const swapped: NodeStats = {
      ...understand,
      backends: understand.backends.map((b) => ({
        ...b,
        role: b.role === "primary" ? "shadow" : "primary",
      })),
    };
    expect(primaryOf(swapped)?.backend).toBe("nimble");
  });

  test("a node nobody shadowed has no shadow to compare against", () => {
    const solo: NodeStats = {
      ...understand,
      backends: [{ ...jev }],
      compared: 0,
    };
    expect(shadowOf(solo)).toBeUndefined();
  });

  test("the timeout rate is errors over calls", () => {
    expect(timeoutRate(nimble)).toBeCloseTo(63 / 228, 4);
    expect(timeoutRate(jev)).toBe(0);
  });

  test("agreement is shown as a count with its sample, not a bare rate", () => {
    expect(agreementText(0.7152, 165)).toBe("118/165 (72%)");
    expect(agreementText(1, 18)).toBe("18/18 (100%)");
    expect(agreementText(0, 0)).toBe("no decisions");
  });

  test("a percentage rounds to a whole number", () => {
    expect(pct(0.7152)).toBe("72%");
  });

  test("the score offset says which way the shadow reads", () => {
    expect(offsetText(0.3785)).toBe("+0.38 (shadow scores higher)");
    expect(offsetText(-0.5)).toBe("-0.50 (shadow scores lower)");
    expect(offsetText(0)).toBe("0.00 (no offset)");
  });

  test("cost is honest about what it does not know", () => {
    expect(costLabel({ ...nimble, est_cost_usd: 0 })).toBe("local, $0");
    expect(costLabel({ ...jev, est_cost_usd: 0 })).toBe(
      "price not set (JEV_USD_PER_MTOK_IN/OUT)",
    );
    expect(costLabel({ ...jev, est_cost_usd: 0.1234 })).toBe("$0.123");
  });
});

describe("sinceToIso", () => {
  test("a blank date sends nothing", () => {
    expect(sinceToIso("")).toBeUndefined();
  });

  test("a date means local midnight, converted to UTC", () => {
    expect(sinceToIso("2026-10-15")).toBe(new Date(2026, 9, 15).toISOString());
  });

  test("garbage sends nothing", () => {
    expect(sinceToIso("not a date")).toBeUndefined();
  });
});
