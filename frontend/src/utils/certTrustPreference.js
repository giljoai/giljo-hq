export function recordCertTrustDismissal(dontShowAgain = false) {
  sessionStorage.setItem('cert_modal_dismissed', '1')
  if (dontShowAgain) {
    localStorage.setItem('cert_modal_never', '1')
  }
}
