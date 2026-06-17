---
status: accepted
date: 2026-06-16
depends-on-adrs: [ADR-0006, ADR-0011]
---

# Real-HA smoke test: load the integration in genuine Home Assistant

## Status

Draft. Defines the contract surface for validating the CycleSteward integration
against **real** Home Assistant internals (not the offline stubs in
`tests/ha_stubs.py`), per ADR-0006 (core-before-plumbing — the plumbing layer
must now be proven against the real framework) and ADR-0011 (the entity/service
surface that must materialize).

## Related docs

- [bdd/ha-adapter/real-ha-smoke-test-bdd.md](../../bdd/ha-adapter/real-ha-smoke-test-bdd.md) — observable behavior
- [STATUS.md](../../STATUS.md) — current phase and active work

## Context

Every test to date runs against `tests/ha_stubs.py`, which installs fake
`homeassistant` and `voluptuous` modules into `sys.modules` so the adapter
modules import offline under the project's Python 3.9 `.venv`. That harness
proves the adapter's *logic* but proves nothing about whether real Home
Assistant will actually **load** the integration, **run** the config flow, and
**register** the entities. HA itself is the single largest untested surface.

This packet closes that gap with the smallest credible real-HA exercise: boot
Home Assistant's own test core via `pytest-homeassistant-custom-component`, load
`custom_components/cyclesteward` through HA's **real loader** (which validates
the manifest), drive the config flow to create an entry, and confirm entities
materialize across all platforms — then tear the entry down cleanly.

It does **not** add new integration behavior. It is a verification slice whose
deliverable is evidence that the existing plumbing survives contact with real HA.

### Environment constraint (load-bearing)

- The project `.venv` is **Python 3.9.6**; modern Home Assistant requires a
  newer interpreter. The real-HA suite needs **Python ≥ 3.13** (HA 2026.6.3's
  floor): it runs locally under a separate `.venv-ha/` on **3.14** and in CI on
  **3.13**, with `homeassistant==2026.6.3` and
  `pytest-homeassistant-custom-component==0.13.339` (both confirmed importable on
  3.14 during scoping).
- `tests/conftest.py` calls `ha_stubs.install()` at collection time for the
  entire `tests/` tree. The real-HA suite therefore **must not** live under
  `tests/` and **must not** be collected by the default `pytest` run; it lives in
  a separate `tests_ha/` tree run by its own invocation under `.venv-ha`.

## Behavior contract

This packet adds **no** production-code public surface. The contract is the test
harness, CI wiring, and packaging:

- `tests_ha/` — new test tree, **excluded** from default `[tool.pytest.ini_options]
  testpaths`. Its own `tests_ha/conftest.py`:
  - does **not** import or install `ha_stubs`;
  - registers the `pytest_homeassistant_custom_component` plugin;
  - provides/enables the `enable_custom_integrations` fixture so HA's loader will
    discover `custom_components/cyclesteward`.
- `tests_ha/test_real_ha_smoke.py` — the harness tests (scenarios A–D below),
  using `MockConfigEntry` / `hass.config_entries` against a real `hass`.
- `pyproject.toml` — a new optional-dependency group `ha-test` pinning
  `homeassistant==2026.6.3` and `pytest-homeassistant-custom-component==0.13.339`,
  installed into `.venv-ha`.
- `.gitignore` — ignore `.venv-ha/`.
- `.github/workflows/ci.yml` — CI workflow with:
  - the official `home-assistant/actions/hassfest` action (canonical manifest
    validation — the half of "hassfest" not shippable via pip);
  - a job that installs the `ha-test` group on Python 3.14 and runs `tests_ha/`.

Local "hassfest" coverage is delivered by HA's **real loader** validating the
manifest during integration setup inside scenario A; the canonical `hassfest`
script runs in CI (it is not distributed in the pip wheel).

## Anchor artifact

`bdd/ha-adapter/real-ha-smoke-test-evidence.md` — raw `.venv-ha/bin/python -m
pytest tests_ha/ -v` output showing the four scenarios passing against real HA
`2026.6.3`, captured on disk. The simplest observable version: **one** test that
loads the integration through the real loader and creates a config entry, run
first, before the entity-assertion and teardown tests are added.

## Implementation order

Concrete-first:

1. `.venv-ha` deps pinned in `pyproject.toml` `[ha-test]`; `.gitignore` updated.
2. `tests_ha/conftest.py` (no stubs; pytest-hacc plugin + custom-integration
   enablement).
3. **Anchor test** (Scenario B): config flow creates an entry against real HA —
   run it green first.
4. Scenario A (manifest/loader validation), C (entities register across
   platforms), D (clean unload).
5. CI workflow (hassfest action + `tests_ha` job on 3.14).
6. Capture evidence; re-run the 279-test offline suite under `.venv` to confirm
   zero regression.

## Proof requirements

1. `.venv-ha/bin/python -m pytest tests_ha/ -v` green against real HA 2026.6.3
   (4 scenarios).
2. BDD scenarios A–D in `bdd/ha-adapter/real-ha-smoke-test-bdd.md` evidenced with
   raw output in `bdd/ha-adapter/real-ha-smoke-test-evidence.md`.
3. The existing offline suite (`.venv/bin/python -m pytest`, 279 tests) still
   green — no regression from the new tree or packaging changes.
4. `.github/workflows/ci.yml` present and internally consistent (hassfest action
   + `tests_ha` job), verified by reading it back on disk.
5. Architecture review (invariants, esp. #8) and BDD-evidence review OK.

## Non-goals

- No live, long-running HA instance (container/UI). The harness is HA's in-process
  test core only.
- No new integration features, entities, or services. Behavior is frozen; this
  slice only validates it loads.
- No replacement of the offline stub suite — it stays as the fast 3.9 unit layer.
- No migration of the project `.venv` to 3.14.
- Tuning thresholds / config defaults (out of scope; see open queue).

## References

- ADR-0006 — core model before HA plumbing
- ADR-0011 — HA entity/service surface
- `docs/specs/config-entry-plumbing.md` — the config flow this exercises
- `docs/specs/ha-entity-adapter.md` — the entities this confirms register
- `tests/ha_stubs.py` / `tests/conftest.py` — the offline harness this complements
