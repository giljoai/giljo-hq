import configService from '@/services/configService'


export function isCeModeValue(mode) {
  return mode === 'ce'
}

export function isSaasModeValue(mode) {
  return mode === 'saas' || mode === 'saas-production'
}

export function useGiljoMode() {
  function getMode() {
    return configService.getGiljoMode()
  }

  function isCeMode() {
    return isCeModeValue(getMode())
  }

  function isSaasMode() {
    return isSaasModeValue(getMode())
  }

  return { getMode, isCeMode, isSaasMode }
}
