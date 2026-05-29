export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [require("daisyui")],
  daisyui: {
    themes: [
      {
        marketwatch: { // Minimalist Mono (default)
          primary: "#f4f4f5",      // Crisp Zinc-100 Silver
          secondary: "#10b981",    // Emerald green
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
      {
        emerald_terminal: { // Financial Emerald
          primary: "#10b981",      // Bloomberg Emerald accent
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
      {
        amber_bronze: { // Amber Bronze
          primary: "#d97706",      // Calmer Cozy Gold Amber accent
          secondary: "#10b981",
          accent: "#d97706",
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
