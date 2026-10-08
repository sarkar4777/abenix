import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { Plus, Bot, BookOpen } from 'lucide-react';
import PageHeader, { docHref, readHowState } from '@/components/layout/PageHeader';
import NextSteps from '@/components/shared/NextSteps';

describe('PageHeader', () => {
  beforeEach(() => localStorage.clear());

  it('shows title, purpose, primary and secondary actions and docs link', () => {
    const onNew = vi.fn();
    render(
      <PageHeader
        title="Agents"
        purpose="Every agent you can use. For everyone."
        icon={Bot}
        primaryAction={{ label: 'New agent', onClick: onNew, icon: Plus, testId: 'agents-new' }}
        secondaryAction={{ label: 'Browse', href: '/marketplace' }}
        steps={['Pick one', 'Chat with it']}
        docSlug="08-howto/02-add-an-agent"
        storageKey="agents"
      />,
    );
    expect(screen.getByTestId('page-header')).toBeInTheDocument();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Agents');
    expect(screen.getByTestId('page-purpose')).toHaveTextContent('Every agent you can use. For everyone.');
    const primary = screen.getByTestId('page-primary-action');
    // the old testid survives inside the wrapper
    fireEvent.click(screen.getByTestId('agents-new'));
    expect(onNew).toHaveBeenCalledOnce();
    expect(primary).toContainElement(screen.getByTestId('agents-new'));
    expect(screen.getByRole('link', { name: 'Browse' })).toHaveAttribute('href', '/marketplace');
    expect(screen.getByTestId('page-docs-link')).toHaveAttribute('href', '/docs?doc=08-howto%2F02-add-an-agent');
  });

  it('opens the how-it-works panel on the first visit and collapses on the next', () => {
    const { unmount } = render(
      <PageHeader title="Evals" purpose="p" steps={['one', 'two', 'three']} storageKey="evals" />,
    );
    const toggle = screen.getByTestId('page-how-toggle');
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('three')).toBeInTheDocument();
    expect(readHowState('evals')).toBe('1');
    unmount();

    render(<PageHeader title="Evals" purpose="p" steps={['one', 'two', 'three']} storageKey="evals" />);
    expect(screen.getByTestId('page-how-toggle')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('three')).not.toBeInTheDocument();
  });

  it('remembers that the person reopened it', () => {
    localStorage.setItem('pageHeader.how.kb', '1');
    const { unmount } = render(<PageHeader title="Knowledge" purpose="p" steps={['a', 'b']} storageKey="kb" />);
    fireEvent.click(screen.getByTestId('page-how-toggle'));
    expect(screen.getByText('a')).toBeInTheDocument();
    expect(readHowState('kb')).toBe('0');
    unmount();
    render(<PageHeader title="Knowledge" purpose="p" steps={['a', 'b']} storageKey="kb" />);
    expect(screen.getByTestId('page-how-toggle')).toHaveAttribute('aria-expanded', 'true');
  });

  it('still renders when storage throws', () => {
    const spy = vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const set = vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    render(<PageHeader title="Private" purpose="p" steps={['a', 'b']} storageKey="private" />);
    expect(screen.getByTestId('page-how-toggle')).toHaveAttribute('aria-expanded', 'true');
    fireEvent.click(screen.getByTestId('page-how-toggle'));
    expect(screen.getByTestId('page-how-toggle')).toHaveAttribute('aria-expanded', 'false');
    spy.mockRestore();
    set.mockRestore();
  });

  it('keeps custom testids and rich steps', () => {
    render(
      <PageHeader
        title="ML Models"
        purpose="p"
        titleTestId="ml-title"
        howTestId="ml-howto"
        howToggleTestId="ml-howto-toggle"
        steps={[{ title: 'Upload', body: 'A trained model file' }, { title: 'Test it' }]}
        howItWorks={<p>Extra note</p>}
        storageKey="ml"
      />,
    );
    expect(screen.getByTestId('ml-title')).toHaveTextContent('ML Models');
    expect(screen.getByTestId('ml-howto')).toBeInTheDocument();
    expect(screen.getByTestId('ml-howto-toggle')).toBeInTheDocument();
    expect(screen.getByText('A trained model file')).toBeInTheDocument();
    expect(screen.getByText('Extra note')).toBeInTheDocument();
  });

  it('accepts a custom node as the primary action and a disabled reason', () => {
    render(
      <PageHeader
        title="Autonomy"
        purpose="p"
        primaryAction={{ label: 'Enrol', disabled: true, title: 'Needs autonomy.manage' }}
        secondaryAction={<button type="button">Custom</button>}
      />,
    );
    const btn = screen.getByRole('button', { name: 'Enrol' });
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute('title', 'Needs autonomy.manage');
    expect(screen.getByRole('button', { name: 'Custom' })).toBeInTheDocument();
    // no steps, no docs, no panel
    expect(screen.queryByTestId('page-how-it-works')).not.toBeInTheDocument();
  });

  it('compact keeps how-it-works shut on the first visit and opens on demand', () => {
    const onNew = vi.fn();
    const { unmount } = render(
      <PageHeader
        compact
        title="Atlas"
        purpose="Map the things in your domain."
        steps={['one', 'two']}
        docSlug="01-architecture/06-atlas-knowledge-engine"
        primaryAction={{ label: 'Create atlas', onClick: onNew }}
        storageKey="atlas"
      />,
    );
    expect(screen.getByTestId('page-header')).toHaveAttribute('data-compact', 'true');
    expect(screen.getByTestId('page-purpose')).toHaveTextContent('Map the things in your domain.');
    expect(screen.getByTestId('page-how-toggle')).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('one')).not.toBeInTheDocument();
    expect(screen.getByTestId('page-docs-link')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Create atlas' }));
    expect(onNew).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByTestId('page-how-toggle'));
    expect(screen.getByText('one')).toBeInTheDocument();
    expect(readHowState('atlas')).toBe('0');
    unmount();
    render(<PageHeader compact title="Atlas" purpose="p" steps={['one', 'two']} storageKey="atlas" />);
    expect(screen.getByTestId('page-how-toggle')).toHaveAttribute('aria-expanded', 'true');
  });

  it('builds docs links with the doc param', () => {
    expect(docHref('02-runtime/12-ml-models')).toBe('/docs?doc=02-runtime%2F12-ml-models');
  });
});

