import { useState } from 'react';
import { useAuthedImage } from '../lib/authedImage';

/** Fetch protected media with the session token; never put credentials in image URLs. */
export default function PortraitImage({ url, name, className = '' }: { url: string; name: string; className?: string }) {
  const src = useAuthedImage(url);
  const [failed, setFailed] = useState(false);
  return src && !failed ? <img src={src} alt={`Портрет: ${name}`} className={`h-full w-full object-cover ${className}`} onError={() => setFailed(true)} /> : null;
}
