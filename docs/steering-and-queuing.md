# Steering and Queuing

Hermes Agent's **Steering and Queuing** feature intelligently handles follow-up messages sent while the agent is busy processing a task. This ensures that important updates get immediate attention while non-urgent messages wait their turn.

---

## What Are Steering and Queuing?

When you send a message to Hermes while it's already working on something, the agent needs to decide how to handle your new input. There are two approaches:

### Steering (Interrupt)
**Steering** immediately interrupts the current task and incorporates your new message as updated instructions or corrections. The agent stops what it's doing and responds to your new input right away.

**Use steering when:**
- You made a mistake in your original request
- You need to correct or clarify something important
- New critical information has come up
- You want to cancel the current task

### Queuing
**Queuing** holds your message until the current task completes. The agent finishes its current work, then processes your follow-up message as a new task.

**Use queuing when:**
- You have a separate, unrelated question
- You want to queue up follow-up tasks
- The current task should complete before addressing your new message
- You're sending additional context that isn't urgent

---

## How Classification Works

Hermes automatically classifies your follow-up messages using keyword and phrase analysis. The classification determines whether a message should **steer** (interrupt) or **queue** (wait).

### Steer Phrases (Interrupt)

Messages containing these types of phrases trigger an immediate interrupt:

| Category | Example Phrases |
|----------|----------------|
| **Corrections** | "actually", "wait", "no, I meant", "that's wrong", "correction" |
| **Cancellations** | "stop", "cancel", "nevermind", "abort", "forget it" |
| **Urgency** | "urgent", "important", "asap", "critical", "emergency" |
| **Clarifications** | "let me rephrase", "what I meant was", "to be clear" |
| **Negations** | "don't do that", "not that", "wrong file", "incorrect" |
| **New instructions** | "instead", "change it to", "do this instead" |

### Queue Phrases (Hold)

Messages containing these patterns are queued for later processing:

| Category | Example Phrases |
|----------|----------------|
| **Separate topics** | "also", "by the way", "additionally", "separately" |
| **Follow-up tasks** | "next, can you", "after that", "then please", "once done" |
| **Low priority** | "when you have time", "no rush", "later" |
| **Questions** | "what is", "how do I", "can you explain" (unrelated to current task) |
| **Context** | "for context", "just so you know", "fyi" |

### Classification Algorithm

1. **Keyword matching**: Your message is scanned for steer/queue keywords
2. **Context analysis**: The relationship to the current task is evaluated
3. **Urgency scoring**: Presence of urgency indicators increases steering likelihood
4. **Decision**: Message is classified as `steer` or `queue`

---

## CLI Configuration: `busy_input_mode`

The `busy_input_mode` setting in your `config.yaml` controls the default behavior when Hermes receives input while busy.

### Setting Location

```yaml
# ~/.hermes/config.yaml
display:
  busy_input_mode: interrupt  # Options: interrupt, queue, smart
```

### Available Modes

| Mode | Behavior |
|------|----------|
| `interrupt` | All new messages immediately interrupt the current task (steering mode) |
| `queue` | All new messages are held until current task completes (queuing mode) |
| `smart` | Automatic classification based on steer/queue phrases (default recommended) |

### Changing the Setting

**Via config file:**
```bash
# Edit ~/.hermes/config.yaml
display:
  busy_input_mode: smart
```

**Via CLI command:**
```bash
hermes config set display.busy_input_mode smart
```

---

## The `/queue` Command

When the agent is busy, you can explicitly control message handling using the `/queue` command prefix.

### Usage

```
/queue <your message>
```

### Examples

**Queue a follow-up question while agent is working:**
```
[Agent is busy writing code...]

User: /queue Can you also check the README for typos when you're done?
→ Message queued, will process after current task
```

**Explicitly queue a separate task:**
```
[Agent is analyzing data...]

User: /queue What was that npm package we used last week?
→ Message queued, will process after current task
```

### Benefits of `/queue`

- **Explicit control**: Override automatic classification
- **Predictability**: Know exactly when your message will be processed
- **Batch processing**: Queue multiple items for sequential handling

---

## Examples: What Gets Steered vs Queued

### Examples That Get Steered (Interrupt)

| Scenario | User Input | Result |
|----------|------------|--------|
| Correction | "Actually, use Python not JavaScript" | Immediate interrupt, switches language |
| Cancellation | "Stop, I changed my mind" | Task aborted immediately |
| Urgent update | "Wait! Use the production API key, not dev" | Immediate switch to production |
| Clarification | "No, I meant the other file" | Stops and asks which file |
| Wrong direction | "Don't commit that yet" | Prevents the commit action |
| Priority change | "This is urgent - fix the bug first" | Switches to bug fixing |

### Examples That Get Queued

| Scenario | User Input | Result |
|----------|------------|--------|
| Side question | "By the way, what's the weather today?" | Waits until current task done |
| Next task | "After that, can you review my PR?" | Queued as next task |
| Additional request | "Also add some comments to the code" | Added to task queue |
| Context info | "FYI, the meeting got moved to 3pm" | Stored for later reference |
| Unrelated question | "What was that restaurant we talked about?" | Processed after current task |
| Low priority | "When you have time, organize these files" | Queued behind urgent tasks |

---

## Best Practices

### When to Use Steering
- **Time-sensitive corrections**: When the agent is about to do something wrong
- **Safety concerns**: When the current action might cause issues
- **Priority shifts**: When something more important comes up

### When to Use Queuing
- **Multiple tasks**: Queue up several independent requests
- **Context switching**: Let the agent finish before changing topics
- **Non-blocking questions**: Ask unrelated questions without interrupting

### Combining Strategies
```
User: Write a Python script to fetch weather data
[Agent starts coding...]

User: Actually, make it async  ← STEER: interrupts, switches approach
[Agent restarts with async code...]

User: /queue Also email me the results  ← QUEUE: will add after script done

User: /queue And add error handling  ← QUEUE: added to queue

User: Wait, use aiohttp not requests  ← STEER: interrupts again
[Agent updates to aiohttp...]
```

---

## Troubleshooting

### My message didn't interrupt when it should have
- Check your `busy_input_mode` setting
- Ensure you're using clear steer phrases
- Use `/steer` prefix for guaranteed interruption (if available)

### Everything is getting queued when I want steering
- Set `busy_input_mode: interrupt` for always-steer behavior
- Use explicit steer phrases like "actually" or "wait"
- Consider setting to `smart` for automatic classification

### Messages interrupting when I wanted them queued
- Use `/queue` prefix to explicitly queue messages
- Avoid steer keywords in non-urgent follow-ups
- Set `busy_input_mode: queue` for always-queue behavior

---

## Summary

| Feature | Purpose | How to Use |
|---------|---------|------------|
| **Steering** | Interrupt current task | Use steer phrases or `busy_input_mode: interrupt` |
| **Queuing** | Hold for later | Use `/queue` prefix or `busy_input_mode: queue` |
| **Smart Mode** | Automatic classification | Set `busy_input_mode: smart` (recommended) |

The steering and queuing system helps you maintain productive conversations with Hermes Agent, ensuring important corrections get immediate attention while allowing you to queue up additional tasks for later processing.
