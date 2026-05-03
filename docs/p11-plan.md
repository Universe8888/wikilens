# P11 — Obsidian Plugin · `v0.11.0` (SDD)

**Status:** Specification — awaiting HITL approval before implementation.
**Created:** 2026-05-03
**Preceded by:** P10 (Epistemic Confidence Mapper) — complete, tag `v0.10.0`.
**Target effort:** ~25–30h part-time.

---

## Goal

Ship `wikilens` as an installable Obsidian community plugin. The plugin is a **view layer only**: it spawns the `wikilens` CLI binary, streams its `--json` output, and renders findings in a side pane. All reasoning stays in the Python CLI; the plugin benefits from every future agent automatically without code changes.

**Success criterion for P11:**

1. `npm run build` in `wikilens-obsidian/` produces `main.js`.
2. Plugin installs in Obsidian desktop (Windows + macOS/Linux), runs `audit` against the active vault with zero config beyond pointing to the installed binary.
3. Findings appear in a side pane; clicking a finding jumps to the relevant note.
4. Pull request opened to `obsidianmd/obsidian-releases` (merge is outside our control; PR open = shipped).

---

## Decisions resolved by research

### Repo layout: **separate repo `wikilens-obsidian`**

Obsidian reads `manifest.json` from the **repo root** for version discovery. All 7 inspected top-tier community plugins (`obsidian-copilot`, `obsidian-dataview`, `Templater`, `obsidian-kanban`, etc.) keep `manifest.json` at root — none use monorepo subdirectory layouts. No `path`/`subdir` field exists in `community-plugins.json`. The root-`manifest.json` duplication requirement is a footgun for version skew in a monorepo, and there is no shared-code argument (Python CLI ≠ TypeScript plugin). **Use `github.com/Universe8888/wikilens-obsidian` from day one.**

### Binary discovery

`spawn("wikilens", …)` without `.exe` and `shell:false` fails with `ENOENT` on Windows. Obsidian launced from Start Menu does not source shell rc files, so `pyenv`/`conda` shims are invisible. Pattern (from Pandoc Plugin, Execute Code):

- Default `binPath = "wikilens"` (works on macOS/Linux after `pip install wikilens`).
- Settings field for absolute path override.
- "Test" button in Settings that runs `wikilens --version` and shows result inline.
- On Windows always resolve via `which` equivalent + `.exe` extension check, or use `shell: true` with properly quoted arguments.

### First end-to-end slice: `audit`

`audit` is deterministic, ~1s, no LLM, no API cost. It exercises the full plugin pipeline (spawn → JSON → render → click-to-jump) with the lowest failure surface. All other subcommands are wired behind a feature toggle after `audit` is solid.

### `isDesktopOnly: true` is mandatory

Any plugin using `child_process` must set this. Review team explicitly checks for it. Mobile checkboxes in the submission PR template are marked "(if applicable)".

### Shelling-out is fully accepted

Pandoc Plugin, Obsidian Git, Execute Code all shell out; all accepted without modification to the pattern. The review team asks only: disclose the external binary in README, use user-configured path rather than bundled binary, no auto-update mechanism.

---

## Architecture

```
wikilens-obsidian/
├── manifest.json          # id:"wikilens", isDesktopOnly:true
├── main.ts                # Plugin.onload — registers view, commands, settings
├── src/
│   ├── WikiLensView.ts    # ItemView — findings pane, progress, log area
│   ├── CliRunner.ts       # spawn wrapper: runCli(argv) → {stdout,stderr,code}
│   ├── parsers.ts         # parse JSON output per subcommand
│   ├── settings.ts        # WikiLensSettings interface + DEFAULTS + SettingTab
│   └── modals.ts          # ConfirmCostModal for LLM-calling commands
├── styles.css             # Obsidian CSS vars only — no hardcoded colors
├── esbuild.config.mjs
├── tsconfig.json
├── package.json
├── tests/
│   ├── __mocks__/obsidian.ts   # minimal stub (~30 lines)
│   ├── parsers.test.ts
│   ├── CliRunner.test.ts       # fake-binary fixture test
│   └── settings.test.ts
├── fixtures/
│   └── fake-wikilens.js        # shebang script; emits fixed JSON on stdout
└── .github/workflows/
    ├── verify.yml         # lint + typecheck + test + build on every PR
    └── release.yml        # on tag: draft GH release with main.js + manifest.json + styles.css
```

