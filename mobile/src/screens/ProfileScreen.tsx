import { Linking, ScrollView, StyleSheet, Text, View } from 'react-native';

import { AppButton, Card, Pill } from '@/components/primitives';
import { Palette, Spacing } from '@/constants/theme';
import { API_BASE_URL, LOCAL_API_HINT } from '@/lib/config';
import { useAuth } from '@/context/auth';
import type { AppTab } from '@/screens/AppShell';

type ProfileScreenProps = {
  goTo: (tab: AppTab) => void;
};

export function ProfileScreen({ goTo }: ProfileScreenProps) {
  const { user, logout, request, refreshUser } = useAuth();

  async function openCheckout() {
    const data = await request<{ checkout_url?: string; data?: { checkout_url?: string } }>('/api/pay/preference', {
      method: 'POST',
      body: {},
    });
    const checkoutUrl = data.checkout_url || data.data?.checkout_url;
    if (checkoutUrl) {
      await Linking.openURL(checkoutUrl);
    }
  }

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.content}>
      <Card style={styles.profile}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{(user?.nome || 'A').slice(0, 1).toUpperCase()}</Text>
        </View>
        <Text style={styles.name}>{user?.nome || 'Usuario AutoAssist'}</Text>
        <Text style={styles.email}>{user?.email || 'Sessao mobile'}</Text>
        <Pill
          tone={user?.is_premium ? 'good' : 'neutral'}
          label={user?.is_premium ? 'Premium ativo' : 'Plano gratuito'}
        />
      </Card>

      <Card style={styles.section}>
        <Text style={styles.sectionTitle}>Conta</Text>
        <Info label="Consultas" value={String(user?.total_consultas ?? 0)} />
        <Info label="Veiculos" value={String(user?.veiculos?.length ?? 0)} />
        <Info label="Teste" value={`${user?.trial_days_remaining ?? 0} dias restantes`} />
      </Card>

      <Card style={styles.section}>
        <Text style={styles.sectionTitle}>Conexao</Text>
        <Info label="API atual" value={API_BASE_URL} />
        <Text style={styles.hint}>Para usar Flask local, defina EXPO_PUBLIC_API_URL={LOCAL_API_HINT} antes de iniciar o Expo.</Text>
      </Card>

      <View style={styles.actions}>
        {!user?.is_premium ? <AppButton title="Ativar Premium" onPress={openCheckout} /> : null}
        <AppButton title="Atualizar dados" variant="ghost" onPress={refreshUser} />
        <AppButton title="Gerenciar veiculos" variant="ghost" onPress={() => goTo('vehicles')} />
        <AppButton title="Sair" variant="danger" onPress={logout} />
      </View>
    </ScrollView>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.infoRow}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  content: {
    padding: Spacing.three,
    gap: Spacing.three,
  },
  profile: {
    alignItems: 'center',
    gap: Spacing.two,
  },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: 24,
    backgroundColor: Palette.surfaceStrong,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    color: Palette.white,
    fontSize: 32,
    fontWeight: '900',
  },
  name: {
    color: Palette.text,
    fontSize: 22,
    fontWeight: '900',
    textAlign: 'center',
  },
  email: {
    color: Palette.textMuted,
  },
  section: {
    gap: Spacing.two,
  },
  sectionTitle: {
    color: Palette.text,
    fontSize: 18,
    fontWeight: '900',
  },
  infoRow: {
    borderTopWidth: 1,
    borderTopColor: Palette.border,
    paddingTop: Spacing.two,
    gap: Spacing.one,
  },
  infoLabel: {
    color: Palette.textMuted,
    fontWeight: '800',
    fontSize: 12,
    textTransform: 'uppercase',
  },
  infoValue: {
    color: Palette.text,
    lineHeight: 20,
  },
  hint: {
    color: Palette.textMuted,
    lineHeight: 20,
  },
  actions: {
    gap: Spacing.two,
  },
});
