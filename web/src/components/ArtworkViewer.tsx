import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

export default function ArtworkViewer({ src, name, label, alt, backdropTestId, onClose, error, onRetry }: {
  src: string | null; name: string; label: string; alt: string; backdropTestId?: string; onClose: () => void;
  error?: boolean; onRetry?: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    const element = dialog.current!;
    element.showModal();
    document.body.style.overflow = 'hidden';
    return () => { element.close(); document.body.style.overflow = overflow; previous?.focus(); };
  }, []);
  return createPortal(<dialog ref={dialog} aria-label={label} data-artwork-viewer
    className='fixed inset-0 m-0 flex h-dvh max-h-none w-screen max-w-none flex-col border-0 bg-black/95 p-0 text-white backdrop:bg-black/85'
    onCancel={event => { event.preventDefault(); event.stopPropagation(); onClose(); }}
    onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); } }}
    onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
    <header className='flex shrink-0 items-center justify-between gap-4 border-b border-white/10 bg-black/60 px-4 py-3 sm:px-6 backdrop-blur-md'>
      <div className='flex items-center gap-2.5 min-w-0'>
        <span className='text-accent/90 text-sm sm:text-base' aria-hidden='true'>✦</span>
        <h2 className='min-w-0 break-words text-sm font-semibold sm:text-base tracking-wide text-white/95'>{name}</h2>
      </div>
      <button type='button' aria-label='Закрыть иллюстрацию' onClick={onClose}
        className='flex min-h-10 min-w-10 shrink-0 items-center justify-center rounded-xl border border-white/20 bg-white/5 px-3 py-1.5 text-xs sm:text-sm font-medium text-white/90 transition-colors hover:border-white/40 hover:bg-white/15 focus-visible:outline-2 focus-visible:outline-white'>Закрыть ×</button>
    </header>
    <div data-testid={backdropTestId} className='relative flex min-h-0 flex-1 items-center justify-center p-4 sm:p-8 select-none'
      onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      {error ? <div className='space-y-3 text-center'><p role='alert' className='text-sm text-red-400'>Не удалось загрузить изображение.</p>
        <button type='button' onClick={onRetry} className='rounded-xl border border-white/30 bg-white/10 px-4 py-2 text-sm text-white hover:bg-white/20 transition-colors'>Повторить загрузку</button></div>
        : src ? <img src={src} alt={alt} className='block max-h-full max-w-full rounded-xl object-contain drop-shadow-[0_20px_50px_rgba(0,0,0,0.95)] ring-1 ring-white/10' />
        : <p role='status' className='text-sm text-white/70'>Загрузка изображения…</p>}
    </div>
  </dialog>, document.body);
}
