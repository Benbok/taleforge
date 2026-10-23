export function compareCounts(a: string, b: string): number {
  const left = BigInt(a), right = BigInt(b);
  return left < right ? -1 : left > right ? 1 : 0;
}

export function formatCount(value: string): string {
  return BigInt(value).toLocaleString('ru-RU');
}
