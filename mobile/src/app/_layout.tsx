import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useColorScheme } from 'react-native';

import { AuthProvider } from '@/context/auth';

export default function TabLayout() {
  const colorScheme = useColorScheme();
  return (
    <AuthProvider>
      <StatusBar style={colorScheme === 'dark' ? 'light' : 'dark'} />
      <Stack screenOptions={{ headerShown: false }} />
    </AuthProvider>
  );
}
