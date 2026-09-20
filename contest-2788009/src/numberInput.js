export function normalizeNumberInput(value) {
  if (value === "" || value == null) return undefined;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? Number.NaN : parsed;
}
