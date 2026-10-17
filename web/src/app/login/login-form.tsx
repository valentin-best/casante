"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createClient } from "@/lib/supabase/client";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError(null);

    const { error } = await createClient().auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      setError(error.message);
      setLoading(false);
    } else {
      router.replace("/");
      router.refresh();
    }
  }

  return (
    <form className="mt-4 space-y-4" onSubmit={handleSubmit}>
      <div>
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
      </div>
      <div>
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </div>
      {error && <p className="text-sm text-red-500">{error}</p>}
      <div className="flex flex-col gap-2">
        <Button
          type="submit"
          className="w-full"
          disabled={!email || !password || loading}
        >
          Login
        </Button>
        <Button
          type="button"
          className="mt-2 w-full"
          variant="secondary"
          onClick={() => {
            setEmail(process.env.NEXT_PUBLIC_DEMO_EMAIL || "");
            setPassword(process.env.NEXT_PUBLIC_DEMO_PASSWORD || "");
          }}
        >
          Fill Demo Credentials
        </Button>
      </div>
    </form>
  );
}
