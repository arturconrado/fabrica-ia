import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./hooks/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172026",
        line: "#D8DEE4",
        panel: "#FFFFFF",
        canvas: "#F5F7F8"
      }
    }
  },
  plugins: []
};

export default config;
