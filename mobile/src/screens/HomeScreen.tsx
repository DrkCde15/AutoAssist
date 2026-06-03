import { useCallback, useEffect, useState } from 'react';
import { RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { AppButton, Card, EmptyState, Pill } from '@/components/primitives';
import { Palette, Spacing } from '@/constants/theme';
import { formatDate, formatKm } from '@/lib/format';
import type { MaintenanceAlert, Vehicle } from '@/lib/types';
import type { AppTab } from '@/screens/AppShell';
import { useAuth } from '@/context/auth';

type HomeScreenProps = {
  goTo: (tab: AppTab) => void;
};

export function HomeScreen({ goTo }: HomeScreenProps) {
  const { user, request, refreshUser } = useAuth();
  const [vehicles, setVehicles] = useState<Vehicle[]>(user?.veiculos || []);
  const [alerts, setAlerts] = useState<MaintenanceAlert[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const isPremium = !!user?.is_premium;

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      await refreshUser();
      const vehicleData = await request<{ veiculos: Vehicle[] }>('/api/veiculos');
      setVehicles(vehicleData.veiculos || []);
      if (isPremium) {
        const alertData = await request<{ alertas: MaintenanceAlert[] }>('/api/maintenance/alerts');
        setAlerts(alertData.alertas || []);
      } else {
        setAlerts([]);
      }
    } catch {
      setAlerts([]);
    } finally {
      setRefreshing(false);
    }
  }, [isPremium, refreshUser, request]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void load();
    }, 0);
    return () => clearTimeout(timer);
  }, [load]);

  const mainVehicle = vehicles[0];

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}>
      <Card style={styles.hero}>
        <View style={styles.heroText}>
          <Text style={styles.kicker}>Painel do motorista</Text>
          <Text style={styles.title}>Ola, {user?.nome?.split(' ')[0] || 'motorista'}.</Text>
          <Text style={styles.subtitle}>
            Consulte o NOG, registre manutencoes e acompanhe sinais importantes do seu veiculo.
          </Text>
        </View>
        <Pill
          tone={isPremium ? 'good' : user?.trial_expired ? 'warn' : 'info'}
          label={isPremium ? 'Premium ativo' : user?.trial_expired ? 'Plano gratuito' : `${user?.trial_days_remaining ?? 0} dias de teste`}
        />
      </Card>

      <View style={styles.grid}>
        <Stat label="Consultas" value={String(user?.total_consultas ?? 0)} />
        <Stat label="Veiculos" value={String(vehicles.length)} />
      </View>

      <Card style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Veiculo principal</Text>
          <AppButton title="Gerenciar" variant="ghost" onPress={() => goTo('vehicles')} />
        </View>
        {mainVehicle ? (
          <View style={styles.vehicleLine}>
            <Text style={styles.vehicleName}>
              {[mainVehicle.marca, mainVehicle.modelo].filter(Boolean).join(' ') || 'Veiculo'}
            </Text>
            <Text style={styles.muted}>
              {mainVehicle.ano_fabricacao || '-'} · {formatKm(mainVehicle.quilometragem)}
            </Text>
          </View>
        ) : (
          <EmptyState
            title="Nenhum veiculo cadastrado"
            body="Adicione seu carro para receber respostas mais contextuais."
          />
        )}
      </Card>

      <View style={styles.actions}>
        <AppButton title="Abrir chat NOG" onPress={() => goTo('chat')} />
        <AppButton title="Nova manutencao" variant="secondary" onPress={() => goTo('maintenance')} />
      </View>

      <Card style={styles.section}>
        <View style={styles.sectionHeader}>
          <Text style={styles.sectionTitle}>Alertas</Text>
          <AppButton title="Historico" variant="ghost" onPress={() => goTo('maintenance')} />
        </View>
        {!isPremium ? (
          <Text style={styles.muted}>Alertas proativos fazem parte do plano Premium.</Text>
        ) : alerts.length ? (
          alerts.slice(0, 3).map((alert, index) => (
            <View key={`${alert.id || index}`} style={styles.alertItem}>
              <Pill tone={toneFromAlert(alert)} label={alert.status_label || alert.status || 'Status'} />
              <Text style={styles.alertTitle}>{alert.maintenance_label || 'Manutencao'}</Text>
              <Text style={styles.muted}>
                {alert.message || `${formatDate(alert.next_due_date)} · ${formatKm(alert.next_due_km)}`}
              </Text>
            </View>
          ))
        ) : (
          <Text style={styles.muted}>Sem alertas acionaveis no momento.</Text>
        )}
      </Card>
    </ScrollView>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card style={styles.stat}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </Card>
  );
}

function toneFromAlert(alert: MaintenanceAlert): 'neutral' | 'good' | 'warn' | 'danger' | 'info' {
  const code = String(alert.status_code || alert.status || '').toLowerCase();
  if (code.includes('overdue') || code.includes('atras') || code.includes('critical')) return 'danger';
  if (code.includes('warning') || code.includes('avis')) return 'warn';
  return 'info';
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  content: {
    padding: Spacing.three,
    gap: Spacing.three,
  },
  hero: {
    gap: Spacing.two,
  },
  heroText: {
    gap: Spacing.one,
  },
  kicker: {
    color: Palette.primary,
    fontSize: 12,
    fontWeight: '900',
    textTransform: 'uppercase',
  },
  title: {
    color: Palette.text,
    fontSize: 26,
    fontWeight: '900',
  },
  subtitle: {
    color: Palette.textMuted,
    lineHeight: 21,
  },
  grid: {
    flexDirection: 'row',
    gap: Spacing.two,
  },
  stat: {
    flex: 1,
    gap: Spacing.one,
  },
  statValue: {
    color: Palette.text,
    fontSize: 28,
    fontWeight: '900',
  },
  statLabel: {
    color: Palette.textMuted,
    fontWeight: '700',
  },
  section: {
    gap: Spacing.two,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: Spacing.two,
  },
  sectionTitle: {
    color: Palette.text,
    fontSize: 18,
    fontWeight: '900',
  },
  vehicleLine: {
    gap: Spacing.one,
  },
  vehicleName: {
    color: Palette.text,
    fontSize: 18,
    fontWeight: '800',
  },
  muted: {
    color: Palette.textMuted,
    lineHeight: 20,
  },
  actions: {
    gap: Spacing.two,
  },
  alertItem: {
    gap: Spacing.one,
    paddingVertical: Spacing.two,
    borderTopWidth: 1,
    borderTopColor: Palette.border,
  },
  alertTitle: {
    color: Palette.text,
    fontWeight: '800',
  },
});
