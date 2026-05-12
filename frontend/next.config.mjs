/** @type {import('next').NextConfig} */
const FLASK_URL = process.env.FLASK_URL || "http://127.0.0.1:5000";

const nextConfig = {
  images: {
    formats: ["image/avif", "image/webp"],
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
