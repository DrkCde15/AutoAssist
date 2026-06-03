import { useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Palette, Spacing } from '@/constants/theme';
import { ChatScreen } from '@/screens/ChatScreen';
import { HomeScreen } from '@/screens/HomeScreen';
import { MaintenanceScreen } from '@/screens/MaintenanceScreen';
import { ProfileScreen } from '@/screens/ProfileScreen';
import { VehiclesScreen } from '@/screens/VehiclesScreen';
import { useAuth } from '@/context/auth';

export type AppTab = 'home' | 'chat' | 'vehicles' | 'maintenance' | 'profile';

const tabs: { key: AppTab; label: string; symbol: string }[] = [
  { key: 'home', label: 'Inicio', symbol: '⌂' },
  { key: 'chat', label: 'Chat', symbol: '◌' },
  { key: 'vehicles', label: 'Veiculos', symbol: '◇' },
  { key: 'maintenance', label: 'Notas', symbol: '□' },
  { key: 'profile', label: 'Perfil', symbol: '◎' },
];

export function AppShell() {
  const [tab, setTab] = useState<AppTab>('home');
  const { user } = useAuth();

  const screen = useMemo(() => {
    switch (tab) {
      case 'chat':
        return <ChatScreen />;
      case 'vehicles':
        return <VehiclesScreen />;
      case 'maintenance':
        return <MaintenanceScreen goTo={setTab} />;
      case 'profile':
        return <ProfileScreen goTo={setTab} />;
      default:
        return <HomeScreen goTo={setTab} />;
    }
  }, [tab]);

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.header}>
        <View style={styles.brandRow}>
          <View style={styles.mark}>
            <Text style={styles.markText}>A</Text>
          </View>
          <View>
            <Text style={styles.brandName}>AutoAssist</Text>
            <Text style={styles.userLine}>{user?.nome || 'Sessao ativa'}</Text>
          </View>
        </View>
      </View>

      <View style={styles.screen}>{screen}</View>

      <View style={styles.tabBar}>
        {tabs.map((item) => {
          const active = item.key === tab;
          return (
            <Pressable
              key={item.key}
              onPress={() => setTab(item.key)}
              style={[styles.tabButton, active ? styles.tabButtonActive : null]}>
              <Text style={[styles.tabSymbol, active ? styles.tabTextActive : null]}>{item.symbol}</Text>
              <Text style={[styles.tabLabel, active ? styles.tabTextActive : null]}>{item.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: Palette.bg,
  },
  header: {
    paddingHorizontal: Spacing.three,
    paddingTop: Spacing.two,
    paddingBottom: Spacing.two,
    borderBottomWidth: 1,
    borderBottomColor: Palette.border,
    backgroundColor: Palette.surface,
  },
  brandRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.two,
  },
  mark: {
    width: 40,
    height: 40,
    borderRadius: 12,
    backgroundColor: Palette.surfaceStrong,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markText: {
    color: Palette.white,
    fontWeight: '900',
    fontSize: 20,
  },
  brandName: {
    color: Palette.text,
    fontSize: 18,
    fontWeight: '900',
  },
  userLine: {
    color: Palette.textMuted,
    fontSize: 12,
    marginTop: 1,
  },
  screen: {
    flex: 1,
  },
  tabBar: {
    flexDirection: 'row',
    gap: Spacing.one,
    paddingHorizontal: Spacing.two,
    paddingTop: Spacing.two,
    paddingBottom: Spacing.two,
    borderTopWidth: 1,
    borderTopColor: Palette.border,
    backgroundColor: Palette.surface,
  },
  tabButton: {
    flex: 1,
    minHeight: 56,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 8,
    gap: 2,
  },
  tabButtonActive: {
    backgroundColor: Palette.bgAlt,
  },
  tabSymbol: {
    color: Palette.textMuted,
    fontSize: 16,
    fontWeight: '900',
  },
  tabLabel: {
    color: Palette.textMuted,
    fontSize: 11,
    fontWeight: '800',
  },
  tabTextActive: {
    color: Palette.primary,
  },
});
