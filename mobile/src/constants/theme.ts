import '@/global.css';

import { Platform } from 'react-native';

export const Palette = {
  bg: '#F7F8FA',
  bgAlt: '#EEF2F6',
  surface: '#FFFFFF',
  surfaceStrong: '#172033',
  border: '#DCE3EA',
  borderStrong: '#A9B6C3',
  text: '#182230',
  textMuted: '#64748B',
  textSoft: '#94A3B8',
  primary: '#0F766E',
  primaryDark: '#115E59',
  blue: '#2563EB',
  amber: '#B45309',
  red: '#DC2626',
  green: '#15803D',
  white: '#FFFFFF',
} as const;

export const Colors = {
  light: {
    text: Palette.text,
    background: Palette.bg,
    backgroundElement: Palette.surface,
    backgroundSelected: Palette.bgAlt,
    textSecondary: Palette.textMuted,
  },
  dark: {
    text: Palette.white,
    background: '#0B111C',
    backgroundElement: '#141D2B',
    backgroundSelected: '#223044',
    textSecondary: '#B7C2D0',
  },
} as const;

export type ThemeColor = keyof typeof Colors.light & keyof typeof Colors.dark;

export const Fonts = Platform.select({
  ios: {
    /** iOS `UIFontDescriptorSystemDesignDefault` */
    sans: 'system-ui',
    /** iOS `UIFontDescriptorSystemDesignSerif` */
    serif: 'ui-serif',
    /** iOS `UIFontDescriptorSystemDesignRounded` */
    rounded: 'ui-rounded',
    /** iOS `UIFontDescriptorSystemDesignMonospaced` */
    mono: 'ui-monospace',
  },
  default: {
    sans: 'normal',
    serif: 'serif',
    rounded: 'normal',
    mono: 'monospace',
  },
  web: {
    sans: 'var(--font-display)',
    serif: 'var(--font-serif)',
    rounded: 'var(--font-rounded)',
    mono: 'var(--font-mono)',
  },
});

export const Spacing = {
  half: 2,
  one: 4,
  two: 8,
  three: 16,
  four: 24,
  five: 32,
  six: 64,
} as const;

export const BottomTabInset = Platform.select({ ios: 50, android: 80 }) ?? 0;
export const MaxContentWidth = 800;
export const Radius = {
  sm: 6,
  md: 8,
  lg: 12,
} as const;
