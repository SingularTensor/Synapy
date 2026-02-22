# CLAUDE.md

## Project Vision

**Synapy** is a state-of-the-art cognitive assessment and problem-solving platform tailored for individual consumers (B2C). Think of it like LeetCode, but for a wider array of industries, using game-styled assessments and puzzles.

### Core Thesis
Traditional standardized tests and interview preparations are stressful and limited. Synapy allows users to evaluate their own core cognitive fitness, working memory, processing speed, and pattern recognition through engaging, game-like puzzles. Users can prove their skills, train for specific career paths, and build a comprehensive "g-factor" problem-solving profile.

### Target Market & Monetization (B2C Focus)
- **Unregistered Free Users:** Access to general, non-field-specific challenges. 
- **Registered Free Users:** Access to general challenges, daily random challenges, limited specific career puzzles, and basic "g-factor" / general intelligence dashboard stats.
- **Paid Premium Users:** Full access to specific career-track games (e.g., Software Engineering, Logistics) and detailed domain-specific statistical breakdowns on their player dashboard.

*(Note: Social features are currently pinned to prevent scope creep. Focus is entirely on the solo consumer loop.)*

### Design Philosophy
- LeetCode evaluation mechanics meet consumer gaming engagement
- Simple puzzle mechanics, satisfying feedback, accurate assessment metrics
- "Game style" assessments adapted for diverse industries
- Player Dashboard emphasizes general cognitive stats for free, and deep domain metrics for paid users

---

## Commands

```bash
# Activate virtual environment (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Seed the database
python seed.py

# Run the Flask development server
python app.py
```

## Architecture

Flask application with SQLAlchemy/SQLite.

**Core files:**
- `app.py` - Flask init, login manager, DB config
- `database.py` - SQLAlchemy models (User, GameType, GameSession, CognitiveScore)
- `routes.py` - All route handlers
- `seed.py` - Database reset and seed script

**Database:** SQLite at `instance/synapy.db`

**Models:**
- `User` - Auth, XP, streaks, recruiter visibility toggle
- `GameType` - Different cognitive games (sequence memory, reaction time, etc.)
- `GameSession` - Individual play sessions with scores/metrics
- `CognitiveScore` - Aggregated domain scores (working memory, processing speed, etc.)

**Cognitive Domains:**
- Working Memory
- Processing Speed
- Attention
- Pattern Recognition
- Mental Math
- Verbal Comprehension

## Code Style

- No emojis in code
- Minimal comments - only when actually noteworthy
- Game logic lives in individual game templates (JS) for now
- API endpoints handle session tracking and scoring

## Agent Guardrails

- See `AGENTS.md` for mandatory cognitive-weight rules and versioning requirements.

## Next Steps (Not Time-Bound)

1. Build first playable game (Sequence Memory is a good start)
2. Implement cognitive score aggregation from session data
3. Design the "brain age" / cognitive profile visualization
4. Add streak tracking and daily challenges
5. Build recruiter dashboard for candidate viewing
