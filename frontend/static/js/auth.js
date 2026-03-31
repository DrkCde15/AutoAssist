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

    async createPremiumPreference() {
        const currentPageUrl = `${window.location.origin}${window.location.pathname}`;
        const payload = {
            items: [
                {
                    id: 'autoassist-premium',
                    title: 'AutoAssist Premium',
                    description: 'Upgrade premium com acesso a recursos exclusivos',
                    quantity: 1,
                    currency_id: 'BRL',
                    unit_price: 29.90
                }
            ],
            back_urls: {
                success: currentPageUrl,
                failure: currentPageUrl,
                pending: currentPageUrl
            },
            payment_methods: {
                excluded_payment_types: [
                    { id: 'bank_transfer' },
                    { id: 'ticket' },
                    { id: 'debit_card' },
                    { id: 'prepaid_card' },
                    { id: 'atm' }
                ]
            },
            auto_return: 'approved'
        };

        const res = await this.authenticatedFetch('/api/pay/preference', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) {
            let details = '';
            if (typeof data?.details === 'string') {
                details = data.details;
            } else if (data?.details && typeof data.details === 'object') {
                details =
                    data.details.message ||
                    data.details.error ||
                    (Array.isArray(data.details.cause) && data.details.cause[0]
                        ? data.details.cause[0].description || data.details.cause[0].code
                        : '');
            }
            const msg = data?.error || 'falha ao criar preferencia de pagamento.';
            throw new Error(details ? `${msg} (${details})` : msg);
        }
        if (!data?.init_point) throw new Error('Mercado Pago não retornou init_point.');

        return data;
    }

    async _getCurrentUserWithEmail() {
        const current = this.getUser() || {};
        if (current.email) return current;

        try {
            const res = await this.authenticatedFetch('/api/user', { method: 'GET' });
            if (res.ok) {
                const fresh = await res.json();
                localStorage.setItem(this.USER_KEY, JSON.stringify(fresh));
                return fresh;
            }
        } catch (error) {
            console.warn('Não foi possível atualizar os dados do usuário para Pix.', error);
        }
        return current;
    }

    _extractErrorMessage(errorPayload) {
        if (!errorPayload) return '';
        if (typeof errorPayload === 'string') return errorPayload;
        return (
            errorPayload.message ||
            errorPayload.error ||
            (Array.isArray(errorPayload.cause) && errorPayload.cause[0]
                ? errorPayload.cause[0].description || errorPayload.cause[0].code
                : '')
        );
    }

    async createPremiumPixPayment() {
        const user = await this._getCurrentUserWithEmail();
        if (!user?.email) {
            throw new Error('Não foi possível identificar o e-mail do usuário para gerar Pix.');
        }

        const payload = {
            customer: {
                name: user.nome || 'Cliente AutoAssist',
                email: user.email
            },
            items: [
                {
                    name: 'AutoAssist Premium',
                    quantity: 1,
                    unit_amount: 2990
                }
            ],
            valor_centavos: 2990
        };

        const res = await this.authenticatedFetch('/pagamentos/pix', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await res.json();

        if (!res.ok || !result?.success) {
            const msg = this._extractErrorMessage(result?.error) || 'falha ao criar pagamento Pix.';
            const details = this._extractErrorMessage(result?.details);
            throw new Error(details ? `${msg} (${details})` : msg);
        }

        const payment = result.data || {};
        const tx = payment?.point_of_interaction?.transaction_data || {};
        const paymentId = payment?.id;
        const orderId = payment?.order_id || payment?.raw_order?.id || null;
        const qrCode = tx?.qr_code;
        const qrCodeBase64 = tx?.qr_code_base64;
        const ticketUrl = tx?.ticket_url;

        if (!paymentId || (!qrCode && !ticketUrl)) {
            throw new Error('Mercado Pago não retornou dados suficientes do Pix.');
        }

        return { paymentId, orderId, qrCode, qrCodeBase64, ticketUrl };
    }

    _stopPixPolling() {
        if (this._pixPollingTimer) {
            clearInterval(this._pixPollingTimer);
            this._pixPollingTimer = null;
        }
    }

    _setPixStatus(modal, message, color = '#94a3b8') {
        const statusEl = modal.querySelector('#pixStatusText');
        if (!statusEl) return;
        statusEl.textContent = message;
        statusEl.style.color = color;
    }

    async _checkAndFinalizePixPayment(paymentId, modal, manualCheck = false, orderId = null) {
        const res = await this.authenticatedFetch('/api/pay/confirm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ payment_id: paymentId, order_id: orderId })
        });
        const data = await res.json();

        if (res.ok) {
            this._stopPixPolling();
            this._setPixStatus(modal, 'Pagamento aprovado. Liberando acesso...', '#4ade80');
            alert(data.message || 'Pagamento aprovado com sucesso.');
            window.location.reload();
            return true;
        }

        if (res.status === 409 || res.status === 404) {
            if (manualCheck) {
                this._setPixStatus(modal, 'Pagamento ainda pendente. Aguarde alguns segundos.', '#fbbf24');
            }
            return false;
        }

        const msg = data?.error || 'falha ao confirmar pagamento.';
        const details = this._extractErrorMessage(data?.details);
        throw new Error(details ? `${msg} (${details})` : msg);
    }

    _startPixPolling(paymentId, modal, orderId = null) {
        this._stopPixPolling();

        const startedAt = Date.now();
        let inFlight = false;
        this._pixPollingTimer = setInterval(async () => {
            if (inFlight) return;
            inFlight = true;
            try {
                const approved = await this._checkAndFinalizePixPayment(paymentId, modal, false, orderId);
                if (approved) return;

                const elapsedMs = Date.now() - startedAt;
                if (elapsedMs >= 3 * 60 * 1000) {
                    this._stopPixPolling();
                    this._setPixStatus(
                        modal,
                        'Ainda nao confirmou. Mantenha o modal aberto e aguarde a confirmacao automatica.',
                        '#fbbf24'
                    );
                }
            } catch (error) {
                this._stopPixPolling();
                this._setPixStatus(modal, `Erro ao verificar pagamento: ${error.message}`, '#f87171');
            } finally {
                inFlight = false;
            }
        }, 5000);
    }

    _renderPixFlow(modal, pixData) {
        let container = modal.querySelector('#pixFlowContainer');
        if (!container) return;

        modal.classList.add('pix-flow-active');
        container.style.display = 'block';

        const qrImageHtml = pixData.qrCodeBase64
            ? `<div class="pix-qr-wrap">
                    <img alt="QR Pix" class="pix-qr-image" src="data:image/png;base64,${pixData.qrCodeBase64}" />
               </div>`
            : `<p class="pix-hint-warning">Imagem QR nao disponivel neste retorno de teste.</p>`;
        const safeTicketUrl = (pixData.ticketUrl || '').replace('/sandbox/payments/', '/payments/');
        const ticketUrlHtml = safeTicketUrl
            ? `<a href="${safeTicketUrl}" target="_blank" rel="noopener noreferrer" class="pix-ticket-link">Abrir cobranca Pix no Mercado Pago</a>`
            : '';
        const qrText = pixData.qrCode || '';
        const disableCopy = qrText ? '' : 'disabled';
        const copyClass = qrText ? 'pix-copy-btn' : 'pix-copy-btn is-disabled';

        container.innerHTML = `
            <div class="pix-card">
                ${qrImageHtml}
                <p class="pix-copy-label">Copia e cola Pix:</p>
                <textarea id="pixCopyCode" readonly class="pix-copy-code">${qrText}</textarea>
                ${ticketUrlHtml}
                <div class="pix-actions">
                    <button id="copyPixCodeBtn" ${disableCopy} class="${copyClass}">Copiar codigo</button>
                </div>
                <p id="pixStatusText" class="pix-status">Aguardando confirmacao automatica do Pix...</p>
            </div>
        `;

        const copyBtn = container.querySelector('#copyPixCodeBtn');
        if (copyBtn) {
            copyBtn.addEventListener('click', async () => {
                const code = container.querySelector('#pixCopyCode')?.value || '';
                try {
                    await navigator.clipboard.writeText(code);
                    this._setPixStatus(modal, 'Codigo Pix copiado com sucesso.', '#4ade80');
                } catch (error) {
                    this._setPixStatus(modal, 'Nao foi possivel copiar automaticamente.', '#fbbf24');
                }
            });
        }
    }

    async handlePaymentReturnFromUrl() {
        if (!this.isAuthenticated()) return;

        const url = new URL(window.location.href);
        const paymentId = url.searchParams.get('payment_id') || url.searchParams.get('collection_id');
        if (!paymentId) return;

        const status = (url.searchParams.get('status') || url.searchParams.get('collection_status') || '').toLowerCase();

        if (status && status !== 'approved') {
            alert(`Pagamento não aprovado (${status}).`);
        } else {
            try {
                const res = await this.authenticatedFetch('/api/pay/confirm', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ payment_id: paymentId })
                });
                const data = await res.json();
                if (res.ok) {
                    alert(data.message || 'Pagamento aprovado com sucesso.');
                    const userRes = await this.authenticatedFetch('/api/user', { method: 'GET' });
                    if (userRes.ok) {
                        const userData = await userRes.json();
                        localStorage.setItem(this.USER_KEY, JSON.stringify(userData));
                    }
                } else {
                    alert(`Erro ao confirmar pagamento: ${data.error || 'falha ao confirmar.'}`);
                }
            } catch (error) {
                alert('Erro de conexão ao confirmar pagamento.');
            }
        }

        const keysToRemove = [
            'payment_id',
            'collection_id',
            'collection_status',
            'status',
            'external_reference',
            'merchant_order_id',
            'preference_id',
            'site_id',
            'processing_mode',
            'merchant_account_id'
        ];
        keysToRemove.forEach((key) => url.searchParams.delete(key));
        window.history.replaceState({}, document.title, url.pathname + url.search);
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
                    <div class="modal-content">
                        <button id="premiumModalClose" type="button" aria-label="Fechar" class="premium-close-btn">&times;</button>
                        <div class="premium-header">
                            <i class="fas fa-crown premium-header-icon"></i>
                            <h2>Recurso Premium</h2>
                            <p>Assine o plano premium para desbloquear esse recurso exclusivo.</p>
                        </div>

                        <div class="premium-benefits">
                            <div class="benefit-item">
                                <i class="fas fa-check-circle"></i>
                                <span>Dashboard inteligente do veiculo</span>
                            </div>
                            <div class="benefit-item">
                                <i class="fas fa-video"></i>
                                <span>Biblioteca e recomendacoes de videos pela IA</span>
                            </div>
                            <div class="benefit-item">
                                <i class="fas fa-file-pdf"></i>
                                <span>Laudos tecnicos em PDF</span>
                            </div>
                        </div>

                        <div class="price-tag">
                            <span class="price-old">R$ 49,90</span>
                            <span class="price-current">R$ 29,90</span>
                            <span class="price-caption">/pagamento unico</span>
                        </div>

                        <button id="btnCheckout" class="btn-cta">
                            <i class="fas fa-credit-card"></i> Pagar com cartao
                        </button>
                        <p class="premium-caption">Pagamento seguro via Mercado Pago</p>
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
                    position: relative;
                    padding: 22px;
                    border-radius: 16px;
                    width: 90%;
                    max-width: 500px;
                    max-height: 90vh;
                    overflow-y: auto;
                    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
                    border: 1px solid #334155;
                    animation: slideIn 0.3s ease-out;
                }
                .premium-close-btn {
                    position: absolute;
                    top: 12px;
                    right: 12px;
                    width: 34px;
                    height: 34px;
                    border-radius: 999px;
                    border: 1px solid #334155;
                    background: #0f172a;
                    color: #94a3b8;
                    font-size: 20px;
                    cursor: pointer;
                }
                .premium-header {
                    text-align: center;
                    margin-bottom: 16px;
                    padding-right: 22px;
                }
                .premium-header-icon {
                    font-size: 40px;
                    color: #fbbf24;
                    margin-bottom: 8px;
                }
                .premium-header h2 {
                    color: #e2e8f0;
                    margin-bottom: 4px;
                }
                .premium-header p {
                    color: #94a3b8;
                    font-size: 14px;
                    line-height: 1.4;
                }
                .premium-benefits {
                    background: #0f172a;
                    padding: 15px;
                    border-radius: 8px;
                    margin: 14px 0;
                    border: 1px solid #22314a;
                }
                .benefit-item {
                    display: flex;
                    gap: 10px;
                    align-items: center;
                    margin-bottom: 8px;
                    color: #e2e8f0;
                    font-size: 14px;
                }
                .benefit-item:last-child {
                    margin-bottom: 0;
                }
                .benefit-item i {
                    color: #4ade80;
                }
                .price-tag {
                    text-align: center;
                    background: linear-gradient(135deg, #2563eb, #1e40af);
                    padding: 15px;
                    border-radius: 8px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    margin-top: 12px;
                }
                .price-old {
                    font-size: 14px;
                    text-decoration: line-through;
                    color: #93c5fd;
                }
                .price-current {
                    font-size: 44px;
                    line-height: 1;
                    font-weight: 700;
                    color: #ffffff;
                    margin-top: 4px;
                }
                .price-caption {
                    font-size: 12px;
                    color: #bfdbfe;
                    margin-top: 4px;
                }
                .btn-cta {
                    width: 100%;
                    margin-top: 14px;
                    background: linear-gradient(135deg, #32bcad, #14b8a6);
                    color: #ffffff;
                    padding: 14px;
                    border-radius: 10px;
                    font-weight: 700;
                    font-size: 16px;
                    border: none;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                }
                .premium-caption {
                    text-align: center;
                    font-size: 12px;
                    color: #94a3b8;
                    margin-top: 8px;
                }
                .pix-card {
                    background: #0f172a;
                    border: 1px solid #334155;
                    border-radius: 12px;
                    padding: 14px;
                    margin-top: 14px;
                }
                .pix-qr-wrap {
                    display: flex;
                    justify-content: center;
                    margin-bottom: 10px;
                }
                .pix-qr-image {
                    width: 220px;
                    height: 220px;
                    border-radius: 8px;
                    background: #ffffff;
                    padding: 8px;
                }
                .pix-hint-warning {
                    margin: 0 0 8px;
                    font-size: 12px;
                    color: #fbbf24;
                    text-align: center;
                }
                .pix-copy-label {
                    margin: 6px 0;
                    font-size: 12px;
                    color: #94a3b8;
                }
                .pix-copy-code {
                    width: 100%;
                    min-height: 72px;
                    border-radius: 8px;
                    padding: 10px;
                    background: #111827;
                    color: #e2e8f0;
                    border: 1px solid #334155;
                    resize: vertical;
                }
                .pix-ticket-link {
                    display: block;
                    margin-top: 8px;
                    text-align: center;
                    color: #60a5fa;
                    font-size: 12px;
                }
                .pix-actions {
                    display: flex;
                    gap: 8px;
                    margin-top: 10px;
                }
                .pix-copy-btn,
                .pix-check-btn {
                    flex: 1;
                    border: none;
                    border-radius: 8px;
                    padding: 10px;
                    font-weight: 600;
                    cursor: pointer;
                }
                .pix-copy-btn {
                    background: #1d4ed8;
                    color: #ffffff;
                }
                .pix-copy-btn.is-disabled {
                    background: #334155;
                    color: #94a3b8;
                    cursor: not-allowed;
                }
                .pix-check-btn {
                    background: #059669;
                    color: #ffffff;
                }
                .pix-status {
                    margin-top: 10px;
                    font-size: 12px;
                    color: #94a3b8;
                    text-align: center;
                }
                .pix-flow-active .premium-benefits {
                    display: none;
                }
                .pix-flow-active .price-current {
                    font-size: 34px;
                }
                @media (max-width: 600px) {
                    .modal-content {
                        width: 94%;
                        padding: 16px;
                        max-height: 92vh;
                    }
                    .price-current {
                        font-size: 36px;
                    }
                    .pix-qr-image {
                        width: 190px;
                        height: 190px;
                    }
                    .pix-actions {
                        flex-direction: column;
                    }
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
                    this._stopPixPolling();
                    modal.classList.remove('pix-flow-active');
                    modal.style.display = 'none';
                }
            });

            const closeButton = modal.querySelector('#premiumModalClose');
            if (closeButton) {
                closeButton.addEventListener('click', () => {
                    this._stopPixPolling();
                    modal.classList.remove('pix-flow-active');
                    modal.style.display = 'none';
                });
            }

            const btnCheckout = modal.querySelector('#btnCheckout');
            if (btnCheckout) {
                btnCheckout.addEventListener('click', async () => {
                    if (!this.isAuthenticated()) {
                        window.location.href = 'login.html';
                        return;
                    }

                    btnCheckout.disabled = true;
                    btnCheckout.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Abrindo checkout...';

                    try {
                        const preference = await this.createPremiumPreference();
                        const checkoutUrl = preference.init_point || preference.sandbox_init_point;
                        if (!checkoutUrl) {
                            throw new Error('Mercado Pago nao retornou URL de checkout.');
                        }
                        window.location.href = checkoutUrl;
                    } catch (error) {
                        alert('Erro no pagamento: ' + (error?.message || 'falha ao processar.'));
                    } finally {
                        btnCheckout.disabled = false;
                        btnCheckout.innerHTML = '<i class="fas fa-credit-card"></i> Pagar com cartao';
                    }
                });
            }

            modal.dataset.bound = 'true';
        }

        return modal;
    }

    showPremiumModal() {
        const modal = this.ensurePremiumModal();
        this._stopPixPolling();
        modal.classList.remove('pix-flow-active');
        modal.style.display = 'flex';
    }

}

const Auth = new AuthManager();

// Renderiza Timer de Teste Grátis globalmente
document.addEventListener('DOMContentLoaded', () => {
    Auth.handlePaymentReturnFromUrl();
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



