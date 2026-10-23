import { useState } from 'react';
import { useAuthedImage } from '../lib/authedImage';

/** Fetch protected media with the session token; never put credentials in image URLs. */
export default function PortraitImage({ url, name, className = '', fit = 'cover' }: { url: string; name: string; className?: string; fit?: 'cover' | 'contain' }) {
  const src = useAuthedImage(url);
  const [failed, setFailed] = useState(false);
  return src && !failed ? <img src={src} alt={`Портрет: ${name}`} className={`h-full w-full ${fit === 'contain' ? 'object-contain' : 'object-cover'} ${className}`} onError={() => setFailed(true)} /> : null;
}
