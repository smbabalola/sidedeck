/** @type {import("tailwindcss").Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
module.exports = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        canvas: v("canvas"), panel: v("panel"), raised: v("raised"), rule: v("rule"),
        ink: v("ink"), muted: v("muted"), faint: v("faint"),
        accent: v("accent"), attention: v("attention"), gain: v("gain"), loss: v("loss"),
      },
      fontFamily: { sans: ['"IBM Plex Sans"', "ui-sans-serif", "system-ui", "sans-serif"] },
      fontSize: { "2xs": ["0.6875rem", "1rem"] },
    },
  },
  plugins: [],
};
