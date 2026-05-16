import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        forge: {
          bg: '#0B0F19',
          dark: '#111827',
          card: '#1E293B',
          'card-hover': '#334155',
          elevated: '#0F172A',
        },
        border: 'rgba(148,163,184,0.1)',
        input: 'rgba(148,163,184,0.15)',
        ring: '#06B6D4',
        background: '#0B0F19',
        foreground: '#F8FAFC',
        primary: {
          DEFAULT: '#06B6D4',
          foreground: '#F8FAFC',
        },
        secondary: {
          DEFAULT: '#1E293B',
          foreground: '#CBD5E1',
        },
        destructive: {
          DEFAULT: '#EF4444',
          foreground: '#F8FAFC',
        },
        muted: {
          DEFAULT: '#1E293B',
          foreground: '#94A3B8',
        },
        accent: {
          DEFAULT: '#A855F7',
          foreground: '#F8FAFC',
        },
        card: {
          DEFAULT: '#1E293B',
          foreground: '#F8FAFC',
        },
      },
      borderRadius: {
        lg: '12px',
        md: '8px',
        sm: '6px',
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('tailwindcss-animate'),
  ],
};

export default config;
