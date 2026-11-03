# Metis screenshots: detailed visual notes

Companion to `docs/design/metis-auto-ui-spec.md` (UI-R09). Read together with the images in `docs/design/metis-screens/` (local only, not committed: Metis's material). Written 2026-11-03 from the six screenshots (2940 × 1606 px, macOS Retina, so on-screen CSS sizes are about **half** the pixel sizes measured in the images). Colours are **visual estimates from the images, not sampled values**: verify by opening the images (sample with a colour picker if available) and adjust the tokens.

## Shared observations (all screens)
- **Language and direction:** Persian, right to left. Brand at the far **right**. English and numbers (dates, `$0.001921`, `8,667`, model ids such as `deepseek:deepseek-v4-flash`) stay left to right inside the RTL layout.
- **Font:** a clean Persian sans-serif in the Vazirmatn family look: bold headings, regular body, tabular digits in metrics.
- **Brand:** circular intertwined ribbon logo (magenta, purple, blue, cyan) followed by the wordmark "متیس" in a heavy weight. **Do not redraw or crop the logo from the screenshots** (UI-R08); use an official asset only if provided, otherwise the text wordmark.
- **Accent:** a saturated blue, close to `#4361EE` / `#3D63FF` (primary buttons, the credit amount, "new" badges, focus, the dark-mode toggle track).
- **Gradient:** blue → purple → magenta → red, right to left in RTL (landing headline, primary CTA pill, outlined pills with gradient borders). Used only on the landing page and the main CTA.
- **Radius:** cards ~12 px, controls ~8 px, pills fully rounded; the landing hero card ~24–32 px.
- **Borders:** 1 px hairlines everywhere; shadows almost none (light mode: a barely visible soft shadow on cards).
- **A floating blue circular support button** sits at the bottom corner of every screen: **do not copy it** (there is no support chat in our app).

## 1. Dark marketing landing (`1-dark-landing.png`) → our entry screen (UI-S01) style
- **Background:** near-black (`~#0A0A10`) with very soft radial glows: a faint navy/indigo glow lower left, a faint wine/red glow upper right. No pattern, no glassmorphism.
- **Floating pill header:** a fully rounded bar inset from the page edges, dark translucent fill slightly lighter than the background, hairline border. Right: logo + "متیس". Centre: text links ("صفحه اصلی", "مدل ها ▾", "قابلیت ها ▾", "پایگاه دانش ▾", "آموزش ویدئویی", "بلاگ", "تماس با ما"), light gray text, small chevrons for menus. Left: a pill button with a **gradient outline** (blue → magenta) and white text ("ورود / ثبت‌نام"). In our app this pill is **not** a login: omit it or use it for the language switch.
- **Hero card:** a very large rounded rectangle with a hairline border on a slightly lighter dark surface.
  - Headline: large bold **gradient text** (blue on the right through purple to magenta/red on the left): "متیس | اتصال بی‌دردسر به مدل‌های هوش‌مصنوعی".
  - A row of six square rounded tiles (dark fill, hairline border) holding AI provider logos. **Do not reproduce third-party logos**: for our entry cards use simple neutral icons (Material icons) instead.
  - Subtitle: muted light gray, medium size, centred.
  - Two buttons, centred, side by side: **primary pill** with the brand gradient fill (magenta → purple → blue) and white bold text ("شروع اتصال"); **secondary pill** with dark fill, hairline border, white text ("مشاهده مدل‌ها").
  - A thin, muted news ticker line under the buttons (dots as separators).
- Below the hero: a centred pill with a gradient outline and a white bold label ("داده‌ها عملکرد موفق متیس را تایید می‌کنند").

**Use for UI-S01:** same background with soft glows, a hero area with a gradient headline (our own copy: "Metis-Auto", "choose your path"), the two journey cards as large rounded dark cards with neutral icons, one gradient primary pill per card, the secondary style for "back".

## 2. Light login (`2-light-login.png`) → our forms (UI-S03 create bot, inputs everywhere)
- White page; one centred card (~ 570 × 520 px CSS), white fill, hairline light-gray border (`~#E4E4E7`), radius ~12, very soft shadow.
- Inside, right-aligned: logo + "متیس" centred at the top; title "ورود" large bold; label "شماره موبایل" bold small; input full width, ~76 px tall in the image (~40–44 px CSS), white fill, light-gray border, radius ~8, placeholder muted gray; a helper line with an inline underlined blue link; **primary button full width, solid blue (`~#4361EE`), white bold text, radius ~8**.
- **Use for:** form layout (labels above inputs, right-aligned), input style, solid-blue primary button in light mode. **We build no login screen** (UI-R08).

## 3. Light dashboard, top (`3-light-dashboard-top.png`) and 4. dark dashboard, top (`4-dark-dashboard-top.png`) → our app shell (UI-H*) and Results (UI-S07)
**Header: two rows, full width, bottom hairline border.**
- Light: header band light gray (`~#F4F4F6`), page white. Dark: header band dark gray (`~#18181B`), page near-black (`~#111113`).
- **Row 1, right:** logo + "متیس" (bold, ~22 px CSS).
- **Row 1, left (from the left edge inwards):** a dropdown chevron; a round avatar; the user's phone number in bold with "کاربر سطح ۰" under it, small and muted; the **theme toggle**: a pill switch ~66 × 32 px in the image. Light: gray track with a white knob showing a sun icon. Dark: **blue track** with a white knob showing a moon. Then the **credit**: "اعتبار: 20.00$", label in body colour, amount in accent blue bold, with a round blue "+" button. Then "پشتیبانی" with a headset line icon and a chevron.
  - **Our version (UI-H04):** no avatar, no phone, no "+" top-up (nothing fake). Keep the chevron-free "Local demo" chip, the theme toggle exactly in this style, the **budget** in the credit's place ("بودجه باقی‌مانده: $x" in accent blue bold; in fake mode "حالت آزمایشی"), the mode chip (Fake/Live), and the language switch.
- **Row 2:** horizontal navigation tabs, right-aligned, each a label with a **line icon to its right**: "داشبورد" (grid icon), "ربات‌ها" (person), "ورکفلوها", "جنریشن‌ها" (sparkle) with a small solid blue "جدید" badge, "پایگاه‌های دانش", "کلیدهای API", "شارژ حقوقی" with a "جدید" badge, "مستندات".
  - **Active tab:** a filled rounded pill behind the label (light: `~#EBEBEF`; dark: `~#27272A`), text bold.
  - **Our version (UI-H03):** tabs "گفتگو" (chat icon) and "نتایج" (chart icon), maybe "تنظیمات"; same pill active state; badges only if they mean something (none needed).

**Filter row** (below the header, right-aligned, one line): four equal-height controls (~52 px in the image, ~40–44 px CSS), radius ~8, hairline border, surface fill (light: white; dark: `~#0B0B10`):
- date range with a calendar icon ("Oct 26, 2026 - Nov 1, 2026", LTR text);
- a dropdown "فیلتر بر اساس بات" with a chevron;
- a select "همهٔ ربات‌ها" with an up/down arrow;
- a dropdown "روزانه" (granularity).
- **Our version (UI-R20):** the baseline selector, the slice selector, the step selector or version switch, in exactly this control style and row.

**KPI cards:** five equal cards in one row, equal gaps (~20 px in the image).
- Light: card fill white or near-white (`~#FCFCFD`), hairline border `~#E4E4E7`. Dark: card fill **darker than the page** (`~#0A0A0F`), hairline border `~#23252F`.
- Content right-aligned: a **muted label** top-right ("مجموع هزینه", "میانگین روزانه", "تعداد توکن‌ها", "رویدادهای GPT", "پیام‌های چت"), with an optional small info-circle icon; the **value large and bold** below (`$0.001921`, `8,667`, `0`) in the body colour (dark: white); an optional muted caption under the value ("مبلغ پرداختی شما"; "ورودی: 6,810 • خروجی: 1,857" with a dot separator).
- **Our version (UI-R21, UI-C*):** baseline cost, saving, saving %, interval, n eligible, in exactly this card style.

**Charts row:** two cards; the wider one on the **right** (~60%), the narrower on the left (~40%).
- Card title: large bold, right-aligned, top-right ("روند هزینه", "توکن‌ها در گذر زمان").
- **Cost trend (right card):** a smooth line with a soft area fill under it. Light: teal line `~#4E9F8F` with a very light teal fill. Dark: brighter green-teal line `~#4FC3A1` with a dark green fill. Legend centred below: small square swatch + label ("هزینه").
- **Tokens over time (left card):** two smooth lines. Light: dark navy `~#2C3E50` (input, "ورودی") and mustard `~#E5C35A` (output, "خروجی"). Dark: orange `~#F59E42` (input) and purple `~#A855F7` (output). **The series colours change with the theme.**
- Axes: thin; tick labels small and muted gray; dates on the x axis LTR ("Oct 26"); y values with decimals; **dashed, very faint vertical and horizontal grid lines**; no chart border inside the card.

## 5. Dark dashboard, bottom (`5-dark-dashboard-bottom.png`) and 6. light dashboard, bottom (`6-light-dashboard-bottom.png`)
- **"هزینه بر اساس ارائه‌دهنده" (cost by provider), wide right card:** **stacked bars** per day, thick bars with slightly rounded top corners. Dark: blue `~#3B5BDB` + green `~#5FB38E`. Light: coral `~#D9775A` + teal `~#4F9D8F`. Legend centred below with `provider:model` labels in LTR ("deepseek:deepseek-v4-flash", "openai_chat_completion:gpt-5-nano"). Faint dashed grid. A thin vertical scrollbar at the card's right edge (the legend scrolls).
- **"رویدادهای ورک‌فلو" (workflow events), narrow left card:** an **empty state**. Dark: an empty dashed-grid area. Light: a flat light-gray placeholder block (`~#D9D9DE`) above a faint grid. Our empty states (UI-K05) should be calmer: an icon, one line, and an action where one exists. Never a bare gray block.
- **"تجزیه هزینه بر اساس نوع" (cost breakdown by type), right-aligned card below:** a **thick donut** (ring ~25% of the radius). Dark: blue. Light: coral. A hairline gap between segments.
- **Our version (UI-G03, UI-G04):** cost by model used (stacked bars) and the savings or cost-block breakdown (donut), with these theme-dependent palettes.

## Token proposal derived from these notes (verify against the images)

| Token | Dark | Light |
|---|---|---|
| `--bg` | `#111113` | `#FFFFFF` |
| `--header` | `#18181B` | `#F4F4F6` |
| `--surface` (cards, controls) | `#0A0A0F` | `#FCFCFD` |
| `--elevated` (active tab, menus) | `#27272A` | `#EBEBEF` |
| `--border` | `#23252F` | `#E4E4E7` |
| `--text` | `#F5F6FA` | `#18181B` |
| `--text-muted` | `#9CA3AF` | `#6B7280` |
| `--accent` | `#4361EE` | `#4361EE` |
| `--brand-gradient` | `linear-gradient(270deg, #3D63FF, #8B3DFF, #D63384, #E5484D)` (right → left in RTL) | same |
| `--landing-bg` | `#0A0A10` + soft radial glows (navy lower left, wine upper right) | n/a |
| chart: cost trend line / fill | `#4FC3A1` / `#4FC3A1` at ~20% | `#4E9F8F` / `#4E9F8F` at ~15% |
| chart: series A / B (two-series charts) | `#F59E42` / `#A855F7` | `#2C3E50` / `#E5C35A` |
| chart: categorical 1 / 2 (bars, donut) | `#3B5BDB` / `#5FB38E` | `#D9775A` / `#4F9D8F` |
| chart: grid | `#FFFFFF` at ~8%, dashed | `#000000` at ~6%, dashed |
