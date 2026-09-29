import { getAgentColor } from '@/config/agentColors'
import { hexToRgba } from '@/utils/colorUtils'

export const JOBS_BOARD_PATH = '/jobs-overview'

export function resolveJobsNavPath() {
  return JOBS_BOARD_PATH
}

export function isJobsRouteActive(path, query) {
  if (query?.via === 'jobs') return true
  if (path === JOBS_BOARD_PATH || path.startsWith(`${JOBS_BOARD_PATH}/`)) return true
  if (path.startsWith('/projects/')) return true
  return false
}

export const JOBS_NAV_ICON_ACTIVE = '/icons/Giljo_YW_Face.svg'
export const JOBS_NAV_ICON_INACTIVE = '/icons/Giljo_Inactive_Dark.svg'

export function resolveJobsNavIcon(path, query) {
  return isJobsRouteActive(path, query) ? JOBS_NAV_ICON_ACTIVE : JOBS_NAV_ICON_INACTIVE
}

export function hubUnreadBadgeStyle() {
  const hex = getAgentColor('implementer')?.hex
  return {
    backgroundColor: hexToRgba(hex, 0.2),
    color: hex,
    borderRadius: '8px',
    fontSize: '0.6rem',
    fontWeight: '700',
    padding: '1px 5px',
    minWidth: '16px',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    lineHeight: '1',
  }
}
