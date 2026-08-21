import { describe, it, expect } from 'vitest';
import {
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
    it('returns Decision Required for awaiting_user', () => {
      expect(getStatusLabel('awaiting_user')).toBe('Decision Required');
    });

    it('returns Needs Input for plain blocked agent', () => {
      expect(getStatusLabel('blocked')).toBe('Needs Input');
    });

    it('returns normal label for other statuses', () => {
      expect(getStatusLabel('working')).toBe('Working');
    });
  });

  describe('getStatusColor with awaiting_user', () => {
    it('returns amber for awaiting_user', () => {
      expect(getStatusColor('awaiting_user')).toBe('#ffc107');
    });

    it('returns orange for blocked', () => {
      expect(getStatusColor('blocked')).toBe('#ff9800');
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
});
