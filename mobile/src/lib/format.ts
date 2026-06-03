export function formatKm(value?: number | string | null) {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${number.toLocaleString('pt-BR')} km`;
}

export function formatCurrency(value?: number | string | null, currency = 'BRL') {
  if (value === null || value === undefined || value === '') return '-';
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency,
  }).format(number);
}

export function formatDate(value?: string | null) {
  if (!value) return '-';
  const normalized = value.includes('T') ? value : `${value}T00:00:00`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date);
}

export function stripMarkdown(value: string) {
  return value
    .replace(/```[\s\S]*?```/g, '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1')
    .replace(/__(.*?)__/g, '$1')
    .replace(/#{1,6}\s/g, '')
    .replace(/\[(.*?)\]\((.*?)\)/g, '$1')
    .trim();
}
