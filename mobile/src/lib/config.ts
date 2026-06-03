import { Platform } from 'react-native';

const PROD_API_URL = 'https://autoassist-l9lr.onrender.com';

function cleanUrl(value: string | undefined) {
  return (value || '').trim().replace(/\/+$/, '');
}

export const API_BASE_URL =
  cleanUrl(process.env.EXPO_PUBLIC_API_URL) ||
  cleanUrl(process.env.EXPO_PUBLIC_FLASK_URL) ||
  PROD_API_URL;

export const LOCAL_API_HINT = Platform.select({
  android: 'http://10.0.2.2:5000',
  ios: 'http://localhost:5000',
  web: 'http://localhost:5000',
  default: 'http://localhost:5000',
});
