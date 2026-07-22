# intuixion.ai — Next.js Setup Guide

## 1. Create your Next.js project

```bash
npx create-next-app@latest intuixion-web \
  --typescript \
  --tailwind \
  --eslint \
  --app \
  --src-dir=false \
  --import-alias="@/*"

cd intuixion-web
```

## 2. Drop in these files

Copy the provided files into your project:

```
app/
  layout.tsx          ← replace the generated one
  page.tsx            ← replace the generated one
components/
  Navbar.tsx          ← new file
  Hero.tsx            ← new file
  TrustBar.tsx        ← new file
styles/
  globals.css         ← replace the generated one (keep Tailwind directives at top)
  animations.css      ← new file
```

**Important:** Keep these lines at the TOP of globals.css (Tailwind requires them):

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

Then paste the rest of the globals.css content below them.

## 3. Import animations.css in layout.tsx

Add to `app/layout.tsx`:
```tsx
import "../styles/animations.css";
```

## 4. Run locally

```bash
npm run dev
```

Visit http://localhost:3000 — you should see the full hero.

## 5. Deploy to Vercel

```bash
npm install -g vercel
vercel
```

Follow the prompts. Your site will be live on a `.vercel.app` URL in ~2 minutes.

## 6. Connect intuixion.ai domain

In your Vercel dashboard:
- Go to your project → Settings → Domains
- Add `intuixion.ai` and `www.intuixion.ai`
- Vercel gives you the DNS records to add in your registrar

## Next components to build (in order)

1. `components/Features.tsx` — the 6-card features grid
2. `components/Sectors.tsx` — Legal / Medical / Finance cards
3. `components/Pricing.tsx` — 3-tier pricing (R750 / R2,500 / R8,000)
4. `components/EarlyAccess.tsx` — email capture form (dark CTA block)
5. `components/Footer.tsx`

Ask Claude for each one — they'll match this exact design system.

## Early access waitlist (do this first!)

Install Resend for email capture:
```bash
npm install resend
```

Create `app/api/waitlist/route.ts` — ask Claude to generate this.
It takes an email POST, saves to your list, and sends a confirmation email.
