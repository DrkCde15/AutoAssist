import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

import type { User } from './types';

const KEYS = {
  access: 'autoassist_access_token',
  refresh: 'autoassist_refresh_token',
  user: 'autoassist_user',
} as const;

async function setItem(key: string, value: string) {
  if (Platform.OS === 'web') {
    window.localStorage.setItem(key, value);
    return;
  }
  await SecureStore.setItemAsync(key, value);
}

async function getItem(key: string) {
  if (Platform.OS === 'web') {
    return window.localStorage.getItem(key);
  }
  return SecureStore.getItemAsync(key);
}

async function deleteItem(key: string) {
  if (Platform.OS === 'web') {
    window.localStorage.removeItem(key);
    return;
  }
  await SecureStore.deleteItemAsync(key);
}

export type StoredSession = {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
};

export async function loadSession(): Promise<StoredSession> {
  const [accessToken, refreshToken, userRaw] = await Promise.all([
    getItem(KEYS.access),
    getItem(KEYS.refresh),
    getItem(KEYS.user),
  ]);

  let user: User | null = null;
  if (userRaw) {
    try {
      user = JSON.parse(userRaw) as User;
    } catch {
      user = null;
    }
  }

  return { accessToken, refreshToken, user };
}

export async function saveSession(accessToken: string, refreshToken: string, user: User) {
  await Promise.all([
    setItem(KEYS.access, accessToken),
    setItem(KEYS.refresh, refreshToken),
    setItem(KEYS.user, JSON.stringify(user)),
  ]);
}

export async function saveAccessToken(accessToken: string) {
  await setItem(KEYS.access, accessToken);
}

export async function saveUser(user: User) {
  await setItem(KEYS.user, JSON.stringify(user));
}

export async function clearSession() {
  await Promise.all([
    deleteItem(KEYS.access),
    deleteItem(KEYS.refresh),
    deleteItem(KEYS.user),
  ]);
}
