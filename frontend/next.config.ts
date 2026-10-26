import type { NextConfig } from 'next';

// The browser only ever calls same-origin /api. In the container and local stack, Caddy routes /api to FastAPI
// before requests reach Next.js. API_PROXY_TARGET (server-side, read at build time) is only for hosts such as
// Vercel, where Next.js itself must forward /api to a separately hosted backend over HTTPS.
const proxyTarget = process.env.API_PROXY_TARGET?.replace(/\/$/, '');
if (proxyTarget && !/^https:\/\//.test(proxyTarget) && process.env.NODE_ENV === 'production') {
  throw new Error('API_PROXY_TARGET must be an https:// origin in production builds');
}

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'" + (process.env.NODE_ENV === 'development' ? " 'unsafe-eval'" : ''),
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join('; ');

const config: NextConfig = {
  poweredByHeader: false,
  output: 'standalone',
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
          { key: 'Content-Security-Policy', value: csp },
        ],
      },
    ];
  },
  async rewrites() {
    return proxyTarget ? { beforeFiles: [{ source: '/api/:path*', destination: `${proxyTarget}/api/:path*` }] } : { beforeFiles: [] };
  },
};
export default config;
