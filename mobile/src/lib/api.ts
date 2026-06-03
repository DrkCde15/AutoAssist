import { API_BASE_URL } from './config';

type ApiRequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  token?: string | null;
  body?: unknown;
  headers?: Record<string, string>;
};

export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(status: number, message: string, payload: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.payload = payload;
  }
}

async function readResponse(response: Response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers || {}),
  };

  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }

  const init: RequestInit = {
    method: options.method || 'GET',
    headers,
  };

  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, init);
  const payload = await readResponse(response);

  if (!response.ok) {
    const message =
      typeof payload === 'object' && payload && 'error' in payload
        ? String((payload as { error?: unknown }).error)
        : `Erro ${response.status}`;
    throw new ApiError(response.status, message, payload);
  }

  return payload as T;
}
