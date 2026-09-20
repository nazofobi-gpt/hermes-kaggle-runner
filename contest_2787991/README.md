# Contest 2787991 — React state update fix

## Root cause
A successful submit can update the server while the client continues rendering an old in-memory collection. Waiting for a full page refresh hides the missing client-state update.

## Fix
Use the object returned by the successful request as the single post-submit payload and append it with a functional React state update:

```js
setItems(current => [...current, created]);
```

The functional form avoids stale-closure bugs. The submit button is disabled while saving to prevent duplicate submissions; empty input is rejected; a failed request leaves the existing list untouched.

## Integration note
In the real application, replace the `Promise.resolve(...)` demo line with the existing API call. Do not append until that call succeeds. If the application uses a query cache instead of local state, apply the same principle through the cache's canonical `setQueryData`/invalidate mechanism rather than maintaining two sources of truth.

## Deterministic QA
Run `node state-update.test.mjs`. Expected marker: `CONTEST_2787991_STATE_TEST_PASS`.

Submission proof should show the item appearing in the list immediately after successful submit, without page reload.
