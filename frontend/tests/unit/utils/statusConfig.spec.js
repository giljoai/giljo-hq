import { describe, it, expect } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import {
  STATUS_COLORS,
  isAwaitingUser,
  getStatusLabel,
  getStatusColor
} from '@/utils/statusConfig';

describe('statusConfig.js', () => {
  describe('isAwaitingUser', () => {
    it('returns true only when status is awaiting_user', () => {
      expect(isAwaitingUser('awaiting_user')).toBe(true);
    });

    it('returns false for any other status', () => {
      expect(isAwaitingUser('working')).toBe(false);
      expect(isAwaitingUser('blocked')).toBe(false);
      expect(isAwaitingUser('complete')).toBe(false);
      expect(isAwaitingUser(null)).toBe(false);
      expect(isAwaitingUser(undefined)).toBe(false);
    });
  });

  describe('getStatusLabel with awaiting_user', () => {
    it('returns Needs decision for awaiting_user', () => {
      expect(getStatusLabel('awaiting_user')).toBe('Needs decision');
    });

    it('returns Blocked for plain blocked agent', () => {
      expect(getStatusLabel('blocked')).toBe('Blocked');
    });

    it('returns normal label for other statuses', () => {
      expect(getStatusLabel('working')).toBe('Working');
    });
  });

  describe('getStatusColor with awaiting_user', () => {
    it('returns amber for awaiting_user', () => {
      expect(getStatusColor('awaiting_user')).toBe('#ffc107');
    });

    it('returns red for blocked (FE-9687: orange is kept for a decision)', () => {
      expect(getStatusColor('blocked')).toBe('#f44336');
    });
  });

  // FE-9296b: the indicator distinguishes wake-waiting / timed sleep / dark.
  // The markers are structured (built by set_agent_status server-side), so the
  // label derives from mechanism, not from free prose.
  describe('getStatusLabel sleeping variants (FE-9296b)', () => {
    it('labels a wake-parked agent as Waiting for wake', () => {
      expect(getStatusLabel('sleeping', 'Waiting for Hub activity | wake_mode=signal')).toBe(
        'Waiting for wake'
      );
      expect(getStatusLabel('sleeping', 'wake_mode=signal')).toBe('Waiting for wake');
    });

    it('labels a timed sleep with its countdown', () => {
      expect(getStatusLabel('sleeping', 'Auto check-in: sleeping for 10 minutes | wake_in_minutes=10')).toBe(
        'Sleeping (10m)'
      );
      expect(getStatusLabel('sleeping', 'wake_in_minutes=30')).toBe('Sleeping (30m)');
    });

    it('falls back to plain Sleeping without a marker', () => {
      expect(getStatusLabel('sleeping')).toBe('Sleeping');
      expect(getStatusLabel('sleeping', 'just resting')).toBe('Sleeping');
      expect(getStatusLabel('sleeping', null)).toBe('Sleeping');
    });

    it('keeps dark as the distinct silent status', () => {
      expect(getStatusLabel('silent')).toBe('Silent');
      // markers on a non-sleeping status change nothing
      expect(getStatusLabel('silent', 'wake_in_minutes=10')).toBe('Silent');
    });

    it('wake signal wins when both markers appear', () => {
      expect(getStatusLabel('sleeping', 'wake_mode=signal | wake_in_minutes=5')).toBe(
        'Waiting for wake'
      );
    });
  });

  describe('STATUS_COLORS is the one status colour map', () => {
    const SCSS_NAME = {
      WAITING: 'waiting',
      WORKING: 'working',
      BLOCKED: 'blocked',
      SILENT: 'silent',
      COMPLETE: 'complete',
      IDLE: 'idle',
      SLEEPING: 'sleeping',
      HANDED_OVER: 'handed-over',
      CLOSED: 'closed',
      DECOMMISSIONED: 'decommissioned',
      CLOSEOUT: 'staged',
      PENDING: 'pending',
    };

    function readTokens(file, re) {
      const text = readFileSync(resolve(__dirname, '../../../src/styles', file), 'utf-8');
      return Object.fromEntries([...text.matchAll(re)].map((m) => [m[1], m[2].toLowerCase()]));
    }

    const scss = readTokens('design-tokens.scss', /\$color-status-([a-z-]+):\s*(#[0-9a-fA-F]{6})/g);
    const css = readTokens('main.scss', /--color-status-([a-z-]+):\s*(#[0-9a-fA-F]{6})/g);

    it('has a design-tokens.scss $color-status-* twin for every status key', () => {
      const drift = Object.entries(SCSS_NAME)
        .filter(([key, name]) => scss[name] !== STATUS_COLORS[key]?.toLowerCase())
        .map(([key, name]) => `${key}=${STATUS_COLORS[key]} vs $color-status-${name}=${scss[name]}`);
      expect(drift).toEqual([]);
    });

    it('keeps the main.scss --color-status-* mirrors equal to the SCSS tokens', () => {
      const statusNames = new Set(Object.values(SCSS_NAME));
      const drift = Object.entries(css)
        .filter(([name]) => statusNames.has(name))
        .filter(([name, hex]) => scss[name] !== hex)
        .map(([name, hex]) => `--color-status-${name}=${hex} vs ${scss[name]}`);
      expect(drift).toEqual([]);
    });

    it('covers every key the map defines except the unknown-status fallback', () => {
      const keys = Object.keys(STATUS_COLORS).filter((k) => k !== 'FALLBACK').sort();
      expect(keys).toEqual(Object.keys(SCSS_NAME).sort());
    });
  });
});
