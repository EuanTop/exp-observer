import { describe, expect, it } from "vitest";
import { metricLeaves, metricPathLabel } from "./metrics";
import { formatMetric, type Metrics } from "./model";

describe("nested metric display", () => {
  it("preserves arrays, null, empty containers and the original object", () => {
    const metrics: Metrics = {
      benchmark: { scores: [0, null, { accuracy: 0.95 }], tags: [] },
      unset: null,
      empty: {},
    };
    const before = JSON.stringify(metrics);
    const rows = metricLeaves(metrics);
    expect(rows.map(({ path, value }) => [path, value])).toEqual([
      [["benchmark", "scores", 0], 0],
      [["benchmark", "scores", 1], null],
      [["benchmark", "scores", 2, "accuracy"], 0.95],
      [["benchmark", "tags"], []],
      [["unset"], null],
      [["empty"], {}],
    ]);
    expect(JSON.stringify(metrics)).toBe(before);
    expect(formatMetric(null)).toBe("null");
    expect(formatMetric(undefined)).toBe("—");
    expect(formatMetric([1, null])).toBe("[1,null]");
  });

  it("keeps dotted keys and object numeric keys distinct from paths and array indices", () => {
    const rows = metricLeaves({
      "a.b": 1,
      a: { b: 2 },
      "x[0]": 3,
      x: [4],
      numeric: { "0": 5 },
    });
    expect(new Set(rows.map((row) => row.key)).size).toBe(rows.length);
    expect(rows.map((row) => metricPathLabel(row.path))).toEqual([
      '$["a.b"]',
      "$.a.b",
      '$["x[0]"]',
      "$.x[0]",
      '$.numeric["0"]',
    ]);
    expect(metricLeaves({ x: { "0": 4 } })[0].key).not.toBe(
      metricLeaves({ x: [4] })[0].key,
    );
  });

  it("retains type changes as distinct comparison rows and does not round tiny measured values to zero", () => {
    const paths = [
      ...metricLeaves({ score: null }),
      ...metricLeaves({ score: [1, 2] }),
    ];
    expect(new Set(paths.map((row) => row.key)).size).toBe(3);
    expect(formatMetric(0.00000012)).not.toBe("0");
  });
});
