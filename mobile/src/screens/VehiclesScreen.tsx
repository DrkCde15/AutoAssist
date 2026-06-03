import { useCallback, useEffect, useState } from 'react';
import { Alert, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';

import { AppButton, Card, EmptyState, Field } from '@/components/primitives';
import { Palette, Spacing } from '@/constants/theme';
import { formatKm } from '@/lib/format';
import type { Vehicle } from '@/lib/types';
import { useAuth } from '@/context/auth';

export function VehiclesScreen() {
  const { request, refreshUser } = useAuth();
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tipo, setTipo] = useState('carro');
  const [marca, setMarca] = useState('');
  const [modelo, setModelo] = useState('');
  const [anoFabricacao, setAnoFabricacao] = useState('');
  const [anoCompra, setAnoCompra] = useState('');
  const [quilometragem, setQuilometragem] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const data = await request<{ veiculos: Vehicle[] }>('/api/veiculos');
      setVehicles(data.veiculos || []);
    } finally {
      setRefreshing(false);
    }
  }, [request]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void load();
    }, 0);
    return () => clearTimeout(timer);
  }, [load]);

  async function addVehicle() {
    if (!marca.trim() || !modelo.trim()) {
      setError('Informe marca e modelo.');
      return;
    }

    setSaving(true);
    setError('');
    try {
      await request('/api/veiculos', {
        method: 'POST',
        body: {
          tipo: tipo.trim() || 'carro',
          marca: marca.trim(),
          modelo: modelo.trim(),
          ano_fabricacao: anoFabricacao.trim() || null,
          ano_compra: anoCompra.trim() || null,
          quilometragem: quilometragem.trim() || null,
        },
      });
      setMarca('');
      setModelo('');
      setAnoFabricacao('');
      setAnoCompra('');
      setQuilometragem('');
      await refreshUser();
      await load();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'Erro ao salvar veiculo.');
    } finally {
      setSaving(false);
    }
  }

  function confirmDelete(vehicle: Vehicle) {
    Alert.alert('Excluir veiculo', 'Remover este veiculo da sua conta?', [
      { text: 'Cancelar', style: 'cancel' },
      {
        text: 'Excluir',
        style: 'destructive',
        onPress: async () => {
          await request(`/api/veiculos/${vehicle.id}`, { method: 'DELETE' });
          await refreshUser();
          await load();
        },
      },
    ]);
  }

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={load} />}>
      <Card style={styles.form}>
        <Text style={styles.title}>Novo veiculo</Text>
        <Text style={styles.muted}>Esses dados deixam o chat e as previsoes mais precisos.</Text>
        <Field label="Tipo" value={tipo} onChangeText={setTipo} placeholder="carro, moto, pickup" />
        <Field label="Marca" value={marca} onChangeText={setMarca} placeholder="Toyota" />
        <Field label="Modelo" value={modelo} onChangeText={setModelo} placeholder="Corolla" />
        <View style={styles.twoColumns}>
          <Field
            label="Ano"
            value={anoFabricacao}
            onChangeText={setAnoFabricacao}
            keyboardType="number-pad"
            placeholder="2020"
            style={styles.flexField}
          />
          <Field
            label="Compra"
            value={anoCompra}
            onChangeText={setAnoCompra}
            keyboardType="number-pad"
            placeholder="2024"
            style={styles.flexField}
          />
        </View>
        <Field
          label="Quilometragem"
          value={quilometragem}
          onChangeText={setQuilometragem}
          keyboardType="number-pad"
          placeholder="65000"
        />
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <AppButton title="Adicionar veiculo" onPress={addVehicle} loading={saving} />
      </Card>

      <View style={styles.listHeader}>
        <Text style={styles.title}>Garagem</Text>
        <Text style={styles.count}>{vehicles.length}</Text>
      </View>

      {vehicles.length ? (
        vehicles.map((vehicle) => (
          <Card key={vehicle.id} style={styles.vehicleCard}>
            <View style={styles.vehicleText}>
              <Text style={styles.vehicleName}>
                {[vehicle.marca, vehicle.modelo].filter(Boolean).join(' ') || 'Veiculo'}
              </Text>
              <Text style={styles.muted}>
                {vehicle.tipo || 'veiculo'} · {vehicle.ano_fabricacao || '-'} · {formatKm(vehicle.quilometragem)}
              </Text>
            </View>
            <AppButton title="Excluir" variant="ghost" onPress={() => confirmDelete(vehicle)} />
          </Card>
        ))
      ) : (
        <EmptyState title="Garagem vazia" body="Cadastre seu primeiro veiculo para personalizar o app." />
      )}
    </ScrollView>
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
  form: {
    gap: Spacing.two,
  },
  title: {
    color: Palette.text,
    fontSize: 20,
    fontWeight: '900',
  },
  muted: {
    color: Palette.textMuted,
    lineHeight: 20,
  },
  twoColumns: {
    flexDirection: 'row',
    gap: Spacing.two,
  },
  flexField: {
    flex: 1,
  },
  error: {
    color: Palette.red,
  },
  listHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  count: {
    color: Palette.primary,
    fontWeight: '900',
    fontSize: 18,
  },
  vehicleCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.two,
  },
  vehicleText: {
    flex: 1,
    gap: Spacing.one,
  },
  vehicleName: {
    color: Palette.text,
    fontSize: 17,
    fontWeight: '900',
  },
});
