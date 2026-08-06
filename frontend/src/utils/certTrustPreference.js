/**
 * FE-9339: CertTrustModal offers "Don't show this again on this device", but the
 * modal only emits the tick — the host that mounted it has to store it. Three hosts
 * mount that modal now, so the write lives here once rather than being retyped (and
 * forgotten) at each door.
 *
 * Read side: WelcomeView.shouldShowCertModal() — 'cert_modal_never' suppresses the
 * modal for good on this device, 'cert_modal_dismissed' only for the browser session.
 */
export function recordCertTrustDismissal(dontShowAgain = false) {
  sessionStorage.setItem('cert_modal_dismissed', '1')
  if (dontShowAgain) {
    localStorage.setItem('cert_modal_never', '1')
  }
}
