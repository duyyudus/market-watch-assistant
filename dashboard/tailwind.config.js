export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        zinc: {
          50: "rgb(var(--zinc-50) / <alpha-value>)",
          100: "rgb(var(--zinc-100) / <alpha-value>)",
          200: "rgb(var(--zinc-200) / <alpha-value>)",
          300: "rgb(var(--zinc-300) / <alpha-value>)",
          400: "rgb(var(--zinc-400) / <alpha-value>)",
          500: "rgb(var(--zinc-500) / <alpha-value>)",
          600: "rgb(var(--zinc-600) / <alpha-value>)",
          700: "rgb(var(--zinc-700) / <alpha-value>)",
          800: "rgb(var(--zinc-800) / <alpha-value>)",
          900: "rgb(var(--zinc-900) / <alpha-value>)",
          950: "rgb(var(--zinc-950) / <alpha-value>)",
        },
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: [
      {
        emerald_light: {
          primary: "#059669",
          "primary-content": "#ffffff",
          secondary: "#059669",
          accent: "#d97706",
          neutral: "#0d9488",
          "neutral-content": "#ffffff",
          "base-100": "#d4d4d8",
          "base-200": "#e4e4e7",
          "base-300": "#a1a1aa",
          "base-content": "#09090b",
          info: "#0284c7",
          success: "#059669",
          warning: "#ca8a04",
          error: "#dc2626",
        },
      },
      {
        emerald_dark: { // Financial Emerald
          primary: "#10b981",
          secondary: "#10b981",
          accent: "#f59e0b",
          neutral: "#2c2c30",
          "base-100": "#121214",
          "base-200": "#1a1a1e",
          "base-300": "#2c2c30",
          "base-content": "#a1a1aa",
          info: "#38bdf8",
          success: "#10b981",
          warning: "#fbbf24",
          error: "#ef4444",
        },
      },
    ],
  },
};
