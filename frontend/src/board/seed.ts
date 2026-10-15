/** FNV-1a, 32 bits: a stable number from a string. */
export function hashString(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** A stable value in [-range, range] for this key and salt. */
export function jitter(key: string, salt: string, range: number): number {
  const unit = hashString(`${salt}:${key}`) / 0xffffffff; // 0..1
  return (unit * 2 - 1) * range;
}
