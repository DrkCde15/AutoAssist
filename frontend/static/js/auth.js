class AuthManager {
    constructor() {
        this.ACCESS_KEY = CONFIG.ACCESS_KEY;
        this.REFRESH_KEY = CONFIG.REFRESH_KEY;
        this.USER_KEY = CONFIG.USER_KEY;
        this.API_URL = CONFIG.API_URL;
    }

    /**
     * Realiza login e salva os tokens
     */
    async login(email, password) {
        try {
            const res = await fetch(`${this.API_URL}/api/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email.toLowerCase(), password })
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Erro no login');

            // Se o login exige 2FA, não salvamos os tokens ainda e retornamos o pending_token
            if (data.two_factor_required) {
                return data;
            }

            localStorage.setItem(this.ACCESS_KEY, data.access_token);
            localStorage.setItem(this.REFRESH_KEY, data.refresh_token);
            localStorage.setItem(this.USER_KEY, JSON.stringify(data.user));

            return data;
        } catch (error) {
            console.error('Erro no processo de login:', error);
            throw error;
        }
    }

    /**
     * Verifica o código 2FA para completar o login
     */
    async verify2FA(pending_token, code) {
        try {
            const res = await fetch(`${this.API_URL}/api/auth/2fa/verify`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pending_token, code })
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Código inválido');

            localStorage.setItem(this.ACCESS_KEY, data.access_token);
            localStorage.setItem(this.REFRESH_KEY, data.refresh_token);
            localStorage.setItem(this.USER_KEY, JSON.stringify(data.user));

            return data;
        } catch (error) {
            console.error('Erro na verificação 2FA:', error);
            throw error;
        }
    }

    /**
     * Realiza cadastro de novo usuário
     */
    async register(nome, email, password, veiculos = []) {
        const payload = { nome, email: email.toLowerCase(), password };
        if (veiculos && veiculos.length > 0) {
            payload.veiculos = veiculos;
        }
        
        const res = await fetch(`${this.API_URL}/api/cadastro`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Erro ao cadastrar');
        return data;
    }

    /**
     * Limpa dados locais e redireciona
     */
    logout(redirect = true) {
        localStorage.removeItem(this.ACCESS_KEY);
        localStorage.removeItem(this.REFRESH_KEY);
        localStorage.removeItem(this.USER_KEY);
        
        if (redirect) {
            // Evita redirecionamento infinito se já estiver na página de login
            if (!window.location.pathname.includes('login')) {
                window.location.href = 'login.html'; // Ajuste conforme sua estrutura
            }
        }
    }

    /**
     * Tenta renovar o Access Token usando o Refresh Token
     */
    async refreshToken() {
        const refreshToken = localStorage.getItem(this.REFRESH_KEY);
        
        if (!refreshToken) {
            this.logout();
            throw new Error('Sessão expirada. Faça login novamente.');
        }

        try {
            const res = await fetch(`${this.API_URL}/api/refresh`, {
                method: 'POST',
                headers: { 
                    'Authorization': `Bearer ${refreshToken}`
                }
            });

            if (!res.ok) throw new Error('Refresh token inválido');

            const data = await res.json();
            localStorage.setItem(this.ACCESS_KEY, data.access_token);
            
            if (data.refresh_token) {
                localStorage.setItem(this.REFRESH_KEY, data.refresh_token);
            }
            
            return data.access_token;
        } catch (error) {
            // Se for erro de rede (Ex: servidor offline), não desloga
            if (error instanceof TypeError && error.message.includes('fetch')) {
                console.warn('Erro de rede ao tentar renovar token. Mantendo sessão.');
            } else {
                console.error('Falha crítica na renovação de token:', error);
                this.logout();
            }
            throw error;
        }
    }

    /**
     * Wrapper do fetch que lida com expiração de token (401) automaticamente
     */
    async authenticatedFetch(url, options = {}) {
        let token = localStorage.getItem(this.ACCESS_KEY);
        options.headers = options.headers || {};
        
        if (token) {
            options.headers['Authorization'] = `Bearer ${token}`;
        }

        const finalUrl = url.startsWith('http') ? url : `${this.API_URL}${url}`;

        try {
            let response = await fetch(finalUrl, options);

            // Se o token estiver expirado, tenta renovar UMA VEZ
            if (response.status === 401 && localStorage.getItem(this.REFRESH_KEY)) {
                console.warn('Sessão expirada, tentando renovar...');
                try {
                    const newToken = await this.refreshToken();
                    options.headers['Authorization'] = `Bearer ${newToken}`;
                    return await fetch(finalUrl, options);
                } catch (retryError) {
                    // O logout agora é tratado dentro do refreshToken se necessário
                    throw new Error('Sessão encerrada ou servidor indisponível.');
                }
            }

            return response;
        } catch (error) {
            console.error('Erro na requisição autenticada:', error);
            throw error;
        }
    }

    /**
     * Solicita recuperação de senha via email
     */
    async forgotPassword(email) {
        try {
            const res = await fetch(`${this.API_URL}/api/auth/forgot-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email.toLowerCase() })
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Erro ao processar');
            return data;
        } catch (error) {
            console.error('Erro no processo de esqueci senha:', error);
            throw error;
        }
    }

    /**
     * Define uma nova senha usando o token de recuperação
     */
    async resetPassword(token, password) {
        try {
            const res = await fetch(`${this.API_URL}/api/auth/reset-password`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ token, password })
            });

            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Erro ao processar');
            return data;
        } catch (error) {
            console.error('Erro no processo de redefinir senha:', error);
            throw error;
        }
    }

    isAuthenticated() {
        return !!localStorage.getItem(this.ACCESS_KEY);
    }
    
    getUser() {
        try {
            const userStr = localStorage.getItem(this.USER_KEY);
            return userStr ? JSON.parse(userStr) : null;
        } catch {
            return null;
        }
    }

    ensurePremiumModal() {
        let modal = document.getElementById('paymentModal');

        if (!modal) {
            const wrapper = document.createElement('div');
            wrapper.innerHTML = `
                <div id="paymentModal" class="modal-overlay" style="display: none;">
                    <div class="modal-content" style="position: relative;">
                        <button id="premiumModalClose" type="button" aria-label="Fechar" style="position:absolute;top:12px;right:12px;background:none;border:none;color:#94a3b8;font-size:20px;cursor:pointer;">&times;</button>
                        <div style="text-align: center; margin-bottom: 20px;">
                            <i class="fas fa-crown" style="font-size: 48px; color: #fbbf24; margin-bottom: 10px;"></i>
                            <h2>Recurso Premium</h2>
                            <p style="color: #94a3b8;">Assine o plano premium para desbloquear esse recurso exclusivo.</p>
                        </div>

                        <div class="premium-benefits">
                            <div class="benefit-item">
                                <i class="fas fa-check-circle" style="color: #4ade80;"></i>
                                <span>Dashboard inteligente do veículo</span>
                            </div>
                            <div class="benefit-item">
                                <i class="fas fa-video" style="color: #4ade80;"></i>
                                <span>Biblioteca e recomendações de vídeos pela IA</span>
                            </div>
                            <div class="benefit-item">
                                <i class="fas fa-file-pdf" style="color: #4ade80;"></i>
                                <span>Laudos técnicos em PDF</span>
                            </div>
                        </div>

                        <div class="price-tag">
                            <span style="font-size: 14px; text-decoration: line-through; color: #64748b;">R$ 49,90</span>
                            <span style="font-size: 32px; font-weight: bold; color: #fff;">R$ 29,90</span>
                            <span style="font-size: 12px; color: #94a3b8;">/pagamento único</span>
                        </div>

                        <button id="btnPix" class="btn-cta" style="width: 100%; margin-top: 20px;">
                            <i class="fas fa-qrcode"></i> Pagar com PIX
                        </button>
                        <p style="text-align: center; font-size: 12px; color: #64748b; margin-top: 10px;">Liberação imediata após pagamento</p>
                    </div>
                </div>
            `;
            document.body.appendChild(wrapper.firstElementChild);
            modal = document.getElementById('paymentModal');
        }

        if (!document.getElementById('premiumModalSharedStyle')) {
            const style = document.createElement('style');
            style.id = 'premiumModalSharedStyle';
            style.textContent = `
                .modal-overlay {
                    position: fixed;
                    top: 0;
                    left: 0;
                    width: 100%;
                    height: 100%;
                    background: rgba(0, 0, 0, 0.85);
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    z-index: 9999;
                    backdrop-filter: blur(5px);
                }
                .modal-content {
                    background: #1e293b;
                    padding: 30px;
                    border-radius: 16px;
                    width: 90%;
                    max-width: 400px;
                    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
                    border: 1px solid #334155;
                    animation: slideIn 0.3s ease-out;
                }
                .premium-benefits {
                    background: #0f172a;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 20px 0;
                }
                .benefit-item {
                    display: flex;
                    gap: 10px;
                    align-items: center;
                    margin-bottom: 10px;
                    color: #e2e8f0;
                    font-size: 14px;
                }
                .price-tag {
                    text-align: center;
                    background: linear-gradient(135deg, #2563eb, #1e40af);
                    padding: 15px;
                    border-radius: 8px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                }
                @keyframes slideIn {
                    from { transform: translateY(20px); opacity: 0; }
                    to { transform: translateY(0); opacity: 1; }
                }
            `;
            document.head.appendChild(style);
        }

        if (!modal.dataset.bound) {
            modal.addEventListener('click', (event) => {
                if (event.target === modal) {
                    modal.style.display = 'none';
                }
            });

            const closeButton = modal.querySelector('#premiumModalClose');
            if (closeButton) {
                closeButton.addEventListener('click', () => {
                    modal.style.display = 'none';
                });
            }

            const btnPix = modal.querySelector('#btnPix');
            if (btnPix) {
                btnPix.addEventListener('click', async () => {
                    if (!this.isAuthenticated()) {
                        window.location.href = 'login.html';
                        return;
                    }

                    const originalText = btnPix.innerHTML;
                    btnPix.disabled = true;
                    btnPix.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processando...';

                    try {
                        const res = await this.authenticatedFetch('/api/pay/mock', { method: 'POST' });
                        const data = await res.json();

                        if (res.ok) {
                            alert(data.message);
                            window.location.reload();
                        } else {
                            alert('Erro no pagamento: ' + (data.error || 'falha ao processar.'));
                        }
                    } catch (error) {
                        alert('Erro de conexão.');
                    } finally {
                        btnPix.disabled = false;
                        btnPix.innerHTML = originalText;
                    }
                });
            }

            modal.dataset.bound = 'true';
        }

        return modal;
    }

    showPremiumModal() {
        const modal = this.ensurePremiumModal();
        modal.style.display = 'flex';
    }
}

