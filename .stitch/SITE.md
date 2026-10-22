# TechPulse AI Digest - Site Specification & Roadmap

## 1. Vision
An autonomous, real-time intelligence observatory and editorial dashboard at the intersection of developer infrastructure and tech publication craft. Built on the **Obsidian Telemetry** design system with a 4px baseline grid, dual-stroke glass elevation, and radar telemetry signals.

## 2. Stitch Project Reference
- **Project Title:** TechPulse AI Design System
- **Stitch Project ID:** `17792133599145232927`
- **Design Theme:** Obsidian Telemetry (Dark Technical Minimalist & Glass Precision)
- **Palette Core:** Obsidian Canvas (`#07080b`), Radar Emerald (`#10b981`), Velocity Cyan (`#0ea5e9`), Pulse Violet (`#8b5cf6`), Amber Warning (`#f59e0b`), Mint Luminescence (`#a7f3d0`).

## 3. Screen Registry
| Screen ID | Title | Key Components | Status |
|-----------|-------|----------------|--------|
| `a938963a0db04a9ba84883e49be6e2b8` | Live Feed Dashboard | Top Telemetry Bar, Real-time Ingestion Stream, Split-view Inspector, Filter Chips | Verified & Exported |
| `a227f794d9e54398b33bae9f6851aca8` | Curated Digests Archive | Executive Vault Header, Dispatch Scheduler, Archive Bento Cards, Delivery Health | Verified & Exported |

## 4. Sitemap
- [x] **Live Feed Dashboard** (`/` or `index.html` / `live-feed`)
- [x] **Curated Digests Archive** (`curated-digests.html` / `curated-digests`)
- [ ] **AI Trends & Signals** (`ai-trends-and-signals`)
- [ ] **Sources & Bot Config** (`sources-and-bot-config`)

## 5. Roadmap
- **Phase 1:** Ingest and verify Stitch screens, save code and screenshots in `.stitch/designs`. [Completed]
- **Phase 2:** Integrate navigation links between Live Feed and Curated Digests Archive, expose `/curated-digests` endpoint. [Completed]
- **Phase 3:** Extract and align shared Obsidian Telemetry tokens into `web/styles.css`. [Completed]
