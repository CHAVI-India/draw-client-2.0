/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './dicom_handler/templates/**/*.html',
    './dicom_server/templates/**/*.html',
    './spatial_overlap/templates/**/*.html',
    './user/templates/**/*.html',
    './static/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eff6ff',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
        },
        // Deep ink navy used for the navigation bar
        ink: {
          50: '#eef2f8',
          100: '#d8e0ee',
          200: '#b3c2d9',
          300: '#8298ba',
          400: '#55698e',
          500: '#384b6e',
          600: '#263652',
          700: '#1a2640',
          800: '#121c31',
          900: '#0b1526',
        },
      },
      fontFamily: {
        // Brand wordmark / display headings
        brand: ['Figtree', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        // Navigation links and UI labels
        nav: ['"Noto Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    }
  },
  plugins: [],
}
