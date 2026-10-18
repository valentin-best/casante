"use client";

import { cn } from "cn";
import Link from "next/link";
import { usePathname } from "next/navigation";

export default function NavLink({
  href,
  children,
}: {
  href: string;
  children: React.ReactNode;
}) {
  const active = usePathname() === href;

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "rounded-md px-2.5 py-1.5 transition-colors hover:bg-muted",
        active ? "bg-muted font-medium" : "text-muted-foreground",
      )}
    >
      {children}
    </Link>
  );
}
