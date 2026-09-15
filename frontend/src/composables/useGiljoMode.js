import configService from '@/services/configService'


export function isCeModeValue(mode) {
  return mode === 'ce'
}

export function isSaasModeValue(mode) {
  return mode === 'saas' || mode === 'saas-production'
}

export function isNonCeModeValue(mode) {
  return mode !== 'ce'
}

export function useGiljoMode() {
  function getMode() {
    return configService.getGiljoMode()
  }

  function isCeMode() {
    return getMode() === 'ce'
  }

  function isSaasMode() {
    const m = getMode()
    return m === 'saas' || m === 'saas-production'
  }

  function isNonCeMode() {
    return getMode() !== 'ce'
  }

  return { getMode, isCeMode, isSaasMode, isNonCeMode }
}
