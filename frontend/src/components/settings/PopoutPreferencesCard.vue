<!--
  PopoutPreferencesCard.vue — FE-9553

  The browser popout card. Two rules from the record shape it, and both are
  about not lying to the operator.

  1. THE BROWSER PERMISSION IS STATUS, NEVER A TOGGLE WE OWN. We cannot grant or
     revoke it; only the browser can, per browser and per device. So a BLOCKED
     permission renders no switch at all — just the state and how to fix it.
     Rendering a switch we cannot honour is the definition of a control that
     lies, and a control we cannot honour must not look live.

  2. THE SCOPE CAN ONLY EVER BE "HOW MUCH OF THE BANNER DO I PROJECT". There is
     deliberately no independent category matrix here, and that absence is what
     stops the settings grid growing back — a popout is a delivery medium for a
     banner, not a class of notification with its own rules.

  Advisories never pop regardless of this setting: the classifier decides what
  is advisory, so this control has three positions rather than four.
-->
<template>
  <v-card variant="flat" class="smooth-border settings-card" data-test="popout-preferences">
    <v-card-text>
      <h3 class="text-body-large mb-1">Browser pop-ups</h3>
      <p class="text-body-medium text-muted-a11y mb-4">
        The same banners, delivered by your operating system when this app is hidden. While
        you are looking at it, the banner alone tells you.
      </p>

      <div class="pref-row pref-row--static" data-test="popout-permission-status">
        <v-icon size="18" :color="permission.color" class="mr-3">{{ permission.icon }}</v-icon>
        <div>
          <div class="text-body-medium">{{ permission.label }}</div>
          <div class="text-body-small text-muted-a11y">{{ permission.hint }}</div>
        </div>
      </div>

      <!--
        FE-9592: the ask has to have a control of its own.

        Before this button the only way to reach the browser prompt was to
        CHANGE the scope radio, and the scope already defaults to "everything".
        An operator who is happy with that default never changes it, so the
        prompt never appeared and pop-outs silently never worked. The button is
        deliberately a labelled control rather than making the already-selected
        radio ask again: a radio you re-select emits nothing, so that variant
        would be an unlabelled click target -- fixing a discoverability defect
        with something undiscoverable.

        Not shown on 'off'. The operator has said they want nothing, and asking
        for a capability they have just declined is how a site gets permanently
        blocked. Not shown once answered either: `permission.state` is only
        'default' while the browser genuinely has no answer.
      -->
      <div v-if="canAsk" class="pref-row pref-row--static">
        <v-btn
          color="primary"
          variant="flat"
          :loading="asking"
          data-test="popout-request-permission-btn"
          @click="askForPermission"
        >
          Turn on pop-ups
        </v-btn>
      </div>

      <!--
        No scope control when the browser has blocked us. The setting would be
        real but inert, and an inert control that looks live is worse than an
        honest explanation of why it is absent.
      -->
      <template v-if="permission.state !== 'denied' && permission.state !== 'unsupported'">
        <v-divider class="my-4" />
        <v-radio-group
          :model-value="settings.popoutScope"
          hide-details
          density="compact"
          :disabled="saving"
          data-test="popout-scope-group"
          @update:model-value="save"
        >
          <template #label>
            <span class="text-body-medium">How much to send</span>
          </template>
          <v-radio value="all" data-test="popout-scope-all">
            <template #label>
              <span>
                Everything a banner shows
                <span class="text-body-small text-muted-a11y">
                  — anything asking for you, plus projects starting and finishing
                </span>
              </span>
            </template>
          </v-radio>
          <v-radio value="actionable" data-test="popout-scope-actionable">
            <template #label>
              <span>
                Only things asking for you
                <span class="text-body-small text-muted-a11y">
                  — decisions, your turn, mentions
                </span>
              </span>
            </template>
          </v-radio>
          <v-radio value="off" data-test="popout-scope-off">
            <template #label><span>Nothing</span></template>
          </v-radio>
        </v-radio-group>
      </template>

      <p v-if="error" class="text-body-small mt-3" data-test="popout-prefs-error">
        <v-icon size="16" color="error" class="mr-1">mdi-alert-circle</v-icon>
        Could not save that. Your setting is unchanged.
      </p>
    </v-card-text>
  </v-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import { useSettingsStore } from '@/stores/settings'

const settings = useSettingsStore()
const saving = ref(false)
const asking = ref(false)
const error = ref(false)

/**
 * Read on mount, then updated by us -- never polled.
 *
 * Notification.permission has no change event in every browser we support, and
 * a poll would spend a timer watching for a transition the operator cannot make
 * from this page. The one thing that CAN change it while the card is open is
 * this card asking, so the two places that ask write the answer back here.
 */
const permissionState = ref('default')

onMounted(() => {
  permissionState.value =
    typeof Notification === 'undefined' ? 'unsupported' : Notification.permission
  settings.loadNotificationPrefs()
})

