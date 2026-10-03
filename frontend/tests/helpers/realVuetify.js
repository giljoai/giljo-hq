/**
 * realVuetify.js — FE-9366
 *
 * A sanctioned escape hatch from tests/setup.js's global Vuetify stub map. Read
 * the comment above `config.global.stubs` in tests/setup.js first — it explains
 * why every Vuetify tag renders as a flat `<div><slot /></div>` by default and
 * why that is usually the right call for test speed.
 *
 * The flat stub renders ONLY the default slot, so a component's named/scoped
 * slots (VSelect's #item / #selection, VList's #prepend / #append, ...) never
 * execute under test. FE-9365d shipped a `??` render defect (Vuetify 4 passes
 * `item.raw` into those slots; the code read the Vuetify 3 `item.title` /
 * `item.value`) through 21 passing tests, because the layer the bug lived in
 * was structurally unreachable — the stub swallowed the slot content whole.
 *
 * Two things that look like the fix are not:
 *  - `mount(..., { global: { stubs: { VSelect: false } } })` alone renders
 *    NOTHING: tests/setup.js also mocks the `vuetify` plugin install as a
 *    no-op, so there is no real component registered for `false` to fall
 *    back to.
 *  - Even with a real Vuetify instance supplied via `global.plugins`, setting
 *    `global.stubs.VSelect = false` per-mount still renders the flat stub.
 *    Vue Test Utils merges per-mount stubs OVER `config.global.stubs` by key
 *    (`mergeStubs` in @vue/test-utils) — a key ABSENT from the per-mount map
 *    is left at whatever tests/setup.js's singleton set it to, so `false` is
 *    the only value that changes anything. But VTU ALSO walks every key that
 *    ends up in the merged stub map and pre-registers an empty placeholder
 *    component under that EXACT string ("users expect stubs to work with
 *    globally registered components", vue-test-utils.cjs.js) if nothing is
 *    already registered under it — and Vuetify only ever registers its real
 *    components under the PascalCase name ("VSelect"), never the kebab tag
 *    ("v-select"). That placeholder then wins template resolution ahead of
 *    the real "VSelect" registration, and the component renders blank with a
 *    "Component is missing template or render function" warning. The key
 *    must be ABSENT from the final merged stub map, not merely `false` in
 *    it — which means removing it from the `config.global.stubs` singleton
 *    itself, not from a per-mount override.
 *
 * `withRealVuetify(names)` does that removal SCOPED to one mount: it deletes
 * the requested names from the shared `config.global.stubs` singleton and
 * returns a `restore()` that puts them back. Always call `restore()` (a
 * try/finally, or an `afterEach`) — leaving it off would leak the real
 * component into every OTHER test that shares this test file's module
 * instance of `config.global.stubs`.
 *
 * Real components pull in their own dependencies — VSelect renders VMenu,
 * VOverlay, VField, VList, VListItem internally. Un-stubbing only VSelect
 * still leaves ITS INTERNALS on the flat stub, and the menu will not open.
 * Pass every name your assertions need real, e.g.
 * `['VSelect', 'VMenu', 'VOverlay', 'VList', 'VListItem', 'VField', 'VIcon']`.
 *
 * Next author reaching for this: it exists so a spec can prove a real Vuetify
 * slot renders correctly. It is not a general "unstub everything" toggle —
 * keep the name list to what the assertion actually needs, and prefer the
 * fast flat stub everywhere else in the same mount.
 */
import { vi } from 'vitest'
import { config } from '@vue/test-utils'

// Vuetify names are PascalCase with a single-letter "V" prefix (VSelect,
// VListItem, VDataTableServer), not camelCase -- the usual camelCase->kebab
// regex (lower-then-upper boundary) never fires on the leading "VS" pair, so
// it silently produces "vselect" instead of "v-select" and the override
// misses tests/setup.js's actual kebab key. Insert a hyphen before every
// uppercase letter except the first instead.
function toKebab(name) {
  return name.replace(/[A-Z]/g, (letter, offset) => (offset > 0 ? '-' : '') + letter).toLowerCase()
}

/**
 * Builds a real Vuetify plugin instance (bypassing tests/setup.js's mocks for
 * this call only, via `vi.importActual`) for withRealVuetify.
 */
async function createRealVuetify(options = {}) {
  const [{ createVuetify }, components, directives] = await Promise.all([
    vi.importActual('vuetify'),
    vi.importActual('vuetify/components'),
    vi.importActual('vuetify/directives'),
  ])
  return createVuetify({ components, directives, ...options })
}

/**
 * Opts the given PascalCase Vuetify names (e.g. `['VSelect', 'VListItem']`)
 * into REAL rendering for the duration of one mount. Returns `{ plugin,
 * restore }`: pass `plugin` as a `global.plugins` entry, mount as normal with
 * NO `global.stubs` override of your own for these names, then call
 * `restore()` (try/finally or `afterEach`) to put tests/setup.js's stub map
 * back for every test that runs after this one.
 */
export async function withRealVuetify(names) {
  const plugin = await createRealVuetify()
  const removedKeys = []
  for (const name of names) {
    for (const key of [name, toKebab(name)]) {
      if (key in config.global.stubs) {
        removedKeys.push([key, config.global.stubs[key]])
        delete config.global.stubs[key]
      }
    }
  }
  return {
    plugin,
    restore() {
      for (const [key, value] of removedKeys) {
        config.global.stubs[key] = value
      }
    },
  }
}
