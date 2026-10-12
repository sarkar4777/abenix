// "1 message", "2 messages", with the number shown as given
export function pluralShown(n: number | null | undefined, shown: string | number, one: string, many?: string): string {
  return `${shown} ${Number(n) === 1 ? one : many || `${one}s`}`;
}
