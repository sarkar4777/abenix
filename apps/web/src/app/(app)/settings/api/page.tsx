import { redirect } from 'next/navigation';

export default function ApiRedirect() {
  redirect('/settings/api-keys');
}
