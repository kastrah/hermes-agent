# Steering vs Queuing Architecture Design

## Definitions

### STEERING (Course Correction)
**Purpose**: Amend or clarify the CURRENT task while it's in progress.

**User Intent**: "I see you're working on X, but I need you to adjust how you're doing it."

**Examples**:
- "actually, use the blue theme instead"
- "wait, I meant the other file"
- "fix: use async/await here"
- "never mind that approach, try grep instead"

**Behavior**:
1. PAUSE the current tool execution loop
2. INJECT the new message into conversation history
3. RE-CALL the model with updated context (preserving all tool results so far)
4. CONTINUE the task with the corrected understanding
5. NO RESTART - same task, updated approach

**Key Characteristic**: The agent maintains state and incorporates the correction mid-flight.

---

### QUEUING (Separate Task)
**Purpose**: Add a NEW task to be done AFTER the current one completes.

**User Intent**: "I have something else for you, but finish what you're doing first."

**Examples**:
- "remind me later to check the tests"
- "after this, look at the other PR"
- "another thing: update the docs"
- "for later: optimize the query"

**Behavior**:
1. STORE the message in a pending queue
2. Let the CURRENT task run to completion
3. START a NEW turn with the queued message as fresh user input
4. Context is fresh - new task, new goals

**Key Characteristic**: The agent finishes one task completely before starting the next.

---

## Technical Implementation

### Current (BROKEN) Behavior
```
User sends "actually use blue theme"
    ↓
Agent.interrupt() called
    ↓
Tool loop BREAKS
    ↓
Message queued for NEW turn
    ↓
Agent starts FRESH with no context of what was done
```

### Correct STEERING Behavior
```
User sends "actually use blue theme"
    ↓
Agent PAUSES current API call
    ↓
New message ADDED to conversation history
    ↓
Model RE-CALLED with full context + correction
    ↓
Agent CONTINUES from where it left off
    ↓
User sees: "I'll use the blue theme instead..." (seamless)
```

### Correct QUEUING Behavior
```
User sends "remind me later to check tests"
    ↓
Message STORED in pending_messages[session_id]
    ↓
Current task continues UNDISTURBED
    ↓
Current task COMPLETES
    ↓
Pending message popped from queue
    ↓
NEW turn started with that message
    ↓
User sees: "[Previous task completed. Now checking tests...]"
```

---

## Implementation Plan

### 1. Steering Implementation (run_agent.py)

Need to modify the `interrupt()` method and tool loop:

```python
class AIAgent:
    def __init__(self):
        self._steer_message = None  # New: store steering message
        self._steer_requested = False  # New: flag for steering vs interrupt
        
    def steer(self, message: str) -> None:
        """
        STEERING: Pause, inject context, continue same task.
        
        Unlike interrupt() which breaks the loop, steer():
        1. Sets a flag to pause current API call
        2. Stores the steering message
        3. Lets the tool loop continue with new context
        """
        self._steer_requested = True
        self._steer_message = message
        # Signal to pause, not break
        
    def run(self, messages, ...):
        while not done:
            if self._steer_requested:
                # PAUSE: Don't break, just pause stream
                # INJECT: Add steer message to conversation
                messages.append({"role": "user", "content": self._steer_message})
                self._steer_requested = False
                self._steer_message = None
                # CONTINUE: Re-call model with updated messages
                
            response = self._call_model(messages)
            # ... rest of tool loop
```

### 2. Queuing Implementation (gateway/run.py + base.py)

Already mostly implemented, just need to ensure:
- Message stored in `pending_messages`
- Current task not interrupted
- After completion, pending message processed as new turn

### 3. Classification Updates (base.py)

Update `_busy_followup_route()` to properly distinguish:
- STEER phrases → call `agent.steer()` 
- QUEUE phrases → store in `pending_messages`

---

## UI/UX Differences

### Steering
- User sees: No interruption message, agent just adapts
- Agent response: "I'll use the blue theme instead and continue..."
- Context: All previous tool results preserved

### Queuing  
- User sees: "[Task completed. Starting next task...]"
- Agent response: Fresh turn with new goal
- Context: Fresh context window, new task

---

## Code Changes Required

### Files to Modify:
1. `run_agent.py` - Add `steer()` method, modify tool loop
2. `cli.py` - Update chat() to use steer() vs interrupt()
3. `gateway/platforms/base.py` - Route steer vs queue correctly
4. `gateway/run.py` - Handle steer vs queue in message handler

### Backward Compatibility:
- `interrupt()` stays as-is (for hard stops like /stop)
- New `steer()` method for course corrections
- Existing queue behavior unchanged
