/**
 * hubAvatarAssets.fe9439.spec.js — FE-9439 items 4 + 7
 *
 * Two asset facts that no component test can reach, because both are about files on
 * disk and about a path resolving on an operating system this suite does not run on.
 *
 * WHY THIS EXISTS AT ALL
 *
 * `frontend/public/` shipped TWO byte-identical copies of the face mark:
 * `giljo_YW_Face.svg` (lowercase `g`, public root) and `icons/Giljo_YW_Face.svg`
 * (capital `G`). Windows is case-insensitive, so on the development workstation both
 * paths resolve and the duplicate is invisible. **Linux — production, and every CE
 * self-hoster — treats them as different files.** A reference to one while only the
 * other ships is a broken image that cannot be reproduced on the machine it was written
 * on. That asymmetry is the whole reason these assertions are mechanical rather than
 * left to review: a human reading the diff on Windows has no way to see the bug.
 *
 * WHAT THIS PROVES AND WHAT IT DOES NOT
 *
 * It proves the shipped SOURCE names the surviving path and no longer names the deleted
 * one, and that the notification badge on disk is the shape the OS slot needs. It does
 * NOT prove the browser painted anything — that is what the component specs cover. The
 * scan is deliberately over source text, because the string in the source is precisely
 * what Linux will be asked to resolve at runtime.
 *
 * Edition scope: Both
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync, readdirSync, statSync } from 'node:fs'
import { join, resolve, extname } from 'node:path'

const FRONTEND = resolve(__dirname, '../../..')
const SRC = join(FRONTEND, 'src')
const PUBLIC = join(FRONTEND, 'public')

/** The duplicate FE-9439 removed. */
const DELETED_PATH = '/giljo_YW_Face.svg'
/** The one that survives, and the one every reference must now name. */
const CANONICAL_PATH = '/icons/Giljo_YW_Face.svg'
/** The desktop-notification badge added by item 4. */
const AVATAR = join(PUBLIC, 'icons', 'Giljo_Face_Avatar.png')

const SCANNED_EXTENSIONS = new Set(['.vue', '.js', '.ts', '.html', '.scss', '.css'])

function sourceFiles(dir, acc = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      sourceFiles(full, acc)
    } else if (SCANNED_EXTENSIONS.has(extname(entry))) {
      acc.push(full)
    }
  }
  return acc
}

/**
 * Files naming the deleted path, by NAME — never a count.
 *
 * Matched with the leading slash and a quote in front of it so this finds real
 * references (`src="/giljo_YW_Face.svg"`) and not the substring inside the canonical
 * `/icons/Giljo_YW_Face.svg`, which would otherwise match every correct reference and
 * make the assertion permanently and confusingly red.
 */
function filesReferencingDeletedPath() {
  return sourceFiles(SRC)
    .filter((file) => /["'(]\/giljo_YW_Face\.svg/i.test(readFileSync(file, 'utf8')))
    .map((file) => file.slice(FRONTEND.length + 1).replace(/\\/g, '/'))
}

/** Width and height straight out of the PNG IHDR chunk — bytes 16..23, big-endian. */
function pngDimensions(file) {
  const buf = readFileSync(file)
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
  expect(buf.subarray(0, 8).equals(signature)).toBe(true)
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) }
}

describe('FE-9439 — Hub avatar assets', () => {
  describe('item 7 — the case-duplicate face mark is gone', () => {
    it('the lowercase public-root duplicate no longer ships', () => {
      expect(existsSync(join(PUBLIC, 'giljo_YW_Face.svg'))).toBe(false)
    })

    it('the canonical /icons/ copy does ship', () => {
      expect(existsSync(join(PUBLIC, 'icons', 'Giljo_YW_Face.svg'))).toBe(true)
    })

    /**
     * The one that would have broken production. `NavigationDrawer.vue` referenced the
     * lowercase path for the collapsed-rail logo — the single hit in the whole app —
     * and deleting the file without repointing it first would have left the sidebar
     * logo blank on Linux while staying perfectly fine on Windows.
     */
    it('the collapsed-rail sidebar logo resolves under /icons/', () => {
      const drawer = readFileSync(join(SRC, 'components/navigation/NavigationDrawer.vue'), 'utf8')

      expect(drawer).toContain(CANONICAL_PATH)
      expect(/["'(]\/giljo_YW_Face\.svg/i.test(drawer)).toBe(false)
    })

    it('no source file anywhere references the deleted path', () => {
      // Asserted against the NAMES, so a failure says which files to fix rather than
      // how many there are.
      expect(filesReferencingDeletedPath()).toEqual([])
    })
  })

  describe('item 4 — the desktop-notification badge', () => {
    it('ships at the path the notification code names', () => {
      expect(existsSync(AVATAR)).toBe(true)
    })

    /**
     * Square matters concretely: the OS renders this badge in a square slot, and the
     * 1029x928 source would letterbox in it. Padded on the mark's own navy before the
     * downscale, so there is no bar of a foreign colour either.
     */
    it('is square, so it cannot letterbox in the OS notification slot', () => {
      const { width, height } = pngDimensions(AVATAR)

      expect(width).toBe(height)
      expect(width).toBe(192)
    })

    it('is small enough to be a badge rather than a payload', () => {
      // The 1029px source is ~47 KB for a slot that renders near 64px. Kept well under
      // it; this is a ceiling to catch a careless re-export, not a target.
      expect(statSync(AVATAR).size).toBeLessThan(20 * 1024)
    })

    it('is the path useHubNotifications actually passes to Notification', () => {
      const composable = readFileSync(join(SRC, 'composables/useHubNotifications.js'), 'utf8')

      expect(composable).toContain('/icons/Giljo_Face_Avatar.png')
      // The wordmark was the bug — it must not come back on this path.
      expect(composable).not.toContain("icon: '/Giljo_YW.svg'")
    })

    /**
     * The source filename carries `AMH`, which per the locked product-namespace registry
     * is Giljo Agent Message Hub — a DIFFERENT product. It must not enter this tree, and
     * a filename is exactly the kind of thing that gets copied in by reflex.
     */
    it('carries no other product name', () => {
      const icons = readdirSync(join(PUBLIC, 'icons'))

      expect(icons).toContain('Giljo_Face_Avatar.png')
      expect(icons.filter((f) => /amh/i.test(f))).toEqual([])
    })
  })
})
