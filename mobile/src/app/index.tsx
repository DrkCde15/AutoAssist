import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { Palette, Spacing } from '@/constants/theme';
import { useAuth } from '@/context/auth';
import { AppShell } from '@/screens/AppShell';
import { AuthScreen } from '@/screens/AuthScreen';

export default function HomeScreen() {
  const { loading, user } = useAuth();

  if (loading) {
    return (
      <View style={styles.loading}>
        <View style={styles.mark}>
          <Text style={styles.markText}>A</Text>
        </View>
        <ActivityIndicator color={Palette.primary} />
      </View>
    );
  }

  return user ? <AppShell /> : <AuthScreen />;
}

const styles = StyleSheet.create({
  loading: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    gap: Spacing.three,
    backgroundColor: Palette.bg,
  },
  mark: {
    width: 72,
    height: 72,
    borderRadius: 24,
    backgroundColor: Palette.surfaceStrong,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markText: {
    color: Palette.white,
    fontSize: 34,
    fontWeight: '900',
  },
});
