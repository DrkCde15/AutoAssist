// Declaracoes de tipos para globais expostos em runtime por scripts carregados
// via <script> (padrao vanilla JS do projeto, sem bundler/imports).
// @ts-nocheck

interface Window {
  SecurityUtils?: {
    escapeHTML(value: unknown): string;
    setSafeText(el: Element, message: string, prefix?: string): void;
  };
  AutoAssistAnalytics?: unknown;
}

declare const SecurityUtils: {
  escapeHTML(value: unknown): string;
  setSafeText(el: Element, message: string, prefix?: string): void;
};
