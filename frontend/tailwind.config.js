/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        podgist: {
          DEFAULT: '#008080', // 咱们的极光青主色调
          light: '#F0FDFD',
        }
      }
    },
  },
  plugins: [],
}
