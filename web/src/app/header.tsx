import { createClient } from "@/lib/supabase/server";
import Link from "next/link";
import NavLink from "./nav-link";
import SignOutButton from "./sign-out-button";

export default async function Header() {
  const client = await createClient();
  const { data } = await client.auth.getClaims();
  const email = data?.claims.email || null;

  return (
    <header className="flex items-center justify-between gap-4 border-b px-6 py-3">
      <div className="flex items-center gap-6">
        <Link href="/" className="font-semibold">
          CaSanté
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <NavLink href="/">Documents</NavLink>
          <NavLink href="/record">Health record</NavLink>
        </nav>
      </div>
      <div className="flex items-center gap-3">
        <span className="hidden text-sm text-muted-foreground sm:inline">
          {email}
        </span>
        <SignOutButton />
      </div>
    </header>
  );
}
