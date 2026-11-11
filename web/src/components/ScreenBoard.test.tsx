import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ScreenBoard from './ScreenBoard';
import type { ScreenDeckSnapshot, ScreenPage } from '../screen';

function page(id = 'p1'): ScreenPage {
  return {
    id,
    revision: 'r1',
    lessonId: 'lesson-1',
    kind: 'exercise',
    subject: 'Matte',
    title: 'Hur många är 2 + 3?',
    body: ['Räkna och skriv ditt svar.'],
    answerLabel: 'Ditt svar',
    solution: '5',
    sources: [],
    revealed: false,
    createdAt: 1,
  };
}

function deck(): ScreenDeckSnapshot {
  return {
    profileId: 'profile-1',
    lessonId: 'lesson-1',
    pages: [page('p1'), page('p2')],
    current: 0,
    drafts: {},
    updatedAt: 1,
  };
}

afterEach(cleanup);

const base = {
  learnerName: 'Leo',
  busy: false,
  onAttachCanvas: vi.fn(),
  onDraft: vi.fn().mockResolvedValue(undefined),
  onSubmit: vi.fn().mockResolvedValue(undefined),
  onGoTo: vi.fn().mockResolvedValue(undefined),
};

describe('ScreenBoard', () => {
  it('greets without loading an old page', () => {
    render(<ScreenBoard {...base} snapshot={null} />);
    expect(screen.getByText('Hej Leo!')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Nästa →' })).toBeNull();
  });

  it('navigates one page at a time', () => {
    render(<ScreenBoard {...base} snapshot={deck()} />);
    expect(screen.getByText('Sida 1 av 2')).toBeTruthy();
    expect(screen.getByRole('button', { name: '← Föregående' })).toHaveProperty('disabled', true);
    fireEvent.click(screen.getByRole('button', { name: 'Nästa →' }));
    expect(base.onGoTo).toHaveBeenCalledWith(1);
  });

  it('keeps drafts local until explicit submission', async () => {
    const onDraft = vi.fn().mockResolvedValue(undefined);
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<ScreenBoard {...base} onDraft={onDraft} onSubmit={onSubmit} snapshot={deck()} />);
    const answer = screen.getByPlaceholderText('Skriv här …');
    fireEvent.change(answer, { target: { value: '5' } });
    expect(onDraft).toHaveBeenCalledWith('p1', 'r1', '5');
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Skicka till Räven' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith('p1', 'r1'));
  });
});
