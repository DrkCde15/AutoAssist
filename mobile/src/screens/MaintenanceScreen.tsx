import { useCallback, useEffect, useState } from 'react';
import { Linking, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { AppButton, Card, EmptyState, Field, Pill } from '@/components/primitives';
import { Palette, Spacing } from '@/constants/theme';
import { ApiError } from '@/lib/api';
import { formatCurrency, formatDate, formatKm } from '@/lib/format';
import type { MaintenanceAlert, MaintenanceRecord, MaintenanceSummary } from '@/lib/types';
import type { AppTab } from '@/screens/AppShell';
import { useAuth } from '@/context/auth';

type MaintenanceScreenProps = {
  goTo: (tab: AppTab) => void;
};

export function MaintenanceScreen({ goTo }: MaintenanceScreenProps) {
  const { user, request, refreshUser } = useAuth();
  const [description, setDescription] = useState('');
  const [history, setHistory] = useState<MaintenanceRecord[]>([]);
  const [alerts, setAlerts] = useState<MaintenanceAlert[]>([]);
  const [summary, setSummary] = useState<MaintenanceSummary | null>(null);
  const [premiumBlocked, setPremiumBlocked] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    setRefreshing(true);
    setMessage('');
    try {
      const [historyData, alertsData] = await Promise.all([
        request<{ historico: MaintenanceRecord[]; resumo: MaintenanceSummary }>('/api/maintenance/history'),
        request<{ alertas: MaintenanceAlert[] }>('/api/maintenance/alerts'),
      ]);
      setHistory(historyData.historico || []);
      setSummary(historyData.resumo || null);
      setAlerts(alertsData.alertas || []);
      setPremiumBlocked(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) {
        setPremiumBlocked(true);
      } else {
        setMessage(error instanceof Error ? error.message : 'Erro ao carregar manutencoes.');
      }
    } finally {
      setRefreshing(false);
    }
  }, [request]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void load();
    }, 0);
    return () => clearTimeout(timer);
  }, [load, user?.is_premium]);

  const locked = premiumBlocked || !user?.is_premium;

  async function saveMaintenance() {
    if (!description.trim()) {
      setMessage('Descreva a manutencao realizada.');
      return;
    }
    setSaving(true);
    setMessage('');
    try {
      await request('/api/maintenance/history', {
        method: 'POST',
        body: { descricao: description.trim() },
      });
      setDescription('');
      await load();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Erro ao salvar manutencao.');
    } finally {
      setSaving(false);
    }
  }

  async function openCheckout() {
    setMessage('');
    try {
      const data = await request<{ checkout_url?: string; data?: { checkout_url?: string } }>('/api/pay/preference', {
        method: 'POST',
        body: {},
      });
      const checkoutUrl = data.checkout_url || data.data?.checkout_url;
      if (!checkoutUrl) {
        setMessage('Checkout premium nao configurado.');
        return;
      }
      await Linking.openURL(checkoutUrl);
      await refreshUser();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : 'Nao foi possivel abrir o checkout.');
    }
  }

  if (locked) {
    return (
      <ScrollView style={styles.root} contentContainerStyle={styles.content}>
        <Card style={styles.lockedCard}>
          <Pill label="Premium" tone="info" />
          <Text style={styles.title}>Historico e alertas premium</Text>
          <Text style={styles.muted}>
            No app mobile, as anotacoes de manutencao usam a mesma API do site e liberam previsao de vencimento,
            alertas e resumo de gastos.
          </Text>
          <View style={styles.actions}>
            <AppButton title="Ativar Premium" onPress={openCheckout} />
            <AppButton title="Ir para o chat" variant="ghost" onPress={() => goTo('chat')} />
          </View>
          {message ? <Text style={styles.error}>{message}</Text> : null}
        </Card>
      </ScrollView>
    );
  }

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}>
      <Card style={styles.form}>
        <Text style={styles.title}>Registrar manutencao</Text>
        <Text style={styles.muted}>
          Escreva de forma natural, por exemplo: troquei o oleo hoje com 65000 km por 280 reais.
        </Text>
        <Field
          label="Descricao"
          value={description}
          onChangeText={setDescription}
          multiline
          placeholder="Troquei pastilhas de freio..."
          style={styles.description}
        />
        {message ? <Text style={styles.error}>{message}</Text> : null}
        <AppButton title="Salvar anotacao" onPress={saveMaintenance} loading={saving} />
      </Card>

      <View style={styles.grid}>
        <Card style={styles.stat}>
          <Text style={styles.statValue}>{history.length}</Text>
          <Text style={styles.statLabel}>Registros</Text>
        </Card>
        <Card style={styles.stat}>
          <Text style={styles.statValue}>{formatCurrency(summary?.total_gasto ?? summary?.total_cost ?? 0)}</Text>
          <Text style={styles.statLabel}>Gastos</Text>
        </Card>
      </View>

      <Card style={styles.section}>
        <Text style={styles.sectionTitle}>Alertas</Text>
        {alerts.length ? (
          alerts.map((alert, index) => (
            <View key={`${alert.id || index}`} style={styles.row}>
              <Pill tone={toneFromAlert(alert)} label={alert.status_label || alert.status || 'Status'} />
              <Text style={styles.itemTitle}>{alert.maintenance_label || 'Manutencao'}</Text>
              <Text style={styles.muted}>
                {alert.message || `${formatDate(alert.next_due_date)} · ${formatKm(alert.next_due_km)}`}
              </Text>
            </View>
          ))
        ) : (
          <Text style={styles.muted}>Sem alertas acionaveis agora.</Text>
        )}
      </Card>

      <View style={styles.listHeader}>
        <Text style={styles.sectionTitle}>Historico</Text>
      </View>

      {history.length ? (
        history.map((item) => (
          <Card key={item.id} style={styles.historyCard}>
            <View style={styles.row}>
              <Text style={styles.itemTitle}>{item.maintenance_label || 'Manutencao geral'}</Text>
              <Text style={styles.muted}>{item.description || '-'}</Text>
              <Text style={styles.muted}>
                {formatDate(item.service_date)} · {formatKm(item.service_km)} · {formatCurrency(item.cost, item.currency)}
              </Text>
              <Text style={styles.muted}>
                Proxima: {formatDate(item.next_due_date)} · {formatKm(item.next_due_km)}
              </Text>
            </View>
          </Card>
        ))
      ) : (
        <EmptyState title="Sem anotacoes" body="Registre a primeira manutencao para iniciar o historico." />
      )}
    </ScrollView>
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
  lockedCard: {
    gap: Spacing.two,
  },
  title: {
    color: Palette.text,
    fontSize: 22,
    fontWeight: '900',
  },
  muted: {
    color: Palette.textMuted,
    lineHeight: 20,
  },
  actions: {
    gap: Spacing.two,
  },
  error: {
    color: Palette.red,
    lineHeight: 20,
  },
  form: {
    gap: Spacing.two,
  },
  description: {
    minHeight: 96,
    textAlignVertical: 'top',
    paddingTop: 12,
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
    fontSize: 22,
    fontWeight: '900',
  },
  statLabel: {
    color: Palette.textMuted,
    fontWeight: '800',
  },
  section: {
    gap: Spacing.two,
  },
  sectionTitle: {
    color: Palette.text,
    fontSize: 18,
    fontWeight: '900',
  },
  row: {
    gap: Spacing.one,
  },
  itemTitle: {
    color: Palette.text,
    fontSize: 16,
    fontWeight: '900',
  },
  listHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  historyCard: {
    gap: Spacing.one,
  },
});
