
const LICENSE_NAME = 'Elastic License 2.0'

const licenseCopy = {
  ce: {
    editionLabel: 'Community Edition',
    tagline: 'Self-hosted AI agent orchestration. Run it yourself or your team.',
    longDescription:
      'Free under the Elastic License 2.0. The license restricts only managed-service redistribution to third parties, license-key tampering, and removal of copyright notices — internal team and company use is fine.',
    licenseLine: LICENSE_NAME,
    ctaLabel: 'Download',
  },
  solo: {
    editionLabel: 'Solo',
    tagline: 'GiljoAI for one organization, hosted by us.',
    longDescription:
      'Your hosted Solo subscription includes automatic updates, daily backups, and email support.',
    licenseLine: 'Commercial — Solo',
    ctaLabel: 'Start Solo',
  },
  team: {
    editionLabel: 'Team',
    tagline: 'GiljoAI for multi-seat teams, hosted by us.',
    longDescription:
      'Multi-seat commercial subscription with shared organizations, role-based access, and priority support. Provided under a Commercial License separate from ELv2.',
    licenseLine: 'Commercial — Team',
    ctaLabel: 'Start Team',
  },
}

const MODE_ALIASES = {
  ce: 'ce',
  '': 'ce',
  saas: 'solo',
  'saas-production': 'solo',
  solo: 'solo',
  team: 'team',
}

export function getLicenseCopy(modeOrEdition) {
  const key = MODE_ALIASES[modeOrEdition] || modeOrEdition
  return licenseCopy[key] || licenseCopy.ce
}

export const LICENSE_NAME_FULL = LICENSE_NAME
