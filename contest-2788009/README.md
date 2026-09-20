# Contest 2788009 — React Hook Form + Zod numeric casting fix

`<input type="number">` does not automatically give React Hook Form a JavaScript number. A strict `z.number()` schema therefore rejects the raw DOM string.

This fixture fixes the boundary at registration time with `setValueAs`: empty input becomes `undefined`, non-empty input becomes `Number(value)`, and Zod remains strict about integer/range validation. This avoids the common `Number('') === 0` trap.

## Verify

```bash
npm install
npm test
npm run build
npm run dev
```

Expected behavior: `42` submits as `{ "age": 42 }`; empty, non-numeric, fractional, 0 and >120 values fail validation.