const Auth = new AuthManager();

// Renderiza Timer de Teste Grátis globalmente
document.addEventListener('DOMContentLoaded', () => {
    const navContainer = document.querySelector('.nav-links') || document.querySelector('.nav-menu') || document.querySelector('.header-right');
    const user = Auth.getUser();
    const skipTrialBadge =
        window.location.pathname.endsWith('index.html') ||
        window.location.pathname.endsWith('/') ||
        window.location.pathname.endsWith('login.html') ||
        window.location.pathname.endsWith('cadastro.html');

    if (!skipTrialBadge && navContainer && user && !user.is_premium && user.trial_days_remaining !== undefined) {
        if (!document.getElementById('globalTrialBadge')) {
            const badge = document.createElement('div');
            badge.id = 'globalTrialBadge';
            badge.style.cssText = "background: rgba(245, 158, 11, 0.2); color: #fbbf24; padding: 6px 12px; border-radius: 20px; font-size: 11px; font-weight: bold; border: 1px solid rgba(245, 158, 11, 0.3); display: flex; align-items: center; gap: 5px; margin-right: 15px;";
            badge.innerHTML = `<i class="fas fa-clock"></i> Teste Grátis: ${user.trial_days_remaining} dias`;
            navContainer.prepend(badge);
        }
    }

    document.addEventListener('click', (event) => {
        const premiumTarget = event.target.closest('[data-premium-gate]');
        if (!premiumTarget) return;

        const currentUser = Auth.getUser();
        if (currentUser?.is_premium) return;

        event.preventDefault();
        event.stopPropagation();
        event.stopImmediatePropagation();
        Auth.showPremiumModal();
    }, true);
});
