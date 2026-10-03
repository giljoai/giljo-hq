<template>
  <div>
    <div v-if="showTitle" class="tab-header mb-4">
      <h2 class="text-title-large">{{ title }}</h2>
      <p v-if="showInfoBanner" class="text-body-medium text-muted-a11y mt-1">{{ infoBannerText }}</p>
    </div>

    <v-card class="db-card smooth-border">
    <v-card-text>

      <v-row>
        <v-col cols="12" md="6">
          <v-text-field
            v-model="dbConfig.host"
            label="Host"
            variant="outlined"
            :readonly="readonly"
            :prepend-inner-icon="readonly ? 'mdi-lock' : undefined"
            hint="Database host address"
            persistent-hint
            aria-label="Database host"
            data-test="db-host"
          />
        </v-col>

        <v-col cols="12" md="6">
          <v-text-field
            v-model.number="dbConfig.port"
            label="Port"
            type="number"
            variant="outlined"
            :readonly="readonly"
            :prepend-inner-icon="readonly ? 'mdi-lock' : undefined"
            hint="Database port number"
            persistent-hint
            aria-label="Database port"
            data-test="db-port"
          />
        </v-col>

        <v-col cols="12" md="6">
          <v-text-field
            v-model="dbConfig.name"
            label="Database Name"
            variant="outlined"
            :readonly="readonly"
            :prepend-inner-icon="readonly ? 'mdi-lock' : undefined"
            hint="Name of the database"
            persistent-hint
            aria-label="Database name"
            data-test="db-name"
          />
        </v-col>

        <v-col cols="12" md="6">
          <v-text-field
            v-model="dbConfig.user"
            label="Username"
            variant="outlined"
            :readonly="readonly"
            :prepend-inner-icon="readonly ? 'mdi-lock' : undefined"
            hint="Database username"
            persistent-hint
            aria-label="Database username"
            data-test="db-user"
          />
        </v-col>

        <v-col cols="12">
          <v-text-field
            v-model="dbConfig.password"
            label="Password"
            type="password"
            variant="outlined"
            :readonly="readonly"
            :prepend-inner-icon="readonly ? 'mdi-lock' : undefined"
            hint="Database password (masked for security)"
            persistent-hint
            aria-label="Database password"
            data-test="db-password"
          />
        </v-col>
      </v-row>

      <v-alert v-if="loadError" type="error" variant="tonal" class="mt-4" role="alert" data-test="db-load-error">
        Could not load the database settings: {{ loadError }}
      </v-alert>

      <div v-if="showTestButton" class="mt-4 mb-4">
        <v-btn
          variant="flat"
          color="primary"
          size="large"
          :loading="testing"
          :disabled="testing || Boolean(loadError)"
          aria-label="Test database connection"
          data-test="test-connection-btn"
          @click="testConnection"
        >
          <v-icon start>mdi-database-check</v-icon>
          {{ testButtonText }}
        </v-btn>
      </div>

      <v-divider class="my-6" />

      <v-alert
        v-if="connectionTestResult"
        :type="connectionTestResult.success ? 'success' : 'error'"
        variant="tonal"
        class="mb-4"
        role="alert"
        :aria-live="connectionTestResult.success ? 'polite' : 'assertive'"
        data-test="test-result"
      >
        <div v-html="formatTestResultMessage(connectionTestResult)"></div>
      </v-alert>
    </v-card-text>

    <v-card-actions v-if="$slots.actions">
      <v-spacer />

      <slot name="actions"></slot>
    </v-card-actions>
  </v-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '@/services/api'
import { sanitizeHtml } from '@/composables/useSanitizeMarkdown'
import { escapeHtml } from '@/utils/escapeHtml'
import { parseErrorResponse } from '@/utils/errorMessages'


const props = defineProps({
  readonly: {
    type: Boolean,
    default: false,
  },
  showTestButton: {
    type: Boolean,
    default: true,
  },
  showTitle: {
    type: Boolean,
    default: false,
  },
  title: {
    type: String,
    default: 'PostgreSQL Database Connection',
  },
  showInfoBanner: {
    type: Boolean,
    default: true,
  },
  infoBannerText: {
    type: String,
    default: 'The database this server is connected to right now. It is set at installation and is read only here.',
  },
  testButtonText: {
    type: String,
    default: 'Test Connection',
  },
})

