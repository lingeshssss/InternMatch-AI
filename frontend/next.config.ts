import type { NextConfig } from 'next';
const config: NextConfig = {
  poweredByHeader: false,
  async headers() { return [{source:'/(.*)',headers:[
    {key:'X-Frame-Options',value:'DENY'},
    {key:'X-Content-Type-Options',value:'nosniff'},
    {key:'Referrer-Policy',value:'strict-origin-when-cross-origin'},
    {key:'Content-Security-Policy',value:"default-src 'self'; script-src 'self' 'unsafe-inline'"+(process.env.NODE_ENV==='development'?" 'unsafe-eval'":"")+"; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' "+(process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000')+"; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"}
  ]}]; }
};
export default config;