### Key architectural rules
1. `main.ts` and `WikiLensView.ts` import from `obsidian`. Everything else is pure Node/TS — no obsidian imports in `CliRunner.ts`, `parsers.ts`, `settings.ts`, `modals.ts`. This keeps the unit-testable surface large.
2. `CliRunner.ts` exposes `runCli(binPath: string, args: string[]): Promise<RunResult>` — injectable in tests, no global state.
3. `WikiLensView` is the single DOM owner. All findings state lives there; commands call `view.runCommand(cmd)`.
4. No `innerHTML` / `outerHTML` / `insertAdjacentHTML` anywhere (review rejection criterion). Use `createEl` / `createDiv`.
5. All resources registered via `registerView`, `registerEvent`, `addCommand` — Obsidian auto-cleans on `onunload`.

---

## UX design

### Settings tab (`WikiLensSettingTab`)

| Setting | Type | Default | Notes |
|---------|------|---------|-------|
| `binPath` | text | `"wikilens"` | Full path or name on PATH |
| `dbPath` | text | `""` | Empty = CLI default (`.wikilens/db`) |
| `maxCostPerRunUsd` | number | `2.00` | Hard cap before LLM commands; abort if exceeded |
| `auditOnSave` | toggle | `false` | Off by default — never auto-burn credits |

"Test binary" button runs `wikilens --version`, shows output inline. On failure: "Not found — install with `pip install wikilens` or set an absolute path."

### WikiLens side pane (`WikiLensView`)

```
┌─ WikiLens findings ────────────────────────────────────┐
│ [audit ▼] [contradict] [gap] [concepts] [confidence]   │  ← command buttons
│ ─────────────────────────────────────────────────────  │
│ ▶ broken-links (4)                                     │  ← collapsible class
│   • [[Note A]] → [[Note B]] — target not found         │  ← clickable row
│   • …                                                   │
│ ▶ one-way (8)                                          │
│ ▶ orphans (6)                                          │
│ ─────────────────────────────────────────────────────  │
│ ▸ Log (last run: 1.2s, exit 1)         [Copy diag]    │  ← collapsible log
└────────────────────────────────────────────────────────┘
```

- Filter pills at top toggle visibility of each class.
- `<details>` per class; uses Obsidian CSS vars (`--text-muted`, `--background-secondary`, `--interactive-accent`).
- Status bar item: `wikilens: idle` / `wikilens: audit…` / `wikilens: done (4 findings)`.
- Log area: last N stderr lines in a `<details>` at bottom; "Copy diagnostics" button.

### Progress & cancellation

- Fast commands (`audit`, ~1s): Notice toast `"WikiLens: running audit…"` auto-dismissed + status bar.
- Slow LLM commands (`contradict`, `gap`, `confidence`, `drift`, `concepts`): `ConfirmCostModal` before spawn; status bar ticker during run; Cancel button in findings pane.
- Windows cancellation: `taskkill /pid <pid> /f /t` (kills process tree). macOS/Linux: `SIGTERM` + 3s `SIGKILL` timeout.

### Click-to-navigate

```ts
async jumpTo(path: string, line: number) {
  const file = this.app.vault.getAbstractFileByPath(path) as TFile;
  const leaf = this.app.workspace.getLeaf(false);
  await leaf.openFile(file, { eState: { line, mark: true } });
}
```

`getLeaf(false)` reuses active pane; Ctrl/Cmd-click opens new tab.

### Cost-confirmation modal

Before any LLM-calling command:
```
Run wikilens contradict?
Scanning 47 notes. Est. 24,000 tokens ≈ $0.12 (gpt-4o).
                                    [Cancel]  [Run ▶]
```

Estimate: `note_count × avg_chunks_per_note × ~512 tokens × model_price`. Conservative overestimate. If `maxCostPerRunUsd` would be exceeded, replace Run button with "Exceeds $X cap — raise limit in Settings".