describe('NextSteps', () => {
  it('renders up to four steps with links and buttons', () => {
    const onRun = vi.fn();
    render(
      <NextSteps
        title="Published. What next?"
        testId="publish-next"
        steps={[
          { id: 'chat', label: 'Try it in chat', hint: 'Ask it a real question', icon: Bot, href: '/agents/a1/chat' },
          { id: 'run', label: 'Run it', hint: 'Start a run now', icon: Plus, onClick: onRun },
          { id: 'docs', label: 'Read the docs', hint: 'How agents work', icon: BookOpen, href: '/docs' },
          { id: 'x', label: 'Four', hint: 'h', icon: Plus, href: '/x' },
          { id: 'y', label: 'Five', hint: 'h', icon: Plus, href: '/y' },
        ]}
      />,
    );
    expect(screen.getByTestId('publish-next')).toHaveTextContent('Published. What next?');
    expect(screen.getByTestId('publish-next-chat')).toHaveAttribute('href', '/agents/a1/chat');
    fireEvent.click(screen.getByTestId('publish-next-run'));
    expect(onRun).toHaveBeenCalledOnce();
    expect(screen.getByTestId('publish-next-x')).toBeInTheDocument();
    expect(screen.queryByTestId('publish-next-y')).not.toBeInTheDocument();
  });

  it('can be dismissed and renders nothing without steps', () => {
    const onDismiss = vi.fn();
    const { container, rerender } = render(
      <NextSteps steps={[{ id: 'a', label: 'A', hint: 'h', icon: Plus, href: '/a' }]} onDismiss={onDismiss} />,
    );
    fireEvent.click(screen.getByTestId('next-steps-dismiss'));
    expect(onDismiss).toHaveBeenCalledOnce();
    rerender(<NextSteps steps={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
