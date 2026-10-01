import type { Metadata } from 'next';

import './globals.css';

export const metadata: Metadata = {
  title: 'XGAP Clarification Workspace',
  description:
    'Local authority and execution workspace for XGAP graph queries.',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN" className="dark">
      <body>{children}</body>
    </html>
  );
}
