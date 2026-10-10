// What a failed run means for the person who started it, from the raw error.
export function explainRunError(raw: string): { title: string; hint: string } | null {
  const s = raw || '';
  // the platform's own limits come first, their wording also matches the provider rules below
  if (/ran out of time|pipeline\.timeout_seconds/i.test(s)) {
    return {
      title: 'This run hit its time limit and was stopped.',
      hint: 'An admin can raise the pipeline time limit under Admin, Settings, or the slow step can be made faster.',
    };
  }
  if (/by its rate limit|RATE_LIMITED/.test(s)) {
    return { title: 'This agent takes only a few runs per second.', hint: 'Wait a moment and send it again.' };
  }
  if (/authentication_error|401|revoked|invalid (x-)?api[- ]key|unauthorized/i.test(s)) {
    return {
      title: 'The AI provider rejected the platform credentials, so this run could not start.',
      hint: 'An admin can fix this under Admin, LLM Settings. Nothing you typed was lost.',
    };
  }
  if (/429|rate.?limit|overloaded|529|quota/i.test(s)) {
    return { title: 'The AI provider is busy right now.', hint: 'Try again in a minute.' };
  }
  if (/connection error|name or service not known|timed? ?out|ECONN|network/i.test(s)) {
    return { title: 'The AI provider could not be reached.', hint: 'Check the connection and try again.' };
  }
  if (/budget|spend limit/i.test(s)) {
    return { title: 'This agent has reached its spending limit.', hint: 'Its owner can raise the limit in the builder.' };
  }
  return null;
}
