import { Link } from 'react-router-dom';

/** Вход в кабинет стола из шапки универсальной игры: у неё нет оверлея паузы, где эта ссылка была раньше. */
export default function CabinetLink({ campaignId, canManage }: { campaignId: string; canManage: boolean }) {
  if (!canManage) return null;
  return <Link to={`/c/${campaignId}/manage`} title='Кабинет стола' className='btn min-h-9 px-3 text-xs'>Кабинет</Link>;
}
