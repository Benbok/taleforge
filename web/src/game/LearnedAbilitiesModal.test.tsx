import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import LearnedAbilitiesModal, { type LearnedAbilityItem } from './LearnedAbilitiesModal';
import { useDraft } from './draft';

afterEach(() => {
  cleanup();
  useDraft.setState(useDraft.getInitialState(), true);
});

describe('LearnedAbilitiesModal', () => {
  const sampleAbilities: LearnedAbilityItem[] = [
    {
      id: 'ab1',
      name: 'Огненная стрела',
      cost: '2',
      resource_key: 'int',
      limits: { targets: '1 враг', duration: '0', conditions: ['Дистанция 15 м'] },
    },
    {
      id: 'ab2',
      name: 'Лечащее прикосновение',
      cost: '3',
      resource_key: 'wis',
      limits: { targets: '1 союзник', duration: '5', conditions: [] },
    },
    {
      id: 'ab3',
      name: 'Мощный выпад',
      cost: '1',
      resource_key: 'str',
      limits: { targets: '1 цель', duration: '0', conditions: ['В ближнем бою'] },
    },
  ];

  it('не рендерится, когда isOpen=false', () => {
    const { container } = render(
      <LearnedAbilitiesModal isOpen={false} onClose={() => {}} abilities={sampleAbilities} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('отображает список способностей, параметры и шапку', () => {
    render(
      <LearnedAbilitiesModal
        isOpen={true}
        onClose={() => {}}
        abilities={sampleAbilities}
        heroName='Пупкинатор'
      />
    );

    expect(screen.getByRole('dialog', { name: 'Изученные способности' })).toBeDefined();
    expect(screen.getByText(/Пупкинатор/)).toBeDefined();
    expect(screen.getByText('Огненная стрела')).toBeDefined();
    expect(screen.getByText('Лечащее прикосновение')).toBeDefined();
    expect(screen.getByText('Мощный выпад')).toBeDefined();
    expect(screen.getByText('Цена: 2 · Интеллект')).toBeDefined();
    expect(screen.getByText(/Целей: 1 враг/)).toBeDefined();
  });

  it('фильтрует способности по тексту в строке поиска', () => {
    render(
      <LearnedAbilitiesModal isOpen={true} onClose={() => {}} abilities={sampleAbilities} />
    );

    const searchInput = screen.getByLabelText('Поиск способности');
    fireEvent.change(searchInput, { target: { value: 'огнен' } });

    expect(screen.getByText('Огненная стрела')).toBeDefined();
    expect(screen.queryByText('Лечащее прикосновение')).toBeNull();
    expect(screen.queryByText('Мощный выпад')).toBeNull();
  });

  it('фильтрует способности по кнопкам ресурсов', () => {
    render(
      <LearnedAbilitiesModal isOpen={true} onClose={() => {}} abilities={sampleAbilities} />
    );

    // Фильтр по ресурсу МДР (Мудрость)
    const wisBtn = screen.getByRole('button', { name: /МДР/ });
    fireEvent.click(wisBtn);

    expect(screen.queryByText('Огненная стрела')).toBeNull();
    expect(screen.getByText('Лечащее прикосновение')).toBeDefined();
    expect(screen.queryByText('Мощный выпад')).toBeNull();

    // Возвращаем все
    const allBtn = screen.getByRole('button', { name: /Все/ });
    fireEvent.click(allBtn);
    expect(screen.getByText('Огненная стрела')).toBeDefined();
    expect(screen.getByText('Мощный выпад')).toBeDefined();
  });

  it('применяет способность, подставляет в useDraft и закрывает окно', () => {
    const onClose = vi.fn();
    render(
      <LearnedAbilitiesModal isOpen={true} onClose={onClose} abilities={sampleAbilities} />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Огненная стрела' }));
    expect(useDraft.getState().text).toBe('Применяю способность «Огненная стрела».');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('показывает понятное сообщение при пустом списке способностей', () => {
    render(<LearnedAbilitiesModal isOpen={true} onClose={() => {}} abilities={[]} />);
    expect(screen.getByText('Способности пока не изучены')).toBeDefined();
  });
});

