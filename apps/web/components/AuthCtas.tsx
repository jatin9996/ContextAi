"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export function AuthCtas() {
  const [signedIn, setSignedIn] = useState(false);

  useEffect(() => {
    api("/api/v1/auth/me")
      .then(() => setSignedIn(true))
      .catch(() => setSignedIn(false));
  }, []);

  if (signedIn) {
    return <Link className="btn btn-primary" href="/app">Open workspace</Link>;
  }
  return (
    <>
      <Link className="btn btn-ghost" href="/login">Sign in</Link>
      <Link className="btn btn-primary" href="/register">Create account</Link>
    </>
  );
}