### Error handling

| Condition | UI |
|-----------|-----|
| Binary not found / exit ENOENT | Notice 10s + auto-open Settings tab |
| Exit 0 (clean) | Notice "WikiLens: no findings" |
| Exit 1 (findings) | Render findings pane |
| Exit 2 (bad args / bad vault) | Notice + log pane shows stderr |
| Crash / unexpected exit code | Notice + log pane + "Copy diagnostics" |

---

## Manifest

```json
{
  "id": "wikilens",
  "name": "WikiLens",
  "version": "0.1.0",
  "minAppVersion": "1.5.0",
  "description": "Runs vault-intelligence agents (link audit, contradictions, gaps, confidence) from the wikilens CLI and surfaces findings in a side pane.",
  "author": "Boris Manzov",
  "authorUrl": "https://github.com/Universe8888",
  "isDesktopOnly": true
}
```

Note: Obsidian release tags use **no `v` prefix** — tag `0.1.0` not `v0.1.0`. The wikilens main repo uses `v0.11.0`; the plugin repo uses bare `0.1.0`. These are independent version sequences.

---

## Release workflow

```yaml
# .github/workflows/release.yml (in wikilens-obsidian repo)
on:
  push:
    tags: ['*']
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - run: npm ci
      - run: npm run build
      - uses: ncipollo/release-action@v1
        with:
          artifacts: "main.js,manifest.json,styles.css"
          token: ${{ secrets.GITHUB_TOKEN }}
          draft: true
```

`verify.yml`: runs `npm run lint && npm test && npm run build` on every PR push. No artifact upload.

---

## Testing strategy

Minimum viable suite (~11h estimated):

| File | What it tests | Framework |
|------|--------------|-----------|
| `tests/parsers.test.ts` | JSON → FindingList for each subcommand | Jest 29 + ts-jest |
| `tests/CliRunner.test.ts` | `runCli` with fake binary (`fixtures/fake-wikilens.js`), exit 0/1/2, CRLF stripping | Jest + jest-environment-node |
| `tests/settings.test.ts` | DEFAULTS merge, `normalizePath` on binPath | Jest |
| `tests/__mocks__/obsidian.ts` | Minimal stub: `Plugin`, `Notice`, `TFile`, `ItemView`, `Modal`, `Setting`, `PluginSettingTab` | (mock file) |
| Manual smoke checklist | Install to local vault, run each command, verify UI | `docs/RELEASE_CHECKLIST.md` |

Skipped for v0.11: Playwright/Electron E2E, vitest, full `obsidian` mock. No headless Obsidian harness exists; manual checklist is what the entire community does.

---

## Submission checklist (community-plugins PR)

`community-plugins.json` entry:
```json
{
  "id": "wikilens",
  "name": "WikiLens",
  "author": "Boris Manzov",
  "description": "Surface vault-intelligence findings — broken links, contradictions, knowledge gaps, and low-confidence claims — via the wikilens CLI.",
  "repo": "Universe8888/wikilens-obsidian"
}
```

PR checklist items to satisfy:
- [ ] `manifest.json` `id` == `community-plugins.json` `id` == `"wikilens"`
- [ ] Release tag == `manifest.version` (no `v` prefix)
- [ ] Release assets: `main.js`, `manifest.json`, `styles.css` attached individually
- [ ] `isDesktopOnly: true` in manifest
- [ ] README discloses: external binary dependency, no telemetry, no network calls (CLI makes them, not plugin), MIT license
- [ ] `LICENSE` file present in repo
- [ ] No `innerHTML` / `outerHTML` / `insertAdjacentHTML`
- [ ] No hardcoded colors (CSS vars only)
- [ ] All resources cleaned up in `onunload`
- [ ] Tested on Windows (primary) + macOS

---

## Step plan (PIV-loop-sized)

