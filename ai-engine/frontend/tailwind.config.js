/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Status colors aligned with NORMAL/SUSPECT/CRITICAL classification.
        // We pick saturated, high-contrast values because SOC dashboards are
        // glanced at, not read carefully.
        normal:   { DEFAULT: '#10b981', soft: '#064e3b' },  // emerald
        suspect:  { DEFAULT: '#f59e0b', soft: '#78350f' },  // amber
        critical: { DEFAULT: '#ef4444', soft: '#7f1d1d' },  // red
        // Backgrounds: dark theme by default. SOC rooms are dim.
        ink:      '#0b0f17',
        panel:    '#111827',
        border:   '#1f2937',
        muted:    '#6b7280',
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
    },
  },
  plugins: [],
}