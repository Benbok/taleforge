import { useQueryClient } from '@tanstack/react-query';
import ActionButton from '../components/ActionButton';
import { api } from '../lib/api';
import type { HeroDialogue } from '../lib/universal';

export default function DeleteHeroDraft({ draft, onDeleted, disabled = false }: {
  draft: HeroDialogue; onDeleted?: () => void; disabled?: boolean;
}) {
  const qc = useQueryClient();
  const name = draft.description.name || draft.description.identity.slice(0, 80);
  return <ActionButton danger disabled={disabled} title='Удалить черновик'
    confirm={`Удалить черновик «${name}»? Переписка и предложение будут удалены.`}
    done='Черновик удалён'
    run={async () => {
      await api(`/api/hero-creation/dialogues/${draft.id}?expected_revision=${draft.revision}`, { method: 'DELETE' });
      onDeleted?.();
      qc.removeQueries({ queryKey: ['hero-dialogue', draft.id], exact: true });
      await qc.invalidateQueries({ queryKey: ['hero-drafts'] });
    }}>Удалить</ActionButton>;
}