const permission = computed(() => {
  switch (permissionState.value) {
    case 'granted':
      return {
        state: 'granted',
        icon: 'mdi-bell-ring-outline',
        color: 'success',
        label: 'Your browser allows pop-ups from this app',
        hint: 'Nothing else to do here.',
      }
    case 'denied':
      return {
        state: 'denied',
        icon: 'mdi-bell-off-outline',
        color: 'warning',
        label: 'Your browser is blocking pop-ups from this app',
        hint: 'To turn them on, open your browser’s site settings for this address and allow notifications. Nothing is lost meanwhile: everything still appears in the title bar and the bell.',
      }
    case 'unsupported':
      return {
        state: 'unsupported',
        icon: 'mdi-bell-off-outline',
        color: 'grey',
        label: 'This browser does not support pop-ups',
        hint: 'Everything still appears in the title bar and the bell.',
      }
    default:
      return {
        state: 'default',
        icon: 'mdi-bell-outline',
        color: 'info',
        label: 'Your browser has not been asked yet',
        hint: 'Until you ask it, nothing pops up. Use “Turn on pop-ups” below — your browser will ask you once, and only you can answer it.',
      }
  }
})

/**
 * FE-9592: is there anything left for the operator to ask for?
 *
 * Only 'default' -- a browser that has already answered, either way, cannot be
 * asked again by us, and 'off' means they have said they want none of this.
 */
const canAsk = computed(
  () => permissionState.value === 'default' && settings.popoutScope !== 'off',
)

/**
 * The one place that touches Notification.requestPermission.
 *
 * Both callers -- the explicit button and a scope change -- need identical
 * handling of the answer and of the browsers that hand back a callback rather
 * than a promise, or throw outright. One implementation means the two entry
 * points cannot drift into disagreeing about what a refusal looks like.
 *
 * The card read the permission once on mount, on the reasoning that it could
 * not change while open. This card now changes it, so the display follows.
 */
async function requestPermissionNow() {
  try {
    const answer = await Notification.requestPermission()
    permissionState.value = answer || Notification.permission
  } catch {
    // Older browsers hand back a callback rather than a promise, and some
    // embeddings throw. Neither is a reason to drop the operator's setting.
    permissionState.value =
      typeof Notification === 'undefined' ? 'unsupported' : Notification.permission
  }
}

/**
 * FE-9592: the explicit ask.
 *
 * A button press is a user gesture in a visible tab, which is the exact
 * condition a browser honours -- the same condition the scope radio satisfied,
 * now reachable without changing a setting the operator is happy with. It
 * writes nothing: the scope is already stored, and this only settles the
 * browser's half.
 */
async function askForPermission() {
  asking.value = true
  try {
    await requestPermissionNow()
  } finally {
    asking.value = false
  }
}

/**
 * FE-9553d: ask the browser for permission HERE, on the operator's gesture.
 *
 * Until this existed, pop-outs could never fire on a fresh profile at all. The
 * only requestPermission call lived in the signal path, which by ruling 4(a)
 * runs only when the app is HIDDEN -- and a browser silently ignores a
 * permission request from a hidden tab. So the ask could only happen at the one
 * moment the browser refuses to honour it: chicken-and-egg, invisible, and
 * unreachable by any amount of using the app. That was a consequence of ruling
 * 4(a) rather than an oversight somewhere else, which is why the remedy belongs
 * here rather than in a looser gate there.
 *
 * Choosing a scope is a real gesture in a visible tab, which is exactly the
 * condition a browser honours. It is also the honest moment: the operator has
 * just said they want pop-outs, so being asked follows from what they did.
 *
 * ORDER IS DELIBERATE. The permission request goes FIRST, before the network
 * write. Browsers gate this on the user-gesture that led here, and awaiting an
 * API round-trip before asking risks landing outside that window -- which would
 * reintroduce the same silent failure by a slower route.
 *
 * Only when it is genuinely unanswered: `default`. Re-asking an already
 * granted or denied permission achieves nothing and is noise in the one place
 * a browser watches for abuse. And never on 'off' -- asking for a capability
 * the operator has just declined is how a site gets permanently blocked, and
 * the request cannot be taken back from our side.
 */
async function save(value) {
  saving.value = true
  error.value = false

  if (value !== 'off' && permissionState.value === 'default') {
    await requestPermissionNow()
  }

  try {
    // Saved even when the browser refuses: the preference is the operator's and
    // it outlives this browser. They may be signed in elsewhere, or grant
    // permission here later. Refusing to store their choice because THIS
    // browser said no would silently lose it.
    await settings.updateNotificationPrefs({ popoutScope: value })
  } catch {
    error.value = true
  } finally {
    saving.value = false
  }
}
</script>

<style scoped lang="scss">
.pref-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 0;

  &--static {
    align-items: center;
  }
}
</style>
