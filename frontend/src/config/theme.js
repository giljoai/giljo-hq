// Vuetify Theme Configuration for Giljo HQ Dashboard
export const darkTheme = {
  dark: true,
  colors: {
    // Primary colors from docs/Website colors.txt
    background: '#091520', // Darkest blue (deepened for cosmic atmosphere)
    surface: '#12202e', // Almost as dark blue
    'surface-variant': '#182a3c', // A hue lighter dark blue
    primary: '#ffc300', // Yellow (brand color) - high contrast buttons
    'primary-darken-1': '#1e3147',
    'primary-lighten-1': '#8f97b7', // Lightest blue

    // Accent colors
    // NOTE: secondary is yellow for now for consistency. Future consideration:
    // use lightest blue (#8f97b7) for secondary in dark mode for visual variety
    secondary: '#ffc300', // Yellow (brand color) - same as primary for consistency
    success: '#67bd6d', // Green
    accent: '#8f97b7', // Lightest blue
    info: '#8f97b7', // Lightest blue
    warning: '#ffc300', // Yellow (brand color)
    error: '#c6298c', // Pink red

    // Custom status/highlight colors
    'highlight': '#ffd700', // Gold highlight (status text, badges)
    'highlight-hover': '#ffed4e', // Lighter gold (hover states)

    // Text colors
    'on-background': '#e1e1e1', // White gray
    'on-surface': '#e1e1e1',
    'on-surface-variant': '#c0c0c0', // Caption text
    'on-primary': '#0e1c2d', // Dark text on yellow buttons
    'on-secondary': '#0e1c2d', // Dark text on yellow (matches primary)
    'on-success': '#0e1c2d',
    'on-accent': '#0e1c2d',
    'on-info': '#0e1c2d',
    'on-warning': '#0e1c2d',
    'on-error': '#e1e1e1',
  },
}
