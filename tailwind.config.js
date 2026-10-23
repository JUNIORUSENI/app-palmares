/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html', './apps/**/*.py'],
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui'] },
      colors: {
        sidebar: '#0f172a',
        accent: '#3b82f6',
      },
    },
  },
  plugins: [],
};
