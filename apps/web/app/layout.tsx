import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'SwitchTrade Link Desk',
  description: 'Connect two Nintendo Switch local trade sessions through SwitchTrade.',
  icons: { icon: '/favicon.ico' },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
