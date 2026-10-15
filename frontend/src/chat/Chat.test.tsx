import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, test, vi } from 'vitest';
import type { TurnRecord } from '../api/types';
import { rebuild } from '../game/rebuild';
import type { GameView } from '../game/model';
import { states, transcript } from '../test/fixtures';
import { Chat } from './Chat';
import { pickerText } from './pickerText';

function Harness({ view, busy = false, onSend = vi.fn(), onAnswer = vi.fn() }: { view: GameView; busy?: boolean; onSend?: (t: string) => void; onAnswer?: (a: 'yes' | 'no') => void }) {
  const [draft, setDraft] = useState('');
  return <Chat view={view} busy={busy} maxChars={1000} draft={draft} onDraft={setDraft} onSend={onSend} onAnswer={onAnswer} />;
}

const at = (k: number) => rebuild('g1', states[k]!, transcript.slice(0, k));

describe('Chat rendering', () => {
  test('player slips, replies with speaker and tags, help as an agent note', () => {
    render(<Harness view={at(3)} />);
    const log = screen.getByRole('log');
    expect(within(log).getByText('hello')).toBeInTheDocument();
    expect(within(log).getByText('Ask about a suspect, search a place, or accuse.')).toHaveAttribute('data-kind', 'agent-note');
    expect(within(log).getByText('Mr Grey the butler')).toBeInTheDocument();
    expect(within(log).getByText('stock line')).toBeInTheDocument();
    expect(within(log).getByText('degraded')).toBeInTheDocument();
  });

  test('intent and post_check never show in the chat', () => {
    render(<Harness view={at(3)} />);
    expect(screen.queryByText(/interrogate.*0\.93/)).not.toBeInTheDocument();
    expect(screen.queryByText(/claims_guilt_or_blames_other/)).not.toBeInTheDocument();
  });

  test('a failed tool result is a red error line', () => {
    render(<Harness view={at(4)} />);
    expect(screen.getByText(/CASE FILE: interrogate failed: no such suspect/)).toBeInTheDocument();
  });

  test('accusation pickers send exactly the option name', async () => {
    const onSend = vi.fn();
    render(<Harness view={at(5)} onSend={onSend} />);
    const how = screen.getByRole('group', { name: 'How?' });
    await userEvent.click(within(how).getByRole('button', { name: 'poisoned port' }));
    expect(onSend).toHaveBeenCalledWith('poisoned port');
    expect(pickerText({ handle: 'w1', name: 'an unpaid inheritance' }, 'why')).toBe('an unpaid inheritance');
  });

  test('pickers are disabled while a turn runs', () => {
    render(<Harness view={at(5)} busy />);
    expect(within(screen.getByRole('group', { name: 'How?' })).getByRole('button', { name: 'poisoned port' })).toBeDisabled();
  });

  test('a waiting confirmation shows its text, warnings and Yes/No', async () => {
    const onAnswer = vi.fn();
    render(<Harness view={at(6)} onAnswer={onAnswer} />);
    const card = screen.getByRole('region', { name: 'Accusation confirmation' });
    expect(card).toHaveTextContent('You hold a fact that points away from Mr Grey.');
    await userEvent.click(within(card).getByRole('button', { name: 'Yes' }));
    expect(onAnswer).toHaveBeenCalledWith('yes');
    await userEvent.click(within(card).getByRole('button', { name: 'No' }));
    expect(onAnswer).toHaveBeenCalledWith('no');
  });

  test('reason pending renders next to the still-live confirm card', () => {
    render(<Harness view={at(7)} />);
    expect(screen.getByText(/Still want to go ahead\?/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Accusation confirmation' })).getByRole('button', { name: 'Yes' })).toBeInTheDocument();
  });

  test('a cancelled confirmation is struck through with no buttons', () => {
    render(<Harness view={at(8)} />);
    const card = screen.getByRole('region', { name: 'Accusation confirmation' });
    expect(card).toHaveAttribute('data-state', 'cancelled');
    expect(within(card).queryByRole('button')).not.toBeInTheDocument();
    expect(within(card).getByText(confirmText())).toHaveClass('line-through');
  });

  test('only the confirmation the server holds has buttons', () => {
    render(<Harness view={at(10)} />);
    expect(screen.getAllByRole('region', { name: 'Accusation confirmation' }).map((c) => c.getAttribute('data-state'))).toEqual(['cancelled', 'answered']);
    expect(screen.queryByRole('button', { name: 'Yes' })).not.toBeInTheDocument();
    expect(screen.getByText('Case closed')).toBeInTheDocument();
  });

  test('a waiting confirmation lost from the transcript is pinned from pending', () => {
    render(<Harness view={rebuild('g1', states[6]!, [])} />);
    expect(screen.getByRole('button', { name: 'Yes' })).toBeInTheDocument();
  });

  test('the input is disabled with a typing indicator while a turn runs', () => {
    render(<Harness view={at(1)} busy />);
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('The agent is typing');
  });

  test('the input is closed once the game is over', () => {
    render(<Harness view={at(10)} />);
    expect(screen.getByRole('textbox', { name: 'Message' })).toBeDisabled();
  });

  test('Enter sends and clears; Shift+Enter does not send; text is capped', async () => {
    const onSend = vi.fn();
    render(<Harness view={at(1)} onSend={onSend} />);
    const box = screen.getByRole('textbox', { name: 'Message' });
    expect(box).toHaveAttribute('maxLength', '1000');
    await userEvent.type(box, 'ask the cook{Shift>}{Enter}{/Shift}');
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.type(box, '{Enter}');
    expect(onSend).toHaveBeenCalledWith('ask the cook\n');
    expect(box).toHaveValue('');
  });

  test('a long transcript renders every message in a scrolling log', () => {
    const many: TurnRecord[] = Array.from({ length: 200 }, (_, i) => ({ ...transcript[0]!, turn_id: `t${i}`, text: `hello ${i}` }));
    render(<Harness view={rebuild('g1', states[0]!, many)} />);
    expect(screen.getByText('hello 199')).toBeInTheDocument();
    expect(screen.getByRole('log')).toHaveClass('overflow-y-auto');
  });
});

function confirmText() {
  return 'Accuse Mr Grey the butler, by poisoned port, for an unpaid inheritance?';
}
