---
name: frontend-react-vite
description: >-
  Enforces modern-web-guidance accessibility, semantic HTML, mobile viewport
  truncation, client state hygiene, and compact Vitest verification for React,
  Vite, and TypeScript applications. Use whenever creating or modifying UI
  components, hooks, CSS/Tailwind, or client services.
---

# Frontend React + Vite + TypeScript Playbook

## 1. Run `modern-web-guidance` Before Finalizing UI Changes

Query the CLI (or the built-in `modern-web-guidance` skill) for touched areas:
```sh
npx --offline modern-web-guidance list
```

## 2. Mandatory Accessibility & Semantic HTML Checks

- **Decorative Icons:** Add `aria-hidden="true"` to decorative inline SVGs/icons.
- **Dynamic Errors:** Announce errors with `role="alert"` or `aria-live="polite"`.
- **Progress Bars:** Always clamp `aria-valuenow` within `[aria-valuemin, aria-valuemax]` and provide `aria-valuetext` when raw values can exceed maximums.
- **Threshold Booleans:** Derive limit-reached booleans from raw counts (`count >= max`), never rounded percentages (`Math.round(...) >= 100`).
- **Focus Styles:** Prefer `:focus-visible` outlines (`focus-visible:outline-2 focus-visible:outline-offset-2`).
- **Button Semantics:** Declare `type="button"` on every non-submit `<button>`. Never nest interactive `<button>` elements inside `<a>` or `<Link>` tags; render row actions as adjacent siblings inside a container `<div>`.
- **Background Network Priority:** Pass `priority: 'low'` on fire-and-forget background `fetch()` calls.

## 3. Mobile Viewport & Flex Truncation (`320px–375px`)

- Put `min-w-0 flex-1` and `truncate` on dynamic header/badge text (`shrink-0` on adjacent icons/buttons) so text never collides with controls.
- On multi-item bottom navigation bars (`flex-1`), put `min-w-0` on items, `shrink-0` on icons, and `w-full text-center truncate` on labels.
- Use `break-words` (not `truncate`) on multi-word descriptions so localized copy is never clipped mid-sentence.

## 4. State Hygiene & Token-Efficient Testing

- Deduplicate concurrent client requests and clean up subscriptions/listeners on unmount or user/account switch.
- Iterate with scoped tests (`npx vitest run <file> --reporter=dot`) and finish with `npm run lint`, `npx vitest run --reporter=dot`, and `npm run build`.
