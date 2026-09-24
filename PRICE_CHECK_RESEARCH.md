# PoE2 Bulk Price Checking — Research & Implementation Plan

## Overview

Goal: Scan a stash tab in PoE2, copy each item via Ctrl+C, parse the clipboard text,
and price-check every item automatically.

---

## 1. Existing Tools

| Tool | Language | What It Does | License |
|------|----------|-------------|---------|
| **LAMA** ([CouloirGG/lama](https://github.com/CouloirGG/lama)) | Python | Full pipeline: clipboard monitor, item parser, mod scoring (S/A/B/C/JUNK via RePoE tier data), poe.ninja cache, overlay. Has `stash_client.py` + `stash_scorer.py` for OAuth2 stash scanning (PoE1 only). | MIT |
| **Exiled Exchange 2** ([Kvan7/Exiled-Exchange-2](https://github.com/Kvan7/Exiled-Exchange-2)) | TypeScript/Electron | Clipboard parse, trade API query, overlay. Gold-standard parser for PoE2. No external API. | MIT |
| **Waystone** ([kriskruse/waystone](https://github.com/kriskruse/waystone)) | Rust + TypeScript | Vendors EE2's parser as standalone Node process (`brain/`). Unix socket JSON-lines API. Already proven extraction. | MIT |
| **poe2-mcp-server** ([sergeyklay/poe2-mcp-server](https://github.com/sergeyklay/poe2-mcp-server)) | TypeScript | MCP server with `poe2_parse_item` tool. Clipboard parse + mod tier enrichment via RePoE + unique pricing via poe2scout. | MIT |
| **poe-import2trade** ([intGus/poe-import2trade](https://github.com/intGus/poe-import2trade)) | JS | Browser extension converting clipboard text to trade site filters. | MIT |
| **PoE2-PriceCheck** ([Meliodas8/PoE2-PriceCheck](https://github.com/Meliodas8/PoE2-PriceCheck)) | Rust/Tauri | Wayland price checker using poe.ninja + official trade API. | — |

---

## 2. Pricing Sources

| Source | Auth | Rares | Uniques | Currency | Rate Limit | Update Freq |
|--------|------|-------|---------|----------|------------|-------------|
| **poe.ninja** `/poe2/api/economy/...` | None | No | Yes | Yes | ~12 req/5min | ~1 hour |
| **Official trade API** `/api/trade2/search/...` | POESESSID (optional for `available` status) | **Yes** | Yes | Yes | Strict (429 → Cloudflare) | Real-time |
| **poe2scout.com** | None | No | Yes | No | ~10 req/min | ~1 hour |
| **poeprices.info** | None | PoE1 only | — | — | — | — |

### poe.ninja PoE2 Endpoints

```
GET https://poe.ninja/poe2/api/economy/leagues

# Currency/fragments/etc (exchange)
GET https://poe.ninja/poe2/api/economy/exchange/current/overview?league={id}&type={type}
# Types: Currency, Fragments, Abyss, UncutGems, LineageSupportGems, Essences,
#        SoulCores, Idols, Runes, Ritual, Expedition, Delirium, Breach, Verisium

# Unique items (stash-indexed)
GET https://poe.ninja/poe2/api/economy/stash/current/item/overview?league={id}&type={type}
# Types: UniqueWeapons, UniqueArmours, UniqueAccessories, UniqueFlasks,
#        UniqueCharms, UniqueJewels, UniqueSanctumRelics, UniqueTablets, PrecursorTablets
```

No auth needed. Respect ETags and cache headers (~5 min HTTP cache).

### Official Trade API Endpoints

```
# Get stat ID definitions (cache this!)
GET /api/trade2/data/stats
# Returns: { result: [{ label: "Explicit", entries: [{ id: "explicit.stat_...", text: "+# to maximum Life" }] }] }

# Get currency/item static data
GET /api/trade2/data/static

# Search for items
POST /api/trade2/search/poe2/{league}
# Body: { query: { status, name, type, stats, filters }, sort: { price: "asc" } }
# Returns: { id: "queryId", result: ["hash1","hash2",...], total: N }

# Fetch item details (max 10 per request)
GET /api/trade2/fetch/{hash1,hash2,...}?query={queryId}&realm=poe2

# Currency exchange
POST /api/trade2/exchange/poe2/{league}
```

---

## 3. PoE2 Clipboard Text Format

Items copied with Ctrl+C use `--------` (8 dashes) as section delimiter.

### Structure

```
Item Class: <class>
Rarity: <rarity>
<Name>
<Base Type>                         (for Rare/Unique only)
--------
<Properties: Quality, Armour, ES, Evasion, APS, Crit, Spirit, Sockets, etc.>
--------
Requirements:
Level: N, Str: N, Dex: N, Int: N
--------
Item Level: N
--------
<Implicit mods — lines ending with (implicit)>
--------
<Explicit mods — optionally with advanced mod descriptions>
--------
Corrupted / Mirrored / Unidentified  (if applicable)
```

### Advanced Mod Descriptions

When "Advanced Mod Descriptions" is enabled in game settings, each mod has a metadata line:

```
{Prefix Modifier "Stalwart" (Tier: 2) — Life (augmented)}
+203 to maximum Life
```

Format: `{<Generation> Modifier "<Name>" (Tier: N) — <Tags> [(<roll>% increased)]}`

### Mod Type Suffixes

| Suffix | Type |
|--------|------|
| `(implicit)` | Implicit modifier |
| `(enchant)` | Enchantment |
| `(rune)` | Rune/augment socket mod |
| `(crafted)` | Master-crafted |
| `(fractured)` | Fractured |

### Rarity Values

`Normal`, `Magic`, `Rare`, `Unique`, `Currency`, `Gem`, `Divination Card`, `Quest`

---

## 4. Trade API Search Query Format

### Complete JSON Structure

```json
{
  "query": {
    "status": { "option": "online" },
    "name": "Mageblood",
    "type": "Heavy Belt",
    "stats": [
      {
        "type": "and",
        "filters": [
          { "id": "explicit.stat_3299347043", "value": { "min": 80 } }
        ]
      }
    ],
    "filters": {
      "type_filters": {
        "filters": {
          "category": { "option": "armour.chest" },
          "rarity": { "option": "rare" }
        }
      },
      "equipment_filters": {
        "filters": {
          "ar": { "min": 500 },
          "ev": { "min": 500 },
          "es": { "min": 200 },
          "dps": { "min": 300 },
          "pdps": { "min": 200 },
          "edps": { "min": 100 },
          "aps": { "min": 1.5 },
          "crit": { "min": 7.0 },
          "spirit": { "min": 50 },
          "rune_sockets": { "min": 2 },
          "block": { "min": 30 }
        }
      },
      "req_filters": {
        "filters": {
          "lvl": { "max": 65 }
        }
      },
      "misc_filters": {
        "filters": {
          "ilvl": { "min": 80 },
          "quality": { "min": 20 },
          "corrupted": { "option": "false" },
          "gem_level": { "min": 20 }
        }
      },
      "trade_filters": {
        "filters": {
          "price": { "min": 1, "max": 100, "option": "chaos" },
          "indexed": { "option": "1day" },
          "sale_type": { "option": "priced" }
        }
      }
    }
  },
  "sort": { "price": "asc" }
}
```

### Stat Filter Group Types

| Type | Behavior |
|------|----------|
| `and` | ALL filters must match |
| `if` | Advisory — show if present, don't exclude if absent |
| `count` | At least `value.min` filters must match |
| `weight` | Weighted sum must meet `value.min`; filters have `value.weight` |

### Stat ID Format

`{prefix}.{hash}` — prefix determines the modifier source:

| Prefix | Source |
|--------|--------|
| `explicit.stat_NNNNN` | Explicit mod |
| `implicit.stat_NNNNN` | Implicit mod |
| `pseudo.pseudo_XXXXX` | Combined (sums explicit + implicit) |
| `fractured.stat_NNNNN` | Fractured mod |
| `enchant.stat_NNNNN` | Enchantment |
| `crafted.stat_NNNNN` | Crafted/bench mod |
| `rune.stat_NNNNN` | Rune (PoE2-specific) |

### Mapping Mod Text to Stat IDs

1. Fetch `/api/trade2/data/stats` and cache
2. Normalize mod text: strip `+`, replace numbers with `#`, lowercase
3. Match against stat entries: `"+203 to maximum Life"` → `"+# to maximum Life"` → `explicit.stat_3299347043`
4. Prefer `pseudo.*` stats when available (they aggregate across implicit + explicit)
5. Set filter value to ~90% of rolled value: `{ "min": Math.floor(203 * 0.9) }`

### Item Class to Category Mapping

| Item Class | Trade Category |
|-----------|---------------|
| Body Armours | `armour.chest` |
| Helmets | `armour.head` |
| Gloves | `armour.gloves` |
| Boots | `armour.boots` |
| Shields | `armour.shield` |
| Bows | `weapon.bow` |
| Crossbows | `weapon.crossbow` |
| Staves | `weapon.staff` |
| Wands | `weapon.wand` |
| Sceptres | `weapon.sceptre` |
| Daggers | `weapon.dagger` |
| Rings | `accessory.ring` |
| Amulets | `accessory.amulet` |
| Belts | `accessory.belt` |
| Flasks | `flask` |
| Jewels | `jewel` |
| Skill Gems | `gem.activegem` |
| Support Gems | `gem.supportgem` |
| Waystones | `map.waystone` |

---

## 5. EE2 Parser Extraction (Waystone Blueprint)

### What Waystone Extracted from EE2

| EE2 Source Path | Purpose |
|----------------|---------|
| `renderer/src/parser/` | Clipboard text parser (`parseClipboard()`) |
| `renderer/src/assets/data/` | Game data loader (NDJSON indices) |
| `renderer/public/data/en/` | Bundled game data files (items, stats, trade data) |
| `renderer/src/web/price-check/filters/*.ts` | Stat filter builders |
| `renderer/src/web/price-check/trade/*.ts` | Trade query builder (`createTradeRequest()`) |
| `renderer/src/web/background/{Prices,Leagues,TradeData}.ts` | Background services |

### Modifications Required (5 total, all mechanical)

1. Replace `import.meta.env.BASE_URL` with `globalThis.EE2_DATA_BASE` (8 places)
2. Fix 2 relative import paths (`Leagues.ts`, `Prices.ts`)
3. Backport 1 PoE2 mod-block format fix in `pathofexile-trade.ts`
4. Limit `make-index-files.mjs` to English only

### Stubs Required

| EE2 Module | Stub Provides |
|------------|--------------|
| `@/web/Config` | `AppConfig()` returning minimal config object |
| `@/web/background/IPC` | Empty event emitter |
| `@/web/overlay/widgets` | `PRICE_CHECK_DEFAULTS` constants |

### Bootstrap (Node.js)

```typescript
globalThis.EE2_DATA_BASE = pathToFileURL("vendor/ee2/public/").href;
// Patch globalThis.fetch to handle file:// URLs via fs.readFile
// Then call init("en") to load all game data
```

### Dependency: `vue` + `@vueuse/core`

EE2's reactive data layer uses Vue's reactivity system even outside the UI.
This is a runtime dependency for the extracted parser.

---

## 6. Waystone Brain — Standalone Pricing Service

### Running It

```bash
git clone https://github.com/kriskruse/waystone
cd waystone/brain && npm install
BRAIN_SOCKET=/tmp/poe2-brain.sock npx tsx src/server.ts
```

### Unix Socket Protocol (JSON-lines)

Request:
```json
{"id": "1", "cmd": "price", "clipboard": "Item Class: ...", "league": "Standard"}
```

Response:
```json
{"id": "1", "ok": true, "result": {"total": 42, "listings": [{"price": 1, "priceCurrency": "exalted"}], "stats": [...], "props": [...]}}
```

### Available Commands

| Command | Input | Output |
|---------|-------|--------|
| `ping` | — | `"pong"` |
| `parse` | `clipboard` | Full `ParsedItem` object |
| `price` | `clipboard`, `league?` | Trade listings + stats + price |
| `requery` | `clipboard`, `league?`, `overrides[]` | Re-search with toggled filters |
| `bulk` | `have`, `want`, `league?` | Currency exchange rates |
| `uniqueprices` | `league?` | Unique item price corpus |
| `leagues` | — | Available leagues |
| `login` | `sessionId` | Sets POESESSID for trade API |
| `logout` | — | Clears session |

---

## 7. GGG OAuth2 API (For Reference)

### Status

- **Stash Tab API is PoE1 ONLY** — no PoE2 stash endpoint exists
- **Registration is effectively closed** — "We are currently unable to process new applications"
- Email `oauth@grindinggear.com` when open; low priority, weeks-to-months wait
- They reject LLM-generated requests

### Scopes (when available)

| Scope | Description |
|-------|-------------|
| `account:stashes` | View stashes and items (PoE1 only) |
| `account:characters` | View characters and inventories |
| `account:profile` | Basic profile info |
| `service:psapi` | Public Stash API stream |

Not viable for PoE2 stash scanning at this time.

---

## 8. Implementation Plan

### Phase 1: Stash Scanner (DONE)

Python script (`stash-scanner/stash_scanner.py`):
- Calibrate stash grid corners (click top-left + bottom-right cell centers)
- Normal (12x12) or Quad (24x24) grid support
- Cell-by-cell: move mouse, hover, Ctrl+C, read clipboard
- Deduplicate multi-slot items via MD5 hash
- Print summaries to console

### Phase 2: Pricing via Waystone Brain

- Clone and run Waystone's brain as a sidecar service
- Connect stash scanner to brain via Unix socket
- For each scanned item: send `price` command with clipboard text
- Brain returns parsed item + trade listings + estimated price
- Print priced results sorted by value

### Phase 3: Integration into POE2Sniper Web UI

- Backend endpoints: `POST /api/price-check/bulk`, `GET /api/price-check/status`
- Stash scanner sends items to backend instead of brain directly
- Backend proxies to brain (or embeds EE2 parser via Option B vendoring)
- Frontend: new "Stash Pricer" page with sortable results table
- Columns: item name, base type, key mods, estimated price, grade

### Phase 4: Standalone Parser (Optional)

- Vendor EE2 parser directly into POE2Sniper (no sidecar dependency)
- Follow Waystone's PROVENANCE.md recipe
- Maintain NDJSON data files on game patches
