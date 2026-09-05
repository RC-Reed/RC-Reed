/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Console surfaces — dark, low-chroma, so data colors carry the signal.
        ink: {
          900: "#0d1017",
          850: "#11151d",
          800: "#151a23",
          750: "#1a212c",
          700: "#212a38",
          600: "#2c384a",
          500: "#3d4c63",
        },
        muted: { DEFAULT: "#8b9bb4", strong: "#b7c3d6" },
        // Validated categorical slots (dark column). See docs/architecture.md.
        series: {
          1: "#3987e5",
          2: "#d95926",
          3: "#199e70",
          4: "#c98500",
          5: "#d55181",
          6: "#9085e9",
        },
        status: {
          good: "#199e70",
          warning: "#c98500",
          critical: "#e66767",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
