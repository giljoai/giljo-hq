/**
 * colorTokens.js — Canonical JS color constants for components that call hexToRgba()
 * or pass hex values to Vuetify color props.
 *
 * These constants mirror design-tokens.scss and main.scss `:root` values.
 * Keep in sync with those files — they remain the single source of compile-time truth.
 *
 * WHY HEX STRINGS (not var()): hexToRgba() does arithmetic on the hex digits and
 * requires a real hex string. Using var() or $scss-token would break the computation.
 *
 * FE-6006 unit-1: consolidates ~26 duplicated JS color literals across 13 files.
 */

// ---------------------------------------------------------------------------
// Text / muted
// ---------------------------------------------------------------------------

/** --text-muted (#8895a8): WCAG 4.98:1 on dark surfaces. Used in message/role badges. */
export const TEXT_MUTED = '#8895a8'

/** $color-text-muted / --color-text-muted (#9e9e9e): Material grey, dashboard/project
 *  status fallback and getComputedStyle() resolveColorToken() fallback. */
export const TEXT_MUTED_MATERIAL = '#9e9e9e'

/** $lightest-blue / $color-scrollbar-thumb-hover-background (#8f97b7): Used in
 *  SetupStep2Connect and SetupStep3Commands as the "loading/muted" progress indicator. */
export const TEXT_MUTED_BLUE = '#8f97b7'

/** $color-text-secondary (#999): labels/headers on dark panels. FE-9548: the Jobs
 *  board's Staged lifecycle edge/pill color. */
export const TEXT_SECONDARY = '#999'

// ---------------------------------------------------------------------------
// Status: semantic project / agent status colors
// ---------------------------------------------------------------------------

/** $color-status-complete / --color-accent-success (#67bd6d): completed project / agent. */
export const COLOR_COMPLETE = '#67bd6d'

/** $color-brand-yellow / --color-accent-primary (#ffc300): brand; also cancelled status. */
export const COLOR_BRAND = '#ffc300'

/** $color-status-failed / --color-accent-danger (#c6298c): failed / terminated. */
export const COLOR_FAILED = '#c6298c'

/** $color-status-staged (#ffc107): staged / awaiting-decision status. */
export const COLOR_STAGED = '#ffc107'

// ---------------------------------------------------------------------------
// Status: dot/indicator variants (used in ProjectsView status dots)
// ---------------------------------------------------------------------------

/** Material green (#4caf50): generic success dot in ProjectsView. Distinct from
 *  $color-status-complete (#67bd6d) — do not merge. */
export const DOT_SUCCESS = '#4caf50'

/** Material deep-orange lighten-1 (#fb8c00): cancelled status dot.
 *  Distinct from $color-status-blocked (#ff9800) — do not merge. */
export const DOT_WARNING = '#fb8c00'

/** Material red (#f44336): terminated/deleted status dot.
 *  Distinct from $color-status-failed (#c6298c) — do not merge. */
export const DOT_ERROR = '#f44336'

// ---------------------------------------------------------------------------
// Setup progress icon green (SetupStep2Connect, SetupStep3Commands)
// ---------------------------------------------------------------------------

/** $gradient-brand-end (#6bcf7f): success check icon in setup steps. */
export const COLOR_SUCCESS_SETUP = '#6bcf7f'

// ---------------------------------------------------------------------------
// Integration card accent colors (GitIntegrationCard, SerenaIntegrationCard)
// ---------------------------------------------------------------------------

/** $color-card-git (#90CAF9): Light blue accent for Git integration card. */
export const COLOR_CARD_GIT = '#90CAF9'

/** $color-card-serena (#CE93D8): Light purple accent for Serena integration card. */
export const COLOR_CARD_SERENA = '#CE93D8'
