import type { Metadata } from "next";
import { Geist } from "next/font/google";
import AuthProvider from "@/components/AuthProvider";
import Nav from "@/components/Nav";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Study Guide",
  description: "Turn your notes into revision notes, quizzes, exam papers and flashcards",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <AuthProvider>
          <Nav />
          <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10">{children}</main>
        </AuthProvider>
      </body>
    </html>
  );
}
