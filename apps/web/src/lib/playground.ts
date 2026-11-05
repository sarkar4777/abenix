export const PLAYGROUND_REFUSED = 'This run was refused. Copy the code and run it on your own machine, or ask an admin about the Run playground code permission.';

export const PLAYGROUND_NEEDS_PERMISSION = 'Running code here needs the Run playground code permission, because it runs inside the API. An admin can grant it under Admin, Permissions. You can copy the code and run it on your own machine.';

// a 403 here has no event stream, so read the API's reason from the body
export async function playgroundRefusal(res: Response): Promise<string | null> {
  if (res.ok) return null;
  try {
    const body = await res.clone().json();
    const message = body?.error?.message || body?.error || body?.detail;
    if (typeof message === 'string' && message) return message;
  } catch {
    // not JSON, the fallback below speaks
  }
  return res.status === 403 ? PLAYGROUND_REFUSED : `The run could not start. The server answered ${res.status}.`;
}
