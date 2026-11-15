# Design System: Sinking Cities

The single source of truth for how the Sinking Cities site looks and behaves.
The site is a map tool for city planners, residents and hackathon judges: one
map, one time slider, one neighborhood card. Every number on screen comes from
the pipeline; nothing in the interface is decorative data.

## 1. Visual Theme & Atmosphere

A graphite instrument panel around a glowing map. The interface is dark and
neutral, with no colour of its own, so the only colour on screen is the data:
aqua where the water arrives, coral where a neighborhood crosses the line, and
the teal-to-wine scale of sinking ground. The foot of the screen is a near-black
band that holds the year and the time slider.

- **Density 5, daily-app balanced.** One idea per block, generous spacing in the
  side panel, no dashboards of tiles.
- **Variance 4, offset but orderly.** A fixed left panel, a full-bleed map, a
  full-width time band. Asymmetric by structure, never by decoration.
- **Motion 4, fluid and restrained.** Motion answers the user (press, select,
  drag) and invites exactly one action: pressing play.

## 2. Color Palette & Roles

- **Graphite Sheet** (#16181B) — header, side panel, dialog
- **Recessed Graphite** (#202327) — tracks, hover fills, note blocks, page background
- **Raised Graphite** (#2B2F34) — selected tab, legend, hover label, zoom control
- **Chalk** (#F1F2F0) — primary text and the one solid button; never pure white on pure black
- **Ash** (#9AA2A9) — secondary text, units, captions
- **Seam** (#2A2E33) — 1px dividers and control borders
- **Night Band** (#0D0E10) — the time band at the foot of the page
- **Aqua** (#7FDCF0) — the single interface accent: focus rings, links, the filled slider

Data colors appear only on the map, its legend and the figures that describe it:

- **Flood Blue** (#2B8FD6 long-flooded, #7FE0F5 newly flooded) — flooded ground
- **Coral Alarm** (#FF6B57; 22% wash on the map) — neighborhoods past the flooding
  share, flood years, the sinking trend line
- **Sinking ramp** — teal #1F8A84 (stable), mint #8FCDB9, sand #F3E2A6, apricot #F5A765, coral #E2493A, wine #9C1F4C
- **NISAR coverage** — gold #FFC857 (only NISAR), teal #3FA096 (both radars), slate #7887A0 (only Sentinel-1), graphite #3A3F45 (neither)
- **Map base** — a dark street map tinted to graphite land (#1C1F23) and
  near-black water (#0F1215), with roads as faint light lines and quiet grey labels

No purple, no neon glows, no gradients as decoration. The one gradient on the
site is the sinking legend, because it is the data scale. Printing a
neighborhood brief switches back to dark ink on white paper.

## 3. Typography Rules

- **Display:** Bricolage Grotesque, weight 800, tracking -0.02em to -0.035em —
  headlines, the year, large figures. Hierarchy comes from weight and tight
  tracking, not from size alone. Headlines balance their line breaks.
- **Body:** Public Sans, 15px with 1.55 leading, lines capped near 65 characters.
- **Figures:** tabular numerals everywhere a number can change (year, people
  counts, flood years, table columns) so digits do not jitter while the slider moves.
- **Banned:** Inter, serif faces, all-caps labels, tracked-out eyebrow labels,
  monospace for small data labels.

## 4. Component Stylings

- **Buttons:** 44px minimum height, 8px radius, hairline border on Graphite Sheet.
  One solid Chalk button per screen ("Play the story"). Secondary actions in
  the header are plain text links. Pressing a button moves it down 1px. No glows.
- **View switch:** a recessed track with a Raised Graphite thumb; the
  selected view is the raised one.
- **Toggle:** a pill switch that turns Coral Alarm when sinking is included, with a
  sentence underneath stating what it changes in people.
- **Neighborhood list:** rows separated by seams, not cards. The whole row is
  the button and fills with Recessed Graphite on hover. Flood year or rate sits right,
  in Coral Alarm.
- **Neighborhood card:** a definition list of five facts with large figures, then
  two plain-language notes (residents, planners) on Recessed Graphite.
- **Map furniture:** legend, zoom control, hover label and story captions float
  on the map with 12px radius and one soft black shadow. Elevation is used
  only here, because these sit above the map.
- **Hover label:** pointing at a neighborhood shows its name and its key figure
  for the current view before the user commits to a click.
- **Time slider:** an 8px track on Night Band that fills with Aqua up to a white
  22px thumb. A one-line prompt sits above it until the user first moves it.
- **Loading:** skeleton blocks in the side panel that match the headline, text
  and list they replace. No spinners.
- **Errors:** an inline notice in the panel saying what failed and what to do.

## 5. Layout Principles

- CSS Grid throughout: header / stage / time band, and panel (400px) / map.
- The map is never covered by content except its own small furniture, which
  keeps to the corners.
- Below 820px everything becomes one column: map first, then the panel, with the
  time band pinned to the bottom of the screen.
- No horizontal scroll at any width. All tap targets are at least 44px.

## 6. Motion & Interaction

- Easing is a single soft-spring curve, `cubic-bezier(0.22, 1, 0.36, 1)`; no
  linear transitions on interface elements.
- The neighborhood list cascades in, 30ms per row, when the view changes.
- One perpetual micro-interaction: the play button breathes a faint Aqua ring
  until the user first plays or drags, then stops for good.
- Only `transform` and `opacity` are animated.
- `prefers-reduced-motion` removes the cascade, the breathing ring and all
  transitions.

## 7. Anti-Patterns (Banned)

- No emojis or text glyphs standing in for icons; icons are inline SVG.
- No Inter, no serif faces, no all-caps or tracked-out labels.
- No pure black (#000000); the darkest tone is Night Band (#0D0E10).
- No neon, outer glows, purple, or decorative gradients.
- No rows of equal cards, no card around every block.
- No invented numbers, rounded-for-effect statistics or filler metrics. If the
  pipeline did not produce it, it is not on screen.
- No marketing verbs ("elevate", "seamless", "unleash", "next-gen").
- No "scroll to explore" prompts, bouncing arrows or custom cursors.
- No overlapping text; every element has its own space.
