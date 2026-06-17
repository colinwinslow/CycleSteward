# Real-HA smoke test — Evidence

Paired with [docs/specs/real-ha-smoke-test.md](../../docs/specs/real-ha-smoke-test.md)
and [real-ha-smoke-test-bdd.md](real-ha-smoke-test-bdd.md) (scenarios A–D).

**Run date:** 2026-06-16 20:44 PDT
**Real-HA env:** Python 3.14.5, `homeassistant==2026.6.3`,
`pytest-homeassistant-custom-component==0.13.339` (`.venv-ha/`)
**Offline env:** Python 3.9.6 (`.venv/`, against `tests/ha_stubs.py`)

## How to reproduce

```bash
# Real-HA suite (needs Python >= 3.13; .venv-ha is 3.14):
python3.14 -m venv .venv-ha
.venv-ha/bin/python -m pip install -e ".[ha-test]"
.venv-ha/bin/python -m pytest tests_ha/ -v --asyncio-mode=auto

# Offline suite is unaffected (still excludes tests_ha via testpaths):
.venv/bin/python -m pytest
```

`--asyncio-mode=auto` is required (HA's convention) and is passed on the CLI, not
in the shared `pyproject.toml`, because the offline 3.9 env has no
`pytest-asyncio` and would error on an unknown ini option.

## Scenarios A–D — raw pytest output (real Home Assistant 2026.6.3)

```
$ .venv-ha/bin/python -m pytest tests_ha/ -v --asyncio-mode=auto

============================= test session starts ==============================
platform darwin -- Python 3.14.5, pytest-9.0.3, pluggy-1.6.0 -- /Users/colinwinslow/Documents/GitHub/CycleSteward/.venv-ha/bin/python
cachedir: .pytest_cache
rootdir: /Users/colinwinslow/Documents/GitHub/CycleSteward
configfile: pyproject.toml
plugins: pytest_freezer-0.4.9, anyio-4.14.0, unordered-0.7.0, syrupy-5.2.0, cov-7.1.0, socket-0.7.0, xdist-3.8.0, timeout-2.4.0, github-actions-annotate-failures-0.4.0, asyncio-1.3.0, aiohttp-1.1.0, respx-0.23.1, picked-0.5.1, requests-mock-1.12.1, homeassistant-custom-component-0.13.339
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 4 items

tests_ha/test_real_ha_smoke.py::test_a_real_loader_validates_manifest PASSED [ 25%]
tests_ha/test_real_ha_smoke.py::test_b_config_flow_creates_entry PASSED  [ 50%]
tests_ha/test_real_ha_smoke.py::test_c_entities_register_across_platforms PASSED [ 75%]
tests_ha/test_real_ha_smoke.py::test_d_clean_unload_releases_everything PASSED [100%]

============================== 4 passed in 0.21s ===============================
```

Mapping to BDD scenarios:

- **A — manifest/loader validation** → `test_a_real_loader_validates_manifest`:
  real HA `async_get_integration` resolves `cyclesteward`, asserts
  `domain == "cyclesteward"` and `config_flow is True`, and imports every declared
  platform module (`async_get_platform`) confirming each exposes `async_setup_entry`.
- **B — config flow creates an entry (anchor)** → `test_b_config_flow_creates_entry`:
  `SOURCE_USER` flow returns a `FORM`, then `async_configure` with the two required
  entity IDs returns `CREATE_ENTRY`; one `ConfigEntry` exists with the IDs
  round-tripped in `.data`.
- **C — entities register across platforms** → `test_c_entities_register_across_platforms`:
  `async_setup` reaches `ConfigEntryState.LOADED`; the entity registry contains
  entities for every platform in `PLATFORMS` (`select, sensor, switch, button,
  time`); live `hass.states` carries all five domains; the three services are
  registered.
- **D — clean unload** → `test_d_clean_unload_releases_everything`:
  `async_unload` returns `True`, entry state becomes `NOT_LOADED`, the watcher is
  released (its `<entry_id>.watcher` key — present before unload — is gone after,
  which is the pop that runs `async_stop()`), the coordinator key is dropped, and
  the `set_mode` / `manual_override` / `acknowledge_fault` services are removed
  (last entry gone).

## Offline suite still green (no regression)

```
$ .venv/bin/python -m pytest
........................................................................ [ 77%]
...............................................................          [100%]
279 passed in 0.24s
```

279 (not 283) confirms `tests_ha/` is excluded from the default run by
`testpaths = ["tests"]`.

## Manifest fixes surfaced by this packet

Wiring the canonical `hassfest` action exposed two `manifest.json` issues the
lighter runtime loader (scenario A) does not reject:

- `"documentation": ""` → set to `https://github.com/colinwinslow/CycleSteward`
  (hassfest requires a valid URL).
- key ordering → reordered to `domain`, `name`, then alphabetical (hassfest
  enforces sorted manifest keys); `codeowners` populated with `@colinwinslow`.

## CI half — `.github/workflows/ci.yml`

The canonical `hassfest` is not in the pip wheel, so it runs in CI via the
official action, alongside both test suites:

```yaml
jobs:
  hassfest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master

  test-offline:        # Python 3.12, pip install -e ".[dev]", ruff + pytest
  test-real-ha:        # Python 3.13, pip install -e ".[ha-test]", pytest tests_ha/
```

(See the workflow file for full step contents.) `hassfest` itself is validated in
CI on the GitHub runners, not locally — no HA-core checkout exists in this repo.
