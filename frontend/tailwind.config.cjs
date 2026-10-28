// The prototype's palette as Tailwind tokens: ink (text), line (borders), page (background),
// side (the dark sidebar), and the four semantics — human (pink: needs a person), agent
// (indigo), ok (green), warn (amber), bad (red).
module.exports = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      colors: {
        ink: { DEFAULT: '#14161B', soft: '#3A3F4B', muted: '#5A6170' },
        line: { DEFAULT: '#DFE2E8', soft: '#EEF0F3', strong: '#C9CDD6', hover: '#9097A6' },
        page: '#F4F5F7',
        side: { DEFAULT: '#14161B', hover: '#22252D', on: '#2A2E38', text: '#C3C7D1', muted: '#9AA0AD', border: '#3A3E49' },
        human: { DEFAULT: '#A3134B', bg: '#FCE8EF', strong: '#C2185B' },
        agent: { DEFAULT: '#3B38B8', bg: '#ECEBFA', hover: '#26238A', soft: '#F7F7FE', row: '#F3F3FD' },
        ok: { DEFAULT: '#1E6B35', bg: '#E3F2E6' },
        warn: { DEFAULT: '#8A4F00', bg: '#FBEFD9' },
        bad: { DEFAULT: '#B42318', bg: '#FDECEA', row: '#FFF7F6' },
        muted: { bg: '#EEF0F3' },
      },
      borderRadius: { card: '12px', ctl: '8px', item: '10px' },
    },
  },
  plugins: [],
};
