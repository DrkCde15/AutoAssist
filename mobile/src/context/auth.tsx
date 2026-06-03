import { createContext, PropsWithChildren, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { ApiError, apiRequest } from '@/lib/api';
import { clearSession, loadSession, saveAccessToken, saveSession, saveUser } from '@/lib/storage';
import type { LoginResult, User } from '@/lib/types';

type Credentials = {
  email: string;
  password: string;
};

type RegisterPayload = Credentials & {
  nome: string;
};

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  accessToken: string | null;
  login: (credentials: Credentials) => Promise<LoginResult>;
  register: (payload: RegisterPayload) => Promise<void>;
  verifyTwoFactor: (pendingToken: string, code: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<User | null>;
  request: <T>(path: string, options?: { method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'; body?: unknown }) => Promise<T>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<User | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [refreshToken, setRefreshToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const persistLogin = useCallback(async (result: LoginResult) => {
    if (!result.access_token || !result.refresh_token || !result.user) {
      throw new Error('Sessao invalida retornada pelo servidor.');
    }
    setAccessToken(result.access_token);
    setRefreshToken(result.refresh_token);
    setUser(result.user);
    await saveSession(result.access_token, result.refresh_token, result.user);
  }, []);

  const logout = useCallback(async () => {
    setUser(null);
    setAccessToken(null);
    setRefreshToken(null);
    await clearSession();
  }, []);

  const refreshAccessToken = useCallback(async () => {
    if (!refreshToken) {
      throw new Error('Sessao expirada.');
    }
    const result = await apiRequest<LoginResult>('/api/refresh', {
      method: 'POST',
      token: refreshToken,
    });
    if (!result.access_token) {
      throw new Error('Servidor nao retornou token de acesso.');
    }
    setAccessToken(result.access_token);
    await saveAccessToken(result.access_token);
    return result.access_token;
  }, [refreshToken]);

  const request = useCallback<AuthContextValue['request']>(
    async (path, options = {}) => {
      try {
        return await apiRequest(path, {
          method: options.method,
          body: options.body,
          token: accessToken,
        });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401 && refreshToken) {
          try {
            const freshToken = await refreshAccessToken();
            return await apiRequest(path, {
              method: options.method,
              body: options.body,
              token: freshToken,
            });
          } catch (refreshError) {
            await logout();
            throw refreshError;
          }
        }
        throw error;
      }
    },
    [accessToken, refreshAccessToken, refreshToken, logout],
  );

  const refreshUser = useCallback(async () => {
    if (!accessToken) return null;
    const current = await request<User>('/api/user');
    setUser(current);
    await saveUser(current);
    return current;
  }, [accessToken, request]);

  const login = useCallback(
    async (credentials: Credentials) => {
      const result = await apiRequest<LoginResult>('/api/login', {
        method: 'POST',
        body: credentials,
      });
      if (!result.two_factor_required) {
        await persistLogin(result);
      }
      return result;
    },
    [persistLogin],
  );

  const register = useCallback(
    async (payload: RegisterPayload) => {
      await apiRequest('/api/cadastro', {
        method: 'POST',
        body: payload,
      });
      await login({ email: payload.email, password: payload.password });
    },
    [login],
  );

  const verifyTwoFactor = useCallback(
    async (pendingToken: string, code: string) => {
      const result = await apiRequest<LoginResult>('/api/auth/2fa/verify', {
        method: 'POST',
        body: { pending_token: pendingToken, code },
      });
      await persistLogin(result);
    },
    [persistLogin],
  );

  useEffect(() => {
    let mounted = true;
    loadSession()
      .then((session) => {
        if (!mounted) return;
        setAccessToken(session.accessToken);
        setRefreshToken(session.refreshToken);
        setUser(session.user);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      accessToken,
      login,
      register,
      verifyTwoFactor,
      logout,
      refreshUser,
      request,
    }),
    [user, loading, accessToken, login, register, verifyTwoFactor, logout, refreshUser, request],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth deve ser usado dentro de AuthProvider.');
  }
  return context;
}
