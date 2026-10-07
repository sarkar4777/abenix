import type { ModelOption, SubscriptionState } from '@/lib/models';

type Pickable = Pick<ModelOption, 'value' | 'status' | 'is_deprecated' | 'subscription_remapped_to' | 'subscription_served'> & {
  provider_available?: boolean;
};

// the picker default should name the model that actually runs, not one the subscription silently swaps
export function pickRunnableModel(
  current: string,
  models: Pickable[],
  subscription: Pick<SubscriptionState, 'active' | 'exclusive' | 'default_model'> | null,
): string | null {
  if (!models.length) return null;
  const byValue = new Map(models.map(m => [m.value, m]));
  const usable = (m?: Pickable) =>
    !!m && m.status !== 'unavailable' && !m.is_deprecated && !m.subscription_remapped_to
    && (m.provider_available !== false || !!m.subscription_served);
  const cur = byValue.get(current);
  const subDefault = subscription?.active ? subscription.default_model : '';
  // unknown to the registry, keep it unless a subscription says what runs
  if (!cur) return subDefault || null;
  if (usable(cur)) return current;
  const remapped = cur.subscription_remapped_to;
  if (remapped && (byValue.has(remapped) || subscription?.active)) return remapped;
  if (subDefault && (!byValue.has(subDefault) || usable(byValue.get(subDefault)))) return subDefault;
  const first = models.find(m => usable(m));
  return first ? first.value : null;
}
