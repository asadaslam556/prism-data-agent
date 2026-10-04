import { describe, expect, it } from "vitest";
import { analyse, looksLikeKpis } from "./DataChart.jsx";

const result = (columns, rows) => ({ columns, rows });

describe("looksLikeKpis", () => {
  it("accepts one row of a few columns with a number in it", () => {
    expect(looksLikeKpis(result(["orders", "revenue"], [{ orders: 1400, revenue: 2.3e6 }]))).toBe(true);
  });

  it("rejects more than one row, a lone column, and a row of pure text", () => {
    expect(looksLikeKpis(result(["a", "b"], [{ a: 1, b: 2 }, { a: 3, b: 4 }]))).toBe(false);
    expect(looksLikeKpis(result(["a"], [{ a: 1 }]))).toBe(false);
    expect(looksLikeKpis(result(["name", "city"], [{ name: "Ana", city: "Lima" }]))).toBe(false);
  });
});

describe("analyse", () => {
  const regions = result(
    ["region", "revenue"],
    [
      { region: "Europe", revenue: 10 },
      { region: "Asia", revenue: 20 },
    ]
  );

  it("draws short categories as vertical bars", () => {
    expect(analyse(regions, null).kind).toBe("bar");
  });

  it("turns bars horizontal when a label is long", () => {
    const long = result(["country", "revenue"], [
      { country: "United Kingdom of Great Britain", revenue: 1 },
      { country: "France", revenue: 2 },
    ]);
    expect(analyse(long, "ax.bar(x, y)").kind).toBe("hbar");
  });

  it("draws dates as a line when nothing was declared", () => {
    const months = result(["month", "revenue"], [
      { month: "2025-01", revenue: 1 },
      { month: "2025-02", revenue: 2 },
    ]);
    expect(analyse(months, null).kind).toBe("line");
  });

  it("keeps the model's bars for dates instead of forcing a line", () => {
    const months = result(["month", "revenue"], [
      { month: "2025-01", revenue: 1 },
      { month: "2025-02", revenue: 2 },
    ]);
    expect(analyse(months, "plt.bar(m, r)").kind).toBe("bar");
  });

  it("falls back to the model's picture for shapes it can't redraw", () => {
    expect(analyse(regions, "plt.pie(values)")).toEqual({ asDrawn: true });
  });

  it("caps the chart at 40 points and says so", () => {
    const rows = Array.from({ length: 50 }, (_, i) => ({ label: `p${i}`, value: i }));
    const chart = analyse(result(["label", "value"], rows), null);
    expect(chart.points).toHaveLength(40);
    expect(chart.truncated).toBe(true);
  });
});
