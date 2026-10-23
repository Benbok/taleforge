import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import PortraitImage from './PortraitImage';

function Viewer({ url, name, onClose }: { url: string; name: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const element = dialog.current!;
    element.showModal();
    return () => { element.close(); previous?.focus(); };
  }, []);
  return createPortal(<dialog ref={dialog} aria-label={`Портрет: ${name}`}
    className='fixed inset-0 m-auto max-h-[95dvh] max-w-[95vw] rounded-2xl border border-line bg-surface p-4 text-ink shadow-2xl backdrop:bg-black/80'
    onCancel={event => { event.preventDefault(); onClose(); }}
    onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); } }}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <div><header className='mb-3 flex items-center justify-between gap-4'><h2 className='min-w-0 break-words font-heading text-lg'>{name}</h2>
      <button type='button' className='btn shrink-0' onClick={onClose} aria-label='Закрыть портрет'>Закрыть</button></header>
      <div className='h-[75dvh] w-[min(85vw,1024px)]'><PortraitImage url={url} name={name} fit='contain' /></div>
    </div>
  </dialog>, document.body);
}

export default function PortraitPreview({ url, name }: { url: string; name: string }) {
  const [open, setOpen] = useState(false);
  return <><button type='button' onClick={() => setOpen(true)} aria-label={`Рассмотреть портрет: ${name}`} title='Рассмотреть портрет'
    className='group relative h-40 w-40 shrink-0 overflow-hidden rounded-2xl border border-line bg-bg focus-visible:outline-2 focus-visible:outline-accent sm:h-48 sm:w-48'>
    <PortraitImage url={url} name={name} />
    <span className='absolute inset-x-0 bottom-0 bg-black/65 py-2 text-xs text-white'>Рассмотреть ↗</span>
  </button>{open && <Viewer url={url} name={name} onClose={() => setOpen(false)} />}</>;
}
