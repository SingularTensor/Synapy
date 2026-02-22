# Puzzle & Assessment Design Guidelines

This document outlines the core principles for designing and implementing assessment puzzles on the Synapy platform. When creating a new assessment module or game, agents and developers must adhere to these guidelines to ensure consistency, fairness, and utility for the consumer.

## Core Mechanics

### 1. Duration and Pacing
- **Varied and Short:** Assessments should be designed as micro-games or short puzzles. Users should not be bogged down in monolithic, hour-long exams.
- **Untimed but Tracked:** Puzzles should **not** have a hard time limit that forcefully kicks the user out (unless specifically testing extreme stress reactions, which is rare). Instead, the user takes as much time as they need, but the **completion time is tracked** implicitly in the background as a key performance metric.

### 2. Performance & Scoring (Percentile Variance)
- **Granular Scoring:** Assessments must allow for a wide variance in user performance. A simple "Pass/Fail" is insufficient. 
- **Percentile Tracking:** The scoring model should produce continuous data (e.g., time taken, number of optimal moves vs. actual moves, error rate) so that users can be placed into performance percentiles compared to the broader player pool.
- **Multi-dimensional Metrics:** Look beyond just "did they get the right answer." Track how they arrived there (e.g., hesitancy, back-tracking, efficiency).

### 3. Contextual Data Tracking & Strict Domain Isolation
- **Field-Dependent Metrics:** Data tracking is not one-size-fits-all. The metrics captured must be highly contextual to the industry the puzzle is targeting.
  - *Example (Software Engineering):* Track algorithmic efficiency, edge-case consideration, and logic flow.
  - *Example (Operations/Logistics):* Track spatial reasoning, prioritization speed, and resource allocation efficiency.
  - *Example (Customer Success):* Track empathy mapping, language comprehension, and de-escalation sequence choices.
- **Strict Domain Isolation:** To prevent brand dilution, recruitment assessments **must** be strictly siloed by domain. A high-end software engineer candidate should never see the same assessment designed for a fast-food shift worker. The platform must maintain distinct "Career Tracks" (paid tiers) to ensure prestige and validity are maintained per industry.

## Aesthetic & UX Philosophy

### "Professional to Gamified" Ratio (3:2)
The UI/UX must strike a careful balance. It should look like a serious, high-quality professional assessment tool first and foremost, with gamification elements woven in to reduce stress and increase engagement.

- **Professional (60%):** Clean typography, intuitive UX, accessible contrast, minimal clutter, and clear instructions. It should look like a modern SaaS platform (e.g., Notion, Stripe, Vercel).
- **Gamified (40%):** Satisfying micro-interactions, smooth animations, subtle sound design, progressive disclosure of complexity, and "level complete" satisfaction without being childish or overly flashy. No slot-machine mechanics.

## Implementation Checklist for New Puzzles

When an AI agent or developer is prompted to add a new puzzle, they must ensure:
1. [ ] The puzzle state and completion time are tracked accurately in JavaScript.
2. [ ] The frontend communicates the payload (time taken, errors made, final state) to the backend API (`routes.py`).
3. [ ] The backend is prepared to map this specific data payload to the appropriate user metrics (CognitiveScore / GameSession).
4. [ ] The UI adheres to the 3:2 Professional:Gamified aesthetic ratio.
