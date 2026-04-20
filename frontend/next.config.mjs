/** @type {import('next').NextConfig} */
const FLASK_URL = process.env.FLASK_URL || "http://localhost:5000";

const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },

  /**
   * Proxy reverso para o backend Flask.
   * Em desenvolvimento (next dev), todas as requisições para /api/* e
   * /pagamentos/* são encaminhadas transparentemente ao Flask,
   * eliminando erros de CORS sem alterar o código do frontend.
   */
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${FLASK_URL}/api/:path*`,
      },
      {
        source: "/pagamentos/:path*",
        destination: `${FLASK_URL}/pagamentos/:path*`,
      },
    ];
  },
};

export default nextConfig;
