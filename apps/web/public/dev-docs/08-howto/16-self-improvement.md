# How to let an agent improve itself, under control

> Turn lessons into a proven fix, approve it, release it and watch it. Capture and test cases are in [02-runtime/22-lessons-and-improvements](../02-runtime/22-lessons-and-improvements.md), the proposal side in [02-runtime/23-governed-self-improvement](../02-runtime/23-governed-self-improvement.md).

---

## Before you start

| You want to | You need |
|---|---|
| See lessons, proposals and releases | `improvements.view` (creator, admin), or be the agent's owner |
| Propose a fix, prove it again, roll a release back | `improvements.propose` (creator, admin). Owners can roll back their own agent |
| Approve a release | `improvements.approve` (admin), and you did not build the agent |
| Give thumbs and corrections | `feedback.give` (every role) |

Admins hand these out as permission sets under **Admin -> Permissions**.

---

## 1. Try the sample first

Nothing external is needed beyond one connected model.

1. Open **Monitor -> Improvements** and choose **Try it on the sample agent**. This creates "Temperature helper (sample)". Its instructions carry a planted mistake: it always answers in Fahrenheit. Four corrected lessons are already grouped as "Answers in Fahrenheit when the user asks for Kelvin", with test cases written from them.
2. On the group press **Propose a fix**. The steps show as they run: drafting the change, test set with a count, replay of real inputs, comparing, done. You can leave and come back, you get a notification when it is done.
3. Open the proof. Lessons fixed are green, newly broken cases are red and always 0 for a proposal you are asked to approve. Before and after bars show tests passed, quality, cost and speed, and three real examples sit side by side with the new words marked.
4. Open **Approvals**. The card is labelled "agent improvement". Because this is the sample, you may approve your own fix and the card says why. On a real agent someone else with Approve improvements signs it.
5. Approve. The fix becomes a new revision of the agent with source Improvement. The agent's revision history links back to the proof.
6. The release is watched against the old version. Press **Check now** on the release to compare at once. Give a few answers a thumbs down in chat and the release rolls back on its own, with the reason on the release and in a notification.

Pressing **Try it on the sample agent** again after a loop has finished puts the planted mistake back.

---

## 2. Propose a fix for a real agent

- Wait for lessons to group on the agent's **Improvements** tab, or let a group reach 5 lessons (or high severity) and a fix is proposed on its own.
- Accept the suggested test cases you agree with first. Accepted cases are what the proof holds every fix to.
- Press **Propose a fix** on the group. One small change is drafted: examples, a few edited sentences, one tool setting, one tool, or a model switch the risk tier allows. Pipelines get a patch from the Pipeline Surgeon. Limits, risk tier, autonomy, credentials and sharing are never touched.

## 3. Read the proof

| You see | It means |
|---|---|
| Fixed 3 of 4 | 3 of the group's lessons pass with the fix and did not before |
| Newly broken 0 | Every case that passed before still passes, and no real input that worked now fails |
| Replayed 50 recent real inputs, 7 answered differently, 2 actions were held | Real inputs ran on the new version. Actions were recorded and never ran |
| Did not pass | It missed the bar. Nobody is asked to approve it. The reasons say which part |

**Run the proof again** after you change test cases. **Edit the change** lets you adjust the diff, it is proved again before anyone can approve it.

## 4. Approve, edit or reject

In **Approvals**:

- **Approve** releases it at once.
- **Edit and approve** opens the change, proves the edited version again and brings it back here when it passes.
- **Reject** needs a reason. The reason becomes a lesson, so the next draft avoids it.

If you built the agent, the card says someone else approves and offers **Invite a teammate**. A solo builder, with nobody else who can approve, may approve their own fix and it is recorded as self-approved.

## 5. Watch and roll back

A release is watched for 7 days or 200 runs, whichever comes first. The release card shows old against new on failed runs, thumbs down, cost per run, autonomy accuracy, the same mistake coming back and drift alerts. Anything worse beyond the margin rolls it back on its own. **Roll back now** does the same at once and never needs an approval.

## 6. Budget, settings and the kill switch

- The meter at the top of the Improvements page shows proofs and tokens used today and how many proposals are in line. When the day's budget is spent, new proposals wait with a plain note and start the next day.
- An admin sets the budget and margins in the tenant settings under `improvements` (see the runtime doc). Per agent overrides go under `improvements.agents.<agent_id>`.
- **Admin -> Risk and Controls -> Kill switches -> Agent improvements** stops all proposing and proving for the tenant. Releases in their watch keep being watched.

## 7. From a standalone app

```python
await client.feedback.give(-1, execution_id=run_id, correction="0 °C is 273.15 K")
await client.lessons.report(agent_id, "It answered in Fahrenheit", expected="273.15 K", execution_id=run_id)
for p in await client.improvements.list(agent_id=agent_id, state="released"):
    print(p["cluster"]["title"], p["state_label"])
```

TypeScript and Java have the same calls, see [03-sdk](../03-sdk/00-overview.md).
