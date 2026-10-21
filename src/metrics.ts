import { metricLabel, type JsonValue, type Metrics } from "./model";

export type MetricLeaf = {
  key: string;
  path: (string | number)[];
  value: JsonValue;
};

// These are display rows, never a replacement for the original metric object.
export function metricLeaves(metrics: Metrics): MetricLeaf[] {
  const leaves: MetricLeaf[] = [];
  const visit = (value: JsonValue, path: (string | number)[]) => {
    if (Array.isArray(value) && value.length) {
      value.forEach((item, index) => visit(item, [...path, index]));
    } else if (
      value !== null &&
      !Array.isArray(value) &&
      typeof value === "object" &&
      Object.keys(value).length
    ) {
      Object.entries(value).forEach(([key, item]) =>
        visit(item, [...path, key]),
      );
    } else {
      leaves.push({ key: JSON.stringify(path), path, value });
    }
  };
  Object.entries(metrics).forEach(([key, value]) => visit(value, [key]));
  return leaves;
}

export function metricPathLabel(path: (string | number)[]): string {
  if (
    path.length === 1 &&
    typeof path[0] === "string" &&
    /^[A-Za-z_][A-Za-z0-9_]*$/.test(path[0])
  ) {
    return metricLabel(path[0]);
  }
  return (
    "$" +
    path
      .map((part) =>
        typeof part === "number"
          ? `[${part}]`
          : /^[A-Za-z_][A-Za-z0-9_]*$/.test(part)
            ? `.${part}`
            : `[${JSON.stringify(part)}]`,
      )
      .join("")
  );
}
