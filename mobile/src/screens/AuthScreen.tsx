import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { AppButton, Card, Field } from '@/components/primitives';
import { Palette, Spacing } from '@/constants/theme';
import { ApiError } from '@/lib/api';
import { API_BASE_URL } from '@/lib/config';
import { useAuth } from '@/context/auth';

export function AuthScreen() {
  const { login, register, verifyTwoFactor } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [nome, setNome] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [pendingToken, setPendingToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const title = mode === 'login' ? 'Entrar no AutoAssist' : 'Criar conta';

  async function submit() {
    setMessage('');
    setLoading(true);
    try {
      if (pendingToken) {
        await verifyTwoFactor(pendingToken, code.trim());
        return;
      }

      if (mode === 'login') {
        const result = await login({ email: email.trim(), password });
        if (result.two_factor_required && result.pending_token) {
          setPendingToken(result.pending_token);
          setMessage('Digite o codigo 2FA para concluir o login.');
        }
      } else {
        await register({ nome: nome.trim(), email: email.trim(), password });
      }
    } catch (error) {
      setMessage(error instanceof ApiError || error instanceof Error ? error.message : 'Falha ao autenticar.');
    } finally {
      setLoading(false);
    }
  }

  function switchMode() {
    setMode((current) => (current === 'login' ? 'register' : 'login'));
    setMessage('');
    setPendingToken(null);
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.root}>
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.content}>
        <View style={styles.brand}>
          <View style={styles.mark}>
            <Text style={styles.markText}>A</Text>
          </View>
          <View>
            <Text style={styles.brandName}>AutoAssist</Text>
            <Text style={styles.brandSub}>IA automotiva no bolso</Text>
          </View>
        </View>

        <Card style={styles.card}>
          <Text style={styles.title}>{pendingToken ? 'Verificacao 2FA' : title}</Text>
          <Text style={styles.subtitle}>
            {pendingToken
              ? 'Use o codigo do seu autenticador para liberar a sessao.'
              : 'Acesse o consultor, seus veiculos e o historico de manutencao em uma experiencia nativa.'}
          </Text>

          <View style={styles.form}>
            {pendingToken ? (
              <Field
                label="Codigo 2FA"
                value={code}
                onChangeText={setCode}
                keyboardType="number-pad"
                placeholder="123456"
              />
            ) : (
              <>
                {mode === 'register' ? (
                  <Field
                    label="Nome"
                    value={nome}
                    onChangeText={setNome}
                    autoCapitalize="words"
                    placeholder="Seu nome"
                  />
                ) : null}
                <Field
                  label="Email"
                  value={email}
                  onChangeText={setEmail}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  placeholder="voce@gmail.com"
                />
                <Field
                  label="Senha"
                  value={password}
                  onChangeText={setPassword}
                  secureTextEntry
                  placeholder="Minimo 6 caracteres"
                />
              </>
            )}

            {message ? <Text style={styles.message}>{message}</Text> : null}

            <AppButton
              title={pendingToken ? 'Validar codigo' : mode === 'login' ? 'Entrar' : 'Criar e entrar'}
              onPress={submit}
              loading={loading}
            />

            {pendingToken ? (
              <AppButton
                title="Voltar ao login"
                variant="ghost"
                onPress={() => {
                  setPendingToken(null);
                  setCode('');
                  setMessage('');
                }}
              />
            ) : (
              <AppButton
                title={mode === 'login' ? 'Criar uma conta' : 'Ja tenho conta'}
                variant="ghost"
                onPress={switchMode}
              />
            )}
          </View>
        </Card>

        <Text style={styles.apiText}>API: {API_BASE_URL}</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: Palette.bg,
  },
  content: {
    flexGrow: 1,
    justifyContent: 'center',
    padding: Spacing.three,
    gap: Spacing.three,
  },
  brand: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.two,
  },
  mark: {
    width: 56,
    height: 56,
    borderRadius: 18,
    backgroundColor: Palette.surfaceStrong,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 2,
    borderColor: Palette.primary,
  },
  markText: {
    color: Palette.white,
    fontSize: 28,
    fontWeight: '900',
  },
  brandName: {
    color: Palette.text,
    fontSize: 27,
    fontWeight: '900',
  },
  brandSub: {
    color: Palette.textMuted,
    fontSize: 14,
    marginTop: 2,
  },
  card: {
    gap: Spacing.two,
  },
  title: {
    color: Palette.text,
    fontSize: 24,
    fontWeight: '900',
  },
  subtitle: {
    color: Palette.textMuted,
    lineHeight: 21,
  },
  form: {
    gap: Spacing.two,
    marginTop: Spacing.two,
  },
  message: {
    color: Palette.amber,
    lineHeight: 20,
  },
  apiText: {
    color: Palette.textMuted,
    fontSize: 12,
    textAlign: 'center',
  },
});
