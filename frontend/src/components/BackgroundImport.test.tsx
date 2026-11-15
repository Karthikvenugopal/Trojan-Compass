import { expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BackgroundImport } from './BackgroundImport';

it('requires review and confirmation before using pasted LinkedIn content', async () => {
  const user = userEvent.setup(); const use = vi.fn();
  render(<BackgroundImport disabled={false} onUse={use} />);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /Add a resume/ }));
  await user.click(screen.getByRole('button', { name: 'LinkedIn' }));
  await user.type(screen.getByRole('textbox'), 'Synthetic volunteering experience.');
  expect(use).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'Use this reviewed background' }));
  expect(use).toHaveBeenCalledWith(expect.stringContaining('LinkedIn profile'));
  expect(use).toHaveBeenCalledWith(expect.stringContaining('Synthetic volunteering experience.'));
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
});
it('clears a closed draft and rejects excessive text without truncation', async () => {
  const user = userEvent.setup();
  render(<BackgroundImport disabled={false} onUse={vi.fn()} />);
  await user.click(screen.getByRole('button', { name: /Add a resume/ }));
  const textbox = screen.getByRole('textbox');
  await user.click(textbox); await user.paste('x'.repeat(4000));
  expect(screen.getByRole('button', { name: 'Use this reviewed background' })).toBeDisabled();
  expect(screen.getByText(/nothing will be truncated/)).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Close and clear import' }));
  await user.click(screen.getByRole('button', { name: /Add a resume/ }));
  expect(screen.getByRole('textbox')).toHaveValue('');
});