const emit = defineEmits(['connection-success', 'connection-error'])

const dbConfig = ref({
  host: '',
  port: null,
  name: '',
  user: '',
  password: '********',
})
const loadError = ref('')

const testing = ref(false)
const connectionTestResult = ref(null)

const testConnection = async () => {
  testing.value = true
  connectionTestResult.value = null

  try {
    const { data: result } = await api.settings.testDatabase()

    if (result.success) {
      connectionTestResult.value = {
        success: true,
        message: `Connected to PostgreSQL database '${dbConfig.value.name}' on ${dbConfig.value.host}:${dbConfig.value.port}`,
        details: {
          host: dbConfig.value.host,
          port: dbConfig.value.port,
          database: dbConfig.value.name,
          user: dbConfig.value.user,
        },
      }
      emit('connection-success', connectionTestResult.value)
    } else {
      connectionTestResult.value = {
        success: false,
        message: result.error || 'Database connection failed',
        error: result.error,
        code: result.code,
        suggestions: generateSuggestions(result),
      }
      emit('connection-error', connectionTestResult.value)
    }
  } catch (error) {
    connectionTestResult.value = {
      success: false,
      message: `Connection test failed: ${error.message}`,
      error: error.message,
      suggestions: generateSuggestions(error),
    }
    emit('connection-error', connectionTestResult.value)
  } finally {
    testing.value = false
  }
}

const loadSettings = async () => {
  loadError.value = ''
  try {
    const { data: config } = await api.settings.getDatabase()
    dbConfig.value = {
      host: config.host,
      port: config.port,
      name: config.name,
      user: config.user,
      password: '********',
    }
  } catch (error) {
    loadError.value = parseErrorResponse(error).message
    throw error
  }
}

const clearTestResult = () => {
  connectionTestResult.value = null
}

const formatTestResultMessage = (result) => {
  if (result.success) {
    return sanitizeHtml(escapeHtml(result.message))
  }

  let html = `<strong>${escapeHtml(result.message)}</strong>`

  if (result.suggestions && result.suggestions.length > 0) {
    html += '<div class="mt-2 text-body-small"><strong>Possible causes:</strong></div>'
    html += '<ul class="mt-1 ml-4">'
    result.suggestions.forEach((suggestion) => {
      html += `<li class="text-body-small">${escapeHtml(suggestion)}</li>`
    })
    html += '</ul>'
  }

  return sanitizeHtml(html)
}

const generateSuggestions = (error) => {
  const suggestions = []
  const errorMsg = error.message || error.error || ''

  if (errorMsg.includes('ECONNREFUSED') || errorMsg.includes('Connection refused')) {
    suggestions.push('PostgreSQL service may not be running')
    suggestions.push('Verify PostgreSQL is installed and started')
    suggestions.push('Check if port 5432 is in use by another application')
  }

  if (errorMsg.includes('timeout') || errorMsg.includes('ETIMEDOUT')) {
    suggestions.push('Network timeout - check firewall settings')
    suggestions.push('Verify host address is correct')
  }

  if (errorMsg.includes('authentication') || errorMsg.includes('password')) {
    suggestions.push('Check username and password')
    suggestions.push('Verify PostgreSQL authentication configuration (pg_hba.conf)')
  }

  if (errorMsg.includes('database') && errorMsg.includes('does not exist')) {
    suggestions.push('Database may not have been created during installation')
    suggestions.push('Run database initialization script')
  }

  if (suggestions.length === 0) {
    suggestions.push('Check PostgreSQL service status')
    suggestions.push('Verify connection details are correct')
    suggestions.push('Review PostgreSQL logs for errors')
  }

  return suggestions
}

onMounted(() => loadSettings().catch(() => {}))

defineExpose({
  testConnection,
  loadSettings,
  clearTestResult,
})
</script>

<style lang="scss" scoped>
@use '../styles/design-tokens' as *;

.db-card {
  background: $elevation-raised;
  border-radius: $border-radius-rounded !important;
}

/* Improve readability of suggestion lists */
:deep(ul) {
  list-style-type: disc;
  padding-left: 1.5rem;
}

:deep(li) {
  margin-bottom: 0.25rem;
}
</style>
