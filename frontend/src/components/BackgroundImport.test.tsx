import { expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BackgroundImport } from './BackgroundImport';

it('offers a native attachment picker without a parser or review form', async () => {
  const user = userEvent.setup(); const onFile = vi.fn();
  render(<BackgroundImport disabled={false} onFile={onFile} />);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  expect(screen.queryByText(/Review the text/)).not.toBeInTheDocument();
  const file = new File(['synthetic'], 'resume.pdf', { type: 'application/pdf' });
  await user.upload(screen.getByLabelText('Upload background document'), file);
  expect(onFile).toHaveBeenCalledWith(file);
  expect(screen.getByLabelText('Upload background document')).toHaveValue('');
});

it('disables attachment selection while a chat request is running', () => {
  render(<BackgroundImport disabled onFile={vi.fn()} />);
  expect(screen.getByRole('button', { name: /Attach resume/ })).toBeDisabled();
  expect(screen.getByLabelText('Upload background document')).toBeDisabled();
});
