import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { InformationPanel } from './InformationPanel';
import type { InformationSnapshot } from '../types';

const information: InformationSnapshot = {
  ready: true, missing_fields: [], fields: [
    { field: 'direction', label: 'Interests or direction', category: 'fixed', required: true, status: 'provided', value: 'I like robotics.' },
    { field: 'background', label: 'Skills and experience', category: 'fixed', required: false, status: 'none', value: null },
  ],
};

describe('information editor', () => {
  it('starts collapsed and exposes the four answer choices on request', async () => {
    const user = userEvent.setup();
    render(<InformationPanel information={information} disabled={false} onSave={vi.fn()} />);
    const toggle = screen.getByRole('button', { name: /What I’m using/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const select = screen.getByRole('combobox', { name: 'Interests or direction' });
    expect(select).toHaveValue('provided');
    expect(select.querySelectorAll('option')).toHaveLength(4);
    expect(screen.getByRole('textbox', { name: 'Interests or direction answer' })).toHaveValue('I like robotics.');
    expect(screen.getByRole('combobox', { name: 'Skills and experience' })).toHaveValue('none');
    await user.type(screen.getByRole('textbox', { name: 'Interests or direction answer' }), ' And music.');
    await user.click(toggle);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByRole('textbox', { name: 'Interests or direction answer' })).toHaveValue('I like robotics. And music.');
  });

  it('saves an explicit reset and validates a custom sentence', async () => {
    const user = userEvent.setup();
    const save = vi.fn();
    render(<InformationPanel information={information} disabled={false} onSave={save} />);
    await user.click(screen.getByRole('button', { name: /What I’m using/ }));
    const select = screen.getByRole('combobox', { name: 'Interests or direction' });
    await user.selectOptions(select, 'not_answered');
    await user.click(screen.getByRole('button', { name: 'Save interests or direction' }));
    expect(save).toHaveBeenLastCalledWith({ field: 'direction', status: 'not_answered', value: null }, 'Interests or direction');
    await user.selectOptions(select, 'provided');
    const sentence = screen.getByRole('textbox', { name: 'Interests or direction answer' });
    await user.clear(sentence);
    expect(screen.getByRole('button', { name: 'Save interests or direction' })).toBeDisabled();
    await user.type(sentence, 'I prefer music.');
    await user.click(screen.getByRole('button', { name: 'Save interests or direction' }));
    expect(save).toHaveBeenLastCalledWith({ field: 'direction', status: 'provided', value: 'I prefer music.' }, 'Interests or direction');
  });

  it('cannot save or change answers while a request is pending', async () => {
    const user = userEvent.setup();
    render(<InformationPanel information={information} disabled onSave={vi.fn()} />);
    await user.click(screen.getByRole('button', { name: /What I’m using/ }));
    expect(screen.getByRole('combobox', { name: 'Interests or direction' })).toBeDisabled();
    expect(screen.getByRole('textbox', { name: 'Interests or direction answer' })).toBeDisabled();
  });
});
