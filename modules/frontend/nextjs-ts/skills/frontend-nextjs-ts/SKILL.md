---
name: frontend-nextjs-ts
description: >-
  Enforces Next.js App Router architecture, Server and Client Component (RSC)
  boundaries, strict TypeScript hygiene, accessibility, and Core Web Vitals
  optimization. Use whenever creating or modifying Next.js routes, layouts,
  Server Actions, UI components, or client hooks.
---

# Frontend Next.js (App Router) + TypeScript Playbook

## 1. App Router & Server/Client (RSC) Boundaries

- **Server Components by Default:** Keep `app/**/page.tsx`, `layout.tsx`, `loading.tsx`, `error.tsx`, and data-fetching components as React Server Components. Push `'use client'` down to the smallest interactive leaf components that require browser APIs, event handlers, or React state hooks.
- **Strict Secret Isolation:** Never import server-only modules, database clients, or private environment variables into `'use client'` modules. Mark server utilities with `import 'server-only'` and pass only explicit, minimal, JSON-serializable props across the Server-to-Client boundary.
- **Server Actions & Route Handlers:** Authenticate and authorize the caller inside every `'use server'` action and `route.ts` handler (never trust client-supplied user/tenant IDs or hidden inputs), validate payloads with a strict schema (e.g., `zod`), and call `revalidatePath` / `revalidateTag` intentionally after mutations.
- **Streaming & Error Boundaries:** Wrap slow non-critical async subtrees in `<Suspense>` with lightweight fallbacks, and handle expected missing records with `notFound()` and recoverable failures with segment `error.tsx` boundaries.

## 2. TypeScript Strictness

- Maintain `"strict": true` and `"noUncheckedIndexedAccess": true` in `tsconfig.json`; prohibit `any`, unsafe `as` casts, and `@ts-ignore` unless isolated and documented at an external boundary.
- Explicitly type route segment `params`/`searchParams` (awaiting dynamic request APIs in Next.js 15+), Server Action return states, and `NextRequest`/`NextResponse` payloads.

## 3. Accessibility & Mobile Layout (`320px–375px`)

- Run `npx --offline modern-web-guidance list` when installed before finalizing UI changes, and keep semantic landmarks (`<main>`, `<nav>`, ordered headings).
- Add `aria-hidden="true"` on decorative icons/SVGs, declare `type="button"` on all non-submit `<button>` elements, and never nest `<button>` inside `<Link>` or `<a>` tags.
- Use `:focus-visible` focus rings (`focus-visible:outline-2 focus-visible:outline-offset-2`), announce dynamic errors via `role="alert"` or `aria-live="polite"`, and use `min-w-0 flex-1` + `truncate` or `break-words` so narrow mobile viewports never overflow.

## 4. Core Web Vitals (LCP, INP, CLS) & Bundle Hygiene

- **LCP:** Render hero and content images with `next/image` (`<Image>` with explicit dimensions or `fill` + `sizes`), setting `priority` only on the primary above-the-fold LCP image.
- **CLS:** Load web fonts with `next/font` and reserve explicit dimensions/aspect ratios on media, embeds, and loading skeletons so content never jumps on hydration.
- **INP & Bundle Budget:** Keep heavy libraries (ORMs, markdown/PDF generators, large charting modules) out of client bundles; dynamically import non-critical client widgets with `next/dynamic` and avoid blocking the main thread on interaction handlers.

## 5. Verification Gate

Run compact checks during iteration and the full verification suite before opening a PR:

```sh
npx tsc --noEmit
npm run lint
npm test
npm run build
```
