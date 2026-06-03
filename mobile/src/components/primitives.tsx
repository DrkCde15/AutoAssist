import { PropsWithChildren } from 'react';
import {
  ActivityIndicator,
  Pressable,
  PressableProps,
  StyleSheet,
  Text,
  TextInput,
  TextInputProps,
  View,
  ViewProps,
} from 'react-native';

import { Palette, Radius, Spacing } from '@/constants/theme';

type ButtonProps = PressableProps & {
  title: string;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  loading?: boolean;
};

export function AppButton({ title, variant = 'primary', loading, disabled, style, ...props }: ButtonProps) {
  const isDisabled = disabled || loading;
  return (
    <Pressable
      {...props}
      disabled={isDisabled}
      style={(state) => [
        styles.button,
        styles[`button_${variant}`],
        state.pressed && !isDisabled ? styles.pressed : null,
        isDisabled ? styles.disabled : null,
        typeof style === 'function' ? style(state) : style,
      ]}>
      {loading ? <ActivityIndicator color={variant === 'ghost' ? Palette.primary : Palette.white} /> : null}
      <Text style={[styles.buttonText, styles[`buttonText_${variant}`]]}>{title}</Text>
    </Pressable>
  );
}

type FieldProps = TextInputProps & {
  label: string;
};

export function Field({ label, style, ...props }: FieldProps) {
  return (
    <View style={styles.fieldWrap}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        {...props}
        placeholderTextColor={Palette.textSoft}
        style={[styles.input, style]}
      />
    </View>
  );
}

export function Card({ children, style, ...props }: PropsWithChildren<ViewProps>) {
  return (
    <View {...props} style={[styles.card, style]}>
      {children}
    </View>
  );
}

type PillProps = {
  label: string;
  tone?: 'neutral' | 'good' | 'warn' | 'danger' | 'info';
};

export function Pill({ label, tone = 'neutral' }: PillProps) {
  return (
    <View style={[styles.pill, styles[`pill_${tone}`]]}>
      <Text style={[styles.pillText, styles[`pillText_${tone}`]]}>{label}</Text>
    </View>
  );
}

export function EmptyState({ title, body }: { title: string; body?: string }) {
  return (
    <Card style={styles.empty}>
      <Text style={styles.emptyTitle}>{title}</Text>
      {body ? <Text style={styles.emptyBody}>{body}</Text> : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  button: {
    minHeight: 48,
    borderRadius: Radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: Spacing.two,
    paddingHorizontal: Spacing.three,
    borderWidth: 1,
  },
  button_primary: {
    backgroundColor: Palette.primary,
    borderColor: Palette.primary,
  },
  button_secondary: {
    backgroundColor: Palette.surfaceStrong,
    borderColor: Palette.surfaceStrong,
  },
  button_ghost: {
    backgroundColor: Palette.surface,
    borderColor: Palette.border,
  },
  button_danger: {
    backgroundColor: Palette.red,
    borderColor: Palette.red,
  },
  buttonText: {
    fontSize: 15,
    fontWeight: '700',
  },
  buttonText_primary: {
    color: Palette.white,
  },
  buttonText_secondary: {
    color: Palette.white,
  },
  buttonText_ghost: {
    color: Palette.text,
  },
  buttonText_danger: {
    color: Palette.white,
  },
  pressed: {
    opacity: 0.82,
  },
  disabled: {
    opacity: 0.55,
  },
  fieldWrap: {
    gap: Spacing.one,
  },
  label: {
    color: Palette.text,
    fontSize: 13,
    fontWeight: '700',
  },
  input: {
    minHeight: 48,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Palette.border,
    backgroundColor: Palette.surface,
    color: Palette.text,
    paddingHorizontal: Spacing.three,
    fontSize: 16,
  },
  card: {
    backgroundColor: Palette.surface,
    borderWidth: 1,
    borderColor: Palette.border,
    borderRadius: Radius.md,
    padding: Spacing.three,
  },
  pill: {
    alignSelf: 'flex-start',
    borderRadius: 999,
    paddingHorizontal: Spacing.two,
    paddingVertical: Spacing.one,
    borderWidth: 1,
  },
  pill_neutral: {
    backgroundColor: Palette.bgAlt,
    borderColor: Palette.border,
  },
  pill_good: {
    backgroundColor: '#DCFCE7',
    borderColor: '#86EFAC',
  },
  pill_warn: {
    backgroundColor: '#FEF3C7',
    borderColor: '#FCD34D',
  },
  pill_danger: {
    backgroundColor: '#FEE2E2',
    borderColor: '#FCA5A5',
  },
  pill_info: {
    backgroundColor: '#DBEAFE',
    borderColor: '#93C5FD',
  },
  pillText: {
    fontSize: 12,
    fontWeight: '800',
  },
  pillText_neutral: {
    color: Palette.textMuted,
  },
  pillText_good: {
    color: Palette.green,
  },
  pillText_warn: {
    color: Palette.amber,
  },
  pillText_danger: {
    color: Palette.red,
  },
  pillText_info: {
    color: Palette.blue,
  },
  empty: {
    alignItems: 'center',
    gap: Spacing.one,
  },
  emptyTitle: {
    color: Palette.text,
    fontWeight: '800',
    fontSize: 16,
    textAlign: 'center',
  },
  emptyBody: {
    color: Palette.textMuted,
    textAlign: 'center',
    lineHeight: 20,
  },
});
