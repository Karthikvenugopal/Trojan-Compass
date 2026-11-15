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
