export type Vehicle = {
  id: number;
  tipo?: string | null;
  marca?: string | null;
  modelo?: string | null;
  ano_fabricacao?: number | null;
  ano_compra?: number | null;
  quilometragem?: number | null;
};

export type User = {
  id: number | string;
  nome: string;
  email?: string;
  is_premium: boolean;
  trial_expired?: boolean;
  trial_days_remaining?: number;
  possui_veiculo?: boolean;
  veiculos?: Vehicle[];
  total_consultas?: number;
  maintenance_email_enabled?: boolean;
  maintenance_email_last_sent?: string | null;
};

export type LoginResult = {
  access_token?: string;
  refresh_token?: string;
  user?: User;
  two_factor_required?: boolean;
  pending_token?: string;
  error?: string;
};

export type LinkItem = {
  titulo?: string;
  url?: string;
  descricao?: string;
};

export type VideoItem = {
  titulo?: string;
  url?: string;
  thumbnail?: string | null;
  canal?: string | null;
};

export type ChatRecord = {
  id?: number;
  mensagem_usuario: string;
  resposta_ia: string;
  created_at?: string;
  videos?: VideoItem[];
  links?: LinkItem[];
  topic?: string;
};

export type MaintenanceRecord = {
  id: number;
  description?: string;
  maintenance_label?: string;
  service_date?: string;
  service_km?: number | null;
  cost?: number | string | null;
  currency?: string;
  next_due_date?: string | null;
  next_due_km?: number | null;
  vehicle_marca?: string | null;
  vehicle_modelo?: string | null;
  status_code?: string;
  status_label?: string;
  message?: string;
};

export type MaintenanceAlert = {
  id?: number;
  maintenance_label?: string;
  status?: string;
  status_code?: string;
  status_label?: string;
  message?: string;
  next_due_date?: string | null;
  next_due_km?: number | null;
  vehicle_marca?: string | null;
  vehicle_modelo?: string | null;
};

export type MaintenanceSummary = {
  total?: number;
  total_gasto?: number;
  total_cost?: number;
  currency?: string;
};
