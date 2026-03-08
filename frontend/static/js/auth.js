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
    async register(nome, email, password, veiculo = null) {
        const payload = { nome, email: email.toLowerCase(), password };
        if (veiculo) {
            payload.veiculo = veiculo;
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
                window.location.href = '/login.html'; // Ajuste conforme sua estrutura
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
            this.logout();
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
                    this.logout();
                    throw new Error('Sessão encerrada por segurança.');
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
}

const Auth = new AuthManager();