| Step | Work | Exit criterion |
|------|------|----------------|
| **11.0** | This SDD + HITL approval | Doc merged to main |
| **11.1** | Create `wikilens-obsidian` repo; scaffold `manifest.json`, `main.ts`, `esbuild.config.mjs`, `tsconfig.json`, `package.json`, `.gitignore` | `npm run build` produces `main.js`; `npm test` runs (0 tests, no failures) |
| **11.2** | `settings.ts` + `WikiLensSettingTab` — binPath, dbPath, maxCostPerRunUsd, auditOnSave; "Test binary" button | Settings persist across Obsidian reload; test-binary button shows `wikilens --version` output |
| **11.3** | `CliRunner.ts` + fake-binary fixture + unit tests | `tests/CliRunner.test.ts` green; CRLF stripping tested; exit codes 0/1/2 handled |
| **11.4** | `parsers.ts` for `audit` JSON format + unit tests | `tests/parsers.test.ts` green on `audit` output |
| **11.5** | `WikiLensView.ts` skeleton (ItemView, opens from command palette, empty pane) | Pane opens; status bar item shows "wikilens: idle" |
| **11.6** | Wire `audit` end-to-end: button → `CliRunner` → parser → render findings + click-to-jump | Clicking a broken-link row opens the note at the correct line in the sample vault |
| **11.7** | Error states: binary not found, exit 2, crash | Each error path shows correct Notice + log pane content |
| **11.8** | `ConfirmCostModal` + cost estimation + `maxCostPerRunUsd` abort | Modal shown before `contradict`; cancel works; cap abort works |
| **11.9** | Port spawner to remaining subcommands (`contradict`, `gap`, `answer`, `drift`, `concepts`, `confidence`) behind feature toggle (off by default) | All 7 commands wired; `audit` is the only one enabled in default settings |
| **11.10** | `verify.yml` + `release.yml` CI | GH Actions green on push; draft release created on tag `0.1.0` with 3 assets |
| **11.11** | Plugin README (purpose, install, usage, binary-path docs, network-use disclosure, MIT) | Passes Obsidian submission checklist |
| **11.12** | Manual smoke test on Windows (primary) | All exit-code paths verified in real Obsidian |
| **11.13** | Open PR to `obsidianmd/obsidian-releases` | PR URL recorded in HANDOFF; tag `v0.11.0` on wikilens main repo |
| **11.14** | Update `HANDOFF.md`, `.local/HANDOFF.md`, `ROADMAP.md`, `BENCHMARK.md` in wikilens main repo | HITL-approved push to main |

---

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Obsidian review asks for changes | Medium | Checklist above covers all documented rejection reasons; submission PR description pre-explains `child_process` pattern with precedents |
| Review queue 2–8 weeks | Certain | Tag `v0.11.0` on PR submission, not on merge; treat PR open = done |
| Windows PATH weirdness | High | Settings "Test binary" button is the UX escape hatch; absolute path override always works |
| Windows `child.kill` orphans | High | `taskkill /f /t` kills full process tree; documented in `gotchas.md` |
| `\r\n` JSON parse errors | Medium | `CliRunner` strips before parse; tested in `CliRunner.test.ts` |
| Version skew (`manifest.json` in plugin repo vs main repo version) | Low | Independent version sequences; documented in this SDD |

---

## What this phase is NOT

- Not a reimplementation of any agent in TypeScript.
- Not a bundled Python interpreter or model.
- Not a hosted service — plugin is local-only; LLM calls are made by the CLI, not the plugin.
- Not an auto-running background service — all commands are triggered explicitly.

---

## Open questions for user (before step 11.1)

1. **Confirm separate repo.** Research strongly recommends `Universe8888/wikilens-obsidian` (dedicated repo). Do you want to create it now, or should I defer that to step 11.1?
2. **Node/npm install.** Step 11.1 will run `npm install` in the plugin repo (~30MB dev deps: esbuild, typescript, jest, obsidian types). Confirm OK.
3. **Plugin ID.** `"wikilens"` — confirm it matches what you want in the Obsidian community directory. Cannot be changed post-submission.
4. **v0.1.0 vs v0.11.0.** Plugin repo starts at `0.1.0`; the tag on the main wikilens repo is `v0.11.0`. These are independent. Confirm this two-sequence model is acceptable.
