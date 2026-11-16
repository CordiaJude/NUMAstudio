# Numa Studio: Operator Guide (Jude)

Version 2.1, 2026-11-16. How to run Numa Studio day to day once it is set up. Setup itself is docs/SETUP_GUIDE.md; Katie's side is docs/KATIES_GUIDE.md. Everything here can also be done by asking Claude in the Numa Studio Project.

## Your job in one line

Keep the connections alive, answer the rare one-line escalation, enter new owner answers, and check the system's health once a day for a minute. You never edit posts; the owners approve them.

## Every day (about 2 minutes)

| What | How |
| --- | --- |
| Health check | In the Project, ask "How did the runs go today?" Claude runs `runlog.py check` and `runlog.py summary` and answers with any missed, failed or interrupted run and what it already did about it. All OK means nothing to do. |
| Escalations | Read anything that arrived on your escalation channel (email, or `_Plan/escalations.md` plus the digest's Jude-only footer). Each is one line with the fix. |
| Waiting posts | Optional: glance at the plan Sheet for rows stuck on "Ready to post (Trial Reel / collab / AI label)": those need Katie's Mac awake, or a manual post from the Instagram app. |

## Every week

| When | What |
| --- | --- |
| Monday | Read the digest, especially its Jude-only footer and the run health line. |
| Any day | Check the Higgsfield balance against the month's budget: ask "How many credits are left this month?" (1,200 a month, at most 55% by day 15; Claude never buys credits). |

## Every month

| When | What |
| --- | --- |
| After the 24th | Skim the new plan Sheet and the shoot cards; the plan comes from the Strategist and needs no approval. |
| First week | Look at the dashboard's "Do more of / Do less of" and the digest's "What we learned"; tell Claude if anything looks wrong. |
| Quarterly (12th of Feb, May, Aug, Nov) | The quarterly research reminder lands; re-run the research prompts in docs/RESEARCH_PROMPTS_PLAYBOOK.md when it says to, save the results in Drive `_Plan/Research/`, and ask Claude to import them. |

## Common jobs

| You want to | Do this |
| --- | --- |
| Enter an owner answer (approver, generic voice, music source, kids rule, hours, an event date) | In the Project: `/brand-setup` and give the answer, or "Katie says kids are OK with a parent's yes; update the brand data." It writes `_Plan/brand.json` (and tells you to commit the repo copy). |
| Add or change a person (staff, member yes, do-not-feature) | Edit the private `_Plan/people.json` in Drive, or ask Claude to; members' yeses also go in the Consent List Sheet. Never put names in the repo. |
| Pause posting | Tell the approvers to stop approving: nothing posts unapproved. To stop builds too, pause or turn off each scheduled task in the Claude app. |
| Build or rebuild one post by hand | `/make-reel <day folder>` (reels) or ask "Rebuild Day 07 with ...". The row comes back to Ready to post. |
| Plan a one-off post | "Make a reel for <event> on <date>." Claude writes the card and adds the row. |
| Reconnect Instagram (Meta error 190), Drive, Higgsfield, Gmail | Claude Settings > Connectors > the connector > reconnect; then ask Claude to run `/numa-setup` step 3 (connector check). |
| Card declined (Claude or Higgsfield) | Update the card in that account; tell Claude to re-check. |
| Install a plugin update | Update `numa-studio` in the Claude app (plugin marketplace). The next scheduled run bootstraps itself (`ensure_env.py`); ask Claude to run `/numa-setup` once to re-check. |
| Check a single run | "Show me the run log for last night's night check." |
| See why a post wasn't built | "Why is there no post for Day 12?" Claude reads the run log, the decisions file and the folder. |
| See who approved a post | "Who approved Day 07?" (recorded at posting from the Sheet). |

## What escalations mean

| Escalation line | Fix |
| --- | --- |
| Meta error 190 / Instagram disconnected | Reconnect Composio's Instagram connection |
| Card to renew | Update billing in that account |
| Approval step broken (Sheet unreadable, Status column missing) | Re-add the Status dropdown (Planned, Shot, Ready to build, Ready to post, Approved, Posted) or fix Sheet sharing |
| A task keeps missing | Open the scheduled task, check its prompt matches docs/SCHEDULED_TASKS.md word for word, Run now |
| Story numbers missed | Check the 12:40 pm task ran; see docs/SCHEDULED_TASKS.md "Story capture timing" |

## Commands reference

| Command | What it does | Normally run by |
| --- | --- | --- |
| `/plan-month` | Next month's plan, folders and shoot cards | Scheduled, 24th 9 pm |
| `/night-check` | Tomorrow's material check, Story pulls, approval re-check, guaranteed evening publish slot | Scheduled, daily 8 pm |
| `/build-today` | Builds and stages today's post | Scheduled, daily 5 am |
| `/make-reel <folder>` | Builds one reel by hand | You or the owners |
| `/post-reel` | Stages and (once approved) posts; `approvals` re-checks | Other commands |
| `/dashboard-refresh` (and `stories`) | Insights, learning, dashboard | Scheduled, 10 pm and 12:40 pm |
| `/chrome-queue` | Steps that need Chrome on Katie's Mac | Desktop task, hourly at :47 |
| `/trend-check` | Trend ideas and weather | Scheduled, Fridays 7 pm |
| `/digest` | The Monday digest | Scheduled, Sundays 6 pm |
| `/numa-setup` | Setup and re-checks | You |
| `/brand-setup` | Owner answers into the brand data | You |
