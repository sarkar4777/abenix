// The sign-in form lives on the landing page.
export const SIGN_IN_PATH = '/';
const DEFAULT_RETURN_PATH = '/dashboard';

export function safeReturnPath(raw: string | null | undefined): string {
  if (!raw || !raw.startsWith('/') || raw.startsWith('//') || raw.startsWith('/\\')) {
    return DEFAULT_RETURN_PATH;
  }
  return raw === SIGN_IN_PATH ? DEFAULT_RETURN_PATH : raw;
}

export function signInUrl(returnTo?: string | null, opts: { expired?: boolean } = {}): string {
  const params = new URLSearchParams();
  if (returnTo && returnTo !== SIGN_IN_PATH) params.set('return_to', safeReturnPath(returnTo));
  if (opts.expired) params.set('session', 'expired');
  const qs = params.toString();
  return qs ? `${SIGN_IN_PATH}?${qs}` : SIGN_IN_PATH;
}

export function currentPath(): string {
  if (typeof window === 'undefined') return SIGN_IN_PATH;
  const { pathname, search, hash } = window.location;
  return `${pathname}${search}${hash}`;
}

export function readSignInParams(): { returnTo: string; expired: boolean } {
  if (typeof window === 'undefined') return { returnTo: DEFAULT_RETURN_PATH, expired: false };
  const params = new URLSearchParams(window.location.search);
  return {
    returnTo: safeReturnPath(params.get('return_to')),
    expired: params.get('session') === 'expired',
  };
}
