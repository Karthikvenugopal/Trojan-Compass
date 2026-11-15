import { it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatMessageView } from './ChatMessageView';

it('never preselects course examples and requires student confirmation', async () => {
  const user = userEvent.setup();
  const send = vi.fn();
  render(<ChatMessageView isBusy={false} onSuggestedReply={send} message={{
    id: 'synthetic', role: 'assistant', content: 'Which courses have you completed?',
    course_history_options: [{ code: 'PSYC 100', title: 'PSYC 100: Introduction to Psychology',
      sources: [{ title: 'Synthetic source', url: 'https://classes.usc.edu/', checked_at: null }] }],
  }} />);
  const check = screen.getByRole('checkbox');
  expect(check).not.toBeChecked();
  const confirm = screen.getByRole('button', { name: 'Confirm completed courses' });
  expect(confirm).toBeDisabled();
  expect(send).not.toHaveBeenCalled();
  await user.click(check);
  await user.click(confirm);
  expect(send).toHaveBeenCalledWith('I have completed these courses: PSYC 100.');
});

it('disables suggested replies from earlier turns', () => {
  const send = vi.fn();
  render(<ChatMessageView isBusy={false} isLatest={false} onSuggestedReply={send} message={{
    id: 'earlier-question', role: 'assistant', content: 'What interests you?',
    suggested_replies: ['Building things'],
  }} />);
  expect(screen.getByRole('button', { name: 'Building things' })).toBeDisabled();
});

it('disables selected course controls after their question becomes an earlier turn', async () => {
  const user = userEvent.setup();
  const send = vi.fn();
  const message = {
    id: 'course-question', role: 'assistant' as const, content: 'Completed courses?',
    course_history_options: [{ code: 'TEST 101', title: 'Synthetic course',
      sources: [{ title: 'Synthetic source', url: 'https://example.org/', checked_at: null }] }],
  };
  const view = render(<ChatMessageView message={message} isBusy={false} onSuggestedReply={send} />);
  await user.click(screen.getByRole('checkbox'));
  expect(screen.getByRole('button', { name: 'Confirm completed courses' })).toBeEnabled();
  view.rerender(<ChatMessageView message={message} isBusy={false} isLatest={false} onSuggestedReply={send} />);
  expect(screen.getByRole('checkbox')).toBeDisabled();
  const confirm = screen.getByRole('button', { name: 'Confirm completed courses' });
  expect(confirm).toBeDisabled();
  await user.click(confirm);
  expect(send).not.toHaveBeenCalled();
});
