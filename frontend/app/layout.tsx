import type { Metadata } from 'next';
import './globals.css';
export const metadata:Metadata={title:'InternMatch AI — Evidence before opportunity',description:'Discover internships. Understand your eligibility. Apply with clarity.'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
