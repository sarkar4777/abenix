import { redirect } from 'next/navigation';

// /demo used to redirect to /industrial-iot, which is now a standalone
// app (iot.<cluster-ip>.nip.io in k8s, http://localhost:3003 in dev).
// Anyone landing here now gets the dashboard — the use-cases menu in
// the top bar is where standalone apps are surfaced.
export default function DemoRedirect() {
  redirect('/dashboard');
}